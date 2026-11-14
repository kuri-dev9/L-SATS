"""웹 화면 스모크 테스트: 샘플 데이터로 모든 탭이 오류 없이 그려지고 결과 파일이 만들어지는지."""
from pathlib import Path

from streamlit.testing.v1 import AppTest

APP = str(Path(__file__).resolve().parents[1] / "app.py")


def test_app_runs_with_sample():
    at = AppTest.from_file(APP, default_timeout=120).run()
    assert not at.exception
    assert not at.error
    labels = {m.label for m in at.metric}
    assert {"평균 두께", "적합률", "잔차 RMS"} <= labels


def test_app_builds_outputs():
    at = AppTest.from_file(APP, default_timeout=120).run()
    at.button[0].click().run()
    assert not at.exception
    assert len(at.get("download_button")) == 3


def test_app_interpolate_method():
    at = AppTest.from_file(APP, default_timeout=120).run()
    at.radio[0].set_value("interpolate").run()
    assert not at.exception
