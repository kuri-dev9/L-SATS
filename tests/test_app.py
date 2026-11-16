"""웹 화면 스모크 테스트: 가상 데이터(demo_data)를 올린 것처럼 넣고 화면이 오류 없이 그려지는지."""
import io
import json
from pathlib import Path

import pandas as pd
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]
APP = str(ROOT / "app.py")
NAMES = ["grid_analysis_floor_level_8F.csv", "grid_analysis_floor_level_7F.csv", "report_merge_8F.dxf"]


def _files():
    return {n: (ROOT / "demo_data" / n).read_bytes() for n in NAMES}


def _extra_floor(level_shift: float, name: str) -> bytes:
    """8F 스캔을 한 층 위로 옮긴 가상 층 (9F 등)."""
    df = pd.read_csv(ROOT / "demo_data" / NAMES[0])
    for c in ("floor_z", "ceiling_z", *(c for c in df.columns if c.startswith("Global_"))):
        if c.endswith("_mm"):
            df[c] = df[c] + level_shift * 1000
        else:
            df[c] = df[c] + level_shift
    return df.to_csv(index=False).encode()


def _home() -> AppTest:
    return AppTest.from_file(APP, default_timeout=120).run()


def _analysis(files=None) -> AppTest:
    at = _home()
    at.session_state["files"] = files or _files()
    at.switch_page("views/analysis.py").run()
    return at


def test_home_without_jobs():
    at = _home()
    assert not at.exception
    assert any(m.label == "저장된 작업" and m.value == "0건" for m in at.metric)
    assert any("열린 작업 없음" in c.value for c in at.sidebar.caption)


def test_analysis_without_files_asks_for_upload():
    at = _home()
    at.switch_page("views/analysis.py").run()
    assert not at.exception
    assert any("스캔 파일을 올려 주세요" in i.value for i in at.info)


def test_analysis_runs():
    at = _analysis()
    assert not at.exception
    assert not at.error
    labels = {m.label for m in at.metric}
    assert {"찾은 층", "계산한 층", "전체 평균 두께", "평균 두께", "산출 완료", "검토 필요 / 미산출", "오차(RMS)"} <= labels
    assert at.selectbox(key="floor_sel").value == "8F"  # 계산된 맨 위층
    text = " ".join(str(x.value) for x in [*at.markdown, *at.caption, *at.metric])
    assert "통과" not in text and "미달" not in text  # 판정 없이 현황만


def test_multi_floor_navigation():
    files = {**_files(), "grid_analysis_floor_level_9F.csv": _extra_floor(2.6, "9F")}
    at = _analysis(files)
    assert not at.exception
    opts = at.selectbox(key="floor_sel").options
    assert opts[0].startswith("9F 바닥 / 8F 천장 · 평균") and opts[2] == "7F (맨 아래층) · 계산 안 됨"
    assert at.selectbox(key="floor_sel").value == "9F"
    assert any(m.label == "계산한 층" and m.value == "2개" for m in at.metric)
    at.button(key="down_analysis").click().run()
    assert not at.exception and at.selectbox(key="floor_sel").value == "8F"
    assert at.button(key="down_analysis").disabled is False  # 7F(맨 아래층)도 목록에 있다
    at.button(key="down_analysis").click().run()
    assert not at.exception and at.selectbox(key="floor_sel").value == "7F"
    assert any("맨 아래층" in w.value for w in at.warning)
    at.selectbox(key="floor_sel").set_value("9F").run()
    assert not at.exception
    # 9F 는 8F 도면을 쓰지 못한다(층 표기가 다르고 공용 도면도 없음) → 도면 없이 계산
    assert at.selectbox(key="room_zoom").options == ["(전체)"]


def test_point_zoom_and_detail():
    at = _analysis()
    at.selectbox(key="room_zoom").set_value("101호_거실").run()
    assert not at.exception
    at.selectbox(key="pt_pick").set_value("P010").run()
    assert not at.exception
    # 점 상세는 그림(도면 보기) 안의 카드로 뜬다: 고른 점과 그 점의 상세 값이 그림 데이터로 넘어간다
    from views.plan_viewer import _detail, plan_viewer  # noqa: F401
    assert at.selectbox(key="pt_pick").value == "P010"
    at.selectbox(key="pt_pick").set_value(None).run()
    assert not at.exception and at.selectbox(key="pt_pick").value is None


def test_plan_viewer_data():
    """도면 보기에 넘기는 값: 상세 카드 항목, 가장 확대 기준(가장 작은 방), 북쪽 회전각."""
    from slab import analyze, load_cad, load_grid
    from views.plan_viewer import _detail, north_rotation

    r = analyze(load_grid(ROOT / "demo_data" / NAMES[0]), load_grid(ROOT / "demo_data" / NAMES[1]),
                load_cad(ROOT / "demo_data" / NAMES[2]))
    p = r.points.iloc[0]
    rows = dict(_detail(p, {}))
    assert rows["결과 상태"] == p["status"] and "아래층 천장 Z" in rows
    assert north_rotation(r) == round(-r.transform.rotation_deg, 2)


def test_sub_views():
    at = _analysis()
    for view in ("table", "3d", "rooms"):
        at.button_group(key="sub_view").set_value(view).run()
        assert not at.exception


def test_analysis_is_saved_to_history():
    from slab import history

    at = _analysis()
    at.text_input(key="meta_dong").set_value("101동").run()
    jobs = history.list_jobs()
    assert len(jobs) == 1  # 같은 작업은 고쳐 쓰고 새로 만들지 않는다
    job = jobs[0]
    assert job["dong"] == "101동" and job["summary"]["n_floors"] == 1
    assert job["floors_text"] == "8F-7F"
    assert set(history.load_files(job["id"])) == set(NAMES)
    assert any("101동" in m.value for m in at.sidebar.markdown)


def _open_script():
    import sys

    import streamlit as st

    sys.path.insert(0, st.session_state["root"])
    from views.shared import compute, open_job

    ok = open_job(st.session_state["open_id"])
    b = compute()
    st.write(f"ok={ok} dong={st.session_state.get('meta_dong')} names={st.session_state.room_names} "
             f"labels={st.session_state.floor_labels} mean={b.ready[0].result.summary['mean_mm']:.3f}")


def test_open_job_restores_result():
    from slab import history

    at = _analysis()
    at.text_input(key="meta_dong").set_value("101동").run()
    job = history.list_jobs()[0]
    mean = job["summary"]["floors"][0]["mean_mm"]
    history.update_job(job["id"], room_names={NAMES[2]: {"R08": "102호_창고"}})
    t = AppTest.from_function(_open_script, default_timeout=120)
    t.session_state["root"] = str(ROOT)
    t.session_state["open_id"] = job["id"]
    t.run()
    assert not t.exception
    text = t.markdown[0].value
    assert "ok=True" in text and "dong=101동" in text and "102호_창고" in text
    assert f"mean={mean:.1f}"[:-1] in text
    assert len(history.list_jobs()) == 1  # 연 작업은 새로 만들지 않는다
    home = _home()
    assert any(m.label == "저장된 작업" and m.value == "1건" for m in home.metric)


def test_old_v02_job_opens():
    """v0.2 작업(위층·아래층·도면 칸): 파일 이름에 층이 없어도 저장된 층 이름을 쓴다."""
    from slab import history

    folder = history.history_dir() / "files" / "old"
    folder.mkdir(parents=True)
    src = _files()
    for kind, name in zip(("upper", "lower", "cad"), NAMES):
        (folder / f"{kind}_{kind}.{name.rsplit('.', 1)[1]}").write_bytes(src[name])
    job = {"id": "old", "dong": "101동", "upper_floor": "8층", "lower_floor": "7층", "updated": "2026-01-01T00:00:00",
           "room_names": {"R08": "창고"},
           "files": {k: {"name": f"{k}.{n.rsplit('.', 1)[1]}", "md5": ""} for k, n in zip(("upper", "lower", "cad"),
                                                                                       NAMES)},
           "summary": {"verdict": "미달", "n_ok": 1, "n_rooms": 8, "mean_mm": 140.0}}
    (history.history_dir() / "history.json").write_text(json.dumps([job], ensure_ascii=False), encoding="utf-8")
    at = AppTest.from_file(APP, default_timeout=120)
    at.query_params["job"] = "old"
    at.run()
    at.switch_page("views/analysis.py").run()
    assert not at.exception
    assert at.selectbox(key="floor_sel").value == "8층"
    assert "창고" in at.selectbox(key="room_zoom").options
    jobs = _home()
    jobs.switch_page("views/jobs.py").run()
    assert not jobs.exception


def test_jobs_page_edit_and_delete():
    from slab import history

    _analysis()
    job_id = history.list_jobs()[0]["id"]
    history.update_job(job_id, name="첫 작업", memo="코어 확인 예정")
    at = _home()
    at.switch_page("views/jobs.py").run()
    assert not at.exception
    assert at.button(key="jobs_open").disabled and at.button(key="jobs_delete").disabled
    history.delete_job(job_id)
    at.run()
    assert not at.exception
    assert history.list_jobs() == [] and not (history.history_dir() / "files" / job_id).exists()


def test_settings_snapshot_and_recalc(_settings_file):
    from slab import Settings
    from slab.settings_store import save_settings

    at = _analysis()
    save_settings(Settings(method="nearest"), _settings_file)
    at.run()
    assert not at.exception
    assert at.button(key="recalc")  # 지금 설정과 다르다는 안내
    at.button(key="recalc").click().run()
    assert not at.exception
    assert not [b for b in at.button if b.key == "recalc"]


def test_floor_names_and_cad_can_be_fixed():
    at = _analysis()
    at.session_state["floor_labels"] = {NAMES[0]: "8층"}
    at.session_state["cad_choice"] = {"8층": ""}
    at.run()
    assert not at.exception
    assert at.selectbox(key="floor_sel").value == "8층"
    assert at.selectbox(key="room_zoom").options == ["(전체)"]  # 도면 없이


def test_settings_page_saves(_settings_file):
    at = _home()
    at.switch_page("views/settings.py").run()
    assert not at.exception
    assert any("판정 없음" in b.label for b in at.get("badge")) or any("판정 없음" in m.value for m in at.markdown)
    assert at.button(key="settings_save").disabled
    at.number_input(key="set_max_match_dist_m").set_value(0.15)
    at.selectbox(key="set_excel_layout").set_value("full").run()
    assert not at.exception
    assert any("저장 안 된 변경 2개" in m.value for m in at.markdown)
    at.button(key="settings_save").click().run()
    assert not at.exception
    saved = json.loads(_settings_file.read_text(encoding="utf-8"))
    assert saved["max_match_dist_m"] == 0.15 and saved["excel_layout"] == "full"
    assert "design_mm" not in saved
    at.button(key="reset_all").click().run()
    assert at.number_input(key="set_max_match_dist_m").value == 1.2
    at.button(key="settings_revert").click().run()
    assert at.number_input(key="set_max_match_dist_m").value == 0.15


def test_report_page():
    at = _analysis()
    at.switch_page("views/report.py").run()
    assert not at.exception
    assert len(at.get("download_button")) == 7  # 전체 2 + 이 층 5
    assert at.session_state["report_sections"] == ["summary", "point_map", "room_map", "review", "notes", "signoff"]
    at.button_group(key="report_kind").set_value("상세 보고서").run()
    assert not at.exception
    assert "points_table" in at.session_state["report_sections"]
    at.button_group(key="report_sections").set_value(["summary"]).run()
    assert not at.exception


def test_report_page_without_files():
    at = _home()
    at.switch_page("views/report.py").run()
    assert not at.exception
    assert any("계산된 층이 없어요" in i.value for i in at.info)


def test_job_reopens_from_url():
    from slab import history

    _analysis()
    job_id = history.list_jobs()[0]["id"]
    at = AppTest.from_file(APP, default_timeout=120)
    at.query_params["job"] = job_id
    at.run()
    assert not at.exception
    assert at.session_state["job_id"] == job_id
    at.switch_page("views/report.py").run()
    assert not at.exception and len(at.get("download_button")) == 7


def test_build_all_zip():
    import zipfile

    from slab.report import build_all
    from views.shared import stem_of

    files = {**_files(), "grid_analysis_floor_level_9F.csv": _extra_floor(2.6, "9F")}
    at = _analysis(files)
    assert not at.exception
    from slab import analyze, load_cad, load_grid

    r = analyze(load_grid(ROOT / "demo_data" / NAMES[0]), load_grid(ROOT / "demo_data" / NAMES[1]),
                load_cad(ROOT / "demo_data" / NAMES[2]))
    runs = [({"동": "101동", "상부층": "8F", "하부층": "7F"}, r, ""), ({"동": "101동", "상부층": "7F", "하부층": ""},
                                                                    None, "맨 아래층")]
    z = zipfile.ZipFile(io.BytesIO(build_all(runs, "101동", stem_of)))
    assert sorted(z.namelist()) == ["101동_전체층_요약.xlsx", "층별/101동_8F-7F_슬래브두께.dxf",
                                    "층별/101동_8F-7F_슬래브두께.xlsx"]


def test_mismatched_cad_and_scans_is_an_error():
    """다른 현장의 도면(방이 측정점과 전혀 겹치지 않음)을 올리면 그 층은 결과 대신 오류를 보여 주고 내역에 저장하지 않는다."""
    import ezdxf

    from slab import history

    up = pd.read_csv(ROOT / "demo_data" / NAMES[0])
    doc = ezdxf.new("R2018")
    msp = doc.modelspace()
    for pid, x, y in up[["point_id", "x", "y"]].head(5).itertuples(index=False):  # 측정점 라벨은 맞지만
        msp.add_circle((x * 1000, y * 1000), 50)
        msp.add_text(pid, height=100).set_placement((x * 1000, y * 1000))
    msp.add_lwpolyline([(0, 0), (5000, 0), (5000, 5000), (0, 5000)], close=True,  # 방은 엉뚱한 곳
                       dxfattribs={"layer": "ROOM_BOUNDARY"})
    buf = io.StringIO()
    doc.write(buf)
    files = _files()
    del files[NAMES[2]]
    files["other_site_8F.dxf"] = buf.getvalue().encode()
    at = _analysis(files)
    assert not at.exception
    assert any("모두 도면" in w.value and "방 밖" in w.value for w in at.warning)
    assert not [m for m in at.metric if m.label == "평균 두께"]
    assert history.list_jobs() == []


def test_uploads_are_added_and_dong_autofills():
    def script():
        import sys

        import streamlit as st

        sys.path.insert(0, st.session_state["root"])
        from views.shared import init_state, store_uploads

        class Up:
            def __init__(self, name):
                self.name = name

            def getvalue(self):
                return b"x"

        init_state()
        for batch in st.session_state["seq"]:
            st.session_state["k"] = [Up(n) for n in batch]
            store_uploads("k")
        st.write(f"{sorted(st.session_state.files)}|{st.session_state.get('meta_dong')}|{st.session_state.up_n}")

    t = AppTest.from_function(script)
    t.session_state["root"] = str(ROOT)
    # 두 번 나눠 올려도 모두 남고, 같은 이름은 바뀌고, 다른 형식은 빠진다
    t.session_state["seq"] = [["101동_7F.csv", "101동_8F.csv"], ["101동_8F.csv", "plan.dxf", "memo.pdf"]]
    t.run()
    assert t.markdown[0].value == "['101동_7F.csv', '101동_8F.csv', 'plan.dxf']|101동|2"
    # 직접 쓴 동 이름은 바꾸지 않는다
    t2 = AppTest.from_function(script)
    t2.session_state["root"] = str(ROOT)
    t2.session_state["meta_dong"] = "가동"
    t2.session_state["seq"] = [["101동_8F.csv"]]
    t2.run()
    assert "|가동|" in t2.markdown[0].value
