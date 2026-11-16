"""웹 화면 스모크 테스트: 가상 데이터(demo_data)를 올린 것처럼 넣고 화면이 오류 없이 그려지는지."""
import json
from pathlib import Path

from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]
APP = str(ROOT / "app.py")
FILES = {"upper": "grid_analysis_floor_level_8F.csv", "lower": "grid_analysis_floor_level_7F.csv",
         "cad": "report_merge_8F.dxf"}


def _files():
    return {k: (n, (ROOT / "demo_data" / n).read_bytes()) for k, n in FILES.items()}


def _home() -> AppTest:
    return AppTest.from_file(APP, default_timeout=120).run()


def _analysis() -> AppTest:
    at = _home()
    at.session_state["files"] = _files()
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
    assert any("파일을 올려 주세요" in i.value for i in at.info)


def test_analysis_runs():
    at = _analysis()
    assert not at.exception
    assert not at.error[1:]  # 오류 상자는 '얇은 방' 판정 하나뿐
    labels = {m.label for m in at.metric}
    assert {"평균 두께", "기준 통과한 방", "미달 방", "사용한 측정점", "오차(RMS)"} <= labels
    # 가상 데이터에서는 101호_침실2만 얇게 만들어 두었다
    assert "101호_침실2" in at.error[0].value


def test_analysis_is_saved_to_history():
    from slab import history

    at = _analysis()
    at.text_input(key="meta_dong").set_value("101동").run()
    jobs = history.list_jobs()
    assert len(jobs) == 1  # 같은 작업은 고쳐 쓰고 새로 만들지 않는다
    job = jobs[0]
    assert job["dong"] == "101동" and job["summary"]["n_bad"] == 1
    assert set(history.load_files(job["id"])) == {"cad", "upper", "lower"}
    assert any("101동" in m.value for m in at.sidebar.markdown)


def _open_script():
    import sys

    import streamlit as st

    sys.path.insert(0, st.session_state["root"])
    from views.shared import compute, open_job

    ok = open_job(st.session_state["open_id"])
    run = compute()
    st.write(f"ok={ok} dong={st.session_state.get('meta_dong')} names={st.session_state.room_names} "
             f"mean={run.result.summary['mean_mm']:.3f}")


def test_open_job_restores_result():
    from slab import history

    at = _analysis()
    at.text_input(key="meta_dong").set_value("101동").run()
    mean = history.list_jobs()[0]["summary"]["mean_mm"]
    job_id = history.list_jobs()[0]["id"]
    history.update_job(job_id, room_names={"R08": "102호_창고"})
    t = AppTest.from_function(_open_script, default_timeout=120)
    t.session_state["root"] = str(ROOT)
    t.session_state["open_id"] = job_id
    t.run()
    assert not t.exception
    text = t.markdown[0].value
    assert "ok=True" in text and "dong=101동" in text and "102호_창고" in text
    assert f"mean={mean:.1f}"[:-1] in text
    assert len(history.list_jobs()) == 1  # 연 작업은 새로 만들지 않는다
    home = _home()
    assert any(m.label == "저장된 작업" and m.value == "1건" for m in home.metric)


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


def test_open_job_restores_inputs():
    from slab import history
    from views import shared

    at = _analysis()
    at.text_input(key="meta_dong").set_value("102동").run()
    job_id = history.list_jobs()[0]["id"]
    files = history.load_files(job_id)
    assert {k: v[0] for k, v in files.items()} == FILES


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


def test_room_table_filters():
    at = _analysis()
    at.text_input(key="room_q").set_value("침실2").run()
    assert not at.exception
    at.toggle(key="room_bad").set_value(True).run()
    assert not at.exception
    assert any("1개 방 표시 중" in c.value for c in at.caption)


def test_floor_guess():
    from views.shared import guess_floor

    assert guess_floor(FILES["upper"]) == "8F" and guess_floor("B1_천장.csv") == "B1"


def test_view_toggle():
    at = _analysis()
    for view in ("3d", "points", "map"):
        at.button_group(key="view_mode").set_value(view).run()
        assert not at.exception


def test_settings_page_saves(_settings_file):
    at = _home()
    at.switch_page("views/settings.py").run()
    assert not at.exception
    assert any("판정 기준 고정" in m.value and "135" in m.value for m in at.markdown)  # 보여 주기만 한다
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
    assert len(at.get("download_button")) == 5
    assert at.session_state["report_sections"] == ["summary", "room_map", "action", "notes", "signoff"]
    at.button_group(key="report_kind").set_value("상세 보고서").run()
    assert not at.exception
    assert "points_table" in at.session_state["report_sections"]
    at.button_group(key="report_sections").set_value(["summary"]).run()
    assert not at.exception


def test_report_page_without_files():
    at = _home()
    at.switch_page("views/report.py").run()
    assert not at.exception
    assert any("파일이 없어요" in i.value for i in at.info)


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
    assert not at.exception and len(at.get("download_button")) == 5


def test_mismatched_cad_and_scans_is_an_error():
    """다른 현장의 도면(방이 측정점과 전혀 겹치지 않음)을 올리면 결과 대신 오류를 보여 주고 내역에 저장하지 않는다."""
    import io

    import ezdxf
    import pandas as pd

    from slab import history

    up = pd.read_csv(ROOT / "demo_data" / FILES["upper"])
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
    files["cad"] = ("other_site.dxf", buf.getvalue().encode())
    at = _home()
    at.session_state["files"] = files
    at.switch_page("views/analysis.py").run()
    assert not at.exception
    assert any("모두 도면의 방 밖" in e.value for e in at.error)
    assert not [m for m in at.metric if m.label == "평균 두께"]
    assert history.list_jobs() == []


def test_floor_autofill_follows_new_file():
    from views import shared  # noqa: F401

    def script():
        import sys

        import streamlit as st

        sys.path.insert(0, st.session_state["root"])
        from views.shared import init_state, store_upload

        class Up:
            def __init__(self, name):
                self.name = name

            def getvalue(self):
                return b"x"

        init_state()
        for kind, name in st.session_state["seq"]:
            st.session_state[f"up_{kind}"] = Up(name)
            store_upload(kind)
        st.write(f"{st.session_state.get('meta_upper')}|{st.session_state.get('meta_lower')}")

    t = AppTest.from_function(script)
    t.session_state["root"] = str(ROOT)
    # 위층 칸에 7F 파일을 잘못 올렸다가 8F 파일로 바꾸면 위층 이름도 8F 로 바뀐다
    t.session_state["seq"] = [("upper", "scan_7F.csv"), ("lower", "scan_7F.csv"), ("upper", "scan_8F.csv")]
    t.run()
    assert t.markdown[0].value == "8F|7F"
    # 직접 쓴 이름은 바꾸지 않는다
    t2 = AppTest.from_function(script)
    t2.session_state["root"] = str(ROOT)
    t2.session_state["meta_upper"] = "9층"
    t2.session_state["seq"] = [("upper", "scan_8F.csv")]
    t2.run()
    assert t2.markdown[0].value.startswith("9층|")
