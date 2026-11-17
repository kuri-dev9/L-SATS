"""LAS 결과의 방 배치: 층 구조 묶기 → 구조마다 방(직사각형 + 이름) 정하기 → 같은 구조 층 도면에 넣기.

LAS 로 만든 층은 모두 같은 격자(건물 축 좌표)라서, 한 구조에서 정한 방을 같은 구조의 다른 층에 그대로 씌울 수 있다.
배치는 작업 폴더(LSATS_grid)의 layouts.json 에 둔다:
    {"layouts": {"구조 A": [{"name": "2호_침실1", "x0":.., "y0":.., "x1":.., "y1":..}, ...]},
     "floors": {"7F": "구조 A", ...}}
방 좌표는 건물 축 좌표(m, CSV 의 local_x/local_y 와 같음).
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


# ------------------------------------------------------------------ 방 자동 나누기
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


def snap_room(room: dict, xs: np.ndarray, ys: np.ndarray, tol: float = SNAP_M) -> dict:
    """방 네 변을 가까운 벽 면에 맞춘다 (tol 안에 있을 때만)."""
    out = dict(room)
    for key, cand in (("x0", xs), ("x1", xs), ("y0", ys), ("y1", ys)):
        if len(cand):
            d = np.abs(cand - out[key])
            if d.min() <= tol:
                out[key] = round(float(cand[np.argmin(d)]), 3)
    return out


def auto_rooms(plan: dict) -> list[dict]:
    """벽 사이 빈 공간을 방으로 나눠 직사각형으로 (문틈은 막는다). 이름은 '실01'… 로 붙인다."""
    from scipy import ndimage

    res, u0, v0 = plan["res"], plan["u0"], plan["v0"]
    wall = _wall_mask(plan)
    floor = ndimage.binary_fill_holes(ndimage.binary_closing(plan["floor"] > 0, iterations=6))
    grow = max(1, int(round(DOOR_GAP / res)))
    free = floor & ~ndimage.binary_dilation(wall, iterations=grow)
    lab, n = ndimage.label(free)
    xs, ys = wall_coords(plan)
    rooms = []
    for k, sl in enumerate(ndimage.find_objects(lab), start=1):
        if sl is None:
            continue
        m = lab[sl] == k
        if m.sum() * res * res < MIN_ROOM_M2:
            continue
        # 키운 벽만큼 다시 넓힌 범위 (가장자리 1 % 는 잡음으로 빼고)
        rr, cc = np.nonzero(m)
        c0, c1 = np.percentile(cc, [1, 99]) + sl[1].start
        r0, r1 = np.percentile(rr, [1, 99]) + sl[0].start
        room = {"x0": u0 + (c0 - grow) * res, "x1": u0 + (c1 + 1 + grow) * res,
                "y0": v0 + (r0 - grow) * res, "y1": v0 + (r1 + 1 + grow) * res}
        rooms.append(snap_room({k2: round(float(v), 3) for k2, v in room.items()}, xs, ys))
    rooms.sort(key=lambda r: (-round(r["y1"], 0), r["x0"]))  # 위에서 아래, 왼쪽에서 오른쪽
    return [{"name": f"실{i:02d}", **r} for i, r in enumerate(rooms, start=1)]


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
