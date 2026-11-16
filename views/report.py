"""보고서·내려받기 화면 (app.py 가 띄운다).

두께 분석 화면에서 올린 파일과 계산 결과를 그대로 써서 보고서 영역을 고르고, 미리 보고, 파일로 받는다.
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

from slab.report import build_bundle, build_dxf, build_excel, points_table
from slab.report_html import PRESETS, SECTIONS, ReportSpec, build_html
from views.shared import compute, sidebar_status, stem_of, verdict

st.title("보고서·내려받기", icon=":material/description:")
st.caption("두께 분석 결과로 보고서를 만들고, 엑셀·CAD 도면·포인트 목록을 받습니다.")

run = compute()
if run.missing or run.error:
    with st.container(border=True):
        if run.missing:
            st.info(f"아직 **{', '.join(run.missing)}** 파일이 없어요. 두께 분석 화면에서 먼저 파일을 올려 주세요.",
                    icon=":material/upload_file:")
        else:
            st.error(run.error, title=run.error_title)
        st.page_link("views/analysis.py", label="두께 분석으로 가기", icon=":material/arrow_back:")
    sidebar_status(run)
    st.stop()

result, meta = run.result, run.meta
stem = stem_of(meta)
if not (meta["동"] and meta["상부층"] and meta["하부층"]):
    st.warning("보고서 제목에 쓸 동·층 이름이 비어 있어요. 두께 분석 화면의 ① 파일 올리기에서 채울 수 있어요.",
               icon=":material/edit:")


@st.cache_data(show_spinner="보고서 만드는 중…", max_entries=30)
def _report(key: str, meta: tuple, kind: str, sections: tuple, notes: str, custom: tuple, author: str,
            _result) -> str:
    return build_html(_result, dict(meta), ReportSpec(kind, list(sections), notes, list(custom), author))


@st.cache_data(show_spinner="파일 묶는 중…", max_entries=10)
def _bundle(key: str, meta: tuple, stem: str, html: str, _result) -> bytes:
    return build_bundle(_result, dict(meta), stem, html)


def _apply_preset():
    st.session_state["report_sections"] = list(PRESETS[st.session_state["report_kind"]])


key, n_ok, n_bad, n = verdict(result)
with st.container(border=True, horizontal=True, vertical_alignment="center"):
    st.metric("판정", {"적합": "통과", "미달": "미달"}.get(key, "판정 못 함"), border=False,
              help="방 평균 135mm 이상이면 통과")
    if result.plan is not None:
        st.metric("통과한 방", f"{n_ok} / {n}")
        st.metric("미달 방", f"{n_bad}개")
    st.metric("평균 두께", f"{result.summary['mean_mm']:.0f} mm")
    st.metric("사용한 측정점", f"{result.summary['n_valid']}개")

left, right = st.columns([1.1, 3], gap="medium")  # 미리보기를 넓게
with left:
    with st.container(border=True):
        st.subheader("보고서 구성", icon=":material/checklist:")
        st.session_state.setdefault("report_sections", list(PRESETS["간단 보고서"]))
        kind = st.segmented_control(
            "보고서 종류", list(PRESETS), default="간단 보고서", required=True, key="report_kind",
            on_change=_apply_preset, persist_state="session",
            help="간단 보고서: 결론·판정도·조치할 방만 (1~2쪽). 상세 보고서: 분포·측정점·제외 이유·계산 방법·전체 표까지.")
        sections = st.pills("넣을 영역", list(SECTIONS), selection_mode="multi", key="report_sections",
                            format_func=lambda k: SECTIONS[k][0], persist_state="session",
                            help=" · ".join(f"{v[0]}: {v[1]}" for v in SECTIONS.values()))
        st.caption("보고서 종류를 고르면 영역이 그 종류에 맞게 다시 골라집니다. 영역을 눌러 넣고 뺄 수 있어요.")

    with st.container(border=True):
        st.subheader("직접 쓰는 내용", icon=":material/edit_note:")
        author = st.text_input("작성자", key="report_author", placeholder="이름", persist_state="session")
        notes = st.text_area("검토 의견", key="report_notes", height=110, persist_state="session",
                             placeholder="예: 101호_침실2는 코어 채취로 실제 두께를 확인할 예정")
        with st.expander("영역 직접 추가", icon=":material/add_box:"):
            st.caption("맨 아래 빈 줄을 누르면 새 영역이 생기고, 줄 왼쪽을 고른 뒤 휴지통을 누르면 지워집니다.")
            custom = st.data_editor(
                pd.DataFrame({"제목": pd.Series(dtype=str), "내용": pd.Series(dtype=str)}),
                num_rows="dynamic", hide_index=True, width="stretch", key="report_custom",
                column_config={"제목": st.column_config.TextColumn(width="small"),
                               "내용": st.column_config.TextColumn(width="large")}, alt="직접 추가한 보고서 영역")
    custom_rows = tuple((str(t or ""), str(c or "")) for t, c in zip(custom["제목"], custom["내용"]))
    meta_t = tuple(meta.items())

    def html() -> str:
        return _report(run.key, meta_t, kind, tuple(sections or ()), notes, custom_rows, author, result)

    with st.container(border=True):
        st.subheader("파일 받기", icon=":material/download:")
        st.download_button(
            f"{kind} 받기 (HTML)", lambda: html().encode("utf-8"), f"{stem}_{kind.replace(' ', '')}.html",
            "text/html", type="primary", icon=":material/description:", width="stretch", on_click="ignore",
            help="받은 파일을 열면 보고서가 보이고, 위의 '인쇄 / PDF로 저장' 버튼으로 PDF를 만들 수 있어요.")
        st.download_button(
            "모두 받기 (보고서+엑셀+DXF+CSV, ZIP)", lambda: _bundle(run.key, meta_t, stem, html(), result),
            f"{stem}.zip", "application/zip", icon=":material/folder_zip:", width="stretch", on_click="ignore")
        with st.container():
            st.download_button(
                "엑셀", lambda: build_excel(result, meta), f"{stem}.xlsx",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                icon=":material/table_view:", width="stretch", on_click="ignore")
            st.download_button(
                "CAD 도면", lambda: build_dxf(result), f"{stem}.dxf", "application/dxf",
                icon=":material/architecture:", width="stretch", on_click="ignore")
            st.download_button(
                "포인트 CSV", lambda: points_table(result, True).to_csv(index=False).encode("utf-8-sig"),
                f"{stem}_포인트.csv", "text/csv", icon=":material/list:", width="stretch", on_click="ignore")
        excel = ("포인트 결과 · 위치도" if result.settings.excel_layout == "simple"
                 else "요약 · 실별 결과 · 방별 판정도 · 포인트 결과 · 제외·미산출 · 위치도")
        st.caption(f"엑셀: {excel} / DXF: 원본 도면 위에 두께 값과 판정을 색으로 표시. "
                   "구성은 설정 화면에서 바꿀 수 있어요.")

with right:
    with st.container(border=True):
        st.subheader("미리보기", icon=":material/preview:")
        if not sections and not any(t.strip() or c.strip() for t, c in custom_rows):
            st.info("보고서에 넣을 영역을 하나 이상 골라 주세요.", icon=":material/touch_app:")
        else:
            st.iframe(html(), height=1100, alt="슬래브 두께 검사 보고서 미리보기")

sidebar_status(run)
