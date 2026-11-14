"""실별 슬래브 두께 자동 산출 - 웹 화면 (Streamlit)

실행:  streamlit run app.py

화면은 처음 쓰는 사람 기준으로 위에서 아래로 ① 파일 올리기 → ② 결과 → ③ 파일 받기 순서이고,
전문 설정과 상세 표는 맨 아래 '자세히 보기'에 둔다.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import pandas as pd
import streamlit as st

from slab import Settings, __version__, analyze, load_cad, read_table, standardize_grid
from slab.core import DEFAULT_COLUMNS, OUTSIDE_ROOM
from slab.plot import plot_plan
from slab.plot3d import plot_3d
from slab.report import build_dxf, build_excel, points_table, rooms_table, summary_rows

HOW_IT_WORKS = (Path(__file__).parent / "slab" / "assets" / "how_it_works.svg").read_text(encoding="utf-8")
DEMO_DIR = Path(__file__).parent / "demo_data"  # 가상 데모 데이터 (tools/make_demo_data.py)
DEMO = {
    "cad": DEMO_DIR / "report_merge_8F.dxf",
    "upper": DEMO_DIR / "grid_analysis_floor_level_8F.csv",
    "lower": DEMO_DIR / "grid_analysis_floor_level_7F.csv",
}
COLUMN_LABELS = {
    "point_id": "포인트 번호",
    "x": "X 좌표",
    "y": "Y 좌표",
    "floor_z": "바닥 높이 (콘크리트 윗면)",
    "ceiling_z": "천장 높이",
    "floor_error": "바닥 기준면 편차",
    "ceiling_error": "천장 기준면 편차",
}
METHODS = {"nearest": "가장 가까운 점", "interpolate": "천장면 보간"}
NONE = "(없음)"

st.set_page_config(page_title="슬래브 두께 분석기", page_icon=":material/layers:", layout="wide")


class _File:
    """업로드 파일과 데모 파일을 같은 방식으로 다루기 위한 래퍼."""

    def __init__(self, name: str, data: bytes):
        self.name, self.data = name, data

    def getvalue(self) -> bytes:
        return self.data


def _demo(key: str) -> _File:
    return _File(DEMO[key].name, DEMO[key].read_bytes())


@st.cache_data(show_spinner=False)
def _raw_table(name: str, data: bytes) -> pd.DataFrame:
    return read_table(_File(name, data))


@st.cache_resource(show_spinner=False)
def _cad(digest: str, data: bytes, room_layer: str | None):
    return load_cad(_File("cad.dxf", data), room_layer)


def _column_mapping(raw: pd.DataFrame, key: str) -> dict:
    options = [NONE, *raw.columns]
    mapping = {}
    cols = st.columns(4)
    for i, (k, label) in enumerate(COLUMN_LABELS.items()):
        default = DEFAULT_COLUMNS[k] if DEFAULT_COLUMNS[k] in raw.columns else NONE
        sel = cols[i % 4].selectbox(label, options, index=options.index(default), key=f"{key}_{k}")
        mapping[k] = sel if sel != NONE else f"__missing_{k}"
    return mapping


st.title("슬래브 두께 분석기", icon=":material/layers:")
st.caption(f"위층 바닥과 아래층 천장의 높이 차이로 방마다 슬래브 두께를 계산합니다 · v{__version__}")
with st.expander("처음이세요? 이 프로그램이 하는 일을 그림으로 보기", expanded=True, icon=":material/help:"):
    st.image(HOW_IT_WORKS, width="stretch")
    st.caption("슬래브는 위층의 바닥이면서 아래층의 천장인 콘크리트 판입니다. 너무 얇으면 층간소음이 커지고 "
               "안전에도 좋지 않아서, 설계 두께(예: 135mm)만큼 시공됐는지 방마다 확인합니다.")

# ---------------------------------------------------------------- ① 파일 올리기
with st.container(border=True):
    st.subheader("① 파일 올리기", icon=":material/upload_file:")
    c1, c2, c3 = st.columns(3)
    cad_up = c1.file_uploader(
        "도면 (DXF)", type=["dxf"],
        help="방 경계선, 방 이름, 측정점 번호(P001…)가 들어 있는 통합 CAD 도면")
    upper_up = c2.file_uploader(
        "위층 스캔 (CSV·엑셀)", type=["csv", "xlsx", "xlsm"],
        help="예: grid_analysis_floor_level_8F.csv — 위층 바닥 높이를 씁니다")
    lower_up = c3.file_uploader(
        "아래층 스캔 (CSV·엑셀)", type=["csv", "xlsx", "xlsm"],
        help="예: grid_analysis_floor_level_7F.csv — 아래층 천장 높이를 씁니다")

    use_demo = not (cad_up or upper_up or lower_up)
    if use_demo:
        st.info("파일을 올리기 전이라 **연습용 데모 데이터**(가상)로 보여주고 있어요. "
                "실제 파일 3개를 올리면 결과가 바로 바뀝니다.", icon=":material/school:")

    m1, m2, m3, m4, m5 = st.columns(5)
    meta = {
        "동": m1.text_input("동", "데모동" if use_demo else "", placeholder="예: 101동"),
        "상부층": m2.text_input("위층", "8F" if use_demo else "", placeholder="예: 8F"),
        "하부층": m3.text_input("아래층", "7F" if use_demo else "", placeholder="예: 7F"),
    }
    design = m4.number_input("설계 두께 (mm)", 0.0, 1000.0, 135.0, 5.0,
                             help="도면상 슬래브 두께")
    tol = m5.number_input("허용 오차 (mm)", 0.0, 200.0, 10.0, 1.0,
                          help="설계보다 이만큼 얇아도 적합으로 봅니다. "
                               "예: 설계 135, 허용 10 → 125mm 이상이면 적합")

if use_demo:
    upper_f, lower_f, cad_f = _demo("upper"), _demo("lower"), _demo("cad")
else:
    upper_f = _File(upper_up.name, upper_up.getvalue()) if upper_up else None
    lower_f = _File(lower_up.name, lower_up.getvalue()) if lower_up else None
    cad_f = _File(cad_up.name, cad_up.getvalue()) if cad_up else None
    missing = [n for n, f in (("위층 스캔", upper_f), ("아래층 스캔", lower_f)) if f is None]
    if missing:
        st.warning(f"**{', '.join(missing)}** 파일을 올려 주세요. 위층·아래층 스캔이 모두 있어야 계산할 수 있어요.",
                   icon=":material/upload:")
        st.stop()
    if cad_f is None:
        st.caption("도면(DXF)이 없으면 방별로 나누지 않고 전체를 한꺼번에 계산합니다.")

# 결과를 위에, 상세 설정을 아래에 보여주되 계산은 설정을 읽은 뒤에 한다
results_box = st.container()
download_box = st.container()

st.space("medium")
st.subheader("자세히 보기", icon=":material/tune:")
st.caption("담당자·전문가용입니다. 보통은 건드리지 않아도 됩니다.")
tab_rooms, tab_points, tab_excluded, tab_settings = st.tabs(
    ["방 이름 고치기", "포인트별 결과", "제외된 측정점", "계산 설정·도면 정합"])

with tab_settings:
    s1, s2 = st.columns([1, 2])
    method = s1.segmented_control(
        "위·아래층 점 맞추는 방법", list(METHODS), default="nearest", required=True, key="method",
        format_func=METHODS.get,
        help="위층과 아래층은 측정 위치가 조금씩 달라서 좌표로 같은 위치를 찾습니다. "
             "가장 가까운 점: 아래층에서 가장 가까운 점의 천장 높이를 씁니다. "
             "천장면 보간: 아래층 천장점들로 면을 만들어 위층 점 위치의 천장 높이를 계산합니다.")
    st.markdown("**이상한 측정값 자동 제외 기준**")
    e1, e2, e3 = st.columns(3)
    max_dist = e1.number_input("같은 위치로 볼 최대 거리 (m)", 0.01, 5.0, 0.2, 0.05,
                               help="위·아래층 점이 이보다 멀면 같은 위치로 보지 않습니다.")
    max_err = e2.number_input("기준면에서 벗어난 정도 (mm)", 1.0, 1000.0, 30.0, 5.0,
                              help="바닥·천장이 층 기준 높이보다 이만큼 높거나 낮으면 "
                                   "바닥 위 물건·천장 설비 등으로 보고 제외합니다.")
    mad_k = e3.number_input("통계 이상치 기준 (MAD 배수, 0=사용 안 함)", 0.0, 20.0, 5.0, 0.5)
    settings = Settings(design, tol, method, max_dist, max_err, mad_k)

    st.markdown("**입력 파일 열 지정**")
    st.caption("파일의 열 이름이 기본 형식과 다를 때만 바꾸세요.")
    mappings = {}
    for label, key, f in (("위층", "upper", upper_f), ("아래층", "lower", lower_f)):
        raw = _raw_table(f.name, f.data)
        with st.expander(f"{label}: {f.name} ({len(raw)}행)"):
            mappings[key] = _column_mapping(raw, key)
            st.dataframe(raw.head(5), width="stretch")

try:
    upper = standardize_grid(_raw_table(upper_f.name, upper_f.data), mappings.get("upper"))
    lower = standardize_grid(_raw_table(lower_f.name, lower_f.data), mappings.get("lower"))
except ValueError as e:
    results_box.error(str(e), title="파일을 읽지 못했어요")
    st.stop()

plan = None
room_names: dict[str, str] = {}
with tab_rooms:
    if cad_f is None:
        st.caption("도면(DXF)을 올리면 방 이름을 고칠 수 있어요.")
    else:
        digest = hashlib.md5(cad_f.data).hexdigest()
        base = _cad(digest, cad_f.data, None)
        if not base.polygon_layers:
            results_box.error("도면에서 방 경계선(닫힌 폴리라인)을 찾지 못했어요. 도면 파일을 확인해 주세요.",
                              title="도면 문제")
        else:
            with tab_settings:
                layer = st.selectbox("방 경계·방 이름 레이어", base.polygon_layers,
                                     index=base.polygon_layers.index(base.room_layer))
            plan = _cad(digest, cad_f.data, layer)
            st.caption("도면의 방 이름이 틀렸거나 비어 있으면(예: `실_08`) **새 이름** 칸을 눌러 고치세요. "
                       "결과표·위치도·내려받는 파일에 모두 반영됩니다.")
            edit = st.data_editor(
                pd.DataFrame({"ID": [r.room_id for r in plan.rooms],
                              "도면의 이름": [r.name for r in plan.rooms],
                              "새 이름": [r.name for r in plan.rooms]}),
                disabled=["ID", "도면의 이름"], hide_index=True, width="stretch",
                key=f"rooms_{digest}_{layer}")
            room_names = {rid: (name or "").strip() or orig
                          for rid, orig, name in zip(edit["ID"], edit["도면의 이름"], edit["새 이름"])}

try:
    result = analyze(upper, lower, plan, settings, room_names)
except ValueError as e:
    results_box.error(str(e), title="계산하지 못했어요")
    st.stop()

sm = result.summary
rooms = result.rooms
limit = design - tol
title = f"{meta['동']} {meta['상부층']}-{meta['하부층']} 슬래브 두께".strip()

# ---------------------------------------------------------------- ② 결과 한눈에
with results_box:
    with st.container(border=True):
        st.subheader("② 결과 한눈에 보기", icon=":material/fact_check:")
        judged = rooms[rooms["room"] != OUTSIDE_ROOM]
        bad = judged[judged["judgement"] == "미달"].sort_values("mean_mm")
        n_ok = int((judged["judgement"] == "적합").sum())
        n_judged = int(judged["judgement"].isin(["적합", "미달"]).sum())
        if result.plan is None:
            if sm["mean_mm"] >= limit:
                st.success(f"전체 평균 {sm['mean_mm']:.0f}mm로 기준({limit:g}mm 이상)을 통과했어요.",
                           title="통과", icon=":material/check_circle:")
            else:
                st.error(f"전체 평균 {sm['mean_mm']:.0f}mm로 기준({limit:g}mm 이상)보다 얇아요.",
                         title="미달", icon=":material/error:")
        elif bad.empty:
            st.success(f"검사한 방 {n_judged}개가 모두 기준({limit:g}mm 이상)을 통과했어요.",
                       title="모든 방 통과", icon=":material/check_circle:")
        else:
            names = ", ".join(f"{r.room}({r.mean_mm:.0f}mm)" for r in bad.head(5).itertuples())
            if len(bad) > 5:
                names += f" 외 {len(bad) - 5}개 (아래 표 참고)"
            st.error(f"설계 {design:g}mm, 기준 {limit:g}mm 이상 → 가장 얇은 방부터: {names}",
                     title=f"{len(bad)}개 방이 설계보다 얇아요 (전체 {n_judged}개 중)", icon=":material/error:")

        unknown = judged[judged["judgement"] == "판정불가"]
        if len(unknown):
            st.warning(f"{', '.join(unknown['room'])} — 쓸 수 있는 측정값이 없어 판정하지 못했어요. "
                       "측정점이 너무 적거나 단차·개구부 같은 특수한 곳일 수 있으니 현장에서 확인해 주세요. "
                       "이유는 '자세히 보기 → 제외된 측정점'에서 볼 수 있어요.",
                       title=f"판정하지 못한 방 {len(unknown)}개", icon=":material/help:")

        c = st.columns(3)
        c[0].metric("평균 두께", f"{sm['mean_mm']:.0f} mm", f"{sm['mean_mm'] - design:+.0f} mm (설계 대비)",
                    border=True, help=f"제외된 점을 뺀 {sm['n_valid']}개 측정점의 평균")
        if result.plan is not None:
            c[1].metric("기준 통과한 방", f"{n_ok} / {n_judged}", border=True,
                        help="방 안 측정점들의 평균 두께가 기준 이상이면 통과")
        else:
            c[1].metric("기준 통과한 점", f"{sm['pass_rate'] * 100:.0f}%", border=True)
        c[2].metric("사용한 측정점", f"{sm['n_valid']} / {sm['n_points']}", border=True,
                    help="바닥 위 물건, 천장 배관, 단차 등으로 값이 이상한 점은 자동으로 뺐습니다. "
                         "'자세히 보기 → 제외된 측정점'에서 확인할 수 있어요.")

        if result.plan is not None:
            st.markdown("**방별 결과** (얇은 방이 위에 옵니다)")
            view = rooms.assign(
                order=rooms["judgement"].map({"미달": 0, "판정불가": 1, "적합": 2}),
            ).sort_values(["order", "mean_mm"])
            view = pd.DataFrame({
                "방": view["room"],
                "판정": view["judgement"].map(
                    {"적합": "✅ 적합", "미달": "❌ 미달", "판정불가": "– 측정값 없음"}),
                "평균 두께(mm)": view["mean_mm"].round(0),
                "설계 대비(mm)": view["mean_dev_mm"].round(0),
                "가장 얇은 곳(mm)": view["min_mm"].round(0),
                "측정점": view["n_valid"].astype(str) + " / " + view["n_points"].astype(str),
            })
            st.dataframe(
                view, hide_index=True, width="stretch", alt="방별 슬래브 두께 판정표",
                column_config={
                    "평균 두께(mm)": st.column_config.NumberColumn(format="%d"),
                    "설계 대비(mm)": st.column_config.NumberColumn(format="%+d"),
                    "가장 얇은 곳(mm)": st.column_config.NumberColumn(format="%d"),
                })

        view_mode = st.segmented_control(
            "그림으로 보기", ["3D로 보기", "평면도로 보기"], default="3D로 보기", required=True,
            key="view_mode")
        if view_mode == "3D로 보기":
            st.caption(f"파란 반투명 판이 기준 두께({limit:g}mm)예요. 측정한 곳마다 기준과의 차이만큼 막대를 세웠어요. "
                       ":green[초록 막대]는 판 위로 솟아 통과, :red[빨간 막대]는 판 아래로 내려가 미달입니다. "
                       "마우스로 끌면 돌아가고, 휠로 확대·축소, 막대에 올리면 방 이름과 두께가 보여요.")
            st.plotly_chart(plot_3d(result), width="stretch", key="plot3d")
        else:
            st.caption("점의 색: :red[빨간색]일수록 설계보다 얇고, :blue[파란색]일수록 두껍습니다. "
                       "빨간 동그라미는 기준 미달, 회색 X는 제외된 점입니다. 숫자는 두께(mm)입니다.")
            st.pyplot(plot_plan(result, True, title), width="stretch", alt="방별 측정점 두께 위치도")

# ---------------------------------------------------------------- ③ 파일 받기
stem = f"{meta['동']}_{meta['상부층']}-{meta['하부층']}_슬래브두께".replace(" ", "").strip("_") or "슬래브두께"
with download_box:
    with st.container(border=True):
        st.subheader("③ 결과 파일 받기", icon=":material/download:")
        d = st.columns(3)
        d[0].download_button(
            "엑셀 보고서 받기", lambda: build_excel(result, meta), f"{stem}.xlsx",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            type="primary", icon=":material/table_view:", width="stretch", on_click="ignore")
        d[1].download_button(
            "CAD 도면(DXF) 받기", lambda: build_dxf(result), f"{stem}.dxf", "application/dxf",
            icon=":material/architecture:", width="stretch", on_click="ignore")
        d[2].download_button(
            "포인트 목록(CSV) 받기", lambda: points_table(result).to_csv(index=False).encode("utf-8-sig"),
            f"{stem}_포인트.csv", "text/csv", icon=":material/list:", width="stretch", on_click="ignore")
        st.caption("엑셀: 요약 · 방별 결과 · 포인트별 결과 · 제외된 점 · 위치도 그림 / "
                   "DXF: 원본 도면 위에 두께 값과 판정을 색으로 표시")

# ---------------------------------------------------------------- 자세히 보기
with tab_points:
    pt = points_table(result)
    flt = st.pills("판정", ["적합", "미달", "제외"], selection_mode="multi", default=["적합", "미달", "제외"],
                  key="point_filter")
    st.dataframe(pt[pt["판정"].isin(flt or [])], hide_index=True, width="stretch", alt="포인트별 두께 결과")
    st.markdown("**방별 상세 통계**")
    st.dataframe(rooms_table(result), hide_index=True, width="stretch", alt="방별 상세 통계",
                 column_config={c: st.column_config.NumberColumn(format="%.1f")
                                for c in ("평균(mm)", "최소(mm)", "최대(mm)", "표준편차(mm)", "평균-설계(mm)")})

with tab_excluded:
    ex = result.points[result.points["excluded"]]
    if ex.empty:
        st.caption("제외된 측정점이 없습니다.")
    else:
        reasons = ex["exclude_reason"].str.split(", ").explode().value_counts()
        st.caption(f"전체 {sm['n_points']}개 중 {len(ex)}개를 계산에서 뺐습니다. 이유별 개수:")
        st.dataframe(reasons.rename_axis("이유").reset_index(name="개수"), hide_index=True,
                     alt="제외 이유별 개수")
        st.dataframe(points_table(result).loc[ex.index, ["포인트", "실명", "두께(mm)", "제외 사유"]],
                     hide_index=True, width="stretch", alt="제외된 측정점 목록")

with tab_settings:
    t = result.transform
    if t is not None:
        st.markdown("**도면 ↔ 측량 좌표 맞춤**")
        unit = {1.0: "1 : 1", 0.001: "mm → m"}.get(round(t.scale, 5), f"{t.scale:.6f}")
        c = st.columns(4)
        c[0].metric("방식", t.method)
        c[1].metric("회전각", f"{t.rotation_deg:.3f}°")
        c[2].metric("축척", unit)
        c[3].metric("오차(RMS)", f"{t.rms_m * 1000:.1f} mm")
        if t.rms_m > 0.05:
            results_box.warning("도면과 스캔 좌표가 잘 맞지 않아요. 도면의 측정점 번호가 위층 스캔 파일과 "
                                "같은지 담당자에게 확인해 주세요.", icon=":material/warning:")
        outside = int((result.points["room"] == OUTSIDE_ROOM).sum())
        if outside:
            st.caption(f"방 경계 밖 측정점 {outside}개는 '{OUTSIDE_ROOM}'으로 따로 집계합니다.")
    st.markdown("**계산 설정 요약**")
    st.dataframe(pd.DataFrame(summary_rows(result, meta), columns=["항목", "값"]).astype(str),
                 hide_index=True, width="stretch", alt="계산 설정 요약")
