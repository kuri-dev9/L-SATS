"""홈: 프로그램 소개와 최근 분석. 줄을 누르면 그 작업을 다시 연다."""
from __future__ import annotations

import datetime as _dt

import pandas as pd
import streamlit as st

from slab import Settings, history
from views.shared import ROOT, clear_files, jobs_frame, open_and_go, sidebar_status

HOW_IT_WORKS = (ROOT / "slab" / "assets" / "how_it_works.svg").read_text(encoding="utf-8")
LIMIT = Settings.design_mm - Settings.tolerance_mm

st.title("슬래브 두께 분석기", icon=":material/layers:")
st.caption("레이저 스캔으로 잰 위층 바닥과 아래층 천장 높이의 차이로, 방마다 슬래브 두께를 계산하고 판정합니다.")

jobs = history.list_jobs()

left, right = st.columns([3, 2], gap="large")
with left:
    with st.container(border=True, height="stretch", vertical_alignment="center"):
        st.image(HOW_IT_WORKS, width="stretch")
        st.caption("슬래브는 위층의 바닥이면서 아래층의 천장인 콘크리트 판입니다. 너무 얇으면 층간소음이 커지고 "
                   "안전에도 좋지 않아서, 설계 두께만큼 시공됐는지 방마다 확인합니다.")
with right:
    with st.container(border=True, height="stretch"):
        st.subheader("이렇게 씁니다", icon=":material/route:")
        st.markdown(
            "1. **두께 분석**에서 도면(DXF)과 위층·아래층 스캔 파일을 올립니다.\n"
            f"2. 방마다 평균 두께가 **{LIMIT:g}mm 이상**이면 통과, 아니면 미달로 판정합니다.\n"
            "3. **보고서·내려받기**에서 보고서(PDF 인쇄)와 엑셀·CAD 도면을 받습니다.\n"
            "4. 분석은 **작업 내역**에 자동으로 저장되어 언제든 다시 열 수 있습니다.")
        st.space("small")
        if st.button("새 분석 시작", icon=":material/add:", type="primary", width="stretch", on_click=clear_files):
            st.switch_page("views/analysis.py")

today = _dt.date.today()
month = [j for j in jobs if j.get("created", "")[:7] == today.strftime("%Y-%m")]
bad = [j for j in jobs if j.get("summary", {}).get("verdict") == "미달"]
c = st.columns(4)
c[0].metric("저장된 작업", f"{len(jobs)}건", border=True)
c[1].metric("이번 달 분석", f"{len(month)}건", border=True)
c[2].metric("미달 방이 있는 작업", f"{len(bad)}건", border=True)
last = _dt.datetime.fromisoformat(jobs[0]["updated"]) if jobs else None
c[3].metric("마지막 분석", f"{last.month}월 {last.day}일" if last else "-", border=True,
            help=last.strftime("%Y-%m-%d %H:%M") if last else None)

with st.container(border=True):
    head, link = st.columns([3, 1], vertical_alignment="center")
    head.subheader("최근 분석", icon=":material/history:")
    link.page_link("views/jobs.py", label="작업 내역 전체 보기", icon=":material/arrow_forward:", width="stretch")
    if not jobs:
        st.caption("아직 분석한 작업이 없어요. '새 분석 시작'을 눌러 파일을 올려 보세요.")
    else:
        df = jobs_frame(jobs[:10])
        st.caption("줄을 누르면 그 작업을 열어 결과를 다시 볼 수 있어요.")
        event = st.dataframe(
            df.drop(columns=["id", "메모"]), hide_index=True, width="stretch", on_select="rerun",
            selection_mode="single-row", key="dash_jobs", alt="최근 분석 목록",
            column_config={"평균(mm)": st.column_config.NumberColumn(format="%.0f"),
                           "수정": st.column_config.DatetimeColumn("마지막 수정", format="YYYY-MM-DD HH:mm")})
        rows = event.selection.rows
        if rows:
            open_and_go(df.iloc[rows[0]]["id"])

sidebar_status()
