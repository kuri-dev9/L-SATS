"""실별 슬래브 두께 자동 산출 - 웹 화면 (Streamlit)

실행:  streamlit run app.py

왼쪽 메뉴: 홈(views/dashboard.py, 기본) · 두께 분석 · 보고서·내려받기 · LAS 변환 · 작업 내역 · 설정(맨 아래).
올린 파일과 계산 결과는 views/shared.py 가 세션에 두고, 작업 내역(slab/history.py)에 자동 저장한다.

미리보기 모드(설정 → 화면, user_settings.json 의 ui.preview_mode)를 켜면 초창기 버전처럼 꾸밈 없는 화면
(views/preview.py)과 투박한 주소(pg_main_v01 등)로 바뀐다. 계산·보고서·엑셀은 같은 코드라 결과 파일은 똑같다.
"""
from pathlib import Path

import streamlit as st

from slab.settings_store import load_ui
from views.shared import init_state, open_job, open_last_job

ASSETS = Path(__file__).parent / "slab" / "assets"

PREVIEW = load_ui()["preview_mode"]
if PREVIEW:
    st.set_page_config(page_title="slab_v01", layout="wide")
    # 꾸밈 없는 초창기 화면: 기본 글꼴·회색 배경·각진 상자·움직임 없음 (사용자가 요청한 '못생긴' 미리보기)
    st.html("""<style>
html,body,[class*="st-"],.stApp,.stMarkdown,button,input,textarea,select{font-family:'Times New Roman',Batang,serif!important}
.stApp{background:#e9e9e9!important}
[data-testid="stSidebar"]{background:#d4d4d4!important}
[data-testid="stSidebar"] *{color:#000!important}
*{border-radius:0!important;box-shadow:none!important;animation:none!important;transition:none!important}
h1,h2,h3{font-weight:400!important;color:#000!important}
[data-testid="stIconMaterial"],[data-testid="stIconMaterial"] *{font-family:'Material Symbols Rounded'!important}
</style>""")
else:
    st.set_page_config(page_title="슬래브 두께 분석기", page_icon=":material/layers:", layout="wide")
    st.logo(str(ASSETS / "logo.svg"), icon_image=str(ASSETS / "logo_icon.svg"), size="large")
init_state()

# 지금 작업을 주소(?job=…)에 남겨, 새로고침하거나 주소를 다시 열어도 같은 작업이 열리게 한다
_qid = st.query_params.get("job")
if _qid and not st.session_state.get("job_id") and not open_job(_qid):
    del st.query_params["job"]
# 새로 접속하면(프로그램을 다시 켠 뒤 등) 마지막 작업을 자동으로 다시 연다. 세션마다 한 번만.
if not st.session_state.get("_started"):
    st.session_state._started = True
    if not st.session_state.get("job_id") and not st.session_state.files:
        open_last_job()

if PREVIEW:
    page = st.navigation(
        [st.Page("views/preview.py", title="main", url_path="pg_main_v01", default=True),
         st.Page("views/report.py", title="rpt", url_path="pg_rpt_v01"),
         st.Page("views/settings.py", title="cfg", url_path="pg_cfg_v01")],
        position="sidebar",
    )
else:
    page = st.navigation(
    {
        "": [st.Page("views/dashboard.py", title="홈", icon=":material/home:", default=True)],
        "작업": [
            st.Page("views/analysis.py", title="두께 분석", icon=":material/layers:"),
            st.Page("views/report.py", title="보고서·내려받기", icon=":material/description:"),
            st.Page("views/las.py", title="LAS 변환", icon=":material/grid_on:"),
            st.Page("views/jobs.py", title="작업 내역", icon=":material/history:"),
        ],
        "관리": [st.Page("views/settings.py", title="설정", icon=":material/settings:")],
    },
    position="sidebar",
    )
if st.session_state.get("job_id"):
    st.query_params["job"] = st.session_state.job_id
page.run()
