"""LAS 변환 (slab/las.py): 가상 점군(tools/make_demo_las.py)으로 격자·높이·정렬을 검사한다."""
import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

pytest.importorskip("laspy")

from slab import analyze, load_grid  # noqa: E402
from slab.las import GRID_FILE, GridSpec, LasParams, convert, find_axis, find_las  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def las_dir(tmp_path_factory):
    spec = importlib.util.spec_from_file_location("mk", ROOT / "tools" / "make_demo_las.py")
    mk = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mk)
    d = tmp_path_factory.mktemp("las")
    mk.main(d)
    return d, mk


@pytest.fixture(scope="module")
def converted(las_dir):
    d, mk = las_dir
    grid, summary, paths = convert(find_las(d), d / "out", LasParams())
    return d, mk, grid, summary, paths


def test_same_grid_on_every_floor(converted):
    d, mk, grid, summary, paths = converted
    assert grid.angle_deg == pytest.approx(mk.ANGLE_DEG, abs=0.2)  # 기울어진 건물 축을 찾는다
    assert list(summary["층"]) == list(mk.FLOORS)
    ids = [set(pd.read_csv(p)["point_id"]) for p in paths]
    assert ids[0] == ids[1] == ids[2]  # 모든 층 같은 격자점
    xy = [pd.read_csv(p).set_index("point_id")[["x", "y"]] for p in paths]
    assert np.allclose(xy[0].loc[sorted(ids[0])], xy[1].loc[sorted(ids[0])])
    assert (d / "out" / GRID_FILE).exists()


def test_levels_and_thickness(converted):
    d, mk, grid, summary, paths = converted
    assert summary["바닥면 높이(m)"].iloc[0] == pytest.approx(mk.BASE_Z, abs=0.005)
    up, lo = paths[1], paths[0]
    r = analyze(load_grid(up), load_grid(lo))
    p = r.points.merge(pd.read_csv(up)[["point_id", "local_x"]], on="point_id")
    v = p[p["thickness_mm"].notna()]
    assert (r.points["match_dist_m"].dropna() < 1e-6).all()  # 같은 격자라 같은 위치끼리
    left = v.loc[v["local_x"] < 9.5, "thickness_mm"].mean()
    right = v.loc[v["local_x"] > 10.5, "thickness_mm"].mean()
    assert left == pytest.approx(mk.THICK["left"] * 1000, abs=2)
    assert right == pytest.approx(mk.THICK["right"] * 1000, abs=2)


def test_result_is_aligned_to_building_axis(converted):
    """측량 좌표는 기울어져 있으므로, 도면 없이도 건물 축(격자 방향)에 맞춰 그린다."""
    d, mk, grid, summary, paths = converted
    r = analyze(load_grid(paths[1]), load_grid(paths[0]))
    assert r.transform is not None and r.transform.rotation_deg == pytest.approx(grid.angle_deg)
    local = pd.read_csv(paths[1]).set_index("point_id").loc[r.points["point_id"], ["local_x", "local_y"]]
    assert np.allclose(r.points["cad_x"], local["local_x"], atol=1e-3)
    assert np.allclose(r.points["cad_y"], local["local_y"], atol=1e-3)


def test_grid_is_reused(converted, las_dir):
    d, mk, grid, summary, paths = converted
    again, _, _ = convert(find_las(d)[:1], d / "out", LasParams())  # 한 층만 다시 해도 같은 격자
    assert again == grid
    assert GridSpec.load(d / "out" / GRID_FILE) == grid


def test_find_axis_rotated_rectangle():
    rng = np.random.default_rng(0)
    t = rng.uniform(0, 1, 4000)
    side = rng.integers(0, 4, 4000)
    lx = np.select([side == 0, side == 1, side == 2], [t * 8, t * 8, np.zeros(4000)], np.full(4000, 8.0))
    ly = np.select([side == 0, side == 1, side == 2], [np.zeros(4000), np.full(4000, 5.0), t * 5], t * 5)
    a = np.radians(-31.0)
    xy = np.column_stack([lx * np.cos(a) - ly * np.sin(a), lx * np.sin(a) + ly * np.cos(a)])
    assert find_axis(xy) == pytest.approx(-31.0, abs=0.2)


def test_export_single_and_per_floor(converted):
    import io

    d, mk, grid, summary, paths = converted
    from slab.las import export_results

    labels = list(summary["층"])
    each = export_results(paths, labels, "floor", "csv")
    assert sorted(each) == [f"grid_analysis_floor_level_{f}.csv" for f in mk.FLOORS]
    assert all(v[:3] == b"\xef\xbb\xbf" for v in each.values())  # 엑셀에서 한글이 안 깨지게
    one = export_results(paths, labels, "single", "csv")
    allf = pd.read_csv(io.BytesIO(one["LAS_격자높이_전체.csv"]), encoding="utf-8-sig")
    assert list(allf["층"].unique()) == list(mk.FLOORS) and len(allf) == sum(len(pd.read_csv(p)) for p in paths)
    book = export_results(paths, labels, "single", "xlsx", summary)
    assert pd.ExcelFile(io.BytesIO(book["LAS_격자높이_전체.xlsx"])).sheet_names == ["요약", *mk.FLOORS]
    assert len(export_results(paths, labels, "floor", "xlsx")) == len(mk.FLOORS)


def test_find_las_files_recursive(las_dir, tmp_path):
    d, mk = las_dir
    sub = tmp_path / "a" / "b"
    sub.mkdir(parents=True)
    (sub / "x_7F.LAZ").write_bytes(b"")
    (tmp_path / "note.txt").write_text("x")
    from slab.las import find_las_files

    assert find_las_files(tmp_path) == []
    assert [p.name for p in find_las_files(tmp_path, recursive=True)] == ["x_7F.LAZ"]


def test_ui_remembers_las_folders():
    from slab.settings_store import load_ui, update_ui

    update_ui(las_last_folder="/data/las")
    update_ui(preview_mode=True)
    ui = load_ui()
    assert ui["las_last_folder"] == "/data/las" and ui["preview_mode"] is True and ui["las_out_folder"] == ""
