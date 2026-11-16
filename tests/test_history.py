"""작업 내역 JSON 저장소."""
import json

from slab import history


def _files(tag=b"a"):
    return {"grid_8F.csv": b"u" + tag, "grid_7F.csv": b"l" + tag, "plan.dxf": b"c"}


def test_create_update_delete():
    a = history.create_job(_files(), {"dong": "101동", "floors_text": "7F~8F"})
    b = history.create_job(_files(b"b"), {"dong": "102동"})
    assert {j["id"] for j in history.list_jobs()} == {a, b}
    assert history.display_name(history.get_job(a)) == "101동 7F~8F"
    assert history.load_files(a)["grid_8F.csv"] == b"ua"

    assert history.update_job(a, name="첫 작업", memo="메모")
    assert not history.update_job(a, name="첫 작업")  # 바뀐 게 없으면 쓰지 않는다
    assert history.list_jobs()[0]["id"] == a  # 최근에 고친 작업이 앞에
    assert history.display_name(history.get_job(a)) == "첫 작업"

    more = {**_files(b"z"), "grid_9F.csv": b"n"}
    assert history.update_job(a, files=more)
    assert history.load_files(a) == more
    assert sorted(history.file_names(history.get_job(a))) == sorted(more)

    history.delete_job(a)
    assert history.get_job(a) is None and history.load_files(a) == {}
    assert [j["id"] for j in history.list_jobs()] == [b]


def test_old_v02_job_still_loads():
    """v0.2 작업: files 가 {종류: 정보}, 파일 이름 앞에 종류가 붙어 있다."""
    folder = history.history_dir() / "files" / "old"
    folder.mkdir(parents=True)
    (folder / "upper_8F.csv").write_bytes(b"u")
    (folder / "cad_plan.dxf").write_bytes(b"c")
    job = {"id": "old", "upper_floor": "8F", "lower_floor": "7F", "dong": "101동", "updated": "2026-01-01",
           "files": {"upper": {"name": "8F.csv", "md5": ""}, "cad": {"name": "plan.dxf", "md5": ""}}}
    (history.history_dir() / "history.json").write_text(json.dumps([job]), encoding="utf-8")
    assert history.load_files("old") == {"8F.csv": b"u", "plan.dxf": b"c"}
    assert history.display_name(history.get_job("old")) == "101동 8F-7F"


def test_broken_index_is_empty():
    history.history_dir().mkdir(parents=True, exist_ok=True)
    (history.history_dir() / "history.json").write_text("{깨진", encoding="utf-8")
    assert history.list_jobs() == []
    history.create_job(_files(), {})
    assert len(history.list_jobs()) == 1
