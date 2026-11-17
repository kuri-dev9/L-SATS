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
import streamlit as st

from slab import las_layout as L
from slab.las import CSV_NAME, DXF_NAME, OUT_DIR, PLAN_NAME
from slab.las_plan import has_data, plan_lines, wall_bands, wall_shapes
from slab.settings_store import load_ui
from views.folder_pick import native_pick
from views.room_editor import room_editor
from views.wall_editor import wall_editor
from views.shared import clear_files, sidebar_status

ss = st.session_state
REMOTE = st.context.ip_address is not None

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
    st.subheader("② 구조마다 벽·방 정하기", icon=":material/edit_square:")
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
    grid = pd.read_csv(out / CSV_NAME.format(base), usecols=["point_id", "local_x", "local_y", "floor_z", "ceiling_z"])
    grid = grid[has_data(grid)]  # 값이 없는 자리(벽 위·건물 밖)의 점은 그리지 않는다
    my_walls = data["walls"].get(lay)  # 실무자가 고친 벽 (없으면 자동 추정 띠로 시작)
    bands, est_t = wall_bands(plan)
    edit_walls = my_walls if my_walls is not None else L.walls_from_bands(bands)
    pts = grid[["local_x", "local_y"]].round(3).to_numpy().tolist()
    faces = [[round(float(v), 3) for v in (*ln[0], *ln[-1])] for ln in walls]
    tab_w, tab_r = st.tabs(["벽 고치기", "방 정하기"])

    with tab_w:
        with st.container(horizontal=True, vertical_alignment="center"):
            st.caption("벽(회색)은 처음엔 스캔에서 추정한 벽이에요. 기본 도면과 다르면 여기서 고치세요 — 고친 벽이 이 구조의 모든 층 도면에 들어가요."
                       + (" **지금은 고친 벽을 쓰고 있어요.**" if my_walls is not None else " 지금은 자동 추정 벽이에요."))
            if my_walls is not None and st.button("자동 추정 벽으로 되돌리기", icon=":material/restart_alt:", key="walls_reset",
                                                  help="고친 벽을 지우고 스캔에서 추정한 벽으로 돌아가요."):
                data["walls"].pop(lay, None)
                _save()
                ss.rooms_v = ss.get("rooms_v", 0) + 1
                st.rerun()
        wsaved = wall_editor(key=f"walls_editor_{lay}", faces=faces, points=pts, walls=edit_walls, fit_key=f"{lay}/{base}",
                             default_t=est_t)
        if wsaved and wsaved.get("walls") is not None:
            data["walls"][lay] = [{"k": w.get("k", "line"), "a": [round(float(v), 3) for v in w["a"]],
                                   "b": [round(float(v), 3) for v in w["b"]], "t": round(float(w.get("t", est_t)), 3),
                                   **({"m": [round(float(v), 3) for v in w["m"]]} if w.get("k") == "arc" and w.get("m") else {})}
                                  for w in wsaved["walls"]]
            _save()
            ss.rooms_v = ss.get("rooms_v", 0) + 1
            st.rerun()
        st.caption("검은 가는 선 = 스캔에서 찾은 실제 벽 면 (기준) · 회색 = 벽 · 회색 점 = 격자점. 「／ 직선 벽」: 시작점 클릭 → 끝점 클릭 "
                   "(이어서 다음 벽, Esc 로 끝). 그리는 중 **숫자를 치고 Enter** 면 그 길이(mm)로 그려요. 「◠ 곡선 벽」: 시작점 → 끝점 → 휘는 정도 클릭. "
                   "벽을 클릭해 고르면 끌어서 옮기고, 끝점(□)을 끌어 길이·방향을, 곡선은 ◇ 로 휘는 정도를 바꿔요. 끝점은 다른 벽 끝에 붙고 "
                   "수평·수직은 딱 맞춰져요 (Shift 를 누르면 자유롭게). 오른쪽 위 칸에서 고른 벽의 **두께·길이(mm)** 를 입력해요. "
                   "다 고쳤으면 **저장**.")

    if my_walls is not None:  # 방 경계는 고친 벽의 면에 붙인다
        fx, fy = L.wall_faces(my_walls)
        wx, wy = np.concatenate([wx, fx]), np.concatenate([wy, fy])
    wall_polys = [p.round(3).tolist() for p in wall_shapes(plan, my_walls)]
    with tab_r:
        saved = room_editor(
            key=f"rooms_editor_{lay}", height=600, fit_key=f"{lay}/{base}", rooms=[
                {"name": r["name"], "poly": L.room_poly(r).round(3).tolist()} for r in rooms],
            walls=faces, wall_x=wx, wall_y=wy,
            points=pts, wall_polys=wall_polys)
        if saved and saved.get("rooms") is not None:
            new = [{"name": str(r["name"]).strip(), "poly": L.clean_poly(r["poly"])}
                   for r in saved["rooms"] if str(r.get("name", "")).strip() and len(r["poly"]) >= 3]
            new = [r for r in new if len(r["poly"]) >= 3]
            if saved.get("cut"):  # 「방에서 빼기」: 그린 네모만큼 모든 방에서 뺀다
                new = L.subtract_rect(plan, new, saved["cut"])
            data["layouts"][lay] = L.resolve_overlaps(plan, new)  # 겹친 칸은 새로 그리거나 마지막에 고친 방 쪽으로
            _save()
            ss.rooms_v = ss.get("rooms_v", 0) + 1
            st.rerun()
        st.caption("회색 = 벽 (「벽 고치기」에서 고친 벽, 없으면 추정) · 검은 선 = 스캔에서 찾은 실제 벽 면 (기준선, 고칠 수 없음) · 파란 영역 = 내가 정한 방 (이 범위·이름이 도면에 들어가요) · "
                   "회색 점 = 격자점 (두께를 재는 자리). **빈 곳을 끌면 새 방**, **방을 클릭**하면 주황색으로 골라지고 방 안을 끌면 통째로, "
                   "**변을 끌면 그 경계만** 움직여요. 변의 일부만 옮기려면 그 자리에서 **우클릭 → 「여기서 벽면 나누기」** 후 한쪽 조각을 끌어요 (필요 없는 점은 방을 고른 뒤 **꼭짓점을 다른 꼭짓점 위로 끌어 놓으면** 두 점이 곧게 이어지고 사이 점이 없어져요). 슬라브가 없는 곳처럼 방에서 빼야 할 곳은 「－ 방에서 빼기」를 켜고 그 범위를 끌면 바로 빠져요. 벽 가까이 가면 벽에 붙어요. 이미 있는 방 위에 새 방을 그리려면 「방 위에 새 방 그리기」를 "
                   "켜세요 — 저장할 때 겹친 부분은 새 방 쪽으로 정리돼요. 다 고쳤으면 그림 오른쪽 위 **저장**을 누르세요.")
        overlap = L.overlaps(plan, rooms)
        if overlap:
            st.warning("겹치는 방이 있어요 (겹친 곳의 격자점은 한 방에만 들어가요): "
                       + ", ".join(f"{a}·{b} {m2:.1f}㎡" for a, b, m2 in overlap), icon=":material/warning:")
        st.markdown("**방 목록** — 이름을 여기서 한꺼번에 고칠 수 있어요. 줄 왼쪽 칸을 골라 휴지통으로 지워요.")
        rdf = pd.DataFrame({"번호": range(len(rooms)), "이름": [r["name"] for r in rooms],
                            "넓이(㎡)": [round(L.poly_area(L.room_poly(r)), 1) for r in rooms]})
        red = st.data_editor(rdf, hide_index=True, width="stretch", num_rows="dynamic", disabled=["번호", "넓이(㎡)"],
                             key=f"rooms_tab_{lay}_{ss.get('rooms_v', 0)}",
                             column_config={"번호": None, "이름": st.column_config.TextColumn(required=True)})
        new_rooms = [{**rooms[int(r["번호"])], "name": str(r["이름"]).strip()} for _, r in red.iterrows()
                     if pd.notna(r["번호"]) and str(r["이름"] or "").strip()]
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
