"""기본 도면(DXF)의 방을 LAS 벽에 맞춰 방 배치로 가져온다.

도면에 측정점 이름(P001…)이 없어도 된다. LAS 는 건물 전체 벽을 가지고 있으므로, 도면의 방 경계를 벽 위치에 겹쳐
맞춘다: 축척(mm → m) · 90° 단위 회전 · 이동. 자동으로 가장 많이 겹치는 자리를 찾고(`auto_fit`), 실무자가 방 배치
화면의 도면 맞추기 편집기에서 끌어 고친다. 맞춘 결과는 layouts.json 의 "cad" 에 구조마다 둔다:
    {"cad": {"구조 A": {"file": "도면.dxf", "layer": "ROOM_BOUNDARY", "tf": {"k": 0, "s": 0.001, "t": [x, y]}, "score": 0.8}}}
LAS 격자·건물 축은 측량 좌표와 같은 축이라 도면도 보통 90° 단위로만 돌아가 있다 (그 밖의 기울기는 다루지 않는다).
"""
from __future__ import annotations

import io

import numpy as np

from .core import load_cad

DRAWING_DIR = "drawings"  # LSATS_grid 안에 올린 도면 사본을 두는 곳
FIT_TOL_M = 0.15  # 방 경계가 벽에서 이만큼 안이면 '벽에 맞음' (도면 방이 벽 중심선이어도 맞게)


def read_rooms(data: bytes, layer: str | None = None) -> tuple[list[dict], list[str], str | None]:
    """도면의 방 (이름, 도면 좌표 다각형), 다각형 레이어들, 쓴 방 레이어."""
    plan = load_cad(io.BytesIO(data), layer)
    rooms = [{"name": r.name, "poly": np.asarray(r.polygon, float).tolist()} for r in plan.rooms]
    return rooms, plan.polygon_layers, plan.room_layer


def guess_scale(rooms: list[dict]) -> float:
    """도면 단위 → m. 건물 크기가 수백 이상이면 mm 로 본다."""
    if not rooms:
        return 0.001
    p = np.vstack([np.asarray(r["poly"], float) for r in rooms])
    span = float((p.max(0) - p.min(0)).max())
    return 0.001 if span > 500 else 1.0


def _rot(k: int) -> np.ndarray:
    c, s = [(1, 0), (0, 1), (-1, 0), (0, -1)][k % 4]
    return np.array([[c, -s], [s, c]], float)


def transform(poly, tf: dict) -> np.ndarray:
    """도면 좌표 → 건물 축 m."""
    p = np.asarray(poly, float) * float(tf["s"])
    return p @ _rot(int(tf["k"])).T + np.asarray(tf["t"], float)


def fitted_rooms(rooms: list[dict], tf: dict) -> list[dict]:
    return [{"name": r["name"], "poly": np.round(transform(r["poly"], tf), 3).tolist()} for r in rooms]


def _edge_points(polys: list[np.ndarray], step: float) -> np.ndarray:
    out = []
    for p in polys:
        for a, b in zip(p, np.roll(p, -1, 0)):
            n = max(1, int(np.ceil(np.linalg.norm(b - a) / step)))
            out.append(a + (b - a) * (np.arange(n) / n)[:, None])
    return np.vstack(out) if out else np.zeros((0, 2))


def _wall_field(plan: dict, res: float, tol: float) -> tuple[np.ndarray, float, float]:
    """벽 칸을 tol 만큼 키운 마스크를 res 칸으로 (마스크, 원점 u, 원점 v)."""
    from scipy import ndimage

    from .las_plan import WALL_MIN_POINTS

    w = plan["wall"] >= WALL_MIN_POINTS
    f = max(1, int(round(res / plan["res"])))
    if f > 1:
        ny, nx = (w.shape[0] // f) * f, (w.shape[1] // f) * f
        w = w[:ny, :nx].reshape(ny // f, f, nx // f, f).any((1, 3))
    k = max(1, int(round(tol / res)))
    return ndimage.binary_dilation(w, iterations=k), float(plan["u0"]), float(plan["v0"])


def score(plan: dict, rooms_m: list[dict], tol: float = FIT_TOL_M) -> float:
    """방 경계 중 벽(±tol) 위에 놓인 비율 (0~1)."""
    if not rooms_m or plan is None:
        return 0.0
    res = float(plan["res"])
    field, u0, v0 = _wall_field(plan, res, tol)
    e = _edge_points([np.asarray(r["poly"], float) for r in rooms_m], res)
    ix, iy = np.floor((e[:, 0] - u0) / res).astype(int), np.floor((e[:, 1] - v0) / res).astype(int)
    ok = (ix >= 0) & (iy >= 0) & (ix < field.shape[1]) & (iy < field.shape[0])
    hit = np.zeros(len(e), bool)
    hit[ok] = field[iy[ok], ix[ok]]
    return float(hit.mean())


def _best_shift(field: np.ndarray, u0: float, v0: float, res: float, e: np.ndarray,
                window: tuple[float, float, float] | None = None) -> tuple[np.ndarray, float]:
    """도면 경계 점 e(건물 축 m, 이동 전)를 옮겨 벽 칸과 가장 많이 겹치는 이동량과 그때 겹친 비율."""
    from scipy.signal import fftconvolve

    lo = e.min(0)
    ix, iy = np.floor((e - lo) / res).astype(int).T
    img = np.zeros((iy.max() + 1, ix.max() + 1))
    np.add.at(img, (iy, ix), 1.0)
    corr = fftconvolve(field.astype(float), img[::-1, ::-1], mode="full")
    # corr[a, b] = 이미지 원점이 벽 칸 (a - h + 1, b - w + 1) 에 놓였을 때 겹친 점 수
    h, w = img.shape
    if window is not None:  # 이 자리(cx, cy) 근처 ±r m 만 본다
        cx, cy, r = window
        b0, a0 = (cx - u0) / res + w - 1, (cy - v0) / res + h - 1
        rr = int(np.ceil(r / res))
        mask = np.zeros_like(corr, bool)
        a, b = int(round(a0)), int(round(b0))
        mask[max(0, a - rr):a + rr + 1, max(0, b - rr):b + rr + 1] = True
        corr = np.where(mask, corr, -1)
    a, b = np.unravel_index(int(np.argmax(corr)), corr.shape)
    origin = np.array([u0 + (b - w + 1) * res, v0 + (a - h + 1) * res])
    return origin - lo, float(corr[a, b] / len(e))


def auto_fit(plan: dict, rooms: list[dict], s: float | None = None) -> tuple[dict, float]:
    """도면 방을 벽에 가장 잘 맞는 자리로: 네 방향을 0.1 m 칸으로 훑고, 고른 방향을 0.05 m 로 다듬는다. (tf, 겹친 비율)."""
    s = guess_scale(rooms) if s is None else s
    polys = [np.asarray(r["poly"], float) * s for r in rooms]
    coarse = 0.1
    field, u0, v0 = _wall_field(plan, coarse, 0.2)
    best = None
    for k in range(4):
        e = _edge_points([p @ _rot(k).T for p in polys], coarse / 2)
        t, sc = _best_shift(field, u0, v0, coarse, e)
        if best is None or sc > best[2]:
            best = (k, t, sc)
    k, t, _ = best
    res = float(plan["res"])
    field, u0, v0 = _wall_field(plan, res, 0.05)
    e = _edge_points([p @ _rot(k).T for p in polys], res)
    lo = e.min(0)
    t2, _ = _best_shift(field, u0, v0, res, e, window=(*(lo + t), 0.3))
    tf = {"k": k, "s": s, "t": np.round(t2, 3).tolist()}
    return tf, score(plan, fitted_rooms(rooms, tf))


MAX_DRAW_PTS = 300_000  # 화면에 보낼 도면 선 점 수 상한 (넘으면 짧은 선부터 뺀다)


def read_drawing(data: bytes) -> dict:
    """도면 그대로 그리기용: 모든 선(LINE·폴리선·호·원, 도면 좌표)과 글자 [[x, y, 글자], ...]. 블록은 풀어서 읽는다."""
    from ezdxf import recover

    doc, _ = recover.read(io.BytesIO(data))
    msp = doc.modelspace()
    lines, texts = [], []

    def walk(entities, depth=0):
        for e in entities:
            t = e.dxftype()
            try:
                if t == "INSERT" and depth < 4:
                    walk(e.virtual_entities(), depth + 1)
                elif t == "LINE":
                    lines.append([[e.dxf.start.x, e.dxf.start.y], [e.dxf.end.x, e.dxf.end.y]])
                elif t in ("LWPOLYLINE", "POLYLINE", "ARC", "CIRCLE", "ELLIPSE", "SPLINE"):
                    pts = [[v.x, v.y] for v in e.flattening(50.0)] if t != "LWPOLYLINE" else \
                        [[x, y] for x, y in e.get_points("xy")]
                    if t == "LWPOLYLINE" and e.closed and pts:
                        pts.append(pts[0])
                    if len(pts) >= 2:
                        lines.append(pts)
                elif t in ("TEXT", "MTEXT"):
                    s = e.dxf.text if t == "TEXT" else e.plain_text()
                    p = e.dxf.insert
                    if s.strip():
                        texts.append([p.x, p.y, s.strip()[:40]])
            except Exception:  # 깨진 개체는 건너뛴다
                continue

    walk(msp)
    if sum(len(ln) for ln in lines) > MAX_DRAW_PTS:
        lines.sort(key=lambda ln: -float(np.ptp(np.asarray(ln), axis=0).max()))
        keep, n = [], 0
        for ln in lines:
            if n + len(ln) > MAX_DRAW_PTS:
                break
            keep.append(ln)
            n += len(ln)
        lines = keep
    return {"lines": lines, "texts": texts}
