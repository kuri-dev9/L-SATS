"""LAS 결과의 방 배치: 층 구조 묶기 → 구조마다 방(직사각형 + 이름) 정하기 → 같은 구조 층 도면에 넣기.

LAS 로 만든 층은 모두 같은 격자(건물 축 좌표)라서, 한 구조에서 정한 방을 같은 구조의 다른 층에 그대로 씌울 수 있다.
배치는 작업 폴더(LSATS_grid)의 layouts.json 에 둔다:
    {"layouts": {"구조 A": [{"name": "2호_침실1", "poly": [[x, y], ...]}, ...]},
     "floors": {"7F": "구조 A", ...}}
방은 서로 겹치지 않는 다각형(가로·세로 변), 좌표는 건물 축 좌표(m, CSV 의 local_x/local_y 와 같음).
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from .las import CSV_NAME, DXF_NAME, PLAN_NAME

LAYOUT_FILE = "layouts.json"
SAME_STRUCTURE = 0.55  # 벽 위치가 이 비율 넘게 겹치면 같은 구조로 본다
DOOR_GAP = 0.45  # 방 나누기: 벽을 이만큼 키워 문틈(약 0.9 m)을 막는다 (m)
MIN_ROOM_M2 = 1.5  # 이보다 작은 빈 곳은 방으로 보지 않는다
SNAP_M = 0.3  # 방 경계를 이 거리 안의 벽 면에 맞춘다


def load_plan(out_dir: Path, label: str) -> dict | None:
    p = Path(out_dir) / PLAN_NAME.format(label)
    if not p.exists():
        return None
    with np.load(p) as z:
        return {k: (z[k].item() if z[k].ndim == 0 else z[k]) for k in z.files}


def _wall_mask(plan: dict) -> np.ndarray:
    from .las_plan import WALL_MIN_POINTS

    return plan["wall"] >= WALL_MIN_POINTS


# ------------------------------------------------------------------ 층 구조 묶기
def similarity(a: dict, b: dict) -> float:
    """두 층의 벽 위치가 얼마나 겹치는지 (0~1). 같은 격자라 칸끼리 바로 비교한다 (±15 cm 허용)."""
    from scipy import ndimage

    if a["wall"].shape != b["wall"].shape:
        return 0.0
    wa, wb = _wall_mask(a), _wall_mask(b)
    k = max(1, int(round(0.15 / a["res"])))
    da, db = ndimage.binary_dilation(wa, iterations=k), ndimage.binary_dilation(wb, iterations=k)
    hit = (wa & db).sum() + (wb & da).sum()
    tot = wa.sum() + wb.sum()
    return float(hit / tot) if tot else 0.0


def group_floors(out_dir: Path, labels: list[str]) -> tuple[list[list[str]], pd.DataFrame]:
    """벽 위치가 비슷한 층끼리 묶는다. (묶음들, 층마다 묶음 대표 층과 닮은 정도 표)."""
    plans = {lab: load_plan(out_dir, lab) for lab in labels}
    groups: list[list[str]] = []
    rows = []
    for lab in labels:
        p = plans[lab]
        best, score = None, 0.0
        if p is not None:
            for g in groups:
                s = similarity(plans[g[0]], p) if plans[g[0]] is not None else 0.0
                if s > score:
                    best, score = g, s
        if best is not None and score >= SAME_STRUCTURE:
            best.append(lab)
        else:
            groups.append([lab])
            best, score = groups[-1], 1.0
        rows.append({"층": lab, "대표 층": best[0], "닮은 정도": round(score, 2)})
    return groups, pd.DataFrame(rows)


# ------------------------------------------------------------------ 방 (다각형, 서로 겹치지 않게)
def wall_coords(plan: dict) -> tuple[np.ndarray, np.ndarray]:
    """벽 면 선의 x(세로 벽)·y(가로 벽) 위치들 (건물 축 m). 방 경계를 맞출 때 쓴다."""
    from .las_plan import plan_lines

    xs, ys = [], []
    for ln in plan_lines(plan)["벽선"]:
        if abs(ln[0, 0] - ln[-1, 0]) < 1e-9:
            xs.append(ln[0, 0])
        else:
            ys.append(ln[0, 1])
    return np.array(xs), np.array(ys)


def _snap(v: float, cand: np.ndarray, tol: float = SNAP_M) -> float:
    if len(cand):
        d = np.abs(cand - v)
        if d.min() <= tol:
            return float(cand[np.argmin(d)])
    return float(v)


def room_poly(room: dict) -> np.ndarray:
    """방 다각형 (건물 축 m). 예전 직사각형({x0,y0,x1,y1}) 저장도 읽는다."""
    if "poly" in room:
        return np.asarray(room["poly"], float)
    x0, x1 = sorted((room["x0"], room["x1"]))
    y0, y1 = sorted((room["y0"], room["y1"]))
    return np.array([[x0, y0], [x1, y0], [x1, y1], [x0, y1]])


def poly_area(p: np.ndarray) -> float:
    x, y = p[:, 0], p[:, 1]
    return float(0.5 * abs(np.dot(x, np.roll(y, 1)) - np.dot(y, np.roll(x, 1))))


def _cell_xy(plan: dict) -> tuple[np.ndarray, np.ndarray]:
    ny, nx = plan["wall"].shape
    return (plan["u0"] + (np.arange(nx) + 0.5) * plan["res"], plan["v0"] + (np.arange(ny) + 0.5) * plan["res"])


def rooms_mask(plan: dict, rooms: list[dict]) -> np.ndarray:
    """방들이 차지한 칸 (방 번호 1.., 빈 칸 0)."""
    from matplotlib.path import Path as MplPath

    cx, cy = _cell_xy(plan)
    out = np.zeros(plan["wall"].shape, np.int32)
    for i, r in enumerate(rooms, start=1):
        p = room_poly(r)
        lo, hi = p.min(0), p.max(0)
        ci = np.flatnonzero((cx >= lo[0]) & (cx <= hi[0]))
        ri = np.flatnonzero((cy >= lo[1]) & (cy <= hi[1]))
        if not len(ci) or not len(ri):
            continue
        gx, gy = np.meshgrid(cx[ci], cy[ri])
        inside = MplPath(p).contains_points(np.column_stack([gx.ravel(), gy.ravel()])).reshape(gx.shape)
        sub = out[ri[0]:ri[-1] + 1, ci[0]:ci[-1] + 1]
        sub[inside & (sub == 0)] = i
    return out


def _simplify(pts: np.ndarray, tol: float) -> np.ndarray:
    """Douglas–Peucker (닫힌 선, 반복문)."""
    if len(pts) < 4:
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
        dist = (np.abs(d[0] * (seg[:, 1] - p[1]) - d[1] * (seg[:, 0] - p[0])) / L) if L > 0 else np.hypot(*(seg - p).T)
        i = int(np.argmax(dist))
        if dist[i] > tol:
            keep[a + 1 + i] = True
            stack += [(a, a + 1 + i), (a + 1 + i, b)]
    return pts[keep]


def _orthogonal(p: np.ndarray, xs: np.ndarray, ys: np.ndarray) -> np.ndarray:
    """변을 가로·세로로 나눠 이웃한 같은 방향 변은 합치고, 가로 변의 y·세로 변의 x 를 (가까운 벽 면에 맞춰) 정한 뒤
    이웃한 두 변이 만나는 점을 꼭짓점으로 한다 → 모든 변이 정확히 가로·세로."""
    n = len(p)
    edges = []  # (가로?, 그 변의 점들)
    for i in range(n):
        a, b = p[i], p[(i + 1) % n]
        h = abs(b[0] - a[0]) >= abs(b[1] - a[1])
        w = float(np.hypot(*(b - a)))
        if edges and edges[-1][0] == h:
            edges[-1][1].append((a, b, w))
        else:
            edges.append([h, [(a, b, w)]])
    if len(edges) > 1 and edges[0][0] == edges[-1][0]:
        edges[0][1] += edges.pop()[1]
    if len(edges) < 4 or len(edges) % 2:
        return np.round(p, 3)

    def level(e):  # 길이 가중 평균 높이(가로 변) 또는 x(세로 변)
        k = 1 if e[0] else 0
        w = np.array([s[2] for s in e[1]]) + 1e-9
        v = np.array([(s[0][k] + s[1][k]) / 2 for s in e[1]])
        return _snap(float((v * w).sum() / w.sum()), ys if e[0] else xs)

    lv = [level(e) for e in edges]
    out = []
    for i in range(len(edges)):
        j = (i + 1) % len(edges)
        x = lv[j] if edges[i][0] else lv[i]  # 가로 변 다음엔 세로 변: 꼭짓점 = (세로 변 x, 가로 변 y)
        y = lv[i] if edges[i][0] else lv[j]
        out.append((x, y))
    return np.round(np.array(out), 3)


def _trace(mask: np.ndarray, plan: dict, xs: np.ndarray, ys: np.ndarray) -> np.ndarray | None:
    """칸 덩어리 → 바깥 테두리 다각형 (건물 축 m, 가로·세로 변)."""
    import contourpy

    res, u0, v0 = plan["res"], plan["u0"], plan["v0"]
    z = np.pad(mask.astype(float), 1)
    lines = contourpy.contour_generator(z=z, line_type="Separate").lines(0.5)
    if not lines:
        return None
    ln = max(lines, key=len) - 1  # 가장 긴 선 = 바깥 테두리
    pts = np.column_stack([u0 + (ln[:, 0] + 0.5) * res, v0 + (ln[:, 1] + 0.5) * res])
    if np.allclose(pts[0], pts[-1]):
        pts = pts[:-1]
    pts = _simplify(np.vstack([pts, pts[:1]]), 0.12)[:-1]
    return _orthogonal(pts, xs, ys) if len(pts) >= 3 else None


def _smooth(m: np.ndarray, res: float) -> np.ndarray:
    from scipy import ndimage

    k = max(1, int(round(0.15 / res)))
    m = ndimage.binary_opening(m, iterations=k)
    m = ndimage.binary_closing(m, iterations=k)
    lab, n = ndimage.label(m)
    if n > 1:
        m = lab == (np.argmax(np.bincount(lab.ravel())[1:]) + 1)
    return ndimage.binary_fill_holes(m)


def auto_rooms(plan: dict) -> list[dict]:
    """벽 사이 빈 공간을 방으로 나눈다 (문틈은 막고, 방끼리 겹치지 않게, 벽 면을 따라). 이름은 '실01'…."""
    from scipy import ndimage

    res = plan["res"]
    wall = _wall_mask(plan)
    floor = ndimage.binary_fill_holes(ndimage.binary_closing(plan["floor"] > 0, iterations=6))
    grow = max(1, int(round(DOOR_GAP / res)))
    free = floor & ~ndimage.binary_dilation(wall, iterations=grow)
    lab, n = ndimage.label(free)
    sizes = np.bincount(lab.ravel())
    keep = [k for k in range(1, n + 1) if sizes[k] * res * res >= MIN_ROOM_M2]
    seeds = np.zeros_like(lab)
    for i, k in enumerate(keep, start=1):
        seeds[lab == k] = i
    # 줄인 만큼 다시 넓힌다: 빈 칸마다 가장 가까운 방에 붙이되 벽은 넘지 않는다 → 서로 겹치지 않는다
    dist, (ii, jj) = ndimage.distance_transform_edt(seeds == 0, return_indices=True)
    part = seeds[ii, jj] * ((dist <= grow + 1) & floor & ~wall)
    xs, ys = wall_coords(plan)
    rooms = []
    for i in range(1, len(keep) + 1):
        m = _smooth(part == i, res)
        if m.sum() * res * res < MIN_ROOM_M2:
            continue
        poly = _trace(m, plan, xs, ys)
        if poly is not None:
            rooms.append(poly)
    rooms.sort(key=lambda p: (-round(p[:, 1].max(), 0), p[:, 0].min()))  # 위에서 아래, 왼쪽에서 오른쪽
    return [{"name": f"실{i:02d}", "poly": p.tolist()} for i, p in enumerate(rooms, start=1)]


def add_box_room(plan: dict, rooms: list[dict], name: str, box: tuple, snap: bool = True) -> dict | None:
    """끌어 고른 범위(x0, x1, y0, y1)를 방으로: 가까운 벽에 맞추고, 이미 있는 방과 겹치는 칸은 뺀다."""
    xs, ys = wall_coords(plan) if snap else (np.array([]), np.array([]))
    x0, x1 = sorted(box[:2])
    y0, y1 = sorted(box[2:])
    if snap:
        x0, x1, y0, y1 = _snap(x0, xs), _snap(x1, xs), _snap(y0, ys), _snap(y1, ys)
    rect = {"poly": [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]}
    m = (rooms_mask(plan, [rect]) == 1) & (rooms_mask(plan, rooms) == 0)
    if m.sum() * plan["res"] ** 2 < 0.3:
        return None
    from scipy import ndimage

    lab, n = ndimage.label(m)
    if n > 1:
        m = lab == (np.argmax(np.bincount(lab.ravel())[1:]) + 1)
    poly = _trace(m, plan, xs, ys)
    return {"name": name, "poly": poly.tolist()} if poly is not None else None


# ------------------------------------------------------------------ 저장·적용
def load_layouts(out_dir: Path) -> dict:
    p = Path(out_dir) / LAYOUT_FILE
    if p.exists():
        d = json.loads(p.read_text(encoding="utf-8"))
        return {"layouts": d.get("layouts", {}), "floors": d.get("floors", {})}
    return {"layouts": {}, "floors": {}}


def save_layouts(out_dir: Path, data: dict) -> None:
    (Path(out_dir) / LAYOUT_FILE).write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def apply_layouts(out_dir: Path, labels: list[str], data: dict) -> dict[str, int]:
    """층마다 그 층 구조의 방을 넣어 DXF 를 다시 만든다. {층: 방 수}."""
    from .las_plan import plan_dxf

    out_dir = Path(out_dir)
    done = {}
    for lab in labels:
        rooms = data["layouts"].get(data["floors"].get(lab, ""), [])
        df = pd.read_csv(out_dir / CSV_NAME.format(lab))
        plan = load_plan(out_dir, lab) or {}
        (out_dir / DXF_NAME.format(lab)).write_bytes(plan_dxf(df, plan, lab, rooms))
        done[lab] = len(rooms)
    return done


def label_point(poly: np.ndarray) -> np.ndarray:
    """방 이름을 놓을 자리: 다각형 안에서 테두리에서 가장 먼 점 (ㄱ자 방에서도 방 안에 놓인다)."""
    from matplotlib.path import Path as MplPath

    lo, hi = poly.min(0), poly.max(0)
    gx, gy = np.meshgrid(np.linspace(lo[0], hi[0], 40), np.linspace(lo[1], hi[1], 40))
    pts = np.column_stack([gx.ravel(), gy.ravel()])
    inside = MplPath(poly).contains_points(pts)
    if not inside.any():
        return poly.mean(0)
    pts = pts[inside]
    a, b = poly, np.roll(poly, -1, axis=0)
    d = b - a
    t = np.clip(((pts[:, None, :] - a) * d).sum(2) / np.maximum((d * d).sum(1), 1e-12), 0, 1)
    dist = np.linalg.norm(pts[:, None, :] - (a + t[..., None] * d), axis=2).min(1)
    return pts[np.argmax(dist)]


def overlaps(plan: dict, rooms: list[dict]) -> list[tuple[str, str, float]]:
    """서로 겹치는 방 쌍과 겹친 넓이(㎡)."""
    masks = [rooms_mask(plan, [r]) > 0 for r in rooms]
    out = []
    for i in range(len(rooms)):
        for j in range(i + 1, len(rooms)):
            m2 = float((masks[i] & masks[j]).sum() * plan["res"] ** 2)
            if m2 >= 0.05:
                out.append((rooms[i]["name"], rooms[j]["name"], m2))
    return out
