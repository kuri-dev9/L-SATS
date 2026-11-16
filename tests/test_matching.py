"""포인트 대응·TIN·단위·실 배정 검증 (docs/05_ACCEPTANCE.md 기준)."""
import io
import json

import numpy as np
import pandas as pd
import pytest
from openpyxl import load_workbook

from slab import Settings, analyze, standardize_grid
from slab.core import CadPlan, Room, compute_thickness, locate_rooms
from slab.report import build_excel
from slab.settings_store import from_dict, load_settings, save_settings


def grid(rows):
    """rows: (point_id, x, y, floor_z, ceiling_z)"""
    df = pd.DataFrame(rows, columns=["point_id", "x", "y", "floor_z", "ceiling_z"])
    return standardize_grid(df)


def lower_plate(z=3.0, n=6, step=1.0, dx=0.0):
    gx, gy = np.meshgrid(np.arange(n) * step, np.arange(n) * step)
    return grid([(f"L{i}", x + dx, y, 0.0, z) for i, (x, y) in enumerate(zip(gx.ravel(), gy.ravel()))])


def test_match_by_xy_not_point_id():
    # 같은 ID·다른 XY / 다른 ID·같은 XY
    up = grid([("P1", 0, 0, 3.2, 5.0)])
    lo = grid([("P1", 5, 5, 0, 2.0), ("P9", 0, 0, 0, 3.0), ("P2", 1, 1, 0, 3.0), ("P3", 0, 1, 0, 3.0)])
    r = compute_thickness(up, lo, Settings())
    assert r.loc[0, "lower_point_id"] == "P9"
    assert r.loc[0, "thickness_mm"] == pytest.approx(200)


def test_units_m_and_mm_give_same_thickness():
    up = grid([(f"U{i}", x, y, 3.2, 5.6) for i, (x, y) in enumerate([(0, 0), (1, 0), (0, 1), (1, 1), (2, 2)])])
    lo = lower_plate(3.0, 4)
    r_m = analyze(up, lo)
    up_mm = up.copy()
    up_mm[["x", "y", "floor_z", "ceiling_z"]] *= 1000
    r_mix = analyze(up_mm, lo)
    assert np.allclose(r_m.points["thickness_mm"], r_mix.points["thickness_mm"])
    assert r_mix.summary["warnings"]  # 위·아래층 단위가 다르다고 알려 준다
    assert r_mix.summary["units"]["upper"] == {"xy": "mm", "z": "mm", "auto_xy": True, "auto_z": True}


def test_mixed_units_in_one_file_detected():
    up = grid([(f"U{i}", i, 0, 32.0, 34500.0) for i in range(5)])  # 바닥 m, 천장 mm
    with pytest.raises(ValueError, match="단위"):
        analyze(up, lower_plate())


@pytest.mark.parametrize("d, direct", [(0.2, True), (0.2001, False)])
def test_direct_match_distance_boundary(d, direct):
    up = grid([("U1", 2.0 + d, 2.0, 3.2, 5.0)])
    lo = grid([("L1", 2.0, 2.0, 0, 3.0)])  # 한 점뿐이라 TIN 불가
    r = compute_thickness(up, lo, Settings(max_match_dist_m=0.2))
    assert (r.loc[0, "calc_method"] == "직접 대응") is direct
    assert (r.loc[0, "status"] == "산출") is direct


def test_lower_point_reuse_policy():
    up = grid([("U1", 0.0, 0.0, 3.2, 5.0), ("U2", 0.1, 0.0, 3.2, 5.0)])
    lo = grid([("L1", 0.05, 0.0, 0, 3.0)])
    reuse = compute_thickness(up, lo, Settings(allow_reuse=True))
    assert list(reuse["lower_point_id"]) == ["L1", "L1"]
    one = compute_thickness(up, lo, Settings(allow_reuse=False))
    assert (one["lower_point_id"] == "L1").sum() == 1
    miss = one[one["status"] == "미산출"]
    assert len(miss) == 1 and "1:1" in miss.iloc[0]["exclude_reason"]


def test_missing_z_is_not_zero():
    up = grid([("U1", 1.0, 1.0, np.nan, 5.0), ("U2", 2.0, 2.0, 3.2, 5.0)])
    r = compute_thickness(up, lower_plate(), Settings())
    assert r.loc[0, "status"] == "미산출" and np.isnan(r.loc[0, "thickness_mm"])
    assert r.loc[0, "judgement"] == "미산출" and "위층 바닥 측정 없음" in r.loc[0, "exclude_reason"]
    assert r.loc[1, "status"] == "산출"


def test_duplicate_xy():
    lo = lower_plate()
    lo = pd.concat([lo, lo.iloc[[7]].assign(point_id="DUP")], ignore_index=True)
    up = grid([("U1", 1.5, 1.5, 3.2, 5.0), ("U2", 1.5, 1.5, 3.2, 5.0)])
    r = compute_thickness(up, lo, Settings(method="interpolate"))
    assert (r["status"] == "산출").all()
    assert r["review_note"].str.contains("같은 좌표").all()


def test_tin_weights_by_hand():
    lo = grid([("A", 0, 0, 0, 3.0), ("B", 1, 0, 0, 3.1), ("C", 0, 1, 0, 3.2)])
    up = grid([("U", 0.25, 0.25, 3.35, 6.0)])
    r = compute_thickness(up, lo, Settings(method="auto", max_match_dist_m=0.1, max_surface_error_mm=1000)).iloc[0]
    assert r["calc_method"] == "TIN 보간"
    w = {r[f"tin_id{k}"]: r[f"tin_w{k}"] for k in (1, 2, 3)}
    assert w == pytest.approx({"A": 0.5, "B": 0.25, "C": 0.25})
    assert r["lower_ceiling_z"] == pytest.approx(3.075)
    assert r["thickness_mm"] == pytest.approx(275.0)
    assert sorted(r["lower_point_id"].split("/")) == ["A", "B", "C"]


@pytest.mark.parametrize("lower, why", [
    ([("A", 0, 0, 0, 3.0), ("B", 1, 0, 0, 3.0), ("C", 0, 1, 0, 3.0)], "삼각형 밖"),
    ([("A", 0, 0, 0, 3.0), ("B", 1, 0, 0, 3.0)], "3개 미만"),
    ([("A", 0, 0, 0, 3.0), ("B", 1, 0, 0, 3.0), ("C", 2, 0.0, 0, 3.0)], "한 줄"),
])
def test_tin_never_extrapolates(lower, why):
    up = grid([("U", 3.0, 3.0, 3.2, 6.0)])
    r = compute_thickness(up, grid(lower), Settings(method="auto")).iloc[0]
    assert r["status"] == "미산출" and np.isnan(r["thickness_mm"])
    assert why in r["exclude_reason"]


def test_tin_max_edge():
    lo = lower_plate(step=2.0)
    up = grid([("U", 1.0, 1.0, 3.2, 6.0)])
    assert compute_thickness(up, lo, Settings(method="interpolate")).iloc[0]["status"] == "산출"
    r = compute_thickness(up, lo, Settings(method="interpolate", tin_max_edge_m=2.5)).iloc[0]
    assert r["status"] == "미산출" and "너무 큼" in r["exclude_reason"]


def _plan(rooms):
    return CadPlan([Room(rid, name, np.array(poly, float), np.mean(poly, 0)) for rid, name, poly in rooms],
                   "ROOM", ["ROOM"], {}, b"")


def _square(x0, y0, x1, y1):
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]


def test_locate_rooms_boundary_overlap_outside():
    plan = _plan([("R1", "A", _square(0, 0, 10, 10)), ("R2", "B", _square(5, 5, 8, 8)),
                  ("R3", "C", _square(10, 0, 20, 10))])
    hits = locate_rooms(np.array([[2, 2], [6, 6], [10, 5], [30, 30], [10.0005, 5]]), plan.rooms, tol=0.001)
    assert hits[0].room.room_id == "R1" and not hits[0].note
    assert hits[1].room.room_id == "R2" and hits[1].overlap
    assert hits[2].room is not None and hits[2].note == "방 경계선 위"
    assert hits[3].room is None
    assert hits[4].room is not None


def _two_unit_case(t1, t2):
    # 같은 이름 '거실'이 두 세대에 있다. 도면이 측량 좌표 그대로(축척 1).
    plan = _plan([("R1", "101호_거실", _square(0, 0, 4, 4)), ("R2", "102호_거실", _square(4, 0, 8, 4))])
    pts = [(f"U{i}", x + 0.5, y + 0.5, 3.0 + (t1 if x < 4 else t2) / 1000, 6.0)
           for i, (x, y) in enumerate([(x, y) for x in range(8) for y in range(4)])]
    lo = grid([(f"L{i}", x + 0.5, y + 0.5, 0, 3.0) for i, (x, y) in
               enumerate([(x, y) for x in range(8) for y in range(4)])])
    return analyze(grid(pts), lo, plan, room_names={"R1": "거실", "R2": "거실"})


def test_same_name_rooms_not_merged():
    r = _two_unit_case(130, 150)
    assert len(r.rooms) == 2
    rooms = r.rooms.set_index("room_id")
    assert list(rooms["room"]) == ["거실", "거실"]
    assert rooms.loc["R1", "judgement"] == "미달" and rooms.loc["R2", "judgement"] == "적합"


@pytest.mark.parametrize("t, expected", [(134.9, "미달"), (135.0, "적합"), (135.1, "적합")])
def test_room_mean_135_boundary(t, expected):
    r = _two_unit_case(t, 150)
    assert r.rooms.set_index("room_id").loc["R1", "judgement"] == expected


def test_outside_points_counted_separately():
    plan = _plan([("R1", "101호_거실", _square(0, 0, 4, 4))])
    up = grid([("U1", 1, 1, 3.15, 6.0), ("U2", 2, 2, 3.15, 6.0), ("OUT", 50, 50, 3.10, 6.0)])
    lo = lower_plate(3.0, 6)
    lo = pd.concat([lo, grid([("LO", 50, 50, 0, 3.0)])], ignore_index=True)
    r = analyze(up, lo, plan)
    assert r.summary["n_outside"] == 1
    assert r.summary["n_valid"] == 2 and r.summary["mean_mm"] == pytest.approx(150)
    assert list(r.rooms["room_id"]) == ["R1"]


def test_excel_simple_layout():
    r = _two_unit_case(130, 150)
    wb = load_workbook(io.BytesIO(build_excel(r, {})))
    assert wb.sheetnames == ["포인트 결과", "위치도"]
    ws = wb["포인트 결과"]
    assert ws.freeze_panes is None
    text = " ".join(str(c.value) for row in ws.iter_rows() for c in row if c.value is not None)
    assert "적합률" not in text and "초안" in text
    header = [c.value for c in ws[3]]
    for col in ("세대", "실 ID", "상부점 ID", "두께(mm)", "산출방법", "사용 하부점", "상태", "검토 메모"):
        assert col in header
    assert "40%" in wb["위치도"]["A3"].value and "축척과 무관" in wb["위치도"]["A3"].value


def test_excel_map_scale():
    from openpyxl import Workbook
    from PIL import Image

    from slab.plot import figure_png, plot_plan
    from slab.report import _add_image

    png = figure_png(plot_plan(_two_unit_case(130, 150)))
    ws = Workbook().active
    _add_image(ws, png, 40)
    assert ws._images[0].width == pytest.approx(Image.open(io.BytesIO(png)).width * 0.4)


def test_excel_full_layout_options():
    r = _two_unit_case(130, 150)
    r.settings = Settings(excel_layout="full", excel_freeze_panes=True, excel_show_pass_rate=True,
                          report_draft=False)
    wb = load_workbook(io.BytesIO(build_excel(r, {})))
    assert {"요약", "실별 결과", "포인트 결과", "제외·미산출", "방별 판정도", "위치도"} <= set(wb.sheetnames)
    assert wb["포인트 결과"].freeze_panes == "A2"
    assert any(c.value == "적합률" for c in wb["요약"]["A"])


def test_settings_store_roundtrip(tmp_path):
    p = tmp_path / "s.json"
    save_settings(Settings(max_match_dist_m=1.25, outlier_method="iqr"), p)
    data = json.loads(p.read_text(encoding="utf-8"))
    assert "design_mm" not in data
    s = load_settings(p)
    assert s.max_match_dist_m == 1.25 and s.outlier_method == "iqr"
    # 판정 기준은 파일에 적어도 바뀌지 않고, 잘못된 값은 기본값
    s, bad = from_dict({"design_mm": 100, "tolerance_mm": 5, "method": "???", "max_match_dist_m": "abc"})
    assert s.design_mm == 135.0 and s.tolerance_mm == 0.0
    assert s.method == "auto" and set(bad) == {"method", "max_match_dist_m"}
    assert load_settings(tmp_path / "없음.json") == Settings()


def test_outlier_thick_side_only_keeps_thin_points():
    rng = np.random.default_rng(0)
    pts = [(f"U{i}", x, y, 3.0 + 0.150 + rng.normal(0, 0.001), 6.0) for i, (x, y) in
           enumerate([(x + 0.5, y + 0.5) for x in range(5) for y in range(5)])]
    pts[0] = ("THIN", 0.5, 0.5, 3.100, 6.0)
    up, lo = grid(pts), lower_plate(3.0, 7)
    both = compute_thickness(up, lo, Settings(outlier_method="iqr", max_surface_error_mm=1000))
    thick = compute_thickness(up, lo, Settings(outlier_method="iqr", outlier_side="thick", max_surface_error_mm=1000))
    assert both.loc[0, "status"] == "제외"
    assert thick.loc[0, "status"] == "산출"
