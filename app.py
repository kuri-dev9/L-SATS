"""실별 슬래브 두께 자동 산출 - 웹 화면 (Streamlit)

실행:  streamlit run app.py

왼쪽 메뉴: 홈(views/dashboard.py, 기본) · 두께 분석 · 보고서·내려받기 · 작업 내역 · 설정(맨 아래).
올린 파일과 계산 결과는 views/shared.py 가 세션에 두고, 작업 내역(slab/history.py)에 자동 저장한다.
"""
from pathlib import Path

import streamlit as st

from views.shared import init_state, open_job

ASSETS = Path(__file__).parent / "slab" / "assets"

st.set_page_config(page_title="슬래브 두께 분석기", page_icon=":material/layers:", layout="wide")
st.logo(str(ASSETS / "logo.svg"), icon_image=str(ASSETS / "logo_icon.svg"), size="large")
init_state()

# 지금 작업을 주소(?job=…)에 남겨, 새로고침하거나 주소를 다시 열어도 같은 작업이 열리게 한다
_qid = st.query_params.get("job")
if _qid and not st.session_state.get("job_id") and not open_job(_qid):
    del st.query_params["job"]

page = st.navigation(
    {
        "": [st.Page("views/dashboard.py", title="홈", icon=":material/home:", default=True)],
        "작업": [
            st.Page("views/analysis.py", title="두께 분석", icon=":material/layers:"),
            st.Page("views/report.py", title="보고서·내려받기", icon=":material/description:"),
            st.Page("views/jobs.py", title="작업 내역", icon=":material/history:"),
        ],
        "관리": [st.Page("views/settings.py", title="설정", icon=":material/settings:")],
    },
    position="sidebar",
)
if st.session_state.get("job_id"):
    st.query_params["job"] = st.session_state.job_id
page.run()
