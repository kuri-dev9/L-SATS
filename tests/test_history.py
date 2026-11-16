"""작업 내역 JSON 저장소."""
from slab import history


def _files(tag=b"a"):
    return {"upper": ("8F.csv", b"u" + tag), "lower": ("7F.csv", b"l" + tag), "cad": ("plan.dxf", b"c")}


def test_create_update_delete():
    a = history.create_job(_files(), {"dong": "101동", "upper_floor": "8F", "lower_floor": "7F"})
    b = history.create_job(_files(b"b"), {"dong": "102동"})
    assert {j["id"] for j in history.list_jobs()} == {a, b}
    assert history.display_name(history.get_job(a)) == "101동 8F-7F"
    assert history.load_files(a)["upper"] == ("8F.csv", b"ua")

    assert history.update_job(a, name="첫 작업", memo="메모")
    assert not history.update_job(a, name="첫 작업")  # 바뀐 게 없으면 쓰지 않는다
    assert history.list_jobs()[0]["id"] == a  # 최근에 고친 작업이 앞에
    assert history.display_name(history.get_job(a)) == "첫 작업"

    assert history.update_job(a, files=_files(b"z"))
    assert history.load_files(a)["upper"] == ("8F.csv", b"uz")

    history.delete_job(a)
    assert history.get_job(a) is None and history.load_files(a) == {}
    assert [j["id"] for j in history.list_jobs()] == [b]


def test_broken_index_is_empty():
    history.history_dir().mkdir(parents=True, exist_ok=True)
    (history.history_dir() / "history.json").write_text("{깨진", encoding="utf-8")
    assert history.list_jobs() == []
    history.create_job(_files(), {})
    assert len(history.list_jobs()) == 1
