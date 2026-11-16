"""미리보기 모드 화면 (설정 → 화면 → 미리보기 모드).

초창기 버전처럼 꾸밈 없이 보여 준다: 안내 문구·카드·움직임·확대/회전 그림·3D 없음. 그림은 고정 이미지.
계산(views/shared.compute)과 작업 저장, 보고서·엑셀(views/report.py)은 보통 화면과 같은 코드를 쓴다.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import streamlit as st

from slab.plot import figure_png, plot_point_map, plot_rooms
from slab.report import points_table, rooms_table
from views.shared import (
    FLOOR_KEY, clear_files, compute, current_floor, floor_options, sidebar_status, store_uploads, upload_key,
)


@st.cache_data(show_spinner=False, max_entries=40)
def _png(kind: str, key: str, _result) -> bytes:
    if kind == "rooms":
        return figure_png(plot_rooms(_result, title=" "), dpi=70)
    return figure_png(plot_point_map(_result, px_per_m=60), dpi=100)


def _f(v):
    return "" if v is None or not np.isfinite(v) else f"{v:.1f}"


ss = st.session_state
b = compute(progress=False)

st.header("slab thickness calc")
key = upload_key()
st.file_uploader("input files (csv/xlsx/dxf)", type=["csv", "xlsx", "xlsm", "txt", "dxf"], accept_multiple_files=True,
                 key=key, on_change=store_uploads, args=(key,))
ss.pop("_added", None)
st.text_input("dong", key="meta_dong", persist_state="session")
if ss.files:
    st.text(f"files: {len(ss.files)} / scan {b.n_scans} / dxf {b.n_cads} / floors {len(b.plan.floors)}")
    st.button("clear", on_click=clear_files, key="pv_clear")
for n, e in b.read_errors.items():
    st.text(f"ERROR {n}: {e}")
for w in b.plan.warnings:
    st.text(f"WARN {w}")
if not b.ready:
    st.text("no result")
    sidebar_status(b)
    st.stop()

st.subheader("floors")
st.dataframe(pd.DataFrame([{
    "floor": r.pair.upper.label, "lower": r.pair.lower.label if r.pair.lower else "",
    "mean": _f(r.result.summary["mean_mm"]) if r.ok else "", "min": _f(r.result.summary["min_mm"]) if r.ok else "",
    "max": _f(r.result.summary["max_mm"]) if r.ok else "", "n_ok": r.result.summary["n_valid"] if r.ok else None,
    "n_review": r.result.summary["n_review"] if r.ok else None, "n_none": r.result.summary["n_no_value"] if r.ok else None,
    "dxf": r.pair.cad or "", "msg": r.error} for r in b.runs]), hide_index=True, alt="floors")

current_floor(b)
st.selectbox("floor", floor_options(b), key=FLOOR_KEY, persist_state="session")
run = b.run_of(ss.get(FLOOR_KEY))
if run is None or not run.ok:
    st.text(run.error if run else "")
    sidebar_status(b)
    st.stop()
r, sm = run.result, run.result.summary
st.text(f"mean {_f(sm['mean_mm'])} / min {_f(sm['min_mm'])} / max {_f(sm['max_mm'])} / ok {sm['n_valid']} / "
        f"review {sm['n_review']} / none {sm['n_no_value']} / outside {sm['n_outside']}")

st.subheader("point map")
st.image(_png("points", run.key, r), alt="point map")
if r.plan is not None:
    st.subheader("room map")
    st.image(_png("rooms", run.key, r), alt="room map")
st.subheader("rooms")
st.dataframe(rooms_table(r), hide_index=True, alt="rooms")
st.subheader("points")
st.dataframe(points_table(r), hide_index=True, alt="points")
st.text("report / excel: rpt")
sidebar_status(b)
