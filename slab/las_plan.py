"""LAS 변환 결과로 층별 DXF 평면도를 그린다 (건물 축 기준 좌표, 단위 mm).

- 벽선: 바닥에서 1.0~1.5 m 높이 점(벽 단면, las.WALL_Z)이 있는 칸의 윤곽. 창·문이 뚫린 곳은 끊겨 보인다.
- 외곽선: 바닥면 점이 있는 칸을 메운 가장 큰 덩어리의 윤곽.
- 격자점: 점(원) + 이름(G001-001) + 바닥·천장 높이(m)와 층고(mm).

칸 자료(plan)는 las.sample_floor 가 LAS 를 읽으면서 채운다 (las._PlanRaster).
"""
from __future__ import annotations

import io

import numpy as np
import pandas as pd

WALL_MIN_POINTS = 3  # 벽 칸으로 볼 최소 점 수 (흩어진 잡음 제외)
WALL_MIN_AREA_M2 = 0.05  # 이보다 작은 벽 조각은 버린다
SIMPLIFY_M = 0.02  # 선을 줄일 때 허용 오차

LAYERS = {  # 이름: (색 번호, 설명)
    "벽선": (7, "바닥 위 1.0~1.5 m 단면"),
    "외곽선": (3, "바닥면 범위"),
    "격자점": (1, "격자점 위치"),
    "점번호": (2, "격자점 이름"),
    "높이": (8, "바닥·천장 높이(m), 층고(mm)"),
    "제목": (7, ""),
}


def _contours(mask: np.ndarray) -> list[np.ndarray]:
    """참/거짓 칸의 윤곽선들 (칸 번호 좌표: x=열, y=행)."""
    import contourpy

    z = np.pad(mask.astype(float), 1)
    lines = contourpy.contour_generator(z=z, line_type="Separate").lines(0.5)
    return [ln - 1 for ln in lines if len(ln) >= 3]


def _simplify(pts: np.ndarray, tol: float) -> np.ndarray:
    """Douglas–Peucker (반복문, 깊은 재귀 없음)."""
    if len(pts) < 3:
        return pts
    keep = np.zeros(len(pts), bool)
    keep[[0, -1]] = True
    stack = [(0, len(pts) - 1)]
    while stack:
        a, b = stack.pop()
        if b - a < 2:
            continue
        p, q = pts[a], pts[b]
        seg = pts[a + 1:b]
        d = q - p
        L = np.hypot(*d)
        dist = np.abs(d[0] * (seg[:, 1] - p[1]) - d[1] * (seg[:, 0] - p[0])) / L if L > 0 else np.hypot(*(seg - p).T)
        i = int(np.argmax(dist))
        if dist[i] > tol:
            m = a + 1 + i
            keep[m] = True
            stack += [(a, m), (m, b)]
    return pts[keep]


def plan_lines(plan: dict) -> dict[str, list[np.ndarray]]:
    """칸 자료 → {벽선, 외곽선: [건물 축 좌표(m) 선, ...]}."""
    from scipy import ndimage

    res, u0, v0 = plan["res"], plan["u0"], plan["v0"]
    tol = SIMPLIFY_M / res

    def to_m(ln):
        return np.column_stack([u0 + (ln[:, 0] + 0.5) * res, v0 + (ln[:, 1] + 0.5) * res])

    wall = plan["wall"] >= WALL_MIN_POINTS
    wall = ndimage.binary_closing(wall, iterations=1)
    lab, n = ndimage.label(wall)
    if n:
        sizes = ndimage.sum(wall, lab, index=np.arange(1, n + 1))
        small = np.flatnonzero(sizes * res * res < WALL_MIN_AREA_M2) + 1
        wall[np.isin(lab, small)] = False

    floor = plan["floor"] > 0
    floor = ndimage.binary_closing(floor, iterations=max(1, int(round(0.3 / res))))
    floor = ndimage.binary_fill_holes(floor)
    lab, n = ndimage.label(floor)
    if n:
        sizes = ndimage.sum(floor, lab, index=np.arange(1, n + 1))
        floor = lab == (int(np.argmax(sizes)) + 1)

    return {"벽선": [to_m(_simplify(ln, tol)) for ln in _contours(wall)],
            "외곽선": [to_m(_simplify(ln, tol)) for ln in _contours(floor)]}


def plan_dxf(df: pd.DataFrame, plan: dict, label: str) -> bytes:
    """층별 DXF 평면도 (R2010, 단위 mm, 건물 축 좌표)."""
    import ezdxf

    doc = ezdxf.new("R2010", setup=True)
    doc.header["$INSUNITS"] = 4  # mm
    for name, (color, desc) in LAYERS.items():
        doc.layers.add(name, color=color).description = desc
    msp = doc.modelspace()
    mm = 1000.0

    if plan:
        for layer, lines in plan_lines(plan).items():
            for ln in lines:
                msp.add_lwpolyline((ln * mm).tolist(), close=bool(np.allclose(ln[0], ln[-1])),
                                   dxfattribs={"layer": layer})

    s_mm = float(df["grid_spacing_m"].iloc[0]) * mm if len(df) and "grid_spacing_m" in df else 1500.0
    th = s_mm * 0.08  # 글자 높이 (격자 간격에 맞춤)
    for r in df.itertuples(index=False):
        x, y = r.local_x * mm, r.local_y * mm
        msp.add_circle((x, y), th * 0.4, dxfattribs={"layer": "격자점"})
        msp.add_text(r.point_id, height=th, dxfattribs={"layer": "점번호"}).set_placement((x + th * 0.6, y + th * 0.3))
        f = "-" if pd.isna(r.floor_z) else f"{r.floor_z:.3f}"
        c = "-" if pd.isna(r.ceiling_z) else f"{r.ceiling_z:.3f}"
        h = "" if pd.isna(r.height_mm) else f" H{r.height_mm:.0f}"
        msp.add_text(f"F{f} C{c}{h}", height=th * 0.7,
                     dxfattribs={"layer": "높이"}).set_placement((x + th * 0.6, y - th * 0.9))

    if len(df):
        top = df["local_y"].max() * mm + s_mm
        left = df["local_x"].min() * mm
        angle = df["grid_angle_deg"].iloc[0] if "grid_angle_deg" in df else 0
        msp.add_text(f"{label} LAS 평면도 (건물 축 기준, 단위 mm, 측량 좌표에서 {angle:g}° 회전)",
                     height=th * 2, dxfattribs={"layer": "제목"}).set_placement((left, top))

    buf = io.StringIO()
    doc.write(buf)
    return buf.getvalue().encode("utf-8")
