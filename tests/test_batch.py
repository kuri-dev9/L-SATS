"""여러 층 파일: 층 찾기·짝짓기·도면 배정 (slab/batch.py)."""
import numpy as np
import pandas as pd
import pytest

from slab import load_cad, standardize_grid
from slab.batch import floor_number, guess_dong, guess_floor, kind_of, make_floor, plan_floors
from tests.test_core import DATA


def _floor(name, level, storey=2.6, n=10, gap=0.13):
    """바닥 높이 level 인 층. 천장은 바닥 + storey − gap (위층 바닥과 gap 만큼 차이)."""
    raw = pd.DataFrame({"point_id": [f"P{i:03d}" for i in range(n)], "x": np.arange(n, dtype=float),
                        "y": np.zeros(n), "floor_z": level, "ceiling_z": level + storey - gap,
                        "Global_Floor_m": level})
    return make_floor(name, raw, standardize_grid(raw))


def test_guess_names():
    assert guess_floor("grid_analysis_floor_level_8F.csv") == "8F"
    assert guess_floor("report_merge_B1.dxf") == "B1"
    assert guess_floor("report_merge_typical.dxf") == ""
    assert guess_dong("101동_8F.csv") == "101동"
    assert floor_number("B2") == -2 and floor_number("15F") == 15
    assert kind_of("a.DXF") == "cad" and kind_of("a.xlsx") == "scan" and kind_of("a.pdf") == ""


def test_floors_sorted_by_level_not_name():
    # 파일 이름 순서와 상관없이 파일 안의 바닥 높이로 층 순서를 정한다
    floors = [_floor("x_10F.csv", 26.0), _floor("x_8F.csv", 20.8), _floor("x_9F.csv", 23.4)]
    plan = plan_floors(floors, {})
    assert [f.label for f in plan.floors] == ["8F", "9F", "10F"]
    assert [(p.upper.label, p.lower.label if p.lower else None) for p in plan.pairs] == [
        ("10F", "9F"), ("9F", "8F"), ("8F", None)]
    assert not plan.pairs[0].problem and plan.pairs[-1].problem.startswith("맨 아래층")


def test_missing_floor_is_not_paired():
    plan = plan_floors([_floor("a_8F.csv", 20.8), _floor("a_10F.csv", 26.0)], {})
    assert "바로 위·아래층이 아니에요" in plan.pairs[0].problem


def test_same_floor_twice_and_no_label():
    plan = plan_floors([_floor("scan_a.csv", 20.8), _floor("scan_b.csv", 20.9), _floor("scan_c.csv", 23.4)], {})
    assert len(plan.floors) == 2 and "같은 층" in plan.warnings[0]
    assert [f.label for f in plan.floors] == ["층1", "층2"] and plan.floors[0].auto_label
    named = plan_floors([_floor("scan_a.csv", 20.8), _floor("scan_c.csv", 23.4)], {}, {"scan_c.csv": "9F"})
    assert named.floors[1].label == "9F"


def test_cad_by_name_shared_and_choice():
    plan_dxf = load_cad(DATA / "report_merge_8F.dxf")
    floors = [_floor("g_7F.csv", 18.2), _floor("g_8F.csv", 20.8), _floor("g_9F.csv", 23.4)]
    # 이름에 층이 있는 도면은 그 층에, 층 표기 없는 도면 하나는 나머지 층에 공용
    p = plan_floors(floors, {"report_merge_8F.dxf": plan_dxf, "typical.dxf": plan_dxf})
    by = {x.upper.label: x for x in p.pairs}
    assert by["8F"].cad == "report_merge_8F.dxf" and not by["8F"].cad_shared
    assert by["9F"].cad == "typical.dxf" and by["9F"].cad_shared
    # 사용자가 고른 도면이 이긴다 ('' = 도면 없이)
    p = plan_floors(floors, {"report_merge_8F.dxf": plan_dxf, "typical.dxf": plan_dxf},
                    cad_choice={"9F": "report_merge_8F.dxf", "8F": ""})
    by = {x.upper.label: x for x in p.pairs}
    assert by["9F"].cad == "report_merge_8F.dxf" and by["8F"].cad is None


def test_cad_matched_by_content():
    """층 표기 없는 도면이 여러 개면 측정점 번호 좌표가 맞는 층에 붙인다."""
    from slab import load_grid

    plan_dxf = load_cad(DATA / "report_merge_8F.dxf")
    up = load_grid(DATA / "grid_analysis_floor_level_8F.csv")
    lo = load_grid(DATA / "grid_analysis_floor_level_7F.csv")
    raw_u = up.assign(Global_Floor_m=30.0)
    raw_l = lo.assign(Global_Floor_m=27.4)
    floors = [make_floor("upper.csv", raw_u, up), make_floor("lower.csv", raw_l, lo)]
    p = plan_floors(floors, {"plan_a.dxf": plan_dxf, "plan_b.dxf": plan_dxf})
    assert p.pairs[0].cad == "plan_a.dxf"
    assert any("plan_b.dxf" in w for w in p.warnings)
