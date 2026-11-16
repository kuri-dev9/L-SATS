"""작업 내역: 저장된 분석을 찾고, 열고, 이름·메모를 고치고, 지운다."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from slab import history
from slab.settings_store import FIELD_BY_KEY, from_dict, to_dict
from slab import Settings
from views.shared import META_KEYS, close_if_open, jobs_frame, open_and_go, sidebar_status

EDITABLE = {"작업": "name", "동": "dong", "위층": "upper_floor", "아래층": "lower_floor", "메모": "memo"}

st.title("작업 내역", icon=":material/history:")
st.caption(f"분석한 작업은 자동으로 저장됩니다. 저장 위치: `{history.history_dir()}`")

jobs = history.list_jobs()
if not jobs:
    with st.container(border=True):
        st.caption("아직 저장된 작업이 없어요.")
        st.page_link("views/analysis.py", label="새 분석 시작", icon=":material/add:")
    sidebar_status()
    st.stop()


@st.dialog("작업 지우기")
def confirm_delete(ids: list[str]):
    names = [history.display_name(history.get_job(i) or {"id": i}) for i in ids]
    st.write(f"작업 {len(ids)}건을 지울까요? 저장해 둔 입력 파일도 함께 지워지고, 되돌릴 수 없어요.")
    st.caption(", ".join(names))
    a, b = st.columns(2)
    if a.button("지우기", type="primary", icon=":material/delete:", width="stretch"):
        for i in ids:
            close_if_open(i)
            history.delete_job(i)
        st.session_state.pop("jobs_table", None)
        st.toast(f"{len(ids)}건을 지웠어요.", icon=":material/delete:")
        st.rerun()
    if b.button("취소", width="stretch"):
        st.rerun()


with st.container(horizontal=True, vertical_alignment="bottom"):
    q = st.text_input("찾기", placeholder="작업 이름·동·층·메모", icon=":material/search:", key="jobs_q", width=320)
    kinds = ["✅ 통과", "❌ 미달 있음", "– 판정 못 함"]
    flt = st.pills("판정", kinds, selection_mode="multi", default=kinds, key="jobs_filter")

df = jobs_frame(jobs)
df.insert(0, "선택", False)
if q:
    text = df[["작업", "동", "위층", "아래층", "메모"]].fillna("").astype(str).agg(" ".join, axis=1)
    df = df[text.str.contains(q, case=False, regex=False)]
df = df[df["판정"].isin(flt or [])]

st.caption("작업 이름·동·층·메모 칸은 눌러서 바로 고칠 수 있어요. 왼쪽 칸에 체크하면 열거나 지울 수 있어요.")
edited = st.data_editor(
    df.set_index("id"), hide_index=True, width="stretch", key="jobs_table", alt="작업 내역 표",
    disabled=["판정", "통과 방", "평균(mm)", "수정"],
    column_config={
        "선택": st.column_config.CheckboxColumn(width="small"),
        "작업": st.column_config.TextColumn("작업 이름", help="비워 두면 동·층으로 이름을 만들어요."),
        "평균(mm)": st.column_config.NumberColumn(format="%.0f"),
        "메모": st.column_config.TextColumn(width="large"),
        "수정": st.column_config.DatetimeColumn("마지막 수정", format="YYYY-MM-DD HH:mm"),
    })

# 고친 칸을 바로 저장한다
orig = df.set_index("id")
changed = 0
for job_id, row in edited.iterrows():
    fields = {}
    for col, field in EDITABLE.items():
        new, old = str(row[col] or "").strip(), str(orig.at[job_id, col] or "").strip()
        if new != old:
            fields[field] = "" if (col == "작업" and new == history.display_name(
                {**history.get_job(job_id), "name": ""})) else new
    if fields and history.update_job(job_id, **fields):
        changed += 1
        if st.session_state.get("job_id") == job_id:
            for field, key in META_KEYS.items():
                if field in fields:
                    st.session_state[key] = fields[field]
if changed:
    st.session_state.pop("jobs_table", None)
    st.toast(f"{changed}건을 고쳤어요.", icon=":material/check_circle:")
    st.rerun()

picked = list(edited.index[edited["선택"]])
with st.container(horizontal=True):
    if st.button("열기", icon=":material/folder_open:", type="primary", disabled=len(picked) != 1, key="jobs_open",
                 help="체크한 작업 하나를 열어 결과를 다시 봅니다."):
        open_and_go(picked[0])
    if st.button(f"지우기 ({len(picked)})" if picked else "지우기", icon=":material/delete:", disabled=not picked,
                 key="jobs_delete"):
        confirm_delete(picked)

if len(picked) == 1:
    job = history.get_job(picked[0])
    s = job.get("summary", {})
    with st.container(border=True):
        st.subheader(history.display_name(job), icon=":material/info:")
        c = st.columns(4)
        c[0].metric("판정", {"적합": "통과", "미달": "미달 있음"}.get(s.get("verdict"), "-"))
        c[1].metric("통과 방", f"{s.get('n_ok', 0)} / {s.get('n_rooms', 0)}")
        c[2].metric("평균 두께", f"{s.get('mean_mm') or '-'} mm")
        c[3].metric("사용한 측정점", f"{s.get('n_valid', 0)} / {s.get('n_points', 0)}")
        if s.get("bad_rooms"):
            st.markdown("**미달 방:** " + ", ".join(s["bad_rooms"]))
        st.markdown("**입력 파일:** " + " · ".join(f"{v['name']}" for v in job.get("files", {}).values()))
        snap = from_dict(job.get("settings") or {})[0]
        diff = {k: v for k, v in to_dict(snap).items() if to_dict(Settings()).get(k) != v}
        st.caption("계산 설정: " + (", ".join(f"{FIELD_BY_KEY[k].label} = {v}" for k, v in diff.items()
                                             if k in FIELD_BY_KEY) or "모두 기본값"))
        st.caption(f"만든 때 {job.get('created', '')[:16].replace('T', ' ')} · "
                   f"고친 때 {job.get('updated', '')[:16].replace('T', ' ')} · ID {job['id']}")

sidebar_status()
