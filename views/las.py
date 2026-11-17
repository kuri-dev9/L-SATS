"""LAS 변환 화면: 층마다 한 개인 레이저 스캔 점군(LAS/LAZ)에서 같은 격자의 바닥·천장 높이 파일을 만든다.

원본이 1GB 넘게 커서 올리지 않고, 프로그램이 도는 이 PC의 폴더에서 바로 읽는다 (slab/las.py).
① 폴더 고르기(이 PC 의 기본 폴더 선택 창: Windows 탐색기 / Mac Finder) → ② 변환할 파일 고르기 → ③ 변환 → ④ 결과 보기 → ⑤ 저장.
마지막으로 연 폴더와 저장 폴더는 user_settings.json(ui)에 남겨 다음에 그 자리에서 이어 쓴다.
미리보기 모드에서는 메뉴에 나오지 않는다.
"""
from __future__ import annotations

import io
import zipfile
from dataclasses import asdict
from pathlib import Path

import pandas as pd
import streamlit as st

from slab.las import (
    DXF_NAME, GRID_FILE, LAS_TYPES, OUT_DIR, GridSpec, LasParams, convert, export_results, stored_result, find_las_files, floor_label,
    las_info,
)
from slab.settings_store import load_ui, update_ui
from views.folder_pick import native_pick
from views.shared import clear_files, job_settings, sidebar_status

ss = st.session_state
REMOTE = st.context.ip_address is not None  # 다른 PC 에서 접속 (localhost 면 None)


@st.cache_data(show_spinner=False, max_entries=20)
def _plan_fig(dxf_path: str, mtime: float, csv_path: str, csv_mtime: float = 0.0):
    from slab.las_plan import plan_figure

    from slab.las_layout import load_plan

    p = Path(dxf_path)
    plan = load_plan(p.parent, p.stem.replace("LAS_평면도_", "", 1))
    return plan_figure(p.read_bytes(), pd.read_csv(csv_path), plan)


@st.cache_data(show_spinner=False, max_entries=500)
def _info(path: str, mtime: float, size: int) -> dict:
    return las_info(Path(path))


# ---------------------------------------------------------------- 폴더 이동 (마지막 폴더는 설정에 저장)
def _go(path: str) -> None:
    p = Path(str(path).strip().strip('"'))
    if p.is_dir():
        ss.las_dir = str(p.resolve())
        ss.las_path_in = ss.las_dir  # 콜백·화면 맨 위에서만 부른다 (입력 칸을 그린 뒤에는 못 바꾼다)
        update_ui(las_last_folder=ss.las_dir)
    else:
        ss.las_path_in = ss.get("las_dir", "")
        ss._las_bad_path = str(path)


def _typed() -> None:
    _go(ss.las_path_in)


def _pick_dialog() -> None:
    try:
        picked = native_pick(ss.get("las_dir", ""), "LAS·LAZ 파일이 든 폴더를 고르세요")
    except RuntimeError as e:
        ss._las_pick_error = str(e)
        return
    if picked:
        _go(picked)


def _set_all(on: bool) -> None:
    ss.las_sel_all = on
    ss.las_editor_v = ss.get("las_editor_v", 0) + 1


def _send_to_analysis(paths: list[str]) -> None:
    clear_files()
    ss.files = {Path(p).name: Path(p).read_bytes() for p in paths}


if "las_dir" not in ss:
    start = load_ui()["las_last_folder"]
    ss.las_dir = start if start and Path(start).is_dir() else str(Path.home())
if not ss.get("las_path_in"):  # 다른 화면에 다녀오면 Streamlit 이 입력 칸 값을 지운다
    ss.las_path_in = ss.las_dir

st.title("LAS 변환", icon=":material/grid_on:")
st.caption("층마다 하나씩 있는 레이저 스캔 점군(LAS·LAZ)에서, 모든 층에 같은 격자를 놓고 격자점마다 바닥·천장 높이를 뽑아 "
           "두께 분석용 파일을 만듭니다. 파일이 커서 올리지 않고 이 PC의 폴더에서 바로 읽어요.")
if REMOTE:  # 서버 PC 의 폴더를 읽고 폴더 선택 창도 서버 PC 화면에 뜨므로, 다른 PC 에서는 쓰지 못하게 막는다
    st.warning("LAS 변환은 프로그램이 설치된 PC 에서만 쓸 수 있어요.\n\n"
               "LAS 파일이 너무 커서 올리지 않고, 프로그램이 설치된 PC 의 폴더에서 바로 읽기 때문이에요. "
               "다른 PC 에서 접속한 지금은 이 기능을 쓸 수 없습니다. "
               "프로그램이 설치된 PC 에서 직접 열어 주세요 (그 PC 의 브라우저 주소: `http://localhost:8501`).\n\n"
               "변환한 결과(CSV)는 두께 분석에서 올려 쓰면 어디서든 볼 수 있어요.",
               title="다른 PC 에서는 쓸 수 없는 기능이에요", icon=":material/desktop_access_disabled:")
    sidebar_status()
    st.stop()

# ---------------------------------------------------------------- ① 폴더 고르기
with st.container(border=True):
    st.subheader("① 폴더 고르기", icon=":material/folder_open:")
    if ss.pop("_las_bad_path", None):
        st.warning("그 폴더를 찾지 못했어요. 경로를 다시 확인해 주세요.", icon=":material/warning:")
    if err := ss.pop("_las_pick_error", None):
        st.warning(err, icon=":material/warning:")
    with st.container(horizontal=True, vertical_alignment="bottom"):
        st.text_input("지금 폴더", key="las_path_in", on_change=_typed,
                      help="「폴더 선택」으로 고르거나 경로를 붙여 넣고 Enter 를 누르세요. "
                           "마지막으로 연 폴더는 기억해 두었다가 다음에 바로 열어요.")
        st.button("폴더 선택", type="primary", icon=":material/folder_open:", on_click=_pick_dialog, key="las_dialog",
                  help="이 PC 의 폴더 선택 창(Windows 탐색기 / Mac Finder)을 엽니다. 창은 프로그램이 도는 PC 화면에 떠요.")
    recursive = st.toggle("하위 폴더의 파일도 찾기", key="las_recursive")

folder_p = Path(ss.las_dir)
files = find_las_files(folder_p, recursive)

# ---------------------------------------------------------------- ② 파일 고르기
with st.container(border=True):
    st.subheader("② 변환할 파일 고르기", icon=":material/checklist:")
    if not files:
        st.info(f"이 폴더에 LAS·LAZ 파일이 없어요 (`{folder_p}`). 위에서 다른 폴더를 골라 주세요. "
                "화면 없이 하려면 프로그램 폴더의 `LAS_TO_GRID.bat` 에 LAS 폴더를 끌어다 놓아도 돼요.",
                icon=":material/info:")
        sidebar_status()
        st.stop()
    rows, bad = [], []
    for f in files:
        stat = f.stat()
        try:
            i = _info(str(f), stat.st_mtime, stat.st_size)
        except Exception as e:  # 깨진 파일·지원하지 않는 형식
            bad.append(f"{f.name}: {e}")
            continue
        rows.append({"선택": ss.get("las_sel_all", True), "파일": str(f.relative_to(folder_p)), "층": floor_label(f),
                     "점 수": i["points"], "크기(MB)": i["size_mb"],
                     "높이 범위(m)": f"{i['z'][0]:.2f} ~ {i['z'][1]:.2f}"})
    for b in bad:
        st.error(b, title="읽지 못한 파일", icon=":material/error:")
    with st.container(horizontal=True):
        st.button("모두 선택", icon=":material/select_all:", on_click=_set_all, args=(True,), key="las_all",
                  type="tertiary")
        st.button("모두 해제", icon=":material/deselect:", on_click=_set_all, args=(False,), key="las_none",
                  type="tertiary")
    table = st.data_editor(pd.DataFrame(rows), hide_index=True, width="stretch",
                           key=f"las_files_{folder_p}_{recursive}_{ss.get('las_editor_v', 0)}",
                           disabled=["파일", "점 수", "크기(MB)", "높이 범위(m)"], alt="LAS 파일 목록",
                           column_config={"선택": st.column_config.CheckboxColumn(width="small"),
                                          "점 수": st.column_config.NumberColumn(format="localized")})
    use = table[table["선택"]] if len(table) else table
    st.caption(f"{len(use)} / {len(table)}개 선택. 층 이름이 틀렸으면 **층** 칸을 고치세요. 두께 분석에서 이 이름으로 층을 나열합니다.")

# ---------------------------------------------------------------- ③ 변환
out_dir = folder_p / OUT_DIR
params = LasParams.from_settings(job_settings())
with st.container(border=True):
    st.subheader("③ 변환", icon=":material/play_arrow:")
    old = GridSpec.load(out_dir / GRID_FILE)
    new_grid = False
    if old is not None and abs(old.spacing_m - params.spacing_m) < 1e-9:
        st.markdown(f"이 폴더에 정해 둔 격자를 **모든 층에 그대로** 씁니다: 간격 {old.spacing_m:g} m · "
                    f"건물 축 {old.angle_deg:g}° · {old.nx} × {old.ny} 칸")
        new_grid = st.checkbox("격자 새로 정하기", key="las_new_grid",
                               help="건물 범위가 바뀌었을 때만 쓰세요. 이전에 만든 층 파일과 격자가 달라집니다.")
    else:
        st.markdown(f"처음 변환하면 고른 층들을 모두 덮는 격자를 새로 정해 저장해요 (간격 {params.spacing_m:g} m). "
                    "측량 좌표에서 기울어진 건물 축(벽 방향)을 찾아 격자를 맞추고, 결과 그림도 그 방향으로 반듯하게 그립니다.")
    st.caption(f"작업 폴더: `{out_dir}` (층별 CSV·grid.json) · 격자 간격 등은 설정 → LAS 변환에서 바꿀 수 있어요.")
    go = st.button(f"선택한 {len(use)}개 파일 변환", type="primary", icon=":material/play_arrow:", disabled=use.empty,
                   key="las_go", help="큰 파일은 층마다 1~2분 걸릴 수 있어요. 끝날 때까지 이 화면을 닫지 마세요.")
    if go:
        bar = st.progress(0.0, text="시작하는 중…")
        labels = {Path(n).name: str(l).strip() for n, l in zip(use["파일"], use["층"]) if str(l).strip()}
        try:
            grid, summary, paths = convert([folder_p / n for n in use["파일"]], out_dir, params, labels=labels,
                                           new_grid=new_grid, progress=lambda f, m: bar.progress(min(f, 1.0), text=m))
        except (RuntimeError, ValueError, OSError) as e:
            bar.empty()
            st.error(str(e), title="변환하지 못했어요", icon=":material/error:")
        else:
            bar.empty()
            ss.las_result = {"folder": str(folder_p), "grid": asdict(grid), "summary": summary.to_dict("records"),
                             "paths": [str(p) for p in paths], "labels": list(summary["층"]), "out": str(out_dir)}
            ss.pop("las_new_grid", None)
            update_ui(las_last_folder=str(folder_p))

res = ss.get("las_result")
if not res or res.get("folder") != str(folder_p):  # 이 폴더를 전에 변환해 두었으면 다시 변환하지 않고 바로 보여 준다
    stored = stored_result(out_dir)
    if stored is None:
        sidebar_status()
        st.stop()
    res = ss.las_result = {"folder": str(folder_p), "grid": stored["grid"], "summary": stored["rows"],
                           "paths": stored["paths"], "labels": stored["labels"], "out": str(out_dir),
                           "stored": stored["saved"], "current": stored["current"]}

# ---------------------------------------------------------------- ④ 결과
summary = pd.DataFrame(res["summary"])
g = res["grid"]
with st.container(border=True):
    st.subheader("④ 변환 결과", icon=":material/fact_check:")
    if res.get("stored") is not None:
        st.info(f"전에 변환해 둔 결과를 불러왔어요 ({res['stored']}, {len(res['paths'])}개 층). 다시 변환하지 않아도 돼요. "
                "LAS 파일을 바꿨거나 층을 더했다면 ③에서 변환을 누르세요 — 바뀐 층만 새로 해요.", icon=":material/history:")
        if not res.get("current"):
            st.warning("이 결과는 이전 버전 계산 방식으로 만들어졌어요 (예: 벽 위 격자점을 빼기 전). ③에서 한 번 다시 변환해 주세요.",
                       icon=":material/update:")
    else:
        st.success(f"{len(res['paths'])}개 층을 변환했어요. 격자 간격 {g['spacing_m']:g} m · 건물 축 {g['angle_deg']:g}° · "
                   f"{g['nx']} × {g['ny']} 칸 (모든 층 같은 격자)", icon=":material/check_circle:")
    st.dataframe(summary.drop(columns=["CSV", "도면"], errors="ignore"), hide_index=True, width="stretch", alt="층별 변환 결과")
    st.caption("층고 = 천장면 − 바닥면. 바닥·천장 측정은 그 면의 점이 충분한 격자점 수예요. "
               "벽 위(빈 값) = 격자점이 벽 위에 놓여 슬라브 면을 잴 수 없어 값을 비운 점 (두께 분석에서 미산출). "
               "변환 = 새로 변환 / 저장된 결과(LAS 파일이 그대로라 전에 만든 결과를 씀).")
    lab = st.selectbox("층별로 보기", res["labels"], key="las_view_floor")
    df = pd.read_csv(res["paths"][res["labels"].index(lab)])
    view = df.assign(**{"바닥 편차(mm)": (df["floor_error"] * 1000).round(1),
                        "천장 편차(mm)": (df["ceiling_error"] * 1000).round(1)})
    dxf = Path(res["out"]) / DXF_NAME.format(lab)
    if dxf.exists():
        csv_p = Path(res["paths"][res["labels"].index(lab)])
        ev = st.plotly_chart(_plan_fig(str(dxf), dxf.stat().st_mtime, str(csv_p), csv_p.stat().st_mtime),
                             config={"scrollZoom": True, "displaylogo": False}, height=560,
                             key=f"las_plan_{lab}_{ss.get('las_ex_v', 0)}", on_select="rerun",
                             selection_mode=("points", "box", "lasso"))
        picked = []
        for pt in (ev.selection.get("points", []) if ev and ev.selection else []):
            cd = pt.get("customdata")
            cd = cd[0] if isinstance(cd, list) and cd else cd
            if isinstance(cd, str) and cd not in picked:
                picked.append(cd)
        with st.container(horizontal=True, vertical_alignment="center"):
            if picked:
                st.markdown(f"고른 점: **{', '.join(picked)}**")
            else:
                st.caption("불필요한 점은 그림에서 클릭해 고르세요 (여러 개: Shift+클릭, 또는 위쪽 도구의 박스 선택).")
            if st.button(f"고른 점 빼기 ({len(picked)}개)", icon=":material/delete:", key="las_ex_go", disabled=not picked,
                         help="고른 격자점을 결과(CSV·도면·두께 분석)에서 뺍니다. 다시 변환해도 빠진 채로 있고, 아래에서 되살릴 수 있어요."):
                from slab.las_layout import exclude_points

                k = exclude_points(Path(res["out"]), lab, picked)
                ss.las_ex_v = ss.get("las_ex_v", 0) + 1
                ss._las_ex_msg = f"{lab}: {k}개 점을 뺐어요 ({', '.join(picked)})."
                st.rerun()
        if msg := ss.pop("_las_ex_msg", None):
            st.success(msg, icon=":material/check_circle:")
        from slab.las_layout import load_excluded, restore_points

        gone = sorted(load_excluded(Path(res["out"])).get(lab, {}))
        if gone:
            with st.expander(f"뺀 점 {len(gone)}개 — 되살리기"):
                back = st.multiselect("되살릴 점", gone, key=f"las_ex_back_{lab}_{ss.get('las_ex_v', 0)}")
                if st.button("되살리기", icon=":material/undo:", key="las_ex_restore", disabled=not back):
                    restore_points(Path(res["out"]), lab, back)
                    ss.las_ex_v = ss.get("las_ex_v", 0) + 1
                    st.rerun()
        st.caption("평면도 미리보기 (DXF 와 같은 내용): 검은 선 = 스캔된 벽 면(바닥 위 1.0~1.5 m 단면, 칸막이벽은 두 줄·외벽은 안쪽 면 한 줄), "
                   "회색 띠 = 벽(칸막이벽은 두 면 사이, 외벽은 바깥쪽으로 추정 두께만큼), 빨간 점 = 바닥·천장을 모두 잰 격자점(빈 동그라미는 한쪽만). "
                   "값이 없는 자리(벽 위·건물 밖)의 점은 그리지 않아요. 휠로 확대, 끌어서 이동, 점에 마우스를 올리면 높이가 보여요.")
    else:
        st.info("이 결과에는 평면도가 없어요 (이전 버전으로 변환). ③에서 다시 변환하면 만들어져요.", icon=":material/info:")
    left, right = st.columns([1, 1.3])
    with left:
        st.scatter_chart(view.dropna(subset=["바닥 편차(mm)"]), x="local_x", y="local_y", color="바닥 편차(mm)",
                         size=60, x_label="건물 축 X (m)", y_label="건물 축 Y (m)", height=360,
                         alt=f"{lab} 격자점 바닥 높이 편차")
        st.caption("격자점의 바닥 높이가 층 바닥면보다 얼마나 높고 낮은지 (건물 축에 맞춰 그림)")
    with right:
        st.dataframe(view[["point_id", "grid_row", "grid_col", "x", "y", "floor_z", "ceiling_z", "height_mm",
                           "바닥 편차(mm)", "천장 편차(mm)", "floor_points", "ceiling_points"]],
                     hide_index=True, width="stretch", height=360, alt=f"{lab} 격자점 높이")
    st.markdown("**다음 단계** — 방 이름·범위를 정하면 두께 분석이 방별로 나와요. 방 없이 층 전체로만 보려면 바로 보내도 돼요.")
    c1, c2 = st.columns(2)
    if c1.button("방 배치하기", type="primary", icon=":material/floor_lamp:", width="stretch", key="las_to_rooms",
                 help="이 변환 결과로 「방 배치」 화면을 엽니다."):
        ss.rooms_dir = res["out"]
        st.switch_page("views/las_rooms.py")
    if c2.button("방 없이 두께 분석으로 보내기", icon=":material/arrow_forward:", width="stretch", key="las_send",
                 help="변환한 층들을 새 작업으로 두께 분석에 올립니다 (층 전체 결과만). 지금 작업은 작업 내역에 남아요."):
        _send_to_analysis(res["paths"])
        st.switch_page("views/analysis.py")

# ---------------------------------------------------------------- ⑤ 저장
with st.container(border=True):
    st.subheader("⑤ 파일로 저장", icon=":material/save:")
    with st.container(horizontal=True, vertical_alignment="bottom"):
        mode = st.segmented_control("나누기", ["floor", "single"], default="floor", required=True, key="las_save_mode",
                                    format_func={"floor": "층마다 파일", "single": "하나의 파일"}.get)
        fmt = st.segmented_control("형식", ["csv", "xlsx", "dxf"], default="csv", required=True, key="las_save_fmt",
                                   format_func={"csv": "CSV", "xlsx": "엑셀", "dxf": "DXF 평면도"}.get)
    if not ss.get("las_save_dir"):  # 처음이거나, 다른 화면에 다녀와 입력 칸 값이 지워졌을 때
        ss.las_save_dir = ss.get("_las_save_keep") or load_ui()["las_out_folder"] or str(out_dir)
    if ss.get("_las_save_goto"):  # 폴더 선택 창에서 고른 폴더 (입력 칸을 그리기 전에 넣는다)
        ss.las_save_dir = ss.pop("_las_save_goto")
    with st.container(horizontal=True, vertical_alignment="bottom"):
        st.text_input("저장할 폴더", key="las_save_dir", help="없는 폴더면 새로 만들어요. 마지막 저장 폴더를 기억해요.")
        ss._las_save_keep = ss.las_save_dir
        if st.button("폴더 선택", icon=":material/folder_open:", key="las_save_dialog",
                     help="이 PC 의 폴더 선택 창(Windows 탐색기 / Mac Finder)을 엽니다."):
            try:
                picked = native_pick(ss.las_save_dir, "저장할 폴더를 고르세요")
            except RuntimeError as e:
                picked = None
                st.warning(str(e), icon=":material/warning:")
            if picked:
                ss._las_save_goto = picked
                st.rerun()
    files_out = export_results([Path(p) for p in res["paths"]], res["labels"], mode, fmt, summary)
    names = ", ".join(files_out)
    if fmt == "dxf":
        st.caption("DXF 평면도는 층마다 한 장이에요: 벽(바닥 위 1.0~1.5 m 단면의 곧은 벽)·격자점과 높이, "
                   "건물 축에 맞춰 반듯하게, 단위 mm.")
        if not files_out:
            st.info("이 결과에는 평면도가 없어요 (이전 버전으로 변환). ③에서 다시 변환하면 만들어져요.",
                    icon=":material/info:")
    st.caption(f"만들 파일 {len(files_out)}개: {names} · 격자 정의 grid.json 도 함께 저장해요.")
    a, b = st.columns(2)
    if a.button("폴더에 저장", type="primary", icon=":material/save:", width="stretch", key="las_save"):
        dest = Path(ss.las_save_dir.strip().strip('"'))
        try:
            dest.mkdir(parents=True, exist_ok=True)
            for name, data in files_out.items():
                (dest / name).write_bytes(data)
            gj = Path(res["out"]) / GRID_FILE
            if gj.exists() and dest.resolve() != gj.parent.resolve():
                (dest / GRID_FILE).write_bytes(gj.read_bytes())
        except OSError as e:
            st.error(f"저장하지 못했어요: {e}", icon=":material/error:")
        else:
            update_ui(las_out_folder=str(dest))
            st.success(f"{len(files_out)}개 파일을 저장했어요: `{dest}`", icon=":material/check_circle:")

    grid_bytes = (Path(res["out"]) / GRID_FILE).read_bytes() if (Path(res["out"]) / GRID_FILE).exists() else b""

    def _download() -> bytes:  # 누를 때(화면 실행 밖) 부른다: Streamlit 기능을 쓰지 않는다
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            for name, data in files_out.items():
                z.writestr(name, data)
            if grid_bytes:
                z.writestr(GRID_FILE, grid_bytes)
        return buf.getvalue()

    b.download_button("내려받기 (ZIP)", _download, "LAS_격자높이.zip", "application/zip", icon=":material/download:",
                      width="stretch", on_click="ignore", help="위에서 고른 나누기·형식의 파일과 grid.json 을 묶어 받습니다.")

sidebar_status()
