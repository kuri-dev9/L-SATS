import pytest


@pytest.fixture(autouse=True)
def _settings_file(tmp_path, monkeypatch):
    """테스트가 프로그램 폴더의 user_settings.json·work_history 를 읽거나 쓰지 않도록 임시 위치를 쓴다."""
    path = tmp_path / "user_settings.json"
    monkeypatch.setenv("LSATS_SETTINGS", str(path))
    monkeypatch.setenv("LSATS_HISTORY", str(tmp_path / "history"))
    return path
