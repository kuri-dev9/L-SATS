"""웹 화면 스모크 테스트: 데모 데이터로 화면 전체가 오류 없이 그려지는지."""
from pathlib import Path

from streamlit.testing.v1 import AppTest

APP = str(Path(__file__).resolve().parents[1] / "app.py")


def _run() -> AppTest:
    return AppTest.from_file(APP, default_timeout=120).run()


def test_app_runs_with_demo():
    at = _run()
    assert not at.exception
    assert not at.error[1:]  # 데모에서 나오는 오류 상자는 '얇은 방' 판정 하나뿐
    labels = {m.label for m in at.metric}
    assert {"평균 두께", "기준 통과한 방", "사용한 측정점", "오차(RMS)"} <= labels


def test_app_shows_thin_room_verdict():
    at = _run()
    # 데모에서는 101호_침실2만 얇게 만들어 두었다
    assert "101호_침실2" in at.error[0].value


def test_app_has_downloads():
    at = _run()
    assert len(at.get("download_button")) == 3


def test_app_interpolate_method():
    at = _run()
    at.button_group(key="method").set_value("interpolate").run()
    assert not at.exception


def test_app_plan_view_toggle():
    at = _run()
    at.button_group(key="view_mode").set_value("평면도로 보기").run()
    assert not at.exception
