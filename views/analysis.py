"""두께 분석 화면 (app.py 가 띄운다).

위에서 아래로 ① 파일 올리기 → ② 결과 한눈에 보기 → 다음 할 일(보고서·내려받기) 순서이고,
전문 설정과 상세 표는 맨 아래 '자세히 보기'에 둔다.
"""
from __future__ import annotations

import hashlib

import pandas as pd
import streamlit as st

from slab import Settings
from slab.plot import plot_plan
from slab.plot3d import plot_3d, plot_room_map
from slab.report import build_bundle, points_table, rooms_table, summary_rows
from slab import history
from slab.settings_store import FIELD_BY_KEY, changed, load_settings, to_dict
from views.shared import (
    COLUMN_LABELS, KINDS, NONE, clear_files, compute, raw_table, remove_file, sidebar_status, stem_of,
    store_upload, title_of, use_current_settings, verdict,
)

VIEWS = {"map": "방별 판정도", "3d": "3D로 보기", "points": "측정점 위치도"}
LIMIT = Settings.design_mm - Settings.tolerance_mm

# 화면 움직임: 각 단계 상자가 차례로 떠오르고, 숫자 카드는 마우스를 올리면 살짝 뜬다.
# 처음 그릴 때만 움직이고(다시 계산할 때는 그대로), 움직임 줄이기 설정을 켠 사용자에게는 끈다.
st.html("""<style>
@keyframes lst-rise{from{opacity:0;transform:translateY(14px)}to{opacity:1;transform:none}}
@keyframes lst-pop{from{opacity:0;transform:scale(.96)}to{opacity:1;transform:none}}
.st-key-step1,.st-key-step2,.st-key-next,.st-key-details{
  animation:lst-rise .55s cubic-bezier(.2,.8,.2,1) both;transition:box-shadow .3s ease}
.st-key-step2{animation-delay:.08s}.st-key-next{animation-delay:.14s}.st-key-details{animation-delay:.2s}
.st-key-step1:hover,.st-key-step2:hover{box-shadow:0 10px 30px rgba(15,42,74,.07)}
.st-key-verdict{animation:lst-pop .45s .15s cubic-bezier(.2,1.3,.4,1) both}
[class*="st-key-kpi"]{animation:lst-rise .5s both;transition:transform .2s ease,filter .2s ease}
.st-key-kpi1{animation-delay:.05s}.st-key-kpi2{animation-delay:.1s}.st-key-kpi3{animation-delay:.15s}
[class*="st-key-kpi"]:hover{transform:translateY(-3px);filter:drop-shadow(0 6px 12px rgba(15,42,74,.10))}
.st-key-viz{animation:lst-rise .5s .3s both}
@media (prefers-reduced-motion:reduce){[class*="st-key-"]{animation:none!important;transition:none!important}}
</style>""")


@st.cache_data(show_spinner=False, max_entries=60)
def _figure(kind: str, key: str, _result):
    return plot_room_map(_result) if kind == "map" else plot_3d(_result)


@st.cache_data(show_spinner="파일 묶는 중…", max_entries=10)
def _bundle(key: str, meta: tuple, stem: str, _result) -> bytes:
    return build_bundle(_result, dict(meta), stem)


run = compute()
job = history.get_job(st.session_state.get("job_id", "")) if st.session_state.get("job_id") else None
with st.container(horizontal=True, vertical_alignment="center"):
    st.title("두께 분석", icon=":material/layers:", width="content")
    st.space("stretch")
    if st.session_state.files:
        st.button("새 분석", icon=":material/add:", on_click=clear_files, key="new_job",
                  help="올린 파일을 비우고 새 작업을 시작합니다. 지금 작업은 작업 내역에 남아 있어요.")
if job is not None:
    st.caption(f":material/history: 작업 내역 · **{history.display_name(job)}** · "
               f"자동 저장됨 ({job['updated'][:16].replace('T', ' ')})")
else:
    st.caption("위층 바닥과 아래층 천장의 높이 차이로 방마다 슬래브 두께를 계산합니다.")

# ---------------------------------------------------------------- ① 파일 올리기
with st.container(border=True, key="step1"):
    st.subheader("① 파일 올리기", icon=":material/upload_file:")
    helps = {
        "cad": "방 경계선, 방 이름, 측정점 번호(P001…)가 들어 있는 통합 CAD 도면",
        "upper": "예: grid_analysis_floor_level_8F.csv — 위층 바닥 높이를 씁니다",
        "lower": "예: grid_analysis_floor_level_7F.csv — 아래층 천장 높이를 씁니다",
    }
    types = {"cad": ["dxf"], "upper": ["csv", "xlsx", "xlsm"], "lower": ["csv", "xlsx", "xlsm"]}
    cols = st.columns(3)
    for col, (kind, label) in zip(cols, KINDS.items()):
        with col:
            up = st.file_uploader(label, type=types[kind], help=helps[kind], key=f"up_{kind}",
                                  on_change=store_upload, args=(kind,))
            saved = st.session_state.files.get(kind)
            if saved and up is None:  # 다른 화면에 다녀오면 올리기 칸은 비지만 파일은 남아 있다
                with st.container(horizontal=True, vertical_alignment="center", gap="small", key=f"saved_{kind}"):
                    st.caption(f":material/check_circle: **{saved[0]}**", width="content")
                    st.button(":material/close:", key=f"rm_{kind}", on_click=remove_file, args=(kind,),
                              type="tertiary", help="이 파일 빼기")

    m1, m2, m3, m4 = st.columns(4, vertical_alignment="bottom")
    m1.text_input("동", key="meta_dong", persist_state="session", placeholder="예: 101동")
    m2.text_input("위층", key="meta_upper", persist_state="session", placeholder="예: 8F",
                  help="파일 이름에 8F 같은 층 표기가 있으면 자동으로 채워요.")
    m3.text_input("아래층", key="meta_lower", persist_state="session", placeholder="예: 7F")
    m4.metric("기준 두께 (고정)", f"{LIMIT:g} mm", border=True,
              help="방 안 측정점들의 평균 두께가 이 값 이상이면 통과입니다. 현장 기준으로 고정되어 있어요.")

if run.missing:
    st.info(f"**{', '.join(run.missing)}** 파일을 올려 주세요. 위층·아래층 스캔이 모두 있어야 계산할 수 있어요. "
            "도면(DXF)도 올리면 방별로 판정합니다.", icon=":material/upload:")
    sidebar_status(run)
    st.stop()
if run.files["cad"] is None:
    st.caption("도면(DXF)이 없으면 방별로 나누지 않고 전체를 한꺼번에 계산합니다.")
if run.error:
    st.error(run.error, title=run.error_title)
    sidebar_status(run)
    st.stop()

result = run.result
sm, rooms, meta = result.summary, result.rooms, run.meta
if to_dict(result.settings) != to_dict(load_settings()):
    with st.container(horizontal=True, vertical_alignment="center", key="settings_notice"):
        st.caption(":material/info: 이 작업은 분석할 때의 설정으로 계산했어요. 설정 화면의 값이 그 뒤로 바뀌었습니다.")
        st.button("지금 설정으로 다시 계산", icon=":material/refresh:", on_click=use_current_settings,
                  type="tertiary", key="recalc")
title = title_of(meta)
for w in sm.get("warnings", []):
    st.warning(w, icon=":material/straighten:")
if result.transform is not None and result.transform.rms_m > 0.05:
    st.warning("도면과 스캔 좌표가 잘 맞지 않아요. 도면의 측정점 번호가 위층 스캔 파일과 같은지 담당자에게 확인해 주세요.",
               icon=":material/warning:")
overlap = int(result.points["review_note"].str.contains("방 경계 중첩").sum())
if overlap:
    st.warning(f"도면에서 방 경계가 겹치는 곳에 측정점 {overlap}개가 있어요. 도면을 확인해 주세요 "
               "('자세히 보기 → 포인트별 결과'의 검토 메모).", icon=":material/warning:")


# ---------------------------------------------------------------- ② 결과 한눈에
@st.fragment
def result_views(result, key: str, title: str):
    """그림 바꾸기는 이 부분만 다시 그린다 (계산·표는 그대로라 빠르다)."""
    options = list(VIEWS) if result.plan is not None else ["3d", "points"]
    view = st.segmented_control("그림으로 보기", options, default=options[0], required=True,
                                format_func=VIEWS.get, key="view_mode", persist_state="session")
    if view not in options:
        view = options[0]
    with st.container(key="viz"):
        if view == "map":
            st.caption(f"방 안 측정점들의 **평균 두께**로 판정해 방을 칠했어요. :green[초록 방]은 기준({LIMIT:g}mm 이상) 통과, "
                       ":red[빗금 친 빨간 방]은 미달입니다. 방 색은 방 평균, 점 색은 개별 측정점 판정이에요. "
                       "방에 마우스를 올리면 자세한 값, 휠로 확대·축소할 수 있어요.")
            st.plotly_chart(_figure("map", key, result), width="stretch", key="plot_map",
                            config={"scrollZoom": True, "displaylogo": False})
        elif view == "3d":
            st.caption(f"옅은 파란 판이 기준 높이({LIMIT:g}mm)예요. 방마다 평균 두께가 기준보다 두꺼우면 **위로 솟고**, "
                       "얇으면 **아래로 꺼집니다**. 마우스로 끌면 돌아가고, 휠로 확대·축소할 수 있어요.")
            st.plotly_chart(_figure("3d", key, result), width="stretch", key="plot3d",
                            config={"displaylogo": False})
        else:
            st.caption("측정점마다 두께(mm)를 적었어요. :red[빨간색]일수록 설계보다 얇고, :blue[파란색]일수록 두껍습니다. "
                       "빨간 동그라미는 기준 미달인 점, 회색 X는 제외된 점, 회색 동그라미는 두께를 못 구한 점, "
                       "빈 네모는 방 밖(영역외) 점입니다. 점 색은 개별 두께라 방 판정(평균)과 다를 수 있어요.")
            st.pyplot(plot_plan(result, True, title), width="stretch", alt="측정점 두께 위치도")


@st.fragment
def room_table(rooms: pd.DataFrame):
    """방별 결과: 찾기·미달만 보기·세대 고르기는 이 표만 다시 그린다."""
    st.markdown("**방별 결과** (얇은 방이 위에 옵니다)")
    with st.container(horizontal=True, vertical_alignment="bottom"):
        q = st.text_input("방 찾기", placeholder="방 이름 일부 (예: 침실)", key="room_q", icon=":material/search:",
                          width=260)
        units = ["전체", *sorted(u for u in rooms["unit"].unique() if u)]
        unit = st.selectbox("세대", units, key="room_unit", width=160) if len(units) > 2 else "전체"
        only_bad = st.toggle("미달 방만 보기", key="room_bad")
    view = rooms.assign(order=rooms["judgement"].map({"미달": 0, "판정불가": 1, "적합": 2})).sort_values(
        ["order", "mean_mm"])
    if q:
        view = view[view["room"].str.contains(q, case=False, regex=False)]
    if unit != "전체":
        view = view[view["unit"] == unit]
    if only_bad:
        view = view[view["judgement"] == "미달"]
    if view.empty:
        st.caption("조건에 맞는 방이 없어요.")
        return
    table = pd.DataFrame({
        "세대": view["unit"],
        "방": view["room"],
        "판정": view["judgement"].map({"적합": "✅ 통과", "미달": "❌ 미달", "판정불가": "– 측정값 없음"}),
        "평균 두께(mm)": view["mean_mm"],
        "기준 대비": view["mean_mm"] - LIMIT,
        "가장 얇은 곳(mm)": view["min_mm"],
        "측정점": view["n_valid"].astype(str) + " / " + view["n_points"].astype(str),
    })
    styled = table.style.format({"평균 두께(mm)": "{:.0f}", "가장 얇은 곳(mm)": "{:.0f}", "기준 대비": "{:+.0f} mm"},
                                na_rep="-").map(
        lambda v: "" if pd.isna(v) else f"color: {'#c62f2f' if v < 0 else '#2e9d5b'}; font-weight: 700",
        subset=["기준 대비"])
    st.dataframe(styled, hide_index=True, width="stretch", alt="방별 슬래브 두께 판정표",
                 column_config={"기준 대비": st.column_config.Column(
                     f"기준({LIMIT:g}mm) 대비", help="+는 기준보다 두껍고, −는 얇습니다")})
    st.caption(f"{len(view)}개 방 표시 중 (전체 {len(rooms)}개)")


with st.container(border=True, key="step2"):
    st.subheader("② 결과 한눈에 보기", icon=":material/fact_check:")
    key, n_ok, n_bad, n_judged = verdict(result)
    bad = rooms[rooms["judgement"] == "미달"].sort_values("mean_mm")
    with st.container(key="verdict"):
        if result.plan is None:
            if key == "적합":
                st.success(f"전체 평균 {sm['mean_mm']:.0f}mm로 기준({LIMIT:g}mm 이상)을 통과했어요.",
                           title="통과", icon=":material/check_circle:")
            else:
                st.error(f"전체 평균 {sm['mean_mm']:.0f}mm로 기준({LIMIT:g}mm 이상)보다 얇아요.",
                         title="미달", icon=":material/error:")
        elif bad.empty:
            st.success(f"검사한 방 {n_judged}개가 모두 기준({LIMIT:g}mm 이상)을 통과했어요.",
                       title="모든 방 통과", icon=":material/check_circle:")
        else:
            names = ", ".join(f"{r.room}({r.mean_mm:.0f}mm)" for r in bad.head(5).itertuples())
            if len(bad) > 5:
                names += f" 외 {len(bad) - 5}개 (아래 표 참고)"
            st.error(f"기준 {LIMIT:g}mm 이상 → 가장 얇은 방부터: {names}",
                     title=f"{len(bad)}개 방이 설계보다 얇아요 (전체 {n_judged}개 중)", icon=":material/error:")
        unknown = rooms[rooms["judgement"] == "판정불가"]
        if len(unknown):
            st.warning(f"{', '.join(unknown['room'])} — 쓸 수 있는 측정값이 없어 판정하지 못했어요. "
                       "측정점이 너무 적거나 단차·개구부 같은 특수한 곳일 수 있으니 현장에서 확인해 주세요.",
                       title=f"판정하지 못한 방 {len(unknown)}개", icon=":material/help:")

    n_in = sm["n_points"] - sm.get("n_outside", 0)
    rate = sm["n_valid"] / n_in if n_in else 0
    c = st.columns(4)
    c[0].container(key="kpi0").metric(
        "평균 두께", f"{sm['mean_mm']:.0f} mm", f"{sm['mean_mm'] - LIMIT:+.0f} mm (기준 대비)", border=True,
        height="stretch", help=f"제외된 점을 뺀 {sm['n_valid']}개 측정점의 평균")
    if result.plan is not None:
        c[1].container(key="kpi1").metric("기준 통과한 방", f"{n_ok} / {n_judged}", f"{n_ok / n_judged * 100:.0f}% 통과"
                                          if n_judged else None, delta_color="off", border=True, height="stretch",
                                          help="방 안 측정점들의 평균 두께가 기준 이상이면 통과")
        c[2].container(key="kpi2").metric("미달 방", f"{n_bad}개", "확인 필요" if n_bad else "없음",
                                          delta_color="inverse" if n_bad else "off", delta_arrow="off",
                                          border=True, height="stretch")
    else:
        c[1].container(key="kpi1").metric("기준 통과한 점", f"{sm['pass_rate'] * 100:.0f}%", border=True,
                                          height="stretch")
        c[2].container(key="kpi2").metric("기준 미달 점", f"{sm['n_below']}개", border=True, height="stretch")
    c[3].container(key="kpi3").metric(
        "사용한 측정점", f"{sm['n_valid']} / {n_in}", f"산출 성공률 {rate * 100:.0f}%", delta_color="off",
        border=True, height="stretch",
        help=f"같은 위치 점으로 바로 계산 {sm.get('n_direct', 0)}개, 주변 세 점(TIN)으로 계산 {sm.get('n_tin', 0)}개. "
             f"이상한 값이라 뺀 점 {sm['n_excluded']}개, 아래층에 맞는 점이 없어 못 구한 점 "
             f"{sm.get('n_no_value', 0)}개" + (f", 방 밖(영역외) {sm['n_outside']}개는 따로 셉니다" if sm.get("n_outside") else "")
             + ".")

    result_views(result, run.key, title)
    if result.plan is not None:
        room_table(rooms)

# ---------------------------------------------------------------- 다음 할 일
stem = stem_of(meta)
with st.container(border=True, key="next"):
    st.subheader("③ 다음 할 일", icon=":material/arrow_forward:")
    a, b, c3 = st.columns(3)
    if a.button("보고서 만들기", icon=":material/description:", type="primary", width="stretch",
                help="보고서 화면에서 영역을 골라 미리 보고 HTML(인쇄·PDF)로 받을 수 있어요."):
        st.switch_page("views/report.py")
    b.download_button(
        "결과 한꺼번에 받기 (ZIP)", lambda: _bundle(run.key, tuple(meta.items()), stem, result), f"{stem}.zip",
        "application/zip", icon=":material/folder_zip:", width="stretch", on_click="ignore",
        help="엑셀 · CAD 도면(DXF) · 포인트 목록(CSV)을 한 번에 받습니다.")
    c3.page_link("views/settings.py", label="계산·출력 설정 바꾸기", icon=":material/tune:", width="stretch")

# ---------------------------------------------------------------- 자세히 보기
st.space("medium")
with st.container(key="details"):
    st.subheader("자세히 보기", icon=":material/tune:")
    st.caption("담당자·전문가용입니다. 보통은 건드리지 않아도 됩니다.")
    tab_rooms, tab_points, tab_excluded, tab_input = st.tabs(
        [":material/edit: 방 이름 고치기", ":material/table_rows: 포인트별 결과",
         ":material/block: 제외·미산출 점", ":material/architecture: 도면·입력 열"])

with tab_rooms:
    if run.plan is None:
        st.caption("도면(DXF)을 올리면 방 이름을 고칠 수 있어요.")
    else:
        st.caption("도면의 방 이름이 틀렸거나 비어 있으면(예: `실_08`) **새 이름** 칸을 눌러 고치세요. "
                   "결과표·그림·보고서·내려받는 파일에 모두 반영됩니다.")
        names = st.session_state.room_names
        digest = hashlib.md5(run.files["cad"].data).hexdigest()
        edit = st.data_editor(
            pd.DataFrame({"ID": [r.room_id for r in run.plan.rooms],
                          "도면의 이름": [r.name for r in run.plan.rooms],
                          "새 이름": [names.get(r.room_id, r.name) for r in run.plan.rooms]}),
            disabled=["ID", "도면의 이름"], hide_index=True, width="stretch",
            key=f"rooms_{digest}_{run.plan.room_layer}", alt="방 이름 고치기 표")
        new = {rid: (name or "").strip() or orig
               for rid, orig, name in zip(edit["ID"], edit["도면의 이름"], edit["새 이름"])}
        new = {k: v for k, v in new.items() if v != next(r.name for r in run.plan.rooms if r.room_id == k)}
        if new != names:
            st.session_state.room_names = new
            st.rerun()

with tab_points:
    pt = points_table(result)
    with st.container(horizontal=True, vertical_alignment="bottom"):
        pq = st.text_input("찾기", placeholder="포인트 번호 또는 방 이름", key="point_q", icon=":material/search:",
                           width=280)
        kinds = ["적합", "미달", "제외", "미산출"]
        flt = st.pills("판정", kinds, selection_mode="multi", default=kinds, key="point_filter")
    shown = pt[pt["판정"].isin(flt or [])]
    if pq:
        shown = shown[shown["상부점 ID"].str.contains(pq, case=False, regex=False)
                      | shown["실명"].str.contains(pq, case=False, regex=False)]
    st.dataframe(shown, hide_index=True, width="stretch", alt="포인트별 두께 결과")
    st.caption(f"{len(shown)}개 표시 중 (전체 {len(pt)}개)")
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
        st.caption(f"전체 {sm['n_points']}개 중 {len(ex)}개를 계산에서 뺐습니다 "
                   f"(두께를 못 구한 미산출 {int((ex['status'] == '미산출').sum())}개 포함, 0mm로 채우지 않아요). 이유별 개수:")
        st.dataframe(reasons.rename_axis("이유").reset_index(name="개수"), hide_index=True, alt="제외 이유별 개수")
        st.dataframe(points_table(result).loc[ex.index, ["상부점 ID", "실명", "상태", "두께(mm)", "제외·미산출 사유",
                                                        "검토 메모"]],
                     hide_index=True, width="stretch", alt="제외된 측정점 목록")

with tab_input:
    t = result.transform
    if run.base_plan is not None:
        st.selectbox("방 경계·방 이름 레이어", run.base_plan.polygon_layers, key="room_layer",
                     index=run.base_plan.polygon_layers.index(run.base_plan.room_layer), persist_state="session")
    if t is not None:
        st.markdown("**도면 ↔ 측량 좌표 맞춤**")
        unit = {1.0: "1 : 1", 0.001: "mm → m"}.get(round(t.scale, 5), f"{t.scale:.6f}")
        c = st.columns(4)
        c[0].metric("방식", t.method)
        c[1].metric("회전각", f"{t.rotation_deg:.3f}°")
        c[2].metric("축척", unit)
        c[3].metric("오차(RMS)", f"{t.rms_m * 1000:.1f} mm")
        if sm.get("n_outside"):
            st.caption(f"방 경계 밖 측정점 {sm['n_outside']}개는 '영역외'로 따로 셉니다 (평균·판정에 넣지 않아요).")

    st.markdown("**입력 파일 열 지정**")
    st.caption("파일의 열 이름이 기본 형식과 다를 때만 바꾸세요.")
    for label, kind in (("위층", "upper"), ("아래층", "lower")):
        f = run.files[kind]
        raw = raw_table(f.name, f.data)
        with st.expander(f"{label}: {f.name} ({len(raw)}행)"):
            options = [NONE, *raw.columns]
            cols = st.columns(4)
            for i, (k, lab) in enumerate(COLUMN_LABELS.items()):
                default = k if k in raw.columns else NONE
                cols[i % 4].selectbox(lab, options, index=options.index(default), key=f"col_{kind}_{k}",
                                      persist_state="session")
            st.dataframe(raw.head(5), width="stretch", alt=f"{label} 파일 앞부분")

    st.markdown("**계산 설정 요약**")
    diff = changed(result.settings)
    if diff:
        st.caption(f"설정 화면에서 바꾼 값 {len(diff)}개를 쓰고 있어요: " + ", ".join(
            f"{FIELD_BY_KEY[k].label} = {v}" for k, v in diff.items() if k in FIELD_BY_KEY))
    st.dataframe(pd.DataFrame(summary_rows(result, meta), columns=["항목", "값"]).astype(str),
                 hide_index=True, width="stretch", alt="계산 설정 요약")

sidebar_status(run)
