"""여러 화면이 함께 쓰는 입력 파일·계산 결과·작업 내역.

- 올린 파일은 session_state["files"] 에 (이름, 바이트)로 둔다. 다른 화면에 갔다 와도 남는다.
- 동·층 이름, 레이어, 열 지정 위젯은 persist_state="session" 이라 값이 session_state 에 남는다.
- 계산은 입력·설정·방 이름의 지문으로 캐시해서, 화면을 바꿔도 다시 계산하지 않는다.
- 계산이 되면 작업 내역(slab/history.py)에 자동으로 저장한다. 작업마다 계산할 때 쓴 설정을 함께 두어,
  나중에 열어도 같은 결과가 나온다. 설정 화면에서 바꾼 값은 새 작업부터 쓰인다.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import streamlit as st

from slab import AnalysisResult, Settings, analyze, history, load_cad, read_table, standardize_grid
from slab.core import DEFAULT_COLUMNS, CadPlan
from slab.settings_store import from_dict, load_settings, to_dict

ROOT = Path(__file__).resolve().parents[1]
KINDS = {"cad": "도면 (DXF)", "upper": "위층 스캔", "lower": "아래층 스캔"}
COLUMN_LABELS = {
    "point_id": "포인트 번호",
    "x": "X 좌표",
    "y": "Y 좌표",
    "floor_z": "바닥 높이 (콘크리트 윗면)",
    "ceiling_z": "천장 높이",
    "floor_error": "바닥 기준면 편차",
    "ceiling_error": "천장 기준면 편차",
}
NONE = "(없음)"
META_KEYS = {"dong": "meta_dong", "upper_floor": "meta_upper", "lower_floor": "meta_lower"}


class File:
    """세션에 둔 파일을 slab 함수가 읽을 수 있게 감싼다."""

    def __init__(self, name: str, data: bytes):
        self.name, self.data = name, data

    def getvalue(self) -> bytes:
        return self.data


def init_state() -> None:
    ss = st.session_state
    if "files" not in ss:
        ss.files = {}
    if "room_names" not in ss:
        ss.room_names = {}


# ------------------------------------------------------------------ 작업 (열기·새로 시작)
def _col_keys() -> list[str]:
    return [f"col_{kind}_{k}" for kind in ("upper", "lower") for k in COLUMN_LABELS]


def clear_files() -> None:
    """새 작업: 올린 파일과 지금 열린 작업을 비운다."""
    ss = st.session_state
    ss.files = {}
    ss.room_names = {}
    for k in ("job_id", "job_settings", "job_opened", "_auto_floor", *META_KEYS.values(), "room_layer",
              *_col_keys()):
        ss.pop(k, None)
    st.query_params.pop("job", None)


def open_job(job_id: str) -> bool:
    """작업 내역의 작업을 지금 작업으로 연다 (파일·이름·설정을 그때 그대로)."""
    job = history.get_job(job_id)
    files = history.load_files(job_id)
    if job is None or "upper" not in files or "lower" not in files:
        return False
    clear_files()
    ss = st.session_state
    ss.files = files
    ss.room_names = dict(job.get("room_names") or {})
    ss.job_id = job_id
    ss.job_opened = True
    st.query_params["job"] = job_id
    ss.job_settings = job.get("settings") or to_dict(load_settings())
    for field, key in META_KEYS.items():
        ss[key] = job.get(field, "")
    if job.get("layer"):
        ss.room_layer = job["layer"]
    for k, v in (job.get("columns") or {}).items():
        ss[k] = v
    return True


def close_if_open(job_id: str) -> None:
    if st.session_state.get("job_id") == job_id:
        clear_files()


def job_settings() -> Settings:
    """지금 작업에 쓰는 설정: 연 작업이면 그때 설정, 새 작업이면 설정 화면에 저장된 값."""
    snap = st.session_state.get("job_settings")
    return from_dict(snap)[0] if snap else load_settings()


def use_current_settings() -> None:
    st.session_state.job_settings = to_dict(load_settings())


# ------------------------------------------------------------------ 파일
def store_upload(kind: str) -> None:
    """file_uploader 의 on_change: 올린 파일을 세션에 옮겨 둔다. 이름에서 층을 짐작해 채운다."""
    up = st.session_state.get(f"up_{kind}")
    if up is None:
        return
    if st.session_state.get("job_opened"):  # 내역에서 연 작업에 새 파일을 올리면 새 작업으로 본다
        clear_files()
        st.session_state.job_opened = False
    st.session_state.files[kind] = (up.name, up.getvalue())
    if kind == "cad":
        st.session_state.room_names = {}
    floor = guess_floor(up.name)
    target = {"upper": "meta_upper", "lower": "meta_lower"}.get(kind)
    # 비어 있거나 전에 파일 이름에서 자동으로 채운 값이면 새 파일에 맞춰 바꾼다 (직접 쓴 값은 그대로 둔다)
    auto = st.session_state.setdefault("_auto_floor", {})
    if floor and target and st.session_state.get(target, "") in ("", auto.get(target)):
        st.session_state[target] = floor
        auto[target] = floor


def remove_file(kind: str) -> None:
    st.session_state.files.pop(kind, None)
    if kind == "cad":
        st.session_state.room_names = {}


def guess_floor(name: str) -> str:
    """파일 이름에서 층 표기(8F, B1 등)를 찾는다."""
    m = re.search(r"(?<![A-Za-z0-9])(B?\d{1,3}F|B\d{1,2})(?![A-Za-z0-9])", Path(name).stem, re.I)
    return m.group(1).upper() if m else ""


def active_files() -> dict[str, File | None]:
    return {k: File(*st.session_state.files[k]) if k in st.session_state.files else None for k in KINDS}


def meta() -> dict:
    return {
        "동": st.session_state.get("meta_dong") or "",
        "상부층": st.session_state.get("meta_upper") or "",
        "하부층": st.session_state.get("meta_lower") or "",
    }


def title_of(m: dict) -> str:
    return f"{m['동']} {m['상부층']}-{m['하부층']} 슬래브 두께".strip()


def stem_of(m: dict) -> str:
    return f"{m['동']}_{m['상부층']}-{m['하부층']}_슬래브두께".replace(" ", "").strip("_") or "슬래브두께"


# ------------------------------------------------------------------ 캐시
@st.cache_data(show_spinner=False, max_entries=20)
def raw_table(name: str, data: bytes) -> pd.DataFrame:
    return read_table(File(name, data))


@st.cache_resource(show_spinner=False, max_entries=10)
def cad_plan(digest: str, data: bytes, room_layer: str | None) -> CadPlan:
    return load_cad(File("cad.dxf", data), room_layer)


@st.cache_data(show_spinner="두께 계산 중…", max_entries=20)
def _analyze(key: str, _upper, _lower, _plan, _settings, _names) -> AnalysisResult:
    """key 는 입력 파일·설정·방 이름을 묶은 지문. 같은 입력이면 다시 계산하지 않는다."""
    return analyze(_upper, _lower, _plan, _settings, _names)


def fingerprint(*parts) -> str:
    h = hashlib.md5()
    for p in parts:
        h.update(p if isinstance(p, bytes) else repr(p).encode())
    return h.hexdigest()


def mapping(kind: str, raw: pd.DataFrame) -> dict:
    """열 지정 위젯 값(세션)을 standardize_grid 용 사전으로. 지정이 없으면 기본 열 이름."""
    out = {}
    for k in COLUMN_LABELS:
        sel = st.session_state.get(f"col_{kind}_{k}")
        if sel is None or (sel != NONE and sel not in raw.columns):
            sel = DEFAULT_COLUMNS[k] if DEFAULT_COLUMNS[k] in raw.columns else NONE
        out[k] = sel if sel != NONE else f"__missing_{k}"
    return out


@dataclass
class Run:
    """한 번의 계산에 필요한 입력과 결과. error 가 있으면 result 는 None."""

    files: dict
    meta: dict
    base_plan: CadPlan | None = None  # 레이어를 고르기 전 도면 (레이어 목록용)
    plan: CadPlan | None = None
    result: AnalysisResult | None = None
    key: str = ""
    error: str = ""
    error_title: str = ""
    missing: tuple = ()
    layer: str | None = None


def compute() -> Run:
    init_state()
    files = active_files()
    run = Run(files, meta())
    run.missing = tuple(KINDS[k] for k in ("upper", "lower") if files[k] is None)
    if run.missing:
        return run
    upper_f, lower_f, cad_f = files["upper"], files["lower"], files["cad"]
    try:
        upper = standardize_grid(raw_table(upper_f.name, upper_f.data),
                                 mapping("upper", raw_table(upper_f.name, upper_f.data)))
        lower = standardize_grid(raw_table(lower_f.name, lower_f.data),
                                 mapping("lower", raw_table(lower_f.name, lower_f.data)))
    except ValueError as e:
        run.error, run.error_title = str(e), "파일을 읽지 못했어요"
        return run

    if cad_f is not None:
        digest = hashlib.md5(cad_f.data).hexdigest()
        run.base_plan = cad_plan(digest, cad_f.data, None)
        if not run.base_plan.polygon_layers:
            run.error, run.error_title = ("도면에서 방 경계선(닫힌 폴리라인)을 찾지 못했어요. 도면 파일을 확인해 주세요.",
                                          "도면 문제")
            return run
        run.layer = st.session_state.get("room_layer")
        if run.layer not in run.base_plan.polygon_layers:
            run.layer = run.base_plan.room_layer
        run.plan = cad_plan(digest, cad_f.data, run.layer)

    settings = job_settings()
    names = st.session_state.room_names if run.plan is not None else {}
    maps = {k: mapping(k, raw_table(files[k].name, files[k].data)) for k in ("upper", "lower")}
    run.key = fingerprint(upper_f.data, lower_f.data, cad_f.data if cad_f else b"", run.layer, settings,
                          sorted(names.items()), maps)
    try:
        run.result = _analyze(run.key, upper, lower, run.plan, settings, names)
    except ValueError as e:
        run.error, run.error_title = str(e), "계산하지 못했어요"
        return run
    if run.plan is not None and not run.result.points["in_room"].any():
        t = run.result.transform
        run.error_title = "도면과 스캔 파일이 서로 맞지 않아요"
        run.error = (f"측정점 {len(run.result.points)}개가 모두 도면의 방 밖에 놓였어요"
                     + (f" (좌표 맞춤 오차 {t.rms_m:.1f}m)" if t is not None else "")
                     + ". 도면(DXF)과 위층·아래층 스캔이 같은 현장·같은 층의 파일인지 확인해 주세요. "
                       "이름이 같은 다른 폴더의 파일을 올린 경우가 많아요.")
        run.result = None
        return run
    _autosave(run, settings)
    return run


def verdict(result: AnalysisResult) -> tuple[str, int, int, int]:
    """(적합/미달/판정불가 중 대표 판정, 통과 방 수, 미달 방 수, 판정한 방 수)."""
    rooms = result.rooms
    n_ok = int((rooms["judgement"] == "적합").sum())
    n_bad = int((rooms["judgement"] == "미달").sum())
    n = n_ok + n_bad
    if result.plan is None:
        limit = result.settings.design_mm - result.settings.tolerance_mm
        key = "적합" if result.summary["mean_mm"] >= limit else "미달"
    else:
        key = "미달" if n_bad else ("적합" if n_ok else "판정불가")
    return key, n_ok, n_bad, n


def _autosave(run: Run, settings: Settings) -> None:
    """계산된 작업을 작업 내역에 저장하거나(처음) 바뀐 부분만 고친다."""
    ss = st.session_state
    result = run.result
    key, n_ok, n_bad, n = verdict(result)
    sm = result.summary
    record = {
        "dong": run.meta["동"], "upper_floor": run.meta["상부층"], "lower_floor": run.meta["하부층"],
        "settings": to_dict(settings), "room_names": dict(ss.room_names), "layer": run.layer,
        "columns": {k: ss[k] for k in _col_keys() if k in ss},
        "summary": {"verdict": key, "n_ok": n_ok, "n_bad": n_bad, "n_rooms": n,
                    "mean_mm": None if pd.isna(sm["mean_mm"]) else round(float(sm["mean_mm"]), 1),
                    "n_valid": int(sm["n_valid"]), "n_points": int(sm["n_points"]),
                    "bad_rooms": list(result.rooms.loc[result.rooms["judgement"] == "미달", "room"])[:20]},
    }
    job_id = ss.get("job_id")
    if job_id and history.get_job(job_id) is not None:
        history.update_job(job_id, ss.files, **record)
    else:
        ss.job_id = history.create_job(ss.files, record)
        st.query_params["job"] = ss.job_id
        ss.job_settings = record["settings"]


# ------------------------------------------------------------------ 사이드바
def sidebar_status(run: Run | None = None) -> None:
    """왼쪽 메뉴 아래에 지금 열린 작업을 담담하게 보여 주고, 결과로 바로 가는 링크를 둔다."""
    from slab import __version__

    with st.sidebar:
        job = history.get_job(st.session_state.get("job_id", "")) if st.session_state.get("job_id") else None
        if job is None:
            st.caption("열린 작업 없음")
            st.page_link("views/analysis.py", label="새 분석 시작", icon=":material/add:")
        else:
            s = job.get("summary", {})
            st.caption("지금 작업")
            st.markdown(f"**{history.display_name(job)}**")
            if s.get("n_rooms"):
                st.caption(f"통과 {s['n_ok']} / {s['n_rooms']}개 방 · 평균 {s.get('mean_mm') or '-'}mm")
            st.page_link("views/analysis.py", label="결과 보기", icon=":material/visibility:")
            st.page_link("views/report.py", label="보고서·내려받기", icon=":material/description:")
            st.button("작업 닫기", icon=":material/close:", on_click=clear_files, type="tertiary", key="side_clear")
        st.caption(f"v{__version__}")


# ------------------------------------------------------------------ 작업 내역 표
VERDICT_LABELS = {"적합": "✅ 통과", "미달": "❌ 미달 있음", "판정불가": "– 판정 못 함"}


def jobs_frame(jobs: list[dict]) -> pd.DataFrame:
    """작업 내역 목록을 화면 표로."""
    rows = []
    for j in jobs:
        s = j.get("summary", {})
        rows.append({
            "id": j["id"],
            "작업": history.display_name(j),
            "동": j.get("dong", ""),
            "위층": j.get("upper_floor", ""),
            "아래층": j.get("lower_floor", ""),
            "판정": VERDICT_LABELS.get(s.get("verdict"), "-"),
            "통과 방": f"{s.get('n_ok', 0)} / {s.get('n_rooms', 0)}" if s.get("n_rooms") else "-",
            "평균(mm)": s.get("mean_mm"),
            "메모": j.get("memo", ""),
            "수정": pd.to_datetime(j.get("updated")),
        })
    return pd.DataFrame(rows, columns=["id", "작업", "동", "위층", "아래층", "판정", "통과 방", "평균(mm)", "메모", "수정"])


def open_and_go(job_id: str) -> None:
    if open_job(job_id):
        st.switch_page("views/analysis.py")
    st.error("이 작업의 입력 파일을 찾지 못해 열 수 없어요. 작업 내역 폴더가 옮겨졌는지 확인해 주세요.")
