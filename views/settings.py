"""설정 화면: 계산·출력 설정을 바꿔 user_settings.json 에 저장한다.

항목 목록과 설명은 slab/settings_store.py 의 FIELDS 한 곳에서 정한다.
통과/미달 판정 기준은 없다(두께 현황 파악이 목적). 결과 상태(검토·미산출) 기준만 바꿀 수 있다.
값을 바꾸면 위쪽 막대에 '저장 안 된 변경'이 보이고, 저장을 눌러야 파일에 남는다.
"""
from __future__ import annotations

import json

import streamlit as st

from slab import Settings
from slab.settings_store import (
    FIELDS, GROUPS, from_dict, load_settings, load_ui, save_settings, save_ui, settings_path, to_dict,
)
from views.shared import sidebar_status

GROUP_ICONS = {"match": ":material/join_inner:", "units": ":material/straighten:",
               "exclude": ":material/filter_alt:", "rooms": ":material/meeting_room:",
               "output": ":material/description:"}
DEFAULT = Settings()


def _k(key: str) -> str:
    return f"set_{key}"


def _show(f, v) -> str:
    if f.options:
        return f.options.get(v, str(v))
    if isinstance(v, bool):
        return "켬" if v else "끔"
    return f"{v:g}" if isinstance(v, float) else str(v)


def _load_into_widgets(s: Settings) -> None:
    for f in FIELDS:
        st.session_state[_k(f.key)] = getattr(s, f.key)


def _current() -> Settings:
    vals = {f.key: st.session_state[_k(f.key)] for f in FIELDS if _k(f.key) in st.session_state}
    return from_dict({**to_dict(load_settings()), **vals})[0]


def _save() -> None:
    save_settings(_current())
    st.toast("저장했어요. 두께 분석·보고서에 바로 반영됩니다.", icon=":material/check_circle:")


def _revert() -> None:
    _load_into_widgets(load_settings())


def _reset(keys=None) -> None:
    for f in FIELDS:
        if keys is None or f.key in keys:
            st.session_state[_k(f.key)] = getattr(DEFAULT, f.key)


def _import() -> None:
    up = st.session_state.get("settings_upload")
    if up is None:
        return
    try:
        data = json.loads(up.getvalue().decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        st.session_state["settings_import_msg"] = ("error", "설정 파일(JSON)을 읽지 못했어요.")
        return
    s, bad = from_dict(data if isinstance(data, dict) else {})
    _load_into_widgets(s)
    msg = "불러왔어요. 위의 **저장**을 눌러야 적용됩니다."
    if bad:
        msg += " 잘못된 값은 기본값을 썼어요: " + ", ".join(bad)
    st.session_state["settings_import_msg"] = ("info", msg)


# 처음 열 때(또는 저장 파일이 바뀐 뒤) 위젯 값을 저장된 설정으로 채운다
saved = load_settings()
for f in FIELDS:
    if _k(f.key) not in st.session_state:
        st.session_state[_k(f.key)] = getattr(saved, f.key)

st.title("설정", icon=":material/settings:")
st.caption("담당자용입니다. 저장한 값은 이 PC에 남아서, 프로그램을 다시 켜거나 업데이트해도 그대로 쓰입니다.")


def _toggle_preview() -> None:
    ui = load_ui()
    ui["preview_mode"] = bool(st.session_state["ui_preview"])
    save_ui(ui)


bar = st.container(border=True, key="settings_bar")  # 저장 막대: 아래 값을 다 읽은 뒤 채운다

with st.container(horizontal=True, vertical_alignment="center"):
    st.badge("통과/미달 판정 없음 · 두께 현황", color="blue", icon=":material/info:")
    st.caption("측정점마다 두께와 결과 상태(산출 완료·두께 범위 검토·이상치 검토·하한 이하·미산출·영역 외)를 보여 줍니다. "
               "'결과 상태 기준' 탭에서 검토로 표시할 기준을 바꿀 수 있어요.")


def _field(f) -> None:
    key = _k(f.key)
    base = getattr(DEFAULT, f.key)
    left, right = st.columns([3, 2], vertical_alignment="center", gap="medium")
    with left:
        with st.container(horizontal=True, gap="small", vertical_alignment="center"):
            st.markdown(f"**{f.label}**")
            if st.session_state[key] != base:
                st.badge("기본값과 다름", color="blue", icon=":material/edit:")
            if f.pending:
                st.badge("담당자 확인 필요", color="orange", icon=":material/pending:")
        if f.help:
            st.caption(f.help)
    with right:
        kw = dict(key=key, label_visibility="collapsed", persist_state="session")
        if f.options:
            st.selectbox(f.label, list(f.options), format_func=f.options.get, **kw)
        elif isinstance(base, bool):
            st.toggle(f.label, **kw)
        elif isinstance(base, int):
            st.number_input(f.label, int(f.min), int(f.max), step=int(f.step or 1), **kw)
        elif isinstance(base, float):
            st.number_input(f.label, float(f.min), float(f.max), step=float(f.step or 0.1), format="%g", **kw)
        else:
            st.text_input(f.label, **kw)
        st.caption(f"기본값: {_show(f, base)}")


tabs = st.tabs([f"{GROUP_ICONS[g]} {name}" for g, name in GROUPS.items()])
for tab, (g, name) in zip(tabs, GROUPS.items()):
    items = [f for f in FIELDS if f.group == g]
    with tab:
        for i, f in enumerate(items):
            if i:
                st.divider()
            _field(f)
        st.space("small")
        st.button(f"'{name}' 기본값으로", icon=":material/restart_alt:", key=f"reset_{g}", type="tertiary",
                  on_click=_reset, args=([f.key for f in items],))

# ---------------------------------------------------------------- 저장 막대
current = _current()
unsaved = {f.key for f in FIELDS if getattr(current, f.key) != getattr(saved, f.key)}
with bar:
    with st.container(horizontal=True, vertical_alignment="center"):
        if unsaved:
            st.badge(f"저장 안 된 변경 {len(unsaved)}개", color="orange", icon=":material/edit_note:")
            st.caption(", ".join(f.label for f in FIELDS if f.key in unsaved))
        else:
            st.badge("저장됨", color="green", icon=":material/check_circle:")
            n_diff = sum(getattr(saved, f.key) != getattr(DEFAULT, f.key) for f in FIELDS)
            st.caption(f"기본값과 다른 항목 {n_diff}개" if n_diff else "모두 기본값입니다.")
        st.space("stretch")
        st.button("되돌리기", icon=":material/undo:", on_click=_revert, disabled=not unsaved, key="settings_revert")
        st.button("저장", icon=":material/save:", type="primary", on_click=_save, disabled=not unsaved,
                  key="settings_save")

# ---------------------------------------------------------------- 설정 파일
st.space("medium")
with st.container(border=True):
    st.subheader("설정 파일", icon=":material/folder_open:")
    st.caption(f"저장 위치: `{settings_path()}` · 다른 PC에 같은 설정을 쓰려면 받은 파일을 그 PC에서 불러오세요.")
    c1, c2, c3 = st.columns(3, vertical_alignment="top")
    c1.download_button("지금 설정 받기 (JSON)", json.dumps(to_dict(saved), ensure_ascii=False, indent=2),
                       "L-STAS-settings.json", "application/json", icon=":material/download:", width="stretch",
                       on_click="ignore")
    c2.file_uploader("설정 파일 불러오기", type=["json"], key="settings_upload", on_change=_import,
                     label_visibility="collapsed")
    c3.button("모두 기본값으로", icon=":material/restart_alt:", on_click=_reset, width="stretch", key="reset_all",
              help="값만 기본값으로 바꿉니다. 위의 저장을 눌러야 적용돼요.")
    msg = st.session_state.pop("settings_import_msg", None)
    if msg:
        (st.error if msg[0] == "error" else st.info)(msg[1])

# ---------------------------------------------------------------- 화면 모드 (맨 아래)
# 계산 설정과 따로 바로 저장한다 (작업 결과에는 영향 없음)
st.space("medium")
with st.container(border=True, key="ui_box"):
    st.toggle("미리보기 모드", value=load_ui()["preview_mode"], key="ui_preview", on_change=_toggle_preview)

sidebar_status()
