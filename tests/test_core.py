from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from slab import Settings, analyze, load_cad, load_grid, standardize_grid
from slab.core import fit_similarity
from slab.report import build_dxf, build_excel

DATA = Path(__file__).resolve().parents[1] / "demo_data"  # tools/make_demo_data.py 로 만든 가상 데이터


@pytest.fixture(scope="module")
def sample():
    return (
        load_grid(DATA / "grid_analysis_floor_level_8F.csv"),
        load_grid(DATA / "grid_analysis_floor_level_7F.csv"),
        load_cad(DATA / "report_merge_8F.dxf"),
    )


def test_load_sample(sample):
    upper, lower, plan = sample
    assert len(upper) == 58 and len(lower) == 57
    assert len(plan.rooms) == 8
    assert plan.room_layer == "ROOM_BOUNDARY"
    names = [r.name for r in plan.rooms]
    assert "101호_거실" in names
    assert "실_08" in names  # 실명 문자가 없는 경계는 기본 이름


def test_point_ids_differ_between_floors(sample):
    # 같은 번호라도 층마다 위치가 다르므로 번호로 병합하면 안 된다
    upper, lower, _ = sample
    u = upper.set_index("point_id").loc["P001", ["x", "y"]].to_numpy(float)
    l = lower.set_index("point_id").loc["P001", ["x", "y"]].to_numpy(float)
    assert np.linalg.norm(u - l) > 1.0


def test_transform_matches_cad(sample):
    upper, lower, plan = sample
    r = analyze(upper, lower, plan)
    assert r.transform.rms_m < 0.005
    assert r.transform.rotation_deg == pytest.approx(23.5, abs=0.01)


@pytest.mark.parametrize("method", ["nearest", "interpolate"])
def test_thickness_sample(sample, method):
    upper, lower, plan = sample
    r = analyze(upper, lower, plan, Settings(method=method))
    assert r.summary["n_valid"] >= 45
    assert 127 < r.summary["median_mm"] < 133
    assert (r.points["room"] == "(실 외부)").sum() == 0
    valid = r.points[~r.points["excluded"]]
    assert (valid["match_dist_m"] <= 0.2).all()
    # 바닥 위 물체(+0.2m 이상)는 모두 제외되어야 한다
    assert r.points.loc[r.points["upper_floor_error_mm"] > 100, "excluded"].all()
    # 데모에서 얇게 만든 101호_침실2(평균 121mm)만 미달
    rooms = r.rooms.set_index("room")
    assert rooms.loc["101호_침실2", "judgement"] == "미달"
    assert (rooms.drop("101호_침실2")["judgement"] == "적합").all()


def test_room_rename(sample):
    upper, lower, plan = sample
    rid = plan.rooms[0].room_id
    r = analyze(upper, lower, plan, room_names={rid: "테스트실"})
    assert "테스트실" in set(r.rooms["room"])


def test_synthetic_offset_grids():
    # 격자 배치가 다른 두 층: 두께 200mm 평판
    rng = np.random.default_rng(0)
    gx, gy = np.meshgrid(np.arange(0, 10, 1.0), np.arange(0, 10, 1.0))
    up = pd.DataFrame({"x": gx.ravel(), "y": gy.ravel(), "floor_z": 3.2, "ceiling_z": 5.6})
    lo = pd.DataFrame({"x": gx.ravel() + 0.05, "y": gy.ravel() - 0.04,
                       "floor_z": 0.6, "ceiling_z": 3.0 + rng.normal(0, 0.001, gx.size)})
    up.loc[5, "floor_z"] = 3.5  # 바닥 위 물체
    r = analyze(standardize_grid(up), standardize_grid(lo), settings=Settings(design_mm=200))
    assert r.points.loc[5, "excluded"]
    assert r.summary["median_mm"] == pytest.approx(200, abs=3)


def test_fit_similarity_roundtrip():
    rng = np.random.default_rng(1)
    cad = rng.uniform(0, 50000, (10, 2))
    a = np.radians(23.5)
    R = np.array([[np.cos(a), -np.sin(a)], [np.sin(a), np.cos(a)]])
    survey = 0.001 * cad @ R.T + [1000.0, 2000.0]
    t = fit_similarity(cad, survey)
    assert t.rms_m < 1e-6
    assert np.allclose(t.to_cad(survey), cad, atol=1e-3)


def test_reports(sample):
    upper, lower, plan = sample
    r = analyze(upper, lower, plan)
    assert build_excel(r, {"동": "101동", "상부층": "8F", "하부층": "7F"})[:2] == b"PK"
    assert b"ROOM_BOUNDARY" in build_dxf(r)


def test_demo_data_is_reproducible(tmp_path):
    import importlib.util

    spec = importlib.util.spec_from_file_location("mk", DATA.parent / "tools" / "make_demo_data.py")
    mk = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mk)
    mk.main(tmp_path)
    for name in ("grid_analysis_floor_level_8F.csv", "grid_analysis_floor_level_7F.csv"):
        assert (tmp_path / name).read_bytes() == (DATA / name).read_bytes()
