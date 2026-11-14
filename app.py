"""실별 슬래브 두께 자동 산출 - 웹 화면 (Streamlit)

실행:  streamlit run app.py
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import pandas as pd
import streamlit as st

from slab import Settings, analyze, load_cad, read_table, standardize_grid
from slab.core import DEFAULT_COLUMNS
from slab.plot import plot_plan
from slab.report import build_dxf, build_excel, points_table, rooms_table, summary_rows
from slab import __version__

SAMPLE_DIR = Path(__file__).parent / "demo_data"  # 가상 데모 데이터 (tools/make_demo_data.py)
SAMPLE = {
    "cad": SAMPLE_DIR / "report_merge_8F.dxf",
    "upper": SAMPLE_DIR / "grid_analysis_floor_level_8F.csv",
    "lower": SAMPLE_DIR / "grid_analysis_floor_level_7F.csv",
}
COLUMN_LABELS = {
    "point_id": "포인트 번호",
    "x": "X 좌표",
    "y": "Y 좌표",
    "floor_z": "바닥 Z (콘크리트 윗면)",
    "ceiling_z": "천장 Z",
    "floor_error": "바닥 기준면 편차",
    "ceiling_error": "천장 기준면 편차",
}
NONE = "(없음)"

st.set_page_config(page_title="실별 슬래브 두께 자동 산출", layout="wide")


class _File:
    """업로드 파일과 샘플 파일을 같은 방식으로 다루기 위한 래퍼."""

    def __init__(self, name: str, data: bytes):
        self.name, self.data = name, data

    def getvalue(self) -> bytes:
        return self.data


def _pick(uploaded, sample_path: Path, use_sample: bool) -> _File | None:
    if uploaded is not None:
        return _File(uploaded.name, uploaded.getvalue())
    if use_sample:
        return _File(sample_path.name, sample_path.read_bytes())
    return None


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


st.title("슬래브 두께 분석기")
st.caption(
    f"v{__version__} | 두께 = 상부층 바닥(콘크리트 윗면) Z − 하부층 천장 Z | "
    "좌표 기준 대응점 매칭 · 이상값 자동 제외 · 실별 집계 · Excel/DXF 출력"
)

tab_input, tab_cad, tab_result, tab_save = st.tabs(
    ["파일 및 데이터", "통합 CAD·실 경계", "산출 및 검토", "결과 저장"]
)

# ---------------------------------------------------------------- 1. 입력
with tab_input:
    st.subheader("입력 파일")
    cad_up = st.file_uploader(
        "통합 CAD DXF (실 경계 폴리라인 + 실명 문자 + 상부층 측정점 라벨)", type=["dxf"],
        help="실 경계(닫힌 폴리라인)와 실명 TEXT/MTEXT는 같은 레이어에 있어야 합니다. "
             "도면 좌표를 측량 좌표로 맞추기 위해 상부층 측정점 라벨(P001 등)이 3개 이상 필요합니다.")
    c1, c2 = st.columns(2)
    upper_up = c1.file_uploader("상부층 레이저 스캔 (바닥 Z 사용)", type=["csv", "xlsx", "xlsm"])
    lower_up = c2.file_uploader("하부층 레이저 스캔 (천장 Z 사용)", type=["csv", "xlsx", "xlsm"])

    no_upload = not (cad_up or upper_up or lower_up)
    use_sample = st.checkbox(
        "업로드하지 않은 파일은 데모 데이터 사용 (가상 데이터 8F/7F)", value=no_upload,
        help="demo_data 폴더의 가상 데이터: report_merge_8F.dxf, grid_analysis_floor_level_8F.csv / 7F.csv")

    st.divider()
    st.subheader("현장 및 층 정보")
    m1, m2, m3 = st.columns(3)
    meta = {
        "동": m1.text_input("동", "데모동" if use_sample else ""),
        "상부층": m2.text_input("상부층", "8F" if use_sample else ""),
        "하부층": m3.text_input("하부층", "7F" if use_sample else ""),
    }

    st.divider()
    st.subheader("판정 기준")
    s1, s2, s3 = st.columns(3)
    design = s1.number_input("설계 슬래브 두께 (mm)", 0.0, 1000.0, 135.0, 5.0)
    tol = s2.number_input("허용 부족량 (mm)", 0.0, 200.0, 10.0, 1.0,
                          help="두께 ≥ 설계 − 허용 부족량 이면 적합. 기준이 정해지면 수정하세요.")
    method = s3.radio("대응 방식", ["nearest", "interpolate"], horizontal=True,
                      format_func={"nearest": "최근접 대응점", "interpolate": "하부 천장면 보간"}.get,
                      help="최근접: 가장 가까운 하부층 점의 천장 Z 사용. "
                           "보간: 하부층 천장점으로 면을 만들어 상부층 점 위치의 천장 Z를 계산.")
    with st.expander("이상값 제외 기준"):
        e1, e2, e3 = st.columns(3)
        max_dist = e1.number_input("대응점 최대 거리 (m)", 0.01, 5.0, 0.2, 0.05,
                                   help="상·하부층 점이 이보다 멀면 같은 위치로 보지 않습니다.")
        max_err = e2.number_input("기준면 편차 제외 기준 (mm)", 1.0, 1000.0, 30.0, 5.0,
                                  help="층 기준면보다 이만큼 높거나 낮은 바닥/천장 측정값은 "
                                       "물체·설비 등으로 보고 제외합니다.")
        mad_k = e3.number_input("통계 이상치 기준 (MAD 배수, 0=미사용)", 0.0, 20.0, 5.0, 0.5)
    settings = Settings(design, tol, method, max_dist, max_err, mad_k)

    upper_f = _pick(upper_up, SAMPLE["upper"], use_sample)
    lower_f = _pick(lower_up, SAMPLE["lower"], use_sample)
    cad_f = _pick(cad_up, SAMPLE["cad"], use_sample)

    mappings = {}
    if upper_f and lower_f:
        st.divider()
        st.subheader("입력 파일 열 매핑")
        for label, key, f in (("상부층", "upper", upper_f), ("하부층", "lower", lower_f)):
            raw = _raw_table(f.name, f.data)
            with st.expander(f"{label}: {f.name}  ({len(raw)}행)"):
                mappings[key] = _column_mapping(raw, key)
                st.dataframe(raw.head(5), width="stretch")

if not (upper_f and lower_f):
    for t in (tab_cad, tab_result, tab_save):
        t.info("상부층·하부층 스캔 파일을 올리거나 샘플 데이터 사용을 선택하세요.")
    st.stop()

try:
    upper = standardize_grid(_raw_table(upper_f.name, upper_f.data), mappings.get("upper"))
    lower = standardize_grid(_raw_table(lower_f.name, lower_f.data), mappings.get("lower"))
except ValueError as e:
    st.error(str(e))
    st.stop()

# ---------------------------------------------------------------- 2. CAD·실 경계
plan = None
room_names: dict[str, str] = {}
with tab_cad:
    if cad_f is None:
        st.info("DXF가 없으면 실 구분 없이 전체 포인트로만 산출합니다.")
    else:
        digest = hashlib.md5(cad_f.data).hexdigest()
        base = _cad(digest, cad_f.data, None)
        if not base.polygon_layers:
            st.error("DXF에서 닫힌 폴리라인(실 경계)을 찾지 못했습니다.")
        else:
            layer = st.selectbox("실 경계·실명 레이어", base.polygon_layers,
                                 index=base.polygon_layers.index(base.room_layer))
            plan = _cad(digest, cad_f.data, layer)
            st.caption(f"실 {len(plan.rooms)}개 · 측정점 라벨 {len(plan.labels)}개 인식")

            st.markdown("**실명 편집** — `실명` 칸을 고치면 결과표·위치도·DXF에 반영됩니다.")
            edit = st.data_editor(
                pd.DataFrame({"ID": [r.room_id for r in plan.rooms],
                              "도면 실명": [r.name for r in plan.rooms],
                              "실명": [r.name for r in plan.rooms]}),
                disabled=["ID", "도면 실명"], hide_index=True, width="stretch",
                key=f"rooms_{digest}_{layer}")
            room_names = {rid: (name or "").strip() or orig
                          for rid, orig, name in zip(edit["ID"], edit["도면 실명"], edit["실명"])}

try:
    result = analyze(upper, lower, plan, settings, room_names)
except ValueError as e:
    st.error(str(e))
    st.stop()

with tab_cad:
    t = result.transform
    if t is not None:
        st.markdown("**도면 ↔ 측량 좌표 정합**")
        c = st.columns(4)
        c[0].metric("방식", t.method)
        c[1].metric("회전각", f"{t.rotation_deg:.3f}°")
        unit = {1.0: "1 : 1", 0.001: "mm → m"}.get(round(t.scale, 5), f"{t.scale:.6f}")
        c[2].metric("축척", unit)
        c[3].metric("잔차 RMS", f"{t.rms_m * 1000:.1f} mm")
        if t.rms_m > 0.05:
            st.warning("정합 잔차가 큽니다. 도면의 측정점 라벨이 상부층 파일과 같은 번호인지 확인하세요.")
        outside = (result.points["room"] == "(실 외부)").sum()
        if outside:
            st.caption(f"실 경계 밖 포인트 {outside}개는 '(실 외부)'로 집계됩니다.")

# ---------------------------------------------------------------- 3. 산출 및 검토
with tab_result:
    sm = result.summary
    c = st.columns(6)
    c[0].metric("평균 두께", f"{sm['mean_mm']:.1f} mm", f"{sm['mean_mm'] - design:+.1f} mm (설계 대비)",
                delta_color="normal")
    c[1].metric("중앙값", f"{sm['median_mm']:.1f} mm")
    c[2].metric("최소 / 최대", f"{sm['min_mm']:.0f} / {sm['max_mm']:.0f}")
    c[3].metric("유효점 / 전체", f"{sm['n_valid']} / {sm['n_points']}")
    c[4].metric("미달점", f"{sm['n_below']}")
    c[5].metric("적합률", f"{sm['pass_rate'] * 100:.1f}%")

    st.subheader("실별 결과")
    rt = rooms_table(result)
    rt = rt.astype(object).where(rt.notna(), "-")
    st.dataframe(
        rt.style.apply(lambda r: ["background-color:#f8d7da" if r["판정"] == "미달" else ""] * len(r), axis=1)
        .format(precision=1, na_rep="-"),
        hide_index=True, width="stretch")

    st.subheader("포인트 위치도")
    show_values = st.checkbox("두께 값 표시", value=True)
    title = f"{meta['동']} {meta['상부층']}-{meta['하부층']} 슬래브 두께".strip()
    st.pyplot(plot_plan(result, show_values, title), width="stretch")

    st.subheader("포인트별 결과")
    pt = points_table(result)
    flt = st.multiselect("판정 필터", ["적합", "미달", "제외"], ["적합", "미달", "제외"])
    st.dataframe(pt[pt["판정"].isin(flt)], hide_index=True, width="stretch")

    reasons = result.points.loc[result.points["excluded"], "exclude_reason"].str.split(", ").explode()
    if len(reasons):
        st.caption("제외 사유: " + " · ".join(f"{k} {v}개" for k, v in reasons.value_counts().items()))

# ---------------------------------------------------------------- 4. 결과 저장
with tab_save:
    stem = f"{meta['동']}_{meta['상부층']}-{meta['하부층']}_슬래브두께".replace(" ", "")
    st.dataframe(pd.DataFrame(summary_rows(result, meta), columns=["항목", "값"]).astype(str),
                 hide_index=True, width="stretch")
    fingerprint = hashlib.md5(repr((
        upper_f.data, lower_f.data, cad_f.data if cad_f else None,
        settings, meta, sorted(room_names.items()), plan.room_layer if plan else None,
    )).encode()).hexdigest()
    if st.button("결과 파일 만들기", type="primary"):
        with st.spinner("결과 파일 생성 중..."):
            st.session_state["outputs"] = (fingerprint, {
                "xlsx": build_excel(result, meta),
                "dxf": build_dxf(result),
                "csv": points_table(result).to_csv(index=False).encode("utf-8-sig"),
            })
    saved = st.session_state.get("outputs")
    if saved and saved[0] != fingerprint:
        st.info("입력이나 기준이 바뀌었습니다. '결과 파일 만들기'를 다시 눌러 주세요.")
    elif saved:
        out = saved[1]
        c = st.columns(3)
        c[0].download_button("Excel 결과표 (요약·실별·포인트별·위치도)", out["xlsx"], f"{stem}.xlsx",
                             "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        c[1].download_button("결과 DXF (원본 도면 + 두께 레이어)", out["dxf"], f"{stem}.dxf",
                             "application/dxf")
        c[2].download_button("포인트별 CSV", out["csv"], f"{stem}_포인트.csv", "text/csv")
