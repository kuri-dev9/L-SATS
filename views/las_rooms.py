"""방 배치 화면: LAS 결과에 방(직사각형 + 이름)을 정해 도면(DXF)에 넣고, 두께 분석을 방별로 할 수 있게 한다.

① 층 구조 확인 — 벽 위치가 비슷한 층을 자동으로 묶고(slab/las_layout.group_floors), 실무자가 층마다 구조를 고친다.
② 구조마다 방 정하기 — 자동 나누기 초안 → 그림에서 범위를 끌어 방 추가 · 표에서 이름·범위 고치기·지우기.
③ 같은 구조의 모든 층 도면에 넣고 두께 분석으로 보낸다.
배치는 LAS 작업 폴더(LSATS_grid)의 layouts.json 에 저장한다. 미리보기 모드에서는 메뉴에 나오지 않는다.
"""
from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from slab import las_layout as L
from slab.las import CSV_NAME, DXF_NAME, OUT_DIR, PLAN_NAME
from slab.las_plan import plan_lines
from slab.settings_store import load_ui
from views.folder_pick import native_pick
from views.shared import clear_files, sidebar_status

ss = st.session_state
REMOTE = st.context.ip_address is not None
ROOM_COLS = ["name", "x0", "x1", "y0", "y1"]

st.title("방 배치", icon=":material/floor_lamp:")
st.caption("LAS 로 만든 층에 방 이름과 범위를 정해 도면에 넣어요. 같은 구조의 층은 한 번만 정하면 모두 같이 들어가고, "
           "그러면 두께 분석이 방별로 나와요.")
if REMOTE:
    st.warning("방 배치는 프로그램이 설치된 PC 에서만 쓸 수 있어요 (LAS 결과 폴더를 그 PC 에서 바로 읽어요).",
               icon=":material/desktop_access_disabled:")
    sidebar_status()
    st.stop()


# ---------------------------------------------------------------- 작업 폴더
def _default_out() -> str:
    res = ss.get("las_result")
    if res:
        return res["out"]
    last = load_ui().get("las_last_folder") or ""
    return str(Path(last) / OUT_DIR) if last else ""


def _pick() -> None:
    try:
        p = native_pick(ss.get("rooms_dir", ""), "LAS 변환 결과 폴더(LSATS_grid)를 고르세요")
    except RuntimeError as e:
        ss._rooms_err = str(e)
        return
    if p:
        ss.rooms_dir = str(Path(p) / OUT_DIR) if (Path(p) / OUT_DIR).is_dir() else p


if not ss.get("rooms_dir"):
    ss.rooms_dir = _default_out()
with st.container(horizontal=True, vertical_alignment="bottom"):
    st.text_input("LAS 결과 폴더", key="rooms_dir", help="LAS 변환이 만든 LSATS_grid 폴더. 마지막 변환 결과를 자동으로 열어요.")
    st.button("폴더 선택", icon=":material/folder_open:", on_click=_pick, key="rooms_pick")
if err := ss.pop("_rooms_err", None):
    st.warning(err, icon=":material/warning:")

out = Path(ss.rooms_dir.strip().strip('"'))
pat = re.compile("^" + re.escape(CSV_NAME).replace(r"\{\}", "(.+)") + "$")
labels = sorted((m.group(1) for f in (out.iterdir() if out.is_dir() else []) if (m := pat.match(f.name))
                 and (out / PLAN_NAME.format(m.group(1))).exists()), key=lambda s: (len(s), s))
if not labels:
    st.info("이 폴더에 방 배치에 쓸 LAS 결과가 없어요. 먼저 「LAS 변환」에서 변환하세요 "
            "(이전 버전으로 변환했다면 한 번 더 변환해야 해요).", icon=":material/info:")
    sidebar_status()
    st.stop()


@st.cache_data(show_spinner="층 구조를 비교하는 중…", max_entries=10)
def _groups(folder: str, labs: tuple, stamp: float):
    return L.group_floors(Path(folder), list(labs))


@st.cache_data(show_spinner=False, max_entries=50)
def _plan(folder: str, lab: str, stamp: float):
    p = L.load_plan(Path(folder), lab)
    return p, plan_lines(p)["벽선"], L.wall_coords(p)


def _stamp(lab: str) -> float:
    return (out / PLAN_NAME.format(lab)).stat().st_mtime


stamp = max(_stamp(lab) for lab in labels)
groups, sim = _groups(str(out), tuple(labels), stamp)
data = L.load_layouts(out)
if not data["layouts"]:  # 처음: 묶음마다 구조를 만들고 대표 층으로 방 초안
    for i, g in enumerate(groups):
        name = f"구조 {chr(65 + i)}" if i < 26 else f"구조 {i + 1}"
        data["layouts"][name] = L.auto_rooms(_plan(str(out), g[0], _stamp(g[0]))[0])
        for lab in g:
            data["floors"][lab] = name
    L.save_layouts(out, data)
for lab in labels:  # 새로 변환한 층은 가장 닮은 층의 구조로
    if lab not in data["floors"]:
        ref = sim.set_index("층").loc[lab, "대표 층"]
        data["floors"][lab] = data["floors"].get(ref) or next(iter(data["layouts"]))
names = list(data["layouts"])


def _save():
    L.save_layouts(out, data)


# ---------------------------------------------------------------- ① 층 구조
with st.container(border=True):
    st.subheader("① 층 구조 확인", icon=":material/stacks:")
    if len(groups) > 1:
        st.info(f"벽 위치로 보면 **{len(groups)}가지 구조**로 나뉘어요: "
                + " · ".join(f"{g[0]} 등 {len(g)}개 층" for g in groups), icon=":material/info:")
    else:
        st.success(f"모든 층({len(labels)}개)이 같은 구조로 보여요.", icon=":material/check_circle:")
    tab = sim.assign(구조=[data["floors"][lab] for lab in sim["층"]])[["층", "구조", "대표 층", "닮은 정도"]]
    ed = st.data_editor(tab, hide_index=True, width="stretch", key=f"rooms_floor_tab_{len(names)}",
                        disabled=["층", "대표 층", "닮은 정도"], height=min(400, 38 + 35 * len(tab)),
                        column_config={"구조": st.column_config.SelectboxColumn(options=names, required=True),
                                       "닮은 정도": st.column_config.ProgressColumn(min_value=0, max_value=1,
                                                                                format="%.2f")})
    changed = {r["층"]: r["구조"] for _, r in ed.iterrows() if data["floors"].get(r["층"]) != r["구조"]}
    if changed:
        data["floors"].update(changed)
        _save()
    st.caption("닮은 정도 = 대표 층과 벽 위치가 겹치는 비율 (1 에 가까울수록 같은 구조). 담당자가 아는 구조와 다르면 "
               "**구조** 칸을 바꾸세요.")
    with st.expander("새 구조 추가"):
        with st.container(horizontal=True, vertical_alignment="bottom"):
            new_name = st.text_input("구조 이름", placeholder="예: 최상층", key="rooms_new_name")
            base = st.selectbox("바탕 층 (이 층으로 방 초안)", labels, key="rooms_new_base")
            if st.button("추가", icon=":material/add:", key="rooms_new_add", disabled=not new_name.strip()):
                nm = new_name.strip()
                if nm in data["layouts"]:
                    st.warning("같은 이름의 구조가 있어요.", icon=":material/warning:")
                else:
                    data["layouts"][nm] = L.auto_rooms(_plan(str(out), base, _stamp(base))[0])
                    data["floors"][base] = nm
                    _save()
                    ss.rooms_layout = nm
                    st.rerun()

# ---------------------------------------------------------------- ② 방 정하기
with st.container(border=True):
    st.subheader("② 구조마다 방 정하기", icon=":material/edit_square:")
    if ss.get("rooms_layout") not in names:
        ss.rooms_layout = names[0]
    with st.container(horizontal=True, vertical_alignment="bottom"):
        lay = st.selectbox("구조", names, key="rooms_layout")
        members = [lab for lab in labels if data["floors"].get(lab) == lay] or labels
        base = st.selectbox("바탕으로 볼 층", members, key=f"rooms_base_{lay}")
        if st.button("자동으로 다시 나누기", icon=":material/auto_fix_high:", key="rooms_auto",
                     help="이 층의 벽으로 방 초안을 새로 만들어요. 지금 정한 방은 지워져요."):
            data["layouts"][lay] = L.auto_rooms(_plan(str(out), base, _stamp(base))[0])
            _save()
            ss.rooms_v = ss.get("rooms_v", 0) + 1
            st.rerun()
    plan, walls, (wx, wy) = _plan(str(out), base, _stamp(base))
    rooms = data["layouts"][lay]
    grid = pd.read_csv(out / CSV_NAME.format(base), usecols=["point_id", "local_x", "local_y"])

    fig = go.Figure()
    xs, ys = [], []
    for ln in walls:
        xs += [ln[0, 0], ln[-1, 0], None]
        ys += [ln[0, 1], ln[-1, 1], None]
    fig.add_trace(go.Scatter(x=xs, y=ys, mode="lines", line=dict(color="#334155", width=1.2), name="벽",
                             hoverinfo="skip"))
    fig.add_trace(go.Scatter(x=grid["local_x"], y=grid["local_y"], mode="markers", name="격자점",
                             marker=dict(size=5, color="#cbd5e1"), hovertext=grid["point_id"], hoverinfo="text"))
    for i, r in enumerate(rooms):
        x0, x1 = sorted((r["x0"], r["x1"]))
        y0, y1 = sorted((r["y0"], r["y1"]))
        fig.add_shape(type="rect", x0=x0, x1=x1, y0=y0, y1=y1, line=dict(color="#2563eb", width=1.5),
                      fillcolor="rgba(37,99,235,0.08)")
        fig.add_annotation(x=(x0 + x1) / 2, y=(y0 + y1) / 2, text=f"<b>{r['name']}</b>", showarrow=False,
                           font=dict(size=12, color="#1e3a8a"))
    fig.update_layout(margin=dict(l=10, r=10, t=10, b=10), plot_bgcolor="white", dragmode="select",
                      legend=dict(orientation="h", y=1.02, x=0), height=560, selectdirection="any")
    fig.update_xaxes(showgrid=False, zeroline=False, title="건물 축 X (m)")
    fig.update_yaxes(showgrid=False, zeroline=False, title="건물 축 Y (m)", scaleanchor="x", scaleratio=1)
    ev = st.plotly_chart(fig, on_select="rerun", selection_mode="box", key=f"rooms_fig_{lay}_{ss.get('rooms_v', 0)}",
                         config={"scrollZoom": True, "displaylogo": False})
    st.caption("그림에서 **마우스로 끌어 범위를 고르면** 그 범위를 방으로 추가할 수 있어요. 휠로 확대, 위쪽 도구의 손 모양으로 이동.")

    box = (ev.selection.get("box") or [None])[-1] if ev and ev.selection else None
    if box:
        bx, by = sorted(box["x"]), sorted(box["y"])
        with st.container(horizontal=True, vertical_alignment="bottom"):
            nm = st.text_input("방 이름", placeholder="예: 2호_침실1", key="rooms_add_name",
                               help="'호수_실명'으로 쓰면 결과가 세대별로 묶여요.")
            snap = st.checkbox("가까운 벽에 맞추기", value=True, key="rooms_snap")
            if st.button("방으로 추가", type="primary", icon=":material/add_box:", key="rooms_add",
                         disabled=not nm.strip()):
                room = {"name": nm.strip(), "x0": round(bx[0], 3), "x1": round(bx[1], 3),
                        "y0": round(by[0], 3), "y1": round(by[1], 3)}
                rooms.append(L.snap_room(room, wx, wy) if snap else room)
                _save()
                ss.rooms_v = ss.get("rooms_v", 0) + 1
                ss.pop("rooms_add_name", None)
                st.rerun()
        st.caption(f"고른 범위: X {bx[0]:.2f} ~ {bx[1]:.2f} m, Y {by[0]:.2f} ~ {by[1]:.2f} m")

    st.markdown("**방 목록** — 이름·범위(m)를 바로 고칠 수 있어요. 줄 왼쪽을 골라 지우거나, 맨 아래 줄에 직접 더할 수 있어요.")
    rdf = pd.DataFrame(rooms, columns=ROOM_COLS)
    red = st.data_editor(rdf, hide_index=True, width="stretch", num_rows="dynamic",
                         key=f"rooms_tab_{lay}_{ss.get('rooms_v', 0)}",
                         column_config={"name": st.column_config.TextColumn("이름", required=True),
                                        **{c: st.column_config.NumberColumn(c.upper() + " (m)", format="%.2f")
                                           for c in ROOM_COLS[1:]}})
    new_rooms = [{"name": str(r["name"]).strip(), **{c: round(float(r[c]), 3) for c in ROOM_COLS[1:]}}
                 for _, r in red.iterrows() if str(r["name"] or "").strip() and r[ROOM_COLS[1:]].notna().all()]
    if new_rooms != rooms:
        data["layouts"][lay] = new_rooms
        _save()
        st.rerun()
    dup = sorted({r["name"] for r in rooms if [q["name"] for q in rooms].count(r["name"]) > 1})
    if dup:
        st.warning(f"이름이 겹치는 방이 있어요: {', '.join(dup)}", icon=":material/warning:")
    auto = [r["name"] for r in rooms if re.fullmatch(r"실\d+", r["name"])]
    if auto:
        st.caption(f"아직 자동 이름인 방 {len(auto)}개: {', '.join(auto)} — 실제 이름으로 바꿔 주세요.")

# ---------------------------------------------------------------- ③ 적용
with st.container(border=True):
    st.subheader("③ 모든 층 도면에 넣기", icon=":material/done_all:")
    cnt = pd.Series(data["floors"]).reindex(labels).value_counts()
    st.markdown(" · ".join(f"**{k}**: {v}개 층, 방 {len(data['layouts'].get(k, []))}개" for k, v in cnt.items()))
    a, b = st.columns(2)
    if a.button("도면에 방 넣기", type="primary", icon=":material/save:", width="stretch", key="rooms_apply",
                help="층마다 그 층 구조의 방을 LAS_평면도_<층>.dxf 에 넣어요."):
        with st.spinner("층별 도면을 만드는 중…"):
            done = L.apply_layouts(out, labels, data)
        ss.rooms_applied = str(out)
        st.success(f"{len(done)}개 층 도면에 방을 넣었어요.", icon=":material/check_circle:")
    if b.button("두께 분석으로 보내기", icon=":material/arrow_forward:", width="stretch", key="rooms_send",
                disabled=ss.get("rooms_applied") != str(out),
                help="층별 CSV 와 방을 넣은 도면을 새 작업으로 두께 분석에 올립니다. 먼저 「도면에 방 넣기」를 누르세요."):
        clear_files()
        ss.files = {**{CSV_NAME.format(lab): (out / CSV_NAME.format(lab)).read_bytes() for lab in labels},
                    **{DXF_NAME.format(lab): (out / DXF_NAME.format(lab)).read_bytes() for lab in labels}}
        st.switch_page("views/analysis.py")
    st.caption("도면은 위층 기준으로 쓰여요. 두께 분석에서 방별 두께도·엑셀이 이 방 이름으로 나와요.")

sidebar_status()
