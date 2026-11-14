"""가상 데모 데이터 생성기.

실제 현장 데이터와 같은 형식(grid_analysis_floor_level_*.csv, 통합 CAD DXF)으로
가상의 2세대 평면과 상·하부층 스캔 결과를 만든다. 좌표·수치는 모두 가상이다.

    python tools/make_demo_data.py            # demo_data/ 에 생성
"""
from __future__ import annotations

import sys
from pathlib import Path

import ezdxf
import numpy as np
import pandas as pd

OUT = Path(__file__).resolve().parents[1] / "demo_data"
SEED = 7
SPACING = 1500.0  # 측정 격자 간격 (mm)
ROTATION_DEG = 23.5  # 도면 → 측량 좌표 회전
ORIGIN = np.array([1000.0, 2000.0])  # 가상 측량 좌표 원점 (m)
UPPER_FLOOR_Z = 30.000  # 상부층(8F) 바닥 콘크리트 윗면 기준 높이 (m)
LOWER_FLOOR_Z = 27.400  # 하부층(7F) 바닥 기준 높이 (m)

# (실명, x0, y0, x1, y1, 실 평균 두께 mm) - 도면 좌표 mm. 실명이 빈 문자열이면 문자 없이 경계만 둔다.
ROOMS = [
    ("101호_거실", 0, 0, 6000, 4500, 136),
    ("101호_침실1", 6000, 0, 9000, 4500, 128),
    ("101호_주방식당", 0, 4500, 4500, 7500, 133),
    ("101호_침실2", 4500, 4500, 9000, 7500, 121),
    ("102호_거실", 10500, 0, 16500, 4500, 131),
    ("102호_침실1", 16500, 0, 19500, 4500, 138),
    ("102호_주방식당", 10500, 4500, 15000, 7500, 126),
    ("", 15000, 4500, 19500, 7500, 134),
]


def _grid(rng: np.random.Generator, offset: np.ndarray) -> np.ndarray:
    xs = np.arange(750, 19500, SPACING) + offset[0]
    ys = np.arange(750, 7500, SPACING) + offset[1]
    gx, gy = np.meshgrid(xs, ys)
    pts = np.column_stack([gx.ravel(), gy.ravel()])
    inside = np.zeros(len(pts), bool)
    for _, x0, y0, x1, y1, _ in ROOMS:
        inside |= (pts[:, 0] > x0) & (pts[:, 0] < x1) & (pts[:, 1] > y0) & (pts[:, 1] < y1)
    return pts[inside]


def _thickness(cad_xy: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    t = np.full(len(cad_xy), 135.0)
    for _, x0, y0, x1, y1, mean in ROOMS:
        m = (cad_xy[:, 0] >= x0) & (cad_xy[:, 0] < x1) & (cad_xy[:, 1] >= y0) & (cad_xy[:, 1] < y1)
        t[m] = mean
    return t + rng.normal(0, 3.0, len(cad_xy))


def _to_survey(cad_xy: np.ndarray) -> np.ndarray:
    a = np.radians(ROTATION_DEG)
    R = np.array([[np.cos(a), -np.sin(a)], [np.sin(a), np.cos(a)]])
    return cad_xy / 1000 @ R.T + ORIGIN


def _frame(cad_xy, floor_z, ceiling_z, floor_ref, ceiling_ref, rng, drop: set[int]) -> pd.DataFrame:
    xy = _to_survey(cad_xy)
    rows = []
    for i in range(len(cad_xy)):
        if i in drop:  # 측정 누락 → 번호만 건너뛴다 (실제 데이터처럼 층마다 번호가 어긋남)
            continue
        f, c = floor_z[i], ceiling_z[i]
        rows.append({
            "point_number": i + 1,
            "point_id": f"P{i + 1:03d}",
            "x": round(xy[i, 0], 3),
            "y": round(xy[i, 1], 3),
            "Global_Floor_m": round(floor_ref, 3),
            "Global_Floor_mm": round(floor_ref * 1000, 3),
            "Global_Height_m": round(ceiling_ref, 3),
            "Global_Height_mm": round(ceiling_ref * 1000, 3),
            "floor_z": round(f, 3),
            "floor_z_min": round(min(f, floor_ref + rng.normal(0, 0.003)), 3),
            "ceiling_z": round(c, 3),
            "height": round(c - f, 3),
            "height_mm": round((c - f) * 1000, 3),
            "floor_error": round(f - floor_ref, 3),
            "ceiling_error": round(c - ceiling_ref, 3),
            "buffer_points": int(rng.integers(1500, 5000)),
            "is_empty": False,
            "has_floor": True,
            "has_ceiling": True,
        })
    return pd.DataFrame(rows)


def _write_dxf(path: Path, upper_cad: np.ndarray, upper: pd.DataFrame) -> None:
    doc = ezdxf.new("R2018")
    doc.header["$INSUNITS"] = 4  # mm
    for name, color in (("ROOM_BOUNDARY", 7), ("분석 - LABELS", 2), ("분석 - MEASUREMENTS", 4)):
        doc.layers.add(name, color=color)
    msp = doc.modelspace()
    for name, x0, y0, x1, y1, _ in ROOMS:
        msp.add_lwpolyline([(x0, y0), (x1, y0), (x1, y1), (x0, y1)], close=True,
                           dxfattribs={"layer": "ROOM_BOUNDARY"})
        if name:
            msp.add_text(name, height=250, dxfattribs={"layer": "ROOM_BOUNDARY"}).set_placement(
                ((x0 + x1) / 2, y1 - 400), align=ezdxf.enums.TextEntityAlignment.MIDDLE_CENTER)
    for pid, num in zip(upper["point_id"], upper["point_number"]):
        x, y = upper_cad[num - 1]
        msp.add_circle((x, y), 60, dxfattribs={"layer": "분석 - MEASUREMENTS"})
        msp.add_text(pid, height=120, dxfattribs={"layer": "분석 - LABELS", "insert": (x - 160, y + 120)})
    doc.saveas(path)


def main(out: Path = OUT) -> None:
    rng = np.random.default_rng(SEED)
    out.mkdir(parents=True, exist_ok=True)

    # 상부층(8F): 바닥 = 콘크리트 윗면. 하부층(7F): 천장 = 슬래브 아랫면.
    # 하부층 격자는 2~5cm 어긋나고, 1행 더 아래에서 시작해 번호 체계가 다르다.
    up_cad = _grid(rng, np.array([0.0, 0.0]))
    lo_cad = _grid(rng, np.array([30.0, -40.0]))
    lo_cad = np.vstack([lo_cad[lo_cad[:, 1] < 1000][::-1], lo_cad[lo_cad[:, 1] >= 1000]])

    up_floor = UPPER_FLOOR_Z + rng.normal(0, 0.002, len(up_cad))
    up_ceiling = UPPER_FLOOR_Z + 2.48 + rng.normal(0, 0.003, len(up_cad))
    thick = _thickness(lo_cad, rng)
    # 하부층 천장 = 그 위치의 상부층 바닥(평균면) - 두께
    lo_ceiling = UPPER_FLOOR_Z - thick / 1000
    lo_floor = LOWER_FLOOR_Z + rng.normal(0, 0.002, len(lo_cad))

    # 이상값: 상부층 바닥 위 자재(+0.2~0.4m), 하부층 천장 설비(−0.05~−0.15m)
    obj = rng.choice(len(up_cad), 6, replace=False)
    up_floor[obj] += rng.uniform(0.2, 0.4, len(obj))
    pipe = rng.choice(len(lo_cad), 4, replace=False)
    lo_ceiling[pipe] -= rng.uniform(0.05, 0.15, len(pipe))

    ceiling_ref = float(np.median(lo_ceiling))
    upper = _frame(up_cad, up_floor, up_ceiling, UPPER_FLOOR_Z, UPPER_FLOOR_Z + 2.48, rng,
                   drop={int(i) for i in rng.choice(len(up_cad), 2, replace=False)})
    lower = _frame(lo_cad, lo_floor, lo_ceiling, LOWER_FLOOR_Z, ceiling_ref, rng,
                   drop={int(i) for i in rng.choice(len(lo_cad), 3, replace=False)})

    upper.to_csv(out / "grid_analysis_floor_level_8F.csv", index=False, lineterminator="\n")
    lower.to_csv(out / "grid_analysis_floor_level_7F.csv", index=False, lineterminator="\n")
    _write_dxf(out / "report_merge_8F.dxf", up_cad, upper)
    print(f"생성: {out}  (상부 {len(upper)}점, 하부 {len(lower)}점, 실 {len(ROOMS)}개)")


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else OUT)
