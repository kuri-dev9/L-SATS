"""두께 분석 화면 (app.py 가 띄운다).

위에서 아래로 ① 파일 올리기(여러 층 한꺼번에) → ② 층별 현황(층 목록) → ③ 층 보기(측정점 위치도가 메인,
방별 두께도는 서브) → ④ 다음 할 일 순서이고, 전문 설정과 상세 표는 맨 아래 '자세히 보기'에 둔다.
통과/미달 판정은 하지 않는다. 두께 현황과 검토가 필요한 점을 보여 준다.
"""
from __future__ import annotations

import hashlib

import numpy as np
import pandas as pd
import streamlit as st

from slab import history
from slab.batch import kind_of
from slab.core import STATE_OK, STATES
from slab.plot import unit_scale
from slab.plot3d import plot_3d
from slab.report import build_all, build_excel, points_table, rooms_table, summary_rows
from slab.settings_store import FIELD_BY_KEY, changed, load_settings, to_dict
from views.plan_viewer import plan_viewer
from views.shared import (
    COLUMN_LABELS, FLOOR_KEY, NONE, clear_files, compute, dong, floor_nav, floors_text, memo, overall, raw_table,
    remove_files, sidebar_status, stem_of, store_uploads, upload_key, use_current_settings,
)

SUB_VIEWS = {"rooms": "방별 두께도", "table": "방별 표", "3d": "3D로 보기"}

# 화면 움직임: 각 단계 상자가 차례로 떠오른다. 움직임 줄이기 설정을 켠 사용자에게는 끈다.
st.html("""<style>
@keyframes lst-rise{from{opacity:0;transform:translateY(14px)}to{opacity:1;transform:none}}
.st-key-step1,.st-key-step2,.st-key-step3,.st-key-next,.st-key-details{
  animation:lst-rise .55s cubic-bezier(.2,.8,.2,1) both;transition:box-shadow .3s ease}
.st-key-step2{animation-delay:.06s}.st-key-step3{animation-delay:.1s}.st-key-next{animation-delay:.14s}
.st-key-details{animation-delay:.2s}
[class*="st-key-kpi"]{transition:transform .2s ease,filter .2s ease}
[class*="st-key-kpi"]:hover{transform:translateY(-3px);filter:drop-shadow(0 6px 12px rgba(15,42,74,.10))}
@media (prefers-reduced-motion:reduce){[class*="st-key-"]{animation:none!important;transition:none!important}}
</style>""")


@st.cache_data(show_spinner=False, max_entries=60)
def _room_fig(kind: str, key: str, _result):
    return plot_3d(_result)


def _excel(key: str, meta: tuple, result) -> bytes:
    """내려받기 버튼이 누를 때 부른다 (화면 실행 밖이라 Streamlit 기능을 쓰지 않는다)."""
    return memo(("excel", key, meta), lambda: build_excel(result, dict(meta)))


def _num(v, fmt="{:.0f}"):
    return fmt.format(v) if v is not None and np.isfinite(v) else "-"


ss = st.session_state


def _new_job():
    clear_files()
    ss._new_job_msg = True


b = compute()
job = history.get_job(ss.get("job_id", "")) if ss.get("job_id") else None
with st.container(horizontal=True, vertical_alignment="center"):
    st.title("두께 분석", icon=":material/layers:", width="content")
    st.space("stretch")
    if ss.files:
        st.button("새 분석", icon=":material/add:", on_click=_new_job, key="new_job",
                  help="화면을 비우고 새 작업을 시작합니다. 지금 작업은 작업 내역에 그대로 남고, "
                       "새로 올린 파일은 새 작업으로 따로 저장돼요 (같은 파일을 다시 올려도 새 작업).")
if job is not None:
    st.caption(f":material/history: 작업 내역 · **{history.display_name(job)}** · "
               f"자동 저장됨 ({job['updated'][:16].replace('T', ' ')})")
    if ss.pop("auto_opened", False):
        st.toast("지난번 작업을 다시 열었어요. 새로 하려면 오른쪽 위 '새 분석'을 누르세요.", icon=":material/history:")
else:
    st.caption("위층 바닥과 아래층 천장의 높이 차이로 측정점마다 슬래브 두께를 계산해, 층별 현황을 보여 줍니다.")
if ss.pop("_new_job_msg", False):
    st.toast("새 분석을 시작해요. 이전 작업은 '작업 내역'에 그대로 있어요.", icon=":material/add:")

# ---------------------------------------------------------------- ① 파일 올리기
with st.container(border=True, key="step1"):
    st.subheader("① 파일 올리기", icon=":material/upload_file:")
    mode = st.segmented_control("올리는 방법", ["files", "folder"], default="files", required=True,
                                format_func={"files": "파일 고르기", "folder": "폴더 통째로"}.get, key="up_mode",
                                persist_state="session", label_visibility="collapsed")
    key = upload_key()
    st.file_uploader(
        "여러 층의 스캔 파일(CSV·엑셀)과 도면(DXF)을 한꺼번에 올리세요",
        type=["csv", "xlsx", "xlsm", "txt", "dxf"], accept_multiple_files="directory" if mode == "folder" else True,
        key=key, on_change=store_uploads, args=(key,),
        help="예: grid_analysis_floor_level_7F.csv, grid_analysis_floor_level_8F.csv, report_merge_8F.dxf … "
             "파일 안의 바닥 높이로 층을 찾아 차례대로 놓고, 바로 아래층과 짝지어 계산합니다. "
             "도면은 파일 이름의 층(8F)에 붙이고, 층 표기가 없는 도면 하나는 모든 층에 같이 씁니다.")
    if ss.pop("_added", 0):
        st.toast(f"파일을 더했어요. 지금 {len(ss.files)}개", icon=":material/check_circle:")

    if ss.files:
        with st.container(horizontal=True, vertical_alignment="bottom"):
            st.text_input("동", key="meta_dong", persist_state="session", placeholder="예: 101동", width=200,
                          help="파일 이름에 101동 같은 표기가 있으면 자동으로 채워요.")
            st.metric("스캔 파일", f"{b.n_scans}개", border=True, width=150)
            st.metric("도면", f"{b.n_cads}개", border=True, width=150)
            st.metric("찾은 층", f"{len(b.plan.floors)}개", border=True, width=150)
            with st.popover("올린 파일 보기·빼기", icon=":material/folder_open:"):
                files = pd.DataFrame({"파일": b.names, "종류": [
                    {"scan": "스캔", "cad": "도면"}.get(kind_of(n), "-") for n in b.names]})
                ev = st.dataframe(files, hide_index=True, on_select="rerun", selection_mode="multi-row",
                                  key="files_table", alt="올린 파일 목록", height=min(400, 38 + 35 * len(files)))
                picked = [files.iloc[i]["파일"] for i in ev.selection.rows]
                with st.container(horizontal=True):
                    st.button(f"고른 파일 빼기 ({len(picked)})", icon=":material/remove:", disabled=not picked,
                              on_click=remove_files, args=(picked,), key="rm_picked")
                    st.button("모두 빼기", icon=":material/delete:", on_click=clear_files, key="rm_all")

if not ss.files or not b.n_scans:
    st.info("층마다 스캔 파일을 올려 주세요. 두 개 층 이상이 있어야 두께를 계산할 수 있어요 "
            "(위층 바닥 − 아래층 천장). 도면(DXF)도 올리면 방별로 나눠 보여 줍니다.", icon=":material/upload:")
    sidebar_status(b)
    st.stop()
for n, e in b.read_errors.items():
    st.error(e if e.startswith(n) else f"{n}: {e}", title="읽지 못한 파일", icon=":material/error:")
for w in b.plan.warnings:
    st.warning(w, icon=":material/warning:")
if not b.ready:
    st.warning("계산할 수 있는 층이 없어요. 위·아래로 이어진 두 개 층 이상의 스캔 파일이 필요해요. "
               "아래 층 목록의 '상태'에서 이유를 확인해 주세요.", title="계산된 층이 없어요", icon=":material/help:")
    for r in [r for r in b.runs if r.error and r.pair.lower is not None][:5]:  # 맨 아래층 안내는 빼고 이유를 보인다
        st.warning(f"{r.pair.title}: {r.error}", title=r.error_title, icon=":material/warning:")

result0 = b.ready[0].result if b.ready else None
if result0 is not None and to_dict(result0.settings) != to_dict(load_settings()):
    with st.container(horizontal=True, vertical_alignment="center", key="settings_notice"):
        st.caption(":material/info: 이 작업은 분석할 때의 설정으로 계산했어요. 설정 화면의 값이 그 뒤로 바뀌었습니다.")
        st.button("지금 설정으로 다시 계산", icon=":material/refresh:", on_click=use_current_settings,
                  type="tertiary", key="recalc")


# ---------------------------------------------------------------- ② 층별 현황
def _floor_rows() -> pd.DataFrame:
    rows = []
    for r in b.runs:
        p, sm = r.pair, (r.result.summary if r.ok else {})
        rows.append({
            "key": p.key,
            "층": p.upper.label, "아래층": p.lower.label if p.lower else "-",
            "평균(mm)": sm.get("mean_mm"), "최소(mm)": sm.get("min_mm"), "최대(mm)": sm.get("max_mm"),
            "산출 완료": sm.get("n_valid"), "검토": sm.get("n_review"), "미산출": sm.get("n_no_value"),
            "도면": (p.cad + (" (공용)" if p.cad_shared else "")) if p.cad else "-",
            "상태": "계산됨" if r.ok else r.error,
        })
    return pd.DataFrame(rows)


with st.container(border=True, key="step2"):
    st.subheader("② 층별 현황", icon=":material/apartment:")
    o = overall(b)
    if b.ready:
        c = st.columns(4)
        c[0].container(key="kpi0").metric("계산한 층", f"{o['n_floors']}개", border=True, height="stretch",
                                          help=floors_text(b))
        c[1].container(key="kpi1").metric("전체 평균 두께", f"{_num(o['mean_mm'])} mm", border=True,
                                          height="stretch", help="모든 층 '산출 완료' 점의 평균")
        c[2].container(key="kpi2").metric("가장 얇은 곳 / 두꺼운 곳",
                                          f"{_num(o['min_mm'])} / {_num(o['max_mm'])} mm", border=True,
                                          height="stretch")
        c[3].container(key="kpi3").metric("검토 필요 / 미산출 점", f"{o['n_review']} / {o['n_no_value']}개",
                                          border=True, height="stretch",
                                          help="검토 필요: 두께 범위·이상치·하한 이하. 미산출: 두께를 못 구한 점")
    st.caption("위층부터 놓았어요. 줄을 누르면 그 층 결과로 갑니다. 층 이름·도면이 틀렸으면 "
               "'자세히 보기 → 층·도면 고치기'에서 고칠 수 있어요.")
    rows = _floor_rows()
    ev = st.dataframe(
        rows.drop(columns="key"), hide_index=True, width="stretch", on_select="rerun", selection_mode="single-row",
        key=f"floors_{len(rows)}", alt="층별 슬래브 두께 현황", height=min(520, 38 + 35 * len(rows)),
        column_config={"평균(mm)": st.column_config.NumberColumn(format="%.1f"),
                       "최소(mm)": st.column_config.NumberColumn(format="%.0f"),
                       "최대(mm)": st.column_config.NumberColumn(format="%.0f"),
                       "상태": st.column_config.TextColumn(width="large")})
    if ev.selection.rows:
        pick = rows.iloc[ev.selection.rows[0]]["key"]
        if pick != ss.get(FLOOR_KEY):
            ss[FLOOR_KEY] = pick
            ss.pop("pt_pick", None)
            ss.pop("room_zoom", None)
    if len(b.ready) > 1:
        chart = rows[rows["평균(mm)"].notna()][["층", "평균(mm)"]]
        st.bar_chart(chart, x="층", y="평균(mm)", horizontal=True, sort=False, height=min(40 + 22 * len(chart), 900),
                     x_label="평균 두께 (mm)", y_label="", alt="층별 평균 두께 막대그래프")

if not b.ready:
    sidebar_status(b)
    st.stop()

# ---------------------------------------------------------------- ③ 층 보기
with st.container(border=True, key="step3"):
    st.subheader("③ 층 보기", icon=":material/map:")
    run = floor_nav(b, "analysis")
    if run is None or not run.ok:
        st.warning(run.error if run else "층을 골라 주세요.", title=run.error_title if run else None,
                   icon=":material/info:")
        result = None
    else:
        result = run.result
if result is None:
    sidebar_status(b)
    st.stop()

sm, pts, meta = result.summary, result.points, run.meta
pts_by_id = pts.drop_duplicates("point_id").set_index("point_id")

with st.container(key="step3_body"):
    for w in sm.get("warnings", []):
        st.warning(w, icon=":material/straighten:")
    if result.transform is not None and result.transform.rms_m > 0.05:
        st.warning("도면과 스캔 좌표가 잘 맞지 않아요. 도면의 측정점 번호가 위층 스캔 파일과 같은지 확인해 주세요.",
                   icon=":material/warning:")
    n_in = sm["n_points"] - sm["n_outside"]
    c = st.columns(4)
    c[0].metric("평균 두께", f"{_num(sm['mean_mm'])} mm", border=True, height="stretch",
                help=f"'산출 완료' {sm['n_valid']}개 점의 평균 (중앙값 {_num(sm['median_mm'])}mm)")
    c[1].metric("가장 얇은 곳 / 두꺼운 곳", f"{_num(sm['min_mm'])} / {_num(sm['max_mm'])} mm", border=True,
                height="stretch")
    c[2].metric("산출 완료", f"{sm['n_valid']} / {n_in}점", border=True, height="stretch",
                help=f"같은 위치 점으로 바로 계산 {sm['n_direct']}개, 주변 세 점(TIN)으로 계산 {sm['n_tin']}개"
                     + (f". 방 밖(영역 외) {sm['n_outside']}개는 따로 셉니다." if sm["n_outside"] else ""))
    c[3].metric("검토 필요 / 미산출", f"{sm['n_review']} / {sm['n_no_value']}점", border=True, height="stretch",
                help=f"두께 범위 검토 {sm['n_range']} · 이상치 검토 {sm['n_outlier']} · 하한 이하 {sm['n_low']}")

    # ---- 메인: 측정점 위치도
    st.markdown("**측정점 위치도**")
    unit = unit_scale(result)
    room_opts = ["(전체)"] + sorted(set(pts.loc[pts["in_room"], "room"])) if result.plan is not None else ["(전체)"]
    with st.container(horizontal=True, vertical_alignment="bottom"):
        zr = st.selectbox("방으로 확대", room_opts, key="room_zoom", width=220,
                          on_change=lambda: ss.pop("pt_pick", None))
        pid = st.selectbox("포인트 찾기", list(pts_by_id.index), index=None, key="pt_pick", width=180,
                           placeholder="예: P013", help="고르면 그 점으로 확대하고 자세한 값을 보여 줘요. "
                                                       "그림에서 점을 눌러도 됩니다.")
    if pid:  # 목록에서 고른 점은 그 점으로 확대하고 상세 카드를 연다
        p = pts_by_id.loc[pid]
        focus, pad, fkey = np.array([[p["cad_x"], p["cad_y"]]]), 3.5, f"pt:{pid}"
    elif zr and zr != "(전체)":
        sel = pts[pts["room"] == zr]
        poly = [r.polygon for r in result.plan.rooms if r.room_id in set(sel["room_id"])]
        focus, pad, fkey = np.vstack(poly + [sel[["cad_x", "cad_y"]].to_numpy()]), 0.8, f"room:{zr}"
    else:
        focus, pad, fkey = None, 0.0, "all"
    # 그림은 화면 폭 전체. 회전·점 글자·점 상세는 그림 안에서만 바뀌어 화면이 다시 그려지지 않는다.
    plan_viewer(result, key="pm_view", focus_xy=focus, focus_pad_m=pad, fit_key=f"{run.pair.key}|{fkey}",
                selected=pid)
    st.caption("휠 확대·축소 · 끌어서 이동 · **Shift+끌기** 또는 오른쪽 위 **나침반을 끌면 회전**(버튼·`[` `]` 키로 1°씩) · "
               "점을 누르면 그 옆에 자세한 값이 떠요. 기본은 CAD 도면 방향, '북쪽 위'는 측량 좌표 방향입니다. "
               "색: :green[연초록] 얇음 → 연노랑 → :orange[연주황] 두꺼움 · 회색 ×는 미산출, 회색 ○는 방 밖(영역 외)")

    # ---- 서브: 방별
    st.markdown("**서브 자료**")
    opts = list(SUB_VIEWS) if result.plan is not None else ["3d"]
    view = st.segmented_control("서브 자료", opts, default=opts[0], required=True, format_func=SUB_VIEWS.get,
                                key="sub_view", persist_state="session", label_visibility="collapsed")
    if view not in opts:
        view = opts[0]
    if view == "rooms":
        st.caption("방 안 '산출 완료' 점들의 **평균 두께** 색으로 방을 칠했어요. 위 측정점 위치도와 같은 방향으로 돌아가 있어요.")
        plan_viewer(result, key="room_view", mode="rooms", fit_key=run.pair.key, height=520)
    elif view == "table":
        t = result.rooms.sort_values(["unit", "room"])
        st.dataframe(pd.DataFrame({
            "세대": t["unit"], "방": t["room"], "평균(mm)": t["mean_mm"], "최소(mm)": t["min_mm"],
            "최대(mm)": t["max_mm"], "산출 완료/전체": t["n_valid"].astype(str) + " / " + t["n_points"].astype(str),
            "검토": t["n_review"], "미산출": t["n_no_value"]}), hide_index=True, width="stretch",
            alt="방별 두께 현황", column_config={c: st.column_config.NumberColumn(format="%.0f")
                                             for c in ("평균(mm)", "최소(mm)", "최대(mm)")})
    else:
        st.caption("방마다 평균 두께가 이 층 평균보다 두꺼우면 **위로 솟고**, 얇으면 **아래로 꺼집니다**. "
                   "마우스로 끌면 돌아가고, 휠로 확대·축소할 수 있어요.")
        st.plotly_chart(_room_fig("3d", run.key, result), width="stretch", key="plot3d",
                        config={"displaylogo": False}, alt="방별 두께 3D")

# ---------------------------------------------------------------- ④ 다음 할 일
stem = stem_of(meta)
with st.container(border=True, key="next"):
    st.subheader("④ 다음 할 일", icon=":material/arrow_forward:")
    a, c2, c3, c4 = st.columns(4)
    if a.button("보고서 만들기", icon=":material/description:", type="primary", width="stretch",
                help="보고서 화면에서 영역을 골라 미리 보고 HTML(인쇄·PDF)로 받을 수 있어요."):
        st.switch_page("views/report.py")
    c2.download_button(
        f"이 층 엑셀 ({run.pair.upper.label})", lambda: _excel(run.key, tuple(meta.items()), result), f"{stem}.xlsx",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", icon=":material/table_view:",
        width="stretch", on_click="ignore",
        help="슬라브 두께 결과(분포도+표) · 포인트 위치도 · 방별 두께도 시트")

    runs_all, dong_name = [(r.meta, r.result, r.error) for r in b.runs], dong()  # 버튼을 누를 때 쓸 값을 미리

    def _all() -> bytes:
        return memo(("all", tuple(r.key for r in b.runs), dong_name),
                    lambda: build_all(runs_all, dong_name, stem_of), max_entries=4)

    c3.download_button(
        f"전체 {len(b.ready)}개 층 받기 (ZIP)", _all, f"{dong_name or '전체'}_층별_슬래브두께.zip", "application/zip",
        icon=":material/folder_zip:", width="stretch", on_click="ignore",
        help="전체 층 요약 엑셀 + 층마다 결과 엑셀·DXF. 층이 많으면 시간이 걸려요.")
    c4.page_link("views/settings.py", label="계산·출력 설정 바꾸기", icon=":material/tune:", width="stretch")

# ---------------------------------------------------------------- 자세히 보기
st.space("medium")
with st.container(key="details"):
    st.subheader("자세히 보기", icon=":material/tune:")
    st.caption("담당자·전문가용입니다. 보통은 건드리지 않아도 됩니다.")
    tab_points, tab_review, tab_floors, tab_rooms, tab_input = st.tabs(
        [":material/table_rows: 포인트별 결과", ":material/flag: 검토·미산출 점", ":material/apartment: 층·도면 고치기",
         ":material/edit: 방 이름 고치기", ":material/architecture: 입력 열·설정"])

with tab_points:
    pt = points_table(result)
    with st.container(horizontal=True, vertical_alignment="bottom"):
        pq = st.text_input("찾기", placeholder="포인트 번호 또는 방 이름", key="point_q", icon=":material/search:",
                           width=280)
        flt = st.multiselect("결과 상태", list(STATES), default=list(STATES), key="point_filter")
    shown = pt[pt["결과 상태"].isin(flt or [])]
    if pq:
        shown = shown[shown["상부점 ID"].str.contains(pq, case=False, regex=False)
                      | shown["실명"].str.contains(pq, case=False, regex=False)]
    st.dataframe(shown, hide_index=True, width="stretch", alt="포인트별 두께 결과")
    st.caption(f"{len(shown)}개 표시 중 (전체 {len(pt)}개)")
    st.markdown("**방별 상세 통계**")
    st.dataframe(rooms_table(result), hide_index=True, width="stretch", alt="방별 상세 통계",
                 column_config={c: st.column_config.NumberColumn(format="%.1f")
                                for c in ("평균(mm)", "최소(mm)", "최대(mm)", "표준편차(mm)")})

with tab_review:
    ex = pts[pts["status"] != STATE_OK]
    if ex.empty:
        st.caption("검토가 필요하거나 미산출인 측정점이 없습니다.")
    else:
        st.caption("값이 있어도 다시 볼 점(두께 범위·이상치·하한 이하), 두께를 못 구한 점(미산출, 0mm로 채우지 않음), "
                   "방 밖의 점(영역 외)입니다. 방 평균에는 넣지 않았어요.")
        st.dataframe(ex["status"].value_counts().rename_axis("결과 상태").reset_index(name="개수"), hide_index=True,
                     alt="결과 상태별 개수")
        st.dataframe(points_table(result).loc[ex.index, ["상부점 ID", "실명", "결과 상태", "두께(mm)", "계산값(mm)",
                                                         "미산출 사유", "상세 사유", "검토 메모"]],
                     hide_index=True, width="stretch", alt="검토·미산출 측정점 목록")

with tab_floors:
    st.caption("층 이름은 파일 이름(예: `_8F`)에서, 층 순서는 파일 안의 바닥 높이에서 찾았어요. 틀렸으면 **층 이름** 칸을 "
               "고치세요. 도면은 위층 기준이에요(도면의 측정점 번호가 위층 스캔과 같아야 해요).")
    cads = sorted(n for n in b.names if kind_of(n) == "cad")
    fl = list(reversed(b.plan.floors))
    by_up = {r.pair.upper.scan: r.pair for r in b.runs}
    AUTO = "(자동)"
    table = pd.DataFrame({
        "스캔 파일": [f.scan for f in fl],
        "바닥 높이(m)": [round(f.level_m, 3) for f in fl],
        "층 이름": [f.label for f in fl],
        "도면": [ss.cad_choice.get(f.label, AUTO) or NONE if f.label in ss.cad_choice else AUTO for f in fl],
        "지금 쓰는 도면": [(by_up[f.scan].cad or "-") if f.scan in by_up else "-" for f in fl],
    })
    edit = st.data_editor(
        table, hide_index=True, width="stretch", key=f"floor_edit_{hashlib.md5(repr(b.names).encode()).hexdigest()}",
        disabled=["스캔 파일", "바닥 높이(m)", "지금 쓰는 도면"], alt="층 이름·도면 고치기",
        column_config={"도면": st.column_config.SelectboxColumn(options=[AUTO, NONE, *cads], required=True)})
    labels = {s: str(l).strip() for s, l, f in zip(edit["스캔 파일"], edit["층 이름"], fl)
              if str(l).strip() and str(l).strip() != f.label}
    choice = {}
    for lab, c_ in zip(edit["층 이름"], edit["도면"]):
        if c_ != AUTO:
            choice[str(lab).strip()] = "" if c_ == NONE else c_
    new_labels = {**ss.floor_labels, **labels}
    if new_labels != ss.floor_labels or choice != ss.cad_choice:
        ss.floor_labels, ss.cad_choice = new_labels, choice
        st.rerun()

with tab_rooms:
    if run.plan is None:
        st.caption("이 층에 도면(DXF)이 있으면 방 이름을 고칠 수 있어요.")
    else:
        cad = run.pair.cad
        st.caption(f"도면 **{cad}** 의 방 이름이 틀렸거나 비어 있으면(예: `실_08`) **새 이름** 칸을 눌러 고치세요. "
                   "이 도면을 쓰는 모든 층의 결과표·그림·보고서·파일에 반영됩니다.")
        names = ss.room_names.get(cad, {})
        edit = st.data_editor(
            pd.DataFrame({"ID": [r.room_id for r in run.plan.rooms],
                          "도면의 이름": [r.name for r in run.plan.rooms],
                          "새 이름": [names.get(r.room_id, r.name) for r in run.plan.rooms]}),
            disabled=["ID", "도면의 이름"], hide_index=True, width="stretch",
            key=f"rooms_{hashlib.md5(cad.encode()).hexdigest()}_{run.plan.room_layer}", alt="방 이름 고치기 표")
        orig = {r.room_id: r.name for r in run.plan.rooms}
        new = {rid: (name or "").strip() or orig[rid] for rid, name in zip(edit["ID"], edit["새 이름"])}
        new = {k: v for k, v in new.items() if v != orig[k]}
        if new != names:
            ss.room_names = {**ss.room_names, cad: new}
            st.rerun()

with tab_input:
    t = result.transform
    if run.base_plan is not None:
        st.selectbox("방 경계·방 이름 레이어 (모든 도면 공통)", run.base_plan.polygon_layers, key="room_layer",
                     index=run.base_plan.polygon_layers.index(run.base_plan.room_layer), persist_state="session")
    if t is not None:
        st.markdown("**도면 ↔ 측량 좌표 맞춤**")
        unit_txt = {1.0: "1 : 1", 0.001: "mm → m"}.get(round(t.scale, 5), f"{t.scale:.6f}")
        c = st.columns(4)
        c[0].metric("방식", t.method)
        c[1].metric("회전각", f"{t.rotation_deg:.3f}°")
        c[2].metric("축척", unit_txt)
        c[3].metric("오차(RMS)", f"{t.rms_m * 1000:.1f} mm")

    st.markdown("**입력 파일 열 지정** (모든 스캔 파일에 같이 씁니다)")
    st.caption("파일의 열 이름이 기본 형식과 다를 때만 바꾸세요.")
    f = run.pair.upper.scan
    raw = raw_table(f, ss.files[f])
    with st.expander(f"예시: {f} ({len(raw)}행)"):
        options = [NONE, *raw.columns]
        cols = st.columns(4)
        for i, (k, lab) in enumerate(COLUMN_LABELS.items()):
            # 값은 세션에 두고(작업을 열면 저장된 열 지정이 들어온다) 기본값 인자는 주지 않는다
            if ss.get(f"col_{k}") not in options:
                ss[f"col_{k}"] = k if k in raw.columns else NONE
            cols[i % 4].selectbox(lab, options, key=f"col_{k}", persist_state="session")
        st.dataframe(raw.head(5), width="stretch", alt="스캔 파일 앞부분")

    st.markdown("**계산 설정 요약**")
    diff = changed(result.settings)
    if diff:
        st.caption(f"설정 화면에서 바꾼 값 {len(diff)}개를 쓰고 있어요: " + ", ".join(
            f"{FIELD_BY_KEY[k].label} = {v}" for k, v in diff.items() if k in FIELD_BY_KEY))
    st.dataframe(pd.DataFrame(summary_rows(result, meta), columns=["항목", "값"]).astype(str),
                 hide_index=True, width="stretch", alt="계산 설정 요약")

sidebar_status(b)
