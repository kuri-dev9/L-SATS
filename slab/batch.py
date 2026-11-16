"""여러 층 파일을 한꺼번에 받아 층을 찾고, 위·아래층 짝과 도면을 정한다.

- 스캔 파일(CSV/엑셀)마다 층 바닥 높이를 파일 안의 값으로 구한다 (`Global_Floor_m`, 없으면 바닥 Z 중앙값).
  층 순서는 이 높이로 정하고, 층 이름(8F 등)은 파일 이름에서 찾는다. 이름에 층 표기가 없으면 높이 순서로 붙인다.
- 바로 아래 높이의 층을 아래층으로 짝짓는다. 위층 바닥과 아래층 천장의 차이가 슬래브 두께 범위가 아니면
  (층이 빠졌거나 다른 동 파일) 짝을 만들지 않고 이유를 남긴다.
- 도면(DXF)은 위층 기준이다(측정점 번호가 위층 스캔과 같다). 파일 이름의 층 표기로 층에 붙이고,
  층 표기가 없는 도면이 하나면 도면이 없는 층에 공용으로 쓴다. 여러 개면 측정점 좌표가 가장 잘 맞는 층에 붙인다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from .core import CadPlan, estimate_transform, to_meters

SCAN_TYPES = ("csv", "xlsx", "xlsm", "txt")
CAD_TYPES = ("dxf",)
SAME_FLOOR_M = 0.5  # 바닥 높이 차이가 이보다 작으면 같은 층 파일로 본다
SLAB_GAP_M = (-0.3, 1.0)  # 위층 바닥 − 아래층 천장(중앙값)이 이 범위여야 바로 위·아래층이다
CAD_MATCH_RMS_M = 0.05  # 도면을 내용으로 층에 붙일 때 허용하는 좌표 맞춤 오차


def kind_of(name: str) -> str:
    ext = Path(name).suffix.lower().lstrip(".")
    return "cad" if ext in CAD_TYPES else "scan" if ext in SCAN_TYPES else ""


def guess_floor(name: str) -> str:
    """파일 이름에서 층 표기(8F, B1, B2F 등)를 찾는다."""
    m = re.search(r"(?<![A-Za-z0-9])(B?\d{1,3}F|B\d{1,2})(?![A-Za-z0-9])", Path(name).stem, re.I)
    return m.group(1).upper() if m else ""


def guess_dong(name: str) -> str:
    m = re.search(r"(\d{1,4}동)", Path(name).stem)
    return m.group(1) if m else ""


def floor_number(label: str) -> float | None:
    """'8F'→8, 'B1'→-1. 모르면 None."""
    m = re.fullmatch(r"(B?)(\d+)F?", label.upper())
    if not m:
        return None
    n = int(m.group(2))
    return -n if m.group(1) else n


@dataclass
class Floor:
    label: str
    level_m: float  # 층 바닥 높이 (정렬용)
    scan: str  # 스캔 파일 이름
    grid: pd.DataFrame  # standardize_grid 결과
    n_points: int
    floor_z_m: float  # 바닥 Z 중앙값 (m)
    ceiling_z_m: float  # 천장 Z 중앙값 (m)
    auto_label: bool = False  # 파일 이름에 층 표기가 없어 순서로 붙인 이름


@dataclass
class Pair:
    upper: Floor
    lower: Floor | None
    cad: str | None = None  # 쓸 도면 파일 이름
    cad_shared: bool = False  # 공용 도면을 쓰는지
    problem: str = ""  # 짝을 못 지은 이유 (있으면 계산하지 않는다)

    @property
    def key(self) -> str:
        return self.upper.label

    @property
    def title(self) -> str:
        return f"{self.upper.label} / {self.lower.label}" if self.lower else self.upper.label


@dataclass
class Plan:
    floors: list[Floor] = field(default_factory=list)  # 아래층부터
    pairs: list[Pair] = field(default_factory=list)  # 위층부터 (건물 단면처럼)
    cads: list[str] = field(default_factory=list)
    shared_cad: str | None = None
    warnings: list[str] = field(default_factory=list)
    errors: dict[str, str] = field(default_factory=dict)  # 읽지 못한 파일 → 이유


def floor_level(raw: pd.DataFrame, grid: pd.DataFrame) -> float:
    """파일 안의 층 바닥 높이(m). Global_Floor_m 열이 있으면 그 값, 없으면 바닥 Z 중앙값."""
    for col, k in (("Global_Floor_m", 1.0), ("Global_Floor_mm", 0.001)):
        if col in raw.columns:
            v = pd.to_numeric(raw[col], errors="coerce").dropna()
            if len(v):
                return float(v.median()) * k
    return float(grid.loc[grid["valid_floor"], "floor_z"].median())


def make_floor(name: str, raw: pd.DataFrame, grid: pd.DataFrame, xy_unit: str = "auto",
               z_unit: str = "auto") -> Floor:
    g, _ = to_meters(grid, xy_unit, z_unit)
    floor_z = float(g.loc[g["valid_floor"], "floor_z"].median()) if g["valid_floor"].any() else np.nan
    ceil_z = float(g.loc[g["valid_ceiling"], "ceiling_z"].median()) if g["valid_ceiling"].any() else np.nan
    level = floor_level(raw, grid)
    if np.isfinite(floor_z) and abs(level - floor_z) > 50:  # Global_Floor 가 mm 등 다른 단위
        level = floor_z
    return Floor(guess_floor(name), level, name, grid, len(grid), floor_z, ceil_z)


def plan_floors(floors: list[Floor], cads: dict[str, CadPlan | None], labels: dict[str, str] | None = None,
                cad_choice: dict[str, str] | None = None) -> Plan:
    """층 정렬·짝짓기·도면 배정.

    labels: {스캔 파일 이름: 사용자가 고친 층 이름}, cad_choice: {층 이름: 도면 이름 또는 ''(없음)}.
    """
    out = Plan(cads=sorted(cads))
    labels = labels or {}
    fl = sorted((f for f in floors if np.isfinite(f.level_m)), key=lambda f: f.level_m)
    for f in floors:
        if not np.isfinite(f.level_m):
            out.warnings.append(f"{f.scan}: 바닥 높이를 찾지 못해 층 순서를 정할 수 없어 뺐어요.")

    # 같은 층 파일이 두 개면 먼저 온 것만 쓴다
    kept: list[Floor] = []
    for f in fl:
        if kept and f.level_m - kept[-1].level_m < SAME_FLOOR_M:
            out.warnings.append(f"{f.scan}: {kept[-1].scan} 과 같은 층(바닥 높이 {f.level_m:.2f}m)이라 뺐어요.")
            continue
        kept.append(f)

    # 층 이름: 사용자가 고친 이름 > 파일 이름 > 순서
    for i, f in enumerate(kept):
        if labels.get(f.scan):
            f.label, f.auto_label = labels[f.scan], False
        elif not f.label:
            f.label, f.auto_label = f"층{i + 1}", True
    seen: dict[str, int] = {}
    for f in kept:  # 이름이 겹치면 뒤에 번호
        n = seen.get(f.label, 0)
        seen[f.label] = n + 1
        if n:
            f.label = f"{f.label}({n + 1})"
    out.floors = kept

    # 도면 배정
    by_label = {f.label: f for f in kept}
    cad_of: dict[str, str] = {}
    loose: list[str] = []
    for name in sorted(cads):
        lab = guess_floor(name)
        if lab and lab in by_label and lab not in cad_of:
            cad_of[lab] = name
        else:
            loose.append(name)
    if len(loose) == 1:
        out.shared_cad = loose[0]
    else:
        for name in loose:  # 측정점 번호 좌표가 가장 잘 맞는 층
            plan = cads.get(name)
            if plan is None:
                continue
            best, best_rms = None, CAD_MATCH_RMS_M
            for f in kept:
                if f.label in cad_of:
                    continue
                try:
                    t = estimate_transform(plan, to_meters(f.grid)[0])
                except ValueError:
                    continue
                if t.method.startswith("측정점") and t.rms_m < best_rms:
                    best, best_rms = f.label, t.rms_m
            if best:
                cad_of[best] = name
            else:
                out.warnings.append(f"{name}: 어느 층 도면인지 찾지 못했어요. 층 목록에서 직접 골라 주세요.")
    for lab, name in (cad_choice or {}).items():
        if lab in by_label:
            cad_of[lab] = name  # '' 이면 도면 없이

    # 짝짓기 (위층부터)
    for i in range(len(kept) - 1, -1, -1):
        up = kept[i]
        lo = kept[i - 1] if i else None
        cad = cad_of.get(up.label, None if up.label in (cad_choice or {}) else out.shared_cad) or None
        pair = Pair(up, lo, cad, cad is not None and cad == out.shared_cad and up.label not in cad_of)
        if lo is None:
            pair.problem = "맨 아래층이라 아래층 천장이 없어요"
        else:
            gap = up.floor_z_m - lo.ceiling_z_m
            if np.isfinite(gap) and not SLAB_GAP_M[0] <= gap <= SLAB_GAP_M[1]:
                pair.problem = (f"{lo.label} 천장과 {up.label} 바닥 사이가 {gap:.2f}m라 바로 위·아래층이 아니에요 "
                                "(층 파일이 빠졌을 수 있어요)")
        out.pairs.append(pair)
    return out
