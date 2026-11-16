"""LAS 변환 화면: 층마다 한 개인 레이저 스캔 점군(LAS/LAZ)에서 같은 격자의 바닥·천장 높이 파일을 만든다.

원본이 1GB 넘게 커서 올리지 않고, 프로그램이 도는 이 PC의 폴더에서 바로 읽는다 (slab/las.py).
만든 CSV 는 두께 분석 화면으로 바로 보낼 수 있다. 미리보기 모드에서는 메뉴에 나오지 않는다.
"""
from __future__ import annotations

import io
import zipfile
from dataclasses import asdict
from pathlib import Path

import pandas as pd
import streamlit as st

from slab.las import GRID_FILE, OUT_DIR, GridSpec, LasParams, convert, find_las, floor_label, las_info
from views.shared import clear_files, job_settings, sidebar_status

ss = st.session_state


@st.cache_data(show_spinner=False, max_entries=200)
def _info(path: str, mtime: float, size: int) -> dict:
    return las_info(Path(path))


def _send_to_analysis(paths: list[str]) -> None:
    clear_files()
    ss.files = {Path(p).name: Path(p).read_bytes() for p in paths}


st.title("LAS 변환", icon=":material/grid_on:")
st.caption("층마다 하나씩 있는 레이저 스캔 점군(LAS·LAZ)에서, 모든 층에 같은 격자를 놓고 격자점마다 바닥·천장 높이를 뽑아 "
           "두께 분석용 파일을 만듭니다. 파일이 커서 올리지 않고 이 PC의 폴더에서 바로 읽어요.")

# ---------------------------------------------------------------- ① 폴더
with st.container(border=True):
    st.subheader("① LAS 파일이 있는 폴더", icon=":material/folder_open:")
    folder = st.text_input("폴더 경로", key="las_folder", persist_state="session",
                           placeholder=r"예: D:\현장\101동\LAS",
                           help="탐색기 주소 표시줄의 경로를 복사해 붙여 넣으세요. 층마다 한 파일이고, 파일 이름에 "
                                "8F 같은 층 표기가 있으면 층 이름을 자동으로 채워요.")
    folder_p = Path(folder.strip().strip('"')) if folder.strip() else None
    files: list[Path] = []
    if folder_p is not None:
        if not folder_p.is_dir():
            st.error("폴더를 찾지 못했어요. 경로를 다시 확인해 주세요.", icon=":material/error:")
        else:
            files = find_las(folder_p)
            if not files:
                st.warning("이 폴더에 LAS·LAZ 파일이 없어요.", icon=":material/warning:")

if not files:
    st.info("폴더를 넣으면 LAS 파일 목록과 점 수를 보여 줘요. 화면 없이 하려면 프로그램 폴더의 "
            "`LAS_TO_GRID.bat` 위에 LAS 폴더를 끌어다 놓으세요.", icon=":material/info:")
    sidebar_status()
    st.stop()

rows, bad = [], []
for f in files:
    stat = f.stat()
    try:
        i = _info(str(f), stat.st_mtime, stat.st_size)
    except Exception as e:  # 깨진 파일·지원하지 않는 형식
        bad.append(f"{f.name}: {e}")
        continue
    rows.append({"사용": True, "파일": f.name, "층": floor_label(f), "점 수": i["points"], "크기(MB)": i["size_mb"],
                 "높이 범위(m)": f"{i['z'][0]:.2f} ~ {i['z'][1]:.2f}"})
for b in bad:
    st.error(b, title="읽지 못한 파일", icon=":material/error:")
table = st.data_editor(pd.DataFrame(rows), hide_index=True, width="stretch", key=f"las_files_{folder}",
                       disabled=["파일", "점 수", "크기(MB)", "높이 범위(m)"], alt="LAS 파일 목록",
                       column_config={"점 수": st.column_config.NumberColumn(format="localized")})
st.caption("층 이름이 틀렸으면 **층** 칸을 고치세요. 두께 분석에서 이 이름으로 층을 나열합니다.")

# ---------------------------------------------------------------- ② 격자
out_dir = folder_p / OUT_DIR
s = job_settings()
params = LasParams.from_settings(s)
with st.container(border=True):
    st.subheader("② 격자", icon=":material/grid_4x4:")
    old = GridSpec.load(out_dir / GRID_FILE)
    if old is not None and abs(old.spacing_m - params.spacing_m) < 1e-9:
        st.markdown(f"이 폴더에 정해 둔 격자를 **모든 층에 그대로** 씁니다: 간격 {old.spacing_m:g} m · "
                    f"건물 축 {old.angle_deg:g}° · {old.nx} × {old.ny} 칸")
        new_grid = st.checkbox("격자 새로 정하기", key="las_new_grid",
                               help="건물 범위가 바뀌었을 때만 쓰세요. 이전에 만든 층 파일과 격자가 달라집니다.")
    else:
        st.markdown(f"처음 변환하면 모든 층을 덮는 격자를 새로 정해 저장해요 (간격 {params.spacing_m:g} m). "
                    "측량 좌표에서 기울어진 건물 축(벽 방향)을 찾아 격자를 맞추고, 결과 그림도 그 방향으로 반듯하게 그립니다.")
        new_grid = False
    st.caption(f"저장 위치: `{out_dir}` · 격자 간격 등은 설정 → LAS 변환에서 바꿀 수 있어요.")

# ---------------------------------------------------------------- ③ 변환
use = table[table["사용"]]
with st.container(border=True):
    st.subheader("③ 변환", icon=":material/play_arrow:")
    go = st.button(f"{len(use)}개 층 변환", type="primary", icon=":material/play_arrow:", disabled=use.empty,
                   key="las_go", help="큰 파일은 층마다 1~2분 걸릴 수 있어요. 끝날 때까지 이 화면을 닫지 마세요.")
    if go:
        bar = st.progress(0.0, text="시작하는 중…")
        try:
            grid, summary, paths = convert(
                [folder_p / n for n in use["파일"]], out_dir, params,
                labels={n: str(l).strip() for n, l in zip(use["파일"], use["층"]) if str(l).strip()},
                new_grid=new_grid, progress=lambda f, m: bar.progress(min(f, 1.0), text=m))
        except (RuntimeError, ValueError, OSError) as e:
            bar.empty()
            st.error(str(e), title="변환하지 못했어요", icon=":material/error:")
        else:
            bar.empty()
            ss.las_result = {"grid": asdict(grid), "summary": summary.to_dict("records"),
                             "paths": [str(p) for p in paths], "out": str(out_dir)}
            ss.pop("las_new_grid", None)

    res = ss.get("las_result")
    if res and Path(res["out"]) == out_dir:
        g = res["grid"]
        st.success(f"{len(res['paths'])}개 층 파일을 만들었어요. 격자 간격 {g['spacing_m']:g} m · 건물 축 {g['angle_deg']:g}° "
                   f"· {g['nx']} × {g['ny']} 칸 (모든 층 같은 격자)", icon=":material/check_circle:")
        st.dataframe(pd.DataFrame(res["summary"]).drop(columns=["CSV"]), hide_index=True, width="stretch",
                     alt="층별 변환 결과")
        st.caption("층고 = 천장면 − 바닥면. 바닥·천장 측정은 그 면의 점이 충분한 격자점 수예요. "
                   "측정이 적은 격자점은 두께 분석에서 '미산출'로 나옵니다.")
        a, b = st.columns(2)
        if a.button("두께 분석으로 보내기", type="primary", icon=":material/arrow_forward:", width="stretch",
                    key="las_send", help="만든 파일을 새 작업으로 두께 분석에 올립니다. 지금 작업은 작업 내역에 남아요."):
            _send_to_analysis(res["paths"])
            st.switch_page("views/analysis.py")

        def _zip() -> bytes:
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
                for p in res["paths"]:
                    z.write(p, Path(p).name)
                z.write(Path(res["out"]) / GRID_FILE, GRID_FILE)
            return buf.getvalue()

        b.download_button("만든 파일 받기 (ZIP)", _zip, "LAS_격자_높이.zip", "application/zip",
                          icon=":material/folder_zip:", width="stretch", on_click="ignore",
                          help="층별 CSV 와 격자 정의(grid.json). 다른 PC에서 두께 분석에 올릴 때 쓰세요.")

sidebar_status()
