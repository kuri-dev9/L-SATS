"""보고서·내려받기 화면 (app.py 가 띄운다).

두께 분석 화면에서 올린 파일과 계산 결과를 그대로 쓴다. 층을 골라(두께 분석 화면과 같은 층) 보고서 영역을 고르고,
미리 보고, 파일로 받는다. 전체 층은 요약 엑셀과 층마다 결과 엑셀을 ZIP 으로 받는다.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import streamlit as st

from slab.report import build_all, build_bundle, build_dxf, build_excel, build_summary_excel, points_table
from slab.report_html import PRESETS, SECTIONS, ReportSpec, build_html
from views.shared import compute, dong, floor_nav, main_page, memo, sidebar_status, stem_of

st.title("보고서·내려받기", icon=":material/description:")
st.caption("층별 두께 결과로 보고서를 만들고, 엑셀·CAD 도면·포인트 목록을 받습니다.")

b = compute()
if not b.ready:
    with st.container(border=True):
        st.info("아직 계산된 층이 없어요. 두께 분석 화면에서 먼저 파일을 올려 주세요.", icon=":material/upload_file:")
        st.page_link(main_page(), label="두께 분석으로 가기", icon=":material/arrow_back:")
    sidebar_status(b)
    st.stop()


# 보고서·파일은 내려받기 버튼을 누를 때(화면 실행 밖)도 만들어지므로 st.cache_data 대신 memo 를 쓴다.
def _report(key: str, meta: tuple, kind: str, sections: tuple, notes: str, custom: tuple, author: str,
            result) -> str:
    return memo(("html", key, meta, kind, sections, notes, custom, author),
                lambda: build_html(result, dict(meta), ReportSpec(kind, list(sections), notes, list(custom), author)))


def _bundle(key: str, meta: tuple, stem: str, html: str, result) -> bytes:
    return memo(("bundle", key, meta, stem, hash(html)), lambda: build_bundle(result, dict(meta), stem, html),
                max_entries=10)


def _apply_preset():
    st.session_state["report_sections"] = list(PRESETS[st.session_state["report_kind"]])


# ---------------------------------------------------------------- 전체 층
runs = [(r.meta, r.result, r.error) for r in b.runs]
dong_name = dong()  # 버튼을 누를 때(화면 실행 밖) 세션 값을 읽지 않도록 미리
with st.container(border=True):
    st.subheader(f"전체 층 ({len(b.ready)}개 층 계산됨)", icon=":material/apartment:")
    c1, c2 = st.columns(2)
    c1.download_button(
        "전체 층 요약 엑셀", lambda: build_summary_excel(runs, dong_name), f"{dong_name or '전체'}_전체층_요약.xlsx",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", icon=":material/table_view:",
        width="stretch", on_click="ignore", help="층별 요약(평균·최소·최대·상태별 점 수) + 모든 층의 방별 현황")

    def _all() -> bytes:
        return memo(("all", tuple(r.key for r in b.runs), dong_name), lambda: build_all(runs, dong_name, stem_of),
                    max_entries=4)

    c2.download_button(
        "전체 층 한꺼번에 (ZIP)", _all, f"{dong_name or '전체'}_층별_슬래브두께.zip", "application/zip",
        icon=":material/folder_zip:", width="stretch", on_click="ignore", type="primary",
        help="요약 엑셀 + 층마다 결과 엑셀·DXF. 층이 많으면 시간이 걸려요.")

# ---------------------------------------------------------------- 층 하나
with st.container(border=True):
    st.subheader("층별 보고서", icon=":material/layers:")
    run = floor_nav(b, "report")
if run is None or not run.ok:
    st.warning(run.error if run else "층을 골라 주세요.", icon=":material/info:")
    sidebar_status(b)
    st.stop()

result, meta = run.result, run.meta
stem = stem_of(meta)
sm = result.summary
if not meta["동"]:
    st.caption(":material/edit: 보고서 제목에 쓸 동 이름이 비어 있어요. 두께 분석 화면의 ① 파일 올리기에서 채울 수 있어요.")


def _n(v):
    return f"{v:.0f} mm" if v is not None and np.isfinite(v) else "-"


with st.container(border=True, horizontal=True, vertical_alignment="center"):
    st.metric("평균 두께", _n(sm["mean_mm"]))
    st.metric("가장 얇은 곳", _n(sm["min_mm"]))
    st.metric("가장 두꺼운 곳", _n(sm["max_mm"]))
    st.metric("산출 완료", f"{sm['n_valid']}점")
    st.metric("검토 / 미산출", f"{sm['n_review']} / {sm['n_no_value']}점")

left, right = st.columns([1.1, 3], gap="medium")  # 미리보기를 넓게
with left:
    with st.container(border=True):
        st.subheader("보고서 구성", icon=":material/checklist:")
        st.session_state.setdefault("report_sections", list(PRESETS["간단 보고서"]))
        kind = st.segmented_control(
            "보고서 종류", list(PRESETS), default="간단 보고서", required=True, key="report_kind",
            on_change=_apply_preset, persist_state="session",
            help="간단 보고서: 현황·측정점 위치도·방별 두께도·검토할 점. 상세 보고서: 분포·계산 방법·전체 표까지.")
        sections = st.pills("넣을 영역", list(SECTIONS), selection_mode="multi", key="report_sections",
                            format_func=lambda k: SECTIONS[k][0], persist_state="session",
                            help=" · ".join(f"{v[0]}: {v[1]}" for v in SECTIONS.values()))
        st.caption("보고서 종류를 고르면 영역이 그 종류에 맞게 다시 골라집니다. 영역을 눌러 넣고 뺄 수 있어요.")

    with st.container(border=True):
        st.subheader("직접 쓰는 내용", icon=":material/edit_note:")
        author = st.text_input("작성자", key="report_author", placeholder="이름", persist_state="session")
        notes = st.text_area("검토 의견", key="report_notes", height=110, persist_state="session",
                             placeholder="예: 4호 거실 P013은 바닥 위 자재로 보여 재측정 예정")
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
        st.subheader(f"{meta['상부층']} 파일 받기", icon=":material/download:")
        st.download_button(
            f"{kind} 받기 (HTML)", lambda: html().encode("utf-8"), f"{stem}_{kind.replace(' ', '')}.html",
            "text/html", type="primary", icon=":material/description:", width="stretch", on_click="ignore",
            help="받은 파일을 열면 보고서가 보이고, 위의 '인쇄 / PDF로 저장' 버튼으로 PDF를 만들 수 있어요.")
        st.download_button(
            "이 층 모두 받기 (보고서+엑셀+DXF+CSV, ZIP)", lambda: _bundle(run.key, meta_t, stem, html(), result),
            f"{stem}.zip", "application/zip", icon=":material/folder_zip:", width="stretch", on_click="ignore")
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
        excel = ("슬라브 두께 결과 · 포인트 위치도 · 방별 두께도" if result.settings.excel_layout == "basic"
                 else "슬라브 두께 결과 · 포인트 위치도 · 방별 두께도 · 방별 현황 · 계산 상세 · 설정·요약")
        st.caption(f"엑셀: {excel} / DXF: 원본 도면 위에 두께 값과 상태를 레이어로 표시. "
                   "구성은 설정 화면에서 바꿀 수 있어요.")

with right:
    with st.container(border=True):
        st.subheader("미리보기", icon=":material/preview:")
        if not sections and not any(t.strip() or c.strip() for t, c in custom_rows):
            st.info("보고서에 넣을 영역을 하나 이상 골라 주세요.", icon=":material/touch_app:")
        else:
            st.iframe(html(), height=1100, alt="슬래브 두께 현황 보고서 미리보기")

sidebar_status(b)
