"""여러 화면이 함께 쓰는 입력 파일·층 목록·계산 결과·작업 내역.

- 올린 파일은 session_state["files"] 에 {파일 이름: 바이트}로 둔다. 여러 층의 스캔(CSV·엑셀)과 도면(DXF)을 섞어 받는다.
- 층은 파일 안의 바닥 높이로 찾고(slab/batch.py), 바로 아래 층과 짝지어 층마다 두께를 계산한다.
- 사용자가 고친 층 이름·도면 배정·방 이름은 세션에 두어 화면을 옮겨도 남고, 작업 내역에도 저장한다.
- 층마다 계산은 입력·설정·방 이름의 지문으로 캐시해서, 화면을 바꿔도 다시 계산하지 않는다.
- 모든 층이 계산되면 작업 내역(slab/history.py)에 자동으로 저장한다. 작업마다 계산할 때 쓴 설정을 함께 둔다.
"""
from __future__ import annotations

import hashlib
import threading
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st

from slab import AnalysisResult, Settings, analyze, history, load_cad, read_table, standardize_grid
from slab.batch import Pair, Plan, guess_dong, kind_of, make_floor, plan_floors
from slab.core import DEFAULT_COLUMNS, STATE_OK, CadPlan
from slab.settings_store import from_dict, load_settings, load_ui, to_dict

ROOT = Path(__file__).resolve().parents[1]
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
FLOOR_KEY = "floor_sel"  # 지금 보는 층 (두께 분석·보고서 화면이 함께 쓴다)


class File:
    """세션에 둔 파일을 slab 함수가 읽을 수 있게 감싼다."""

    def __init__(self, name: str, data: bytes):
        self.name, self.data = name, data

    def getvalue(self) -> bytes:
        return self.data


def is_preview() -> bool:
    """미리보기 모드(꾸밈 없는 초창기 화면)인지. 설정 → 화면에서 켠다."""
    return load_ui()["preview_mode"]


def main_page() -> str:
    """파일을 올리고 결과를 보는 화면 (미리보기 모드면 views/preview.py)."""
    return "views/preview.py" if is_preview() else "views/analysis.py"


def init_state() -> None:
    ss = st.session_state
    for k in ("files", "room_names", "floor_labels", "cad_choice"):
        if k not in ss:
            ss[k] = {}
    ss.setdefault("up_n", 0)


# ------------------------------------------------------------------ 작업 (열기·새로 시작)
def _col_keys() -> list[str]:
    return [f"col_{k}" for k in COLUMN_LABELS]


def clear_files() -> None:
    """새 작업: 올린 파일과 지금 열린 작업을 비운다."""
    ss = st.session_state
    for k in ("files", "room_names", "floor_labels", "cad_choice"):
        ss[k] = {}
    for k in ("job_id", "job_settings", "job_opened", "auto_opened", "_auto_dong", "meta_dong", "room_layer", FLOOR_KEY,
              "pt_pick", "room_zoom", "_pick_from_map", *_col_keys()):
        ss.pop(k, None)
    ss.up_n = ss.get("up_n", 0) + 1  # 올리기 칸도 비운다
    st.query_params.pop("job", None)


def _from_old_job(job: dict, files: dict[str, bytes]) -> tuple[dict, dict]:
    """v0.2 작업(위층·아래층·도면 한 벌)의 층 이름과 방 이름을 새 형식으로."""
    info = job.get("files") or {}
    labels, names = {}, {}
    if isinstance(info, dict):
        for kind, field_ in (("upper", "upper_floor"), ("lower", "lower_floor")):
            if kind in info and job.get(field_):
                labels[info[kind]["name"]] = job[field_]
        if "cad" in info and job.get("room_names"):
            names = {info["cad"]["name"]: dict(job["room_names"])}
    return labels, names


def open_job(job_id: str) -> bool:
    """작업 내역의 작업을 지금 작업으로 연다 (파일·이름·설정을 그때 그대로)."""
    job = history.get_job(job_id)
    files = history.load_files(job_id)
    if job is None or not any(kind_of(n) == "scan" for n in files):
        return False
    clear_files()
    ss = st.session_state
    ss.files = files
    if isinstance(job.get("files"), dict):
        ss.floor_labels, ss.room_names = _from_old_job(job, files)
    else:
        ss.floor_labels = dict(job.get("floor_labels") or {})
        ss.room_names = {k: dict(v) for k, v in (job.get("room_names") or {}).items()}
        ss.cad_choice = dict(job.get("cad_choice") or {})
    ss.job_id = job_id
    ss.job_opened = True
    st.query_params["job"] = job_id
    ss.job_settings = job.get("settings") or to_dict(load_settings())
    ss.meta_dong = job.get("dong", "")
    if job.get("layer"):
        ss.room_layer = job["layer"]
    for k, v in (job.get("columns") or {}).items():
        if k.startswith("col_upper_"):  # v0.2: 위층 열 지정을 모든 스캔에
            k = "col_" + k[len("col_upper_"):]
        if k in _col_keys():
            ss[k] = v
    return True


def open_last_job() -> bool:
    """가장 최근에 고친 작업을 연다 (입력 파일이 남아 있는 것 중에서)."""
    for job in history.list_jobs()[:5]:
        if open_job(job["id"]):
            st.session_state.auto_opened = True
            return True
    return False


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
def upload_key() -> str:
    return f"up_files_{st.session_state.get('up_n', 0)}"


def store_uploads(key: str) -> None:
    """file_uploader 의 on_change: 올린 파일을 세션 목록에 더하고 올리기 칸을 비운다 (같은 이름은 바꾼다)."""
    ups = st.session_state.get(key) or []
    if not ups:
        return
    ss = st.session_state
    if ss.get("job_opened"):  # 내역에서 연 작업에 파일을 더하면 새 작업으로 본다 (원래 작업은 그대로)
        ss.pop("job_id", None)
        ss.job_opened = False
        st.query_params.pop("job", None)
    added = 0
    for up in ups:
        name = Path(up.name).name
        if kind_of(name):
            ss.files[name] = up.getvalue()
            added += 1
    ss.up_n = ss.get("up_n", 0) + 1
    # 동 이름: 비어 있거나 전에 자동으로 채운 값이면 파일 이름에서 다시 찾는다 (직접 쓴 값은 그대로)
    dong = next((d for d in map(guess_dong, sorted(ss.files)) if d), "")
    if dong and ss.get("meta_dong", "") in ("", ss.get("_auto_dong")):
        ss.meta_dong = dong
        ss._auto_dong = dong
    ss._added = added


def remove_files(names: list[str]) -> None:
    ss = st.session_state
    for n in names:
        ss.files.pop(n, None)
        ss.room_names.pop(n, None)
        ss.floor_labels.pop(n, None)
    ss.cad_choice = {k: v for k, v in ss.cad_choice.items() if v in ss.files or v == ""}


def dong() -> str:
    return st.session_state.get("meta_dong") or ""


def meta_of(pair: Pair) -> dict:
    return {"동": dong(), "상부층": pair.upper.label, "하부층": pair.lower.label if pair.lower else ""}


def title_of(m: dict) -> str:
    return f"{m['동']} {m['상부층']}-{m['하부층']} 슬래브 두께".strip()


def stem_of(m: dict) -> str:
    return f"{m['동']}_{m['상부층']}-{m['하부층']}_슬래브두께".replace(" ", "").strip("_") or "슬래브두께"


# ------------------------------------------------------------------ 캐시
@st.cache_data(show_spinner=False, max_entries=400)
def raw_table(name: str, data: bytes) -> pd.DataFrame:
    return read_table(File(name, data))


@st.cache_resource(show_spinner=False, max_entries=300)
def cad_plan(digest: str, data: bytes, room_layer: str | None) -> CadPlan:
    return load_cad(File("cad.dxf", data), room_layer)


@st.cache_resource(show_spinner=False, max_entries=400)
def _analyze(key: str, _upper, _lower, _plan, _settings, _names) -> AnalysisResult:
    """key 는 입력 파일·설정·방 이름을 묶은 지문. 같은 입력이면 다시 계산하지 않는다.
    결과는 복사하지 않고 함께 쓴다(층이 많아도 빠르게). 결과를 고치는 코드는 없다."""
    return analyze(_upper, _lower, _plan, _settings, _names)


_MEMO: OrderedDict = OrderedDict()
_MEMO_LOCK = threading.Lock()


def memo(key, fn, max_entries: int = 40):
    """내려받기 파일용 캐시. 내려받기 버튼은 누르는 순간(화면 실행 밖)에 파일을 만들어서 st.cache_data·st.progress·
    session_state 를 쓰면 'missing ScriptRunContext' 경고가 쏟아진다. 그래서 Streamlit 을 쓰지 않는 단순 캐시를 둔다."""
    with _MEMO_LOCK:
        if key in _MEMO:
            _MEMO.move_to_end(key)
            return _MEMO[key]
    value = fn()
    with _MEMO_LOCK:
        _MEMO[key] = value
        while len(_MEMO) > max_entries:
            _MEMO.popitem(last=False)
    return value


def fingerprint(*parts) -> str:
    h = hashlib.md5()
    for p in parts:
        h.update(p if isinstance(p, bytes) else repr(p).encode())
    return h.hexdigest()


def mapping(raw: pd.DataFrame) -> dict:
    """열 지정 위젯 값(세션)을 standardize_grid 용 사전으로. 지정이 없으면 기본 열 이름. 모든 스캔에 같이 쓴다."""
    out = {}
    for k in COLUMN_LABELS:
        sel = st.session_state.get(f"col_{k}")
        if sel is None or (sel != NONE and sel not in raw.columns):
            sel = DEFAULT_COLUMNS[k] if DEFAULT_COLUMNS[k] in raw.columns else NONE
        out[k] = sel if sel != NONE else f"__missing_{k}"
    return out


@dataclass
class FloorRun:
    """층 하나(위층 바닥 / 아래층 천장)의 계산."""

    pair: Pair
    meta: dict
    plan: CadPlan | None = None
    base_plan: CadPlan | None = None
    layer: str | None = None
    result: AnalysisResult | None = None
    key: str = ""
    error: str = ""
    error_title: str = ""

    @property
    def ok(self) -> bool:
        return self.result is not None


@dataclass
class Batch:
    """올린 파일 전체: 층 목록과 층마다 계산."""

    names: list[str]
    plan: Plan = field(default_factory=Plan)
    runs: list[FloorRun] = field(default_factory=list)  # 위층부터
    settings: Settings = field(default_factory=Settings)
    read_errors: dict[str, str] = field(default_factory=dict)
    n_scans: int = 0
    n_cads: int = 0
    done: bool = False  # 모든 층을 계산했는지

    @property
    def ready(self) -> list[FloorRun]:
        return [r for r in self.runs if r.ok]

    def run_of(self, key: str | None) -> FloorRun | None:
        return next((r for r in self.runs if r.pair.key == key), None)


def _cad(name: str, layer: str | None) -> tuple[CadPlan | None, CadPlan | None, str | None, str]:
    """(기본 도면, 레이어를 고른 도면, 레이어, 오류)."""
    data = st.session_state.files[name]
    digest = hashlib.md5(data).hexdigest()
    try:
        base = cad_plan(digest, data, None)
    except Exception as e:  # 깨진 DXF
        return None, None, None, f"{name}: 도면을 읽지 못했어요 ({e})"
    if not base.polygon_layers:
        return base, None, None, f"{name}: 도면에서 방 경계선(닫힌 폴리라인)을 찾지 못했어요."
    if layer not in base.polygon_layers:
        layer = base.room_layer
    return base, cad_plan(digest, data, layer), layer, ""


def load_batch() -> Batch:
    """파일을 읽어 층을 찾고 짝짓는다 (두께 계산은 아직 안 함)."""
    init_state()
    ss = st.session_state
    names = sorted(ss.files)
    b = Batch(names, settings=job_settings())
    scans = [n for n in names if kind_of(n) == "scan"]
    cads = [n for n in names if kind_of(n) == "cad"]
    b.n_scans, b.n_cads = len(scans), len(cads)
    floors = []
    for n in scans:
        try:
            raw = raw_table(n, ss.files[n])
            grid = standardize_grid(raw, mapping(raw))
            floors.append(make_floor(n, raw, grid, b.settings.xy_unit, b.settings.z_unit))
        except ValueError as e:
            b.read_errors[n] = str(e)
    plans = {}
    for n in cads:
        base, plan, _, err = _cad(n, ss.get("room_layer"))
        plans[n] = plan
        if err:
            b.read_errors[n] = err
    b.plan = plan_floors(floors, plans, ss.floor_labels, ss.cad_choice)
    for p in b.plan.pairs:
        b.runs.append(FloorRun(p, meta_of(p)))
    return b


def compute_floor(b: Batch, run: FloorRun) -> FloorRun:
    """층 하나 계산 (캐시가 있으면 바로 돌아온다)."""
    if run.result is not None or run.error:
        return run
    p = run.pair
    if p.problem:
        run.error, run.error_title = p.problem, "계산하지 않은 층"
        return run
    ss = st.session_state
    if p.cad:
        run.base_plan, run.plan, run.layer, err = _cad(p.cad, ss.get("room_layer"))
        if err:
            run.error, run.error_title = err, "도면 문제"
            return run
    names = ss.room_names.get(p.cad, {}) if run.plan is not None else {}
    up, lo = p.upper, p.lower
    run.key = fingerprint(ss.files[up.scan], ss.files[lo.scan], ss.files[p.cad] if p.cad else b"", run.layer,
                          b.settings, sorted(names.items()), mapping(raw_table(up.scan, ss.files[up.scan])))
    try:
        run.result = _analyze(run.key, up.grid, lo.grid, run.plan, b.settings, names)
    except ValueError as e:
        run.error, run.error_title = str(e), "계산하지 못했어요"
        return run
    if run.plan is not None and not run.result.points["in_room"].any():
        t = run.result.transform
        run.error_title = "도면과 스캔 파일이 서로 맞지 않아요"
        run.error = (f"측정점 {len(run.result.points)}개가 모두 도면 {p.cad}의 방 밖에 놓였어요"
                     + (f" (좌표 맞춤 오차 {t.rms_m:.1f}m)" if t is not None else "")
                     + f". 도면이 {up.label} 층의 것인지 확인해 주세요. '자세히 보기 → 층·도면 고치기'에서 바꿀 수 있어요.")
        run.result = None
    return run


def compute_all(b: Batch, progress: bool = True) -> Batch:
    """모든 층을 계산한다. 처음 계산할 때만 진행 막대를 보인다. 다 되면 작업 내역에 저장한다."""
    todo = [r for r in b.runs if r.result is None and not r.error]
    bar = st.progress(0.0, text="층별 두께 계산 중…") if progress and len(todo) > 3 else None
    for i, r in enumerate(todo):
        if bar:
            bar.progress(i / len(todo), text=f"층별 두께 계산 중… {r.pair.title} ({i + 1}/{len(todo)})")
        compute_floor(b, r)
    if bar:
        bar.empty()
    b.done = True
    if b.ready:
        _autosave(b)
    return b


def compute(progress: bool = True) -> Batch:
    b = load_batch()
    return compute_all(b, progress) if b.runs else b


# ------------------------------------------------------------------ 요약·저장
def floors_text(b: Batch) -> str:
    ready = b.ready
    if not ready:
        return ""
    if len(ready) == 1:
        r = ready[0]
        return f"{r.pair.upper.label}-{r.pair.lower.label}"
    return f"{ready[-1].pair.upper.label}~{ready[0].pair.upper.label} ({len(ready)}개 층)"


def overall(b: Batch) -> dict:
    """모든 층을 합친 숫자 ('산출 완료' 점의 평균 등)."""
    pts = [r.result.points for r in b.ready]
    allp = pd.concat(pts, ignore_index=True) if pts else pd.DataFrame(columns=["status", "thickness_mm"])
    v = allp.loc[allp["status"] == STATE_OK, "thickness_mm"]
    sms = [r.result.summary for r in b.ready]
    return {
        "n_floors": len(b.ready),
        "n_points": int(sum(s["n_points"] for s in sms)),
        "n_valid": int(len(v)),
        "n_review": int(sum(s["n_review"] for s in sms)),
        "n_no_value": int(sum(s["n_no_value"] for s in sms)),
        "mean_mm": float(v.mean()) if len(v) else np.nan,
        "min_mm": float(v.min()) if len(v) else np.nan,
        "max_mm": float(v.max()) if len(v) else np.nan,
    }


def _r1(v):
    return None if v is None or not np.isfinite(v) else round(float(v), 1)


def _autosave(b: Batch) -> None:
    """계산된 작업을 작업 내역에 저장하거나(처음) 바뀐 부분만 고친다."""
    ss = st.session_state
    o = overall(b)
    record = {
        "dong": dong(), "floors_text": floors_text(b),
        "settings": to_dict(b.settings), "room_names": {k: dict(v) for k, v in ss.room_names.items()},
        "floor_labels": dict(ss.floor_labels), "cad_choice": dict(ss.cad_choice), "layer": ss.get("room_layer"),
        "columns": {k: ss[k] for k in _col_keys() if k in ss},
        "summary": {
            "n_floors": o["n_floors"], "mean_mm": _r1(o["mean_mm"]), "min_mm": _r1(o["min_mm"]),
            "max_mm": _r1(o["max_mm"]), "n_valid": o["n_valid"], "n_points": o["n_points"],
            "n_review": o["n_review"], "n_no_value": o["n_no_value"],
            "floors": [{"upper": r.pair.upper.label, "lower": r.pair.lower.label if r.pair.lower else "",
                        "mean_mm": _r1(r.result.summary["mean_mm"]) if r.ok else None,
                        "problem": r.error} for r in b.runs],
        },
    }
    job_id = ss.get("job_id")
    if job_id and history.get_job(job_id) is not None:
        history.update_job(job_id, ss.files, **record)
    else:
        ss.job_id = history.create_job(ss.files, record)
        st.query_params["job"] = ss.job_id
        ss.job_settings = record["settings"]


# ------------------------------------------------------------------ 층 고르기
def floor_options(b: Batch) -> list[str]:
    return [r.pair.key for r in b.runs]


def current_floor(b: Batch) -> FloorRun | None:
    """지금 고른 층. 고른 적이 없거나 사라졌으면 계산된 맨 위층."""
    opts = floor_options(b)
    if not opts:
        return None
    sel = st.session_state.get(FLOOR_KEY)
    if sel not in opts:
        first = next((r.pair.key for r in b.runs if r.ok), opts[0])
        st.session_state[FLOOR_KEY] = sel = first
    return b.run_of(sel)


def step_floor(opts: list[str], delta: int) -> None:
    """층 이동 버튼: delta=-1 은 위층, +1 은 아래층 (목록이 위층부터라)."""
    ss = st.session_state
    i = opts.index(ss[FLOOR_KEY]) if ss.get(FLOOR_KEY) in opts else 0
    ss[FLOOR_KEY] = opts[min(max(i + delta, 0), len(opts) - 1)]
    ss.pop("pt_pick", None)
    ss.pop("_pick_from_map", None)
    ss.pop("room_zoom", None)


def floor_label(b: Batch, key: str) -> str:
    r = b.run_of(key)
    if r is None:
        return key
    p = r.pair
    text = f"{p.upper.label} 바닥 / {p.lower.label} 천장" if p.lower else f"{p.upper.label} (맨 아래층)"
    if r.ok:
        m = r.result.summary["mean_mm"]
        text += f" · 평균 {m:.0f}mm" if np.isfinite(m) else " · 값 없음"
    else:
        text += " · 계산 안 됨"
    return text


def floor_nav(b: Batch, where: str) -> FloorRun | None:
    """층 고르기 콤보박스 + 위층/아래층 버튼. 두께 분석·보고서 화면이 같은 값을 쓴다."""
    opts = floor_options(b)
    run = current_floor(b)
    if run is None:
        return None
    i = opts.index(run.pair.key)
    with st.container(horizontal=True, vertical_alignment="bottom", key=f"nav_{where}"):
        st.selectbox("층 고르기", opts, key=FLOOR_KEY, format_func=lambda k: floor_label(b, k), width=420,
                     persist_state="session",
                     help="목록에서 층을 고르세요. 글자를 쳐서 찾을 수도 있어요 (예: 15F).",
                     on_change=lambda: [st.session_state.pop(k, None) for k in ("pt_pick", "room_zoom", "_pick_from_map")])
        st.button("위층", icon=":material/arrow_upward:", disabled=i == 0, key=f"up_{where}",
                  on_click=step_floor, args=(opts, -1))
        st.button("아래층", icon=":material/arrow_downward:", disabled=i == len(opts) - 1, key=f"down_{where}",
                  on_click=step_floor, args=(opts, 1))
        st.caption(f"{i + 1} / {len(opts)}번째 층")
    return b.run_of(st.session_state[FLOOR_KEY])


# ------------------------------------------------------------------ 사이드바
def sidebar_status(b: Batch | None = None) -> None:
    """왼쪽 메뉴 아래에 지금 열린 작업을 담담하게 보여 주고, 결과로 바로 가는 링크를 둔다."""
    from slab import __version__

    if is_preview():  # 미리보기 모드: 안내 없이 버전만
        st.sidebar.caption(f"v{__version__}")
        return
    with st.sidebar:
        job = history.get_job(st.session_state.get("job_id", "")) if st.session_state.get("job_id") else None
        if job is None:
            st.caption("열린 작업 없음")
            st.page_link("views/analysis.py", label="새 분석 시작", icon=":material/add:")
        else:
            s = job.get("summary", {})
            st.caption("지금 작업")
            st.markdown(f"**{history.display_name(job)}**")
            if s.get("n_floors"):
                st.caption(f"{s['n_floors']}개 층 · 평균 {s.get('mean_mm') or '-'}mm")
            st.page_link("views/analysis.py", label="결과 보기", icon=":material/visibility:")
            st.page_link("views/report.py", label="보고서·내려받기", icon=":material/description:")
            st.button("작업 닫기", icon=":material/close:", on_click=clear_files, type="tertiary", key="side_clear")
        st.caption(f"v{__version__}")


# ------------------------------------------------------------------ 작업 내역 표
def jobs_frame(jobs: list[dict]) -> pd.DataFrame:
    """작업 내역 목록을 화면 표로."""
    rows = []
    for j in jobs:
        s = j.get("summary", {})
        n_floors = s.get("n_floors", 1 if s.get("n_points") else 0)
        floors = j.get("floors_text") or "-".join(x for x in (j.get("upper_floor"), j.get("lower_floor")) if x)
        rows.append({
            "id": j["id"],
            "작업": history.display_name(j),
            "동": j.get("dong", ""),
            "층": floors,
            "층 수": n_floors,
            "평균(mm)": s.get("mean_mm"),
            "검토·미산출 점": f"{s.get('n_review', 0)} / {s.get('n_no_value', 0)}" if "n_review" in s else "-",
            "메모": j.get("memo", ""),
            "수정": pd.to_datetime(j.get("updated")),
        })
    return pd.DataFrame(rows, columns=["id", "작업", "동", "층", "층 수", "평균(mm)", "검토·미산출 점", "메모", "수정"])


def open_and_go(job_id: str) -> None:
    if open_job(job_id):
        st.switch_page(main_page())
    st.error("이 작업의 입력 파일을 찾지 못해 열 수 없어요. 작업 내역 폴더가 옮겨졌는지 확인해 주세요.")
