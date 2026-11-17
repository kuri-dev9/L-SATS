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


def _signed_area(p: np.ndarray) -> float:
    x, y = p[:, 0], p[:, 1]
    return float(0.5 * (np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1))))


def _trace(mask: np.ndarray, plan: dict, xs: np.ndarray, ys: np.ndarray) -> np.ndarray | None:
    """칸 덩어리 → 테두리 다각형 (건물 축 m, 가로·세로 변).

    안에 구멍(방에서 뺀 곳 등)이 있으면 구멍 테두리를 바깥 테두리와 가는 다리로 이어 한 줄(열쇠구멍 모양)로 만든다.
    구멍은 바깥과 반대로 돌아서 점 포함 판정(matplotlib Path)·DXF 에서 방 밖으로 본다.
    """
    import contourpy

    res, u0, v0 = plan["res"], plan["u0"], plan["v0"]
    z = np.pad(mask.astype(float), 1)
    lines = contourpy.contour_generator(z=z, line_type="Separate").lines(0.5)
    if not lines:
        return None

    def ring(ln):
        pts = np.column_stack([u0 + (ln[:, 0] - 1 + 0.5) * res, v0 + (ln[:, 1] - 1 + 0.5) * res])
        if np.allclose(pts[0], pts[-1]):
            pts = pts[:-1]
        if len(pts) < 3 or abs(_signed_area(pts)) < 0.2:
            return None
        pts = _simplify(np.vstack([pts, pts[:1]]), 0.12)[:-1]
        return _orthogonal(pts, xs, ys) if len(pts) >= 3 else None

    rings = [r for r in (ring(ln) for ln in lines) if r is not None]
    if not rings:
        return None
    rings.sort(key=lambda r: -abs(_signed_area(r)))
    outer = rings[0]
    if _signed_area(outer) < 0:
        outer = outer[::-1]
    for hole in rings[1:]:
        if _signed_area(hole) > 0:
            hole = hole[::-1]
        # 다리: 구멍 꼭짓점에서 바깥 테두리 변으로 곧게(수직으로) 가장 짧게 잇는다
        best = None
        n = len(outer)
        for j, h in enumerate(hole):
            for e in range(n):
                a, b = outer[e], outer[(e + 1) % n]
                if abs(a[1] - b[1]) < 1e-9 and min(a[0], b[0]) < h[0] < max(a[0], b[0]):
                    f, dist = np.array([h[0], a[1]]), abs(h[1] - a[1])
                elif abs(a[0] - b[0]) < 1e-9 and min(a[1], b[1]) < h[1] < max(a[1], b[1]):
                    f, dist = np.array([a[0], h[1]]), abs(h[0] - a[0])
                else:
                    continue
                if best is None or dist < best[0]:
                    best = (dist, e, f, j)
        if best is None:  # 곧게 이을 곳이 없으면 가장 가까운 꼭짓점끼리
            d = np.linalg.norm(outer[:, None, :] - hole[None, :, :], axis=2)
            i, j = np.unravel_index(np.argmin(d), d.shape)
            hole = np.roll(hole, -j, axis=0)
            outer = np.vstack([outer[:i + 1], hole, hole[:1], outer[i:]])
            continue
        _, e, f, j = best
        hole = np.roll(hole, -j, axis=0)
        outer = np.vstack([outer[:e + 1], [f], hole, hole[:1], [f], outer[e + 1:]])  # 변 위 f → 구멍 한 바퀴 → f
    return outer


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
        return {"layouts": d.get("layouts", {}), "floors": d.get("floors", {}), "walls": d.get("walls", {})}
    return {"layouts": {}, "floors": {}, "walls": {}}


def save_layouts(out_dir: Path, data: dict) -> None:
    (Path(out_dir) / LAYOUT_FILE).write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def apply_layouts(out_dir: Path, labels: list[str], data: dict) -> dict[str, int]:
    """층마다 그 층 구조의 방을 넣어 DXF 를 다시 만든다. {층: 방 수}."""
    from .las_plan import plan_dxf

    out_dir = Path(out_dir)
    done = {}
    for lab in labels:
        lay = data["floors"].get(lab, "")
        rooms = data["layouts"].get(lay, [])
        df = pd.read_csv(out_dir / CSV_NAME.format(lab))
        plan = load_plan(out_dir, lab) or {}
        (out_dir / DXF_NAME.format(lab)).write_bytes(plan_dxf(df, plan, lab, rooms, data.get("walls", {}).get(lay)))
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


def resolve_overlaps(plan: dict, rooms: list[dict]) -> list[dict]:
    """겹친 칸은 목록 뒤쪽 방(새로 그리거나 마지막에 고친 방)이 갖는다. 앞쪽 방은 겹친 만큼 깎아 다시 그리고,
    다 덮였으면 뺀다. 겹치지 않은 방은 좌표를 그대로 둔다."""
    from scipy import ndimage

    if len(rooms) < 2:
        return rooms
    # 깎인 변은 벽이 아니라 이긴 방의 변에 맞춘다 (벽에 붙이면 두 방 사이에 빈 띠가 생긴다)
    pts = np.vstack([room_poly(r) for r in rooms])
    xs, ys = np.unique(pts[:, 0]), np.unique(pts[:, 1])
    masks = [rooms_mask(plan, [r]) > 0 for r in rooms]
    taken = np.zeros(plan["wall"].shape, bool)
    out = []
    for r, m in zip(reversed(rooms), reversed(masks)):
        own = m & ~taken
        if not (m & taken).any():
            out.append(r)
        elif own.sum() * plan["res"] ** 2 >= 0.3:
            lab, n = ndimage.label(own)
            if n > 1:
                own = lab == (np.argmax(np.bincount(lab.ravel())[1:]) + 1)
            poly = _trace(own, plan, xs, ys)
            if poly is not None:
                out.append({"name": r["name"], "poly": poly.tolist()})
        taken |= m
    return out[::-1]


def clean_poly(poly) -> list[list[float]]:
    """편집기에서 온 다각형 정리: 같은 점이 이어진 것(나누고 안 옮긴 자리 등)과 한 줄 위의 가운데 점을 뺀다."""
    p = [[round(float(x), 3), round(float(y), 3)] for x, y in poly]
    changed = True
    while changed and len(p) > 3:
        changed = False
        for i in range(len(p)):
            a, b, c = p[i - 1], p[i], p[(i + 1) % len(p)]
            between = (b[0] - a[0]) * (c[0] - b[0]) + (b[1] - a[1]) * (c[1] - b[1]) > 0  # 되돌아가는 점(구멍 다리)은 둔다
            if b == a or (between and abs((b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])) < 1e-9):
                del p[i]
                changed = True
                break
    return p


def subtract_rect(plan: dict, rooms: list[dict], rect) -> list[dict]:
    """네모(x0, x1, y0, y1)만큼 방들에서 뺀다. 방이 둘로 갈리면 큰 쪽은 원래 이름, 나머지는 '이름-2'… 로 남긴다."""
    from scipy import ndimage

    x0, x1 = sorted(rect[:2])
    y0, y1 = sorted(rect[2:])
    cut = rooms_mask(plan, [{"poly": [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]}]) > 0
    pts = np.vstack([room_poly(r) for r in rooms] + [np.array([[x0, y0], [x1, y1]])])
    xs, ys = np.unique(pts[:, 0]), np.unique(pts[:, 1])  # 깎인 변은 네모 변·방 변에 맞춘다
    out = []
    for r in rooms:
        m = rooms_mask(plan, [r]) > 0
        if not (m & cut).any():
            out.append(r)
            continue
        lab, n = ndimage.label(m & ~cut)
        parts = sorted((lab == k for k in range(1, n + 1)), key=lambda a: -a.sum())
        parts = [a for a in parts if a.sum() * plan["res"] ** 2 >= 0.3]
        for i, a in enumerate(parts):
            poly = _trace(a, plan, xs, ys)
            if poly is not None:
                out.append({"name": r["name"] if i == 0 else f"{r['name']}-{i + 1}", "poly": poly.tolist()})
    return out


# ------------------------------------------------------------------ 실무자가 뺀 격자점
EXCLUDE_FILE = "excluded.json"  # {층: {point_id: CSV 한 줄(되살릴 때 씀)}}


def load_excluded(out_dir: Path) -> dict:
    p = Path(out_dir) / EXCLUDE_FILE
    try:
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    except (OSError, ValueError):
        return {}


def drop_excluded(out_dir: Path, label: str, df: pd.DataFrame) -> pd.DataFrame:
    """뺀 점을 CSV 에서 지운다 (다시 변환해도 계속 빠지게 convert 가 부른다)."""
    ids = set(load_excluded(out_dir).get(label, {}))
    return df[~df["point_id"].isin(ids)] if ids else df


def _rebuild_dxf(out_dir: Path, label: str, df: pd.DataFrame) -> None:
    from .las_plan import plan_dxf

    data = load_layouts(out_dir)
    lay = data["floors"].get(label, "")
    rooms = data["layouts"].get(lay, [])
    (Path(out_dir) / DXF_NAME.format(label)).write_bytes(
        plan_dxf(df, load_plan(out_dir, label) or {}, label, rooms, data["walls"].get(lay)))


def exclude_points(out_dir: Path, label: str, ids: list[str]) -> int:
    """격자점을 결과에서 뺀다: CSV·도면에서 지우고(두께 분석에도 안 들어감) 원래 줄은 excluded.json 에 둔다."""
    out_dir = Path(out_dir)
    path = out_dir / CSV_NAME.format(label)
    df = pd.read_csv(path)
    hit = df[df["point_id"].isin(ids)]
    if hit.empty:
        return 0
    ex = load_excluded(out_dir)
    ex.setdefault(label, {}).update({r["point_id"]: r for r in json.loads(hit.to_json(orient="records"))})
    (out_dir / EXCLUDE_FILE).write_text(json.dumps(ex, ensure_ascii=False, indent=1), encoding="utf-8")
    df = df[~df["point_id"].isin(ids)]
    df.to_csv(path, index=False, encoding="utf-8")
    _rebuild_dxf(out_dir, label, df)
    return len(hit)


def restore_points(out_dir: Path, label: str, ids: list[str]) -> int:
    """뺀 격자점을 되살린다."""
    out_dir = Path(out_dir)
    ex = load_excluded(out_dir)
    rows = [ex.get(label, {}).pop(i) for i in ids if i in ex.get(label, {})]
    if not rows:
        return 0
    path = out_dir / CSV_NAME.format(label)
    df = pd.read_csv(path)
    df = pd.concat([df, pd.DataFrame(rows)[df.columns.intersection(pd.DataFrame(rows).columns)]], ignore_index=True)
    df = df.sort_values("point_number").reset_index(drop=True)
    df.to_csv(path, index=False, encoding="utf-8")
    (out_dir / EXCLUDE_FILE).write_text(json.dumps(ex, ensure_ascii=False, indent=1), encoding="utf-8")
    _rebuild_dxf(out_dir, label, df)
    return len(rows)


# ------------------------------------------------------------------ 실무자가 고친 벽 (구조마다)
def walls_from_bands(bands: list) -> list[dict]:
    """자동 추정 벽 띠 [x0, x1, y0, y1] → 편집용 벽 {k: line, a, b, t} (긴 쪽이 중심선, 짧은 쪽이 두께)."""
    out = []
    for x0, x1, y0, y1 in bands:
        if x1 - x0 >= y1 - y0:
            y = round((y0 + y1) / 2, 3)
            out.append({"k": "line", "a": [x0, y], "b": [x1, y], "t": round(y1 - y0, 3)})
        else:
            x = round((x0 + x1) / 2, 3)
            out.append({"k": "line", "a": [x, y0], "b": [x, y1], "t": round(x1 - x0, 3)})
    return out


def _arc(w: dict):
    a, m, b = (np.asarray(w[k], float) for k in ("a", "m", "b"))
    d = 2 * (a[0] * (m[1] - b[1]) + m[0] * (b[1] - a[1]) + b[0] * (a[1] - m[1]))
    if abs(d) < 1e-9:
        return None
    s2 = lambda p: p @ p  # noqa: E731
    c = np.array([s2(a) * (m[1] - b[1]) + s2(m) * (b[1] - a[1]) + s2(b) * (a[1] - m[1]),
                  s2(a) * (b[0] - m[0]) + s2(m) * (a[0] - b[0]) + s2(b) * (m[0] - a[0])]) / d
    r = float(np.hypot(*(a - c)))
    ang = lambda p: np.arctan2(p[1] - c[1], p[0] - c[0])  # noqa: E731
    sa, ma, ea = ang(a), ang(m), ang(b)
    tau = 2 * np.pi
    ccw = (ma - sa) % tau < (ea - sa) % tau
    span = (ea - sa) % tau if ccw else -((sa - ea) % tau)
    return c, r, sa, span


def wall_polygon(w: dict, seg: int = 24) -> np.ndarray:
    """벽 하나를 두께가 있는 다각형으로 (도면 해치·그림용, 건물 축 m)."""
    t = float(w.get("t", 0.2)) / 2
    if w.get("k") == "arc" and w.get("m") is not None and (A := _arc(w)) is not None:
        c, r, sa, span = A
        th = sa + span * np.linspace(0, 1, seg + 1)
        outer = np.column_stack([c[0] + (r + t) * np.cos(th), c[1] + (r + t) * np.sin(th)])
        inner = np.column_stack([c[0] + (r - t) * np.cos(th), c[1] + (r - t) * np.sin(th)])[::-1]
        return np.vstack([outer, inner])
    a, b = np.asarray(w["a"], float), np.asarray(w["b"], float)
    d = b - a
    L = float(np.hypot(*d)) or 1e-9
    n = np.array([-d[1], d[0]]) / L * t
    return np.array([a + n, b + n, b - n, a - n])


def wall_faces(walls: list[dict]) -> tuple[np.ndarray, np.ndarray]:
    """가로·세로 직선 벽의 양쪽 면 위치 (방 경계를 붙일 자리): (x 들, y 들)."""
    xs, ys = [], []
    for w in walls or []:
        if w.get("k") == "arc":
            continue
        (ax, ay), (bx, by), t = w["a"], w["b"], float(w.get("t", 0.2)) / 2
        if abs(ay - by) < 1e-6:
            ys += [ay - t, ay + t]
        elif abs(ax - bx) < 1e-6:
            xs += [ax - t, ax + t]
    return np.array(xs), np.array(ys)
