"""레이저 스캔 그리드 데이터로 실별 슬래브 두께를 산출하는 핵심 로직.

두께(mm) = (상부층 바닥 콘크리트 윗면 Z - 하부층 천장 Z) x 1000

상·하부층은 같은 측량 기준점을 쓰지만 격자 배치와 점 번호가 층마다 다르므로,
점 번호가 아닌 XY 좌표로 대응점을 찾는다.
"""
from __future__ import annotations

import io
import re
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd
from ezdxf import recover
from matplotlib.path import Path as MplPath
from scipy.interpolate import LinearNDInterpolator
from scipy.spatial import cKDTree

# 입력 파일의 기본 열 이름 (grid_analysis_floor_level_*.csv 형식)
DEFAULT_COLUMNS = {
    "point_id": "point_id",
    "x": "x",
    "y": "y",
    "floor_z": "floor_z",
    "ceiling_z": "ceiling_z",
    "floor_error": "floor_error",
    "ceiling_error": "ceiling_error",
}

POINT_LABEL_RE = re.compile(r"^P\d+$")
OUTSIDE_ROOM = "(실 외부)"
NO_CAD = "(도면 없음)"


# ---------------------------------------------------------------------------
# 입력 읽기
# ---------------------------------------------------------------------------
def _read_bytes(src) -> tuple[str, bytes]:
    """경로 또는 업로드 파일 객체에서 (파일명, 바이트)를 얻는다."""
    if isinstance(src, (str, Path)):
        return str(src), Path(src).read_bytes()
    name = getattr(src, "name", "")
    data = src.getvalue() if hasattr(src, "getvalue") else src.read()
    return name, data


def read_table(src) -> pd.DataFrame:
    """CSV/XLSX를 원본 열 그대로 읽는다."""
    name, data = _read_bytes(src)
    if name.lower().endswith((".xlsx", ".xlsm", ".xls")):
        return pd.read_excel(io.BytesIO(data))
    for enc in ("utf-8-sig", "cp949"):
        try:
            return pd.read_csv(io.BytesIO(data), encoding=enc)
        except UnicodeDecodeError:
            continue
    raise ValueError(f"{name}: 인코딩을 인식할 수 없습니다 (UTF-8/CP949 지원)")


def _as_bool(s: pd.Series) -> pd.Series:
    if s.dtype == bool:
        return s
    return s.astype(str).str.strip().str.lower().isin(["true", "1", "y", "yes"])


def standardize_grid(raw: pd.DataFrame, columns: dict | None = None) -> pd.DataFrame:
    """원본 표를 표준 열(point_id, x, y, floor_z, ceiling_z, *_error, valid_*)로 바꾼다.

    오차 열(floor_error, ceiling_error)은 층 기준면 대비 편차(m)이다.
    없으면 해당 층 Z의 중앙값 대비 편차로 대신한다.
    """
    cols = {**DEFAULT_COLUMNS, **(columns or {})}
    for key in ("x", "y"):
        if cols[key] not in raw.columns:
            raise ValueError(f"필수 열({key} 좌표)이 지정되지 않았거나 파일에 없습니다. 열 매핑을 확인하세요.")

    df = pd.DataFrame(index=raw.index)
    if cols["point_id"] in raw.columns:
        df["point_id"] = raw[cols["point_id"]].astype(str).str.strip()
    else:
        df["point_id"] = [f"P{i + 1:03d}" for i in range(len(raw))]
    df["x"] = pd.to_numeric(raw[cols["x"]], errors="coerce")
    df["y"] = pd.to_numeric(raw[cols["y"]], errors="coerce")

    for z, err in (("floor_z", "floor_error"), ("ceiling_z", "ceiling_error")):
        df[z] = pd.to_numeric(raw[cols[z]], errors="coerce") if cols[z] in raw.columns else np.nan
        if cols[err] in raw.columns:
            df[err] = pd.to_numeric(raw[cols[err]], errors="coerce")
        else:
            df[err] = df[z] - df[z].median()

    not_empty = ~_as_bool(raw["is_empty"]) if "is_empty" in raw.columns else True
    has_floor = _as_bool(raw["has_floor"]) if "has_floor" in raw.columns else True
    has_ceiling = _as_bool(raw["has_ceiling"]) if "has_ceiling" in raw.columns else True
    df["valid_floor"] = df["floor_z"].notna() & has_floor & not_empty
    df["valid_ceiling"] = df["ceiling_z"].notna() & has_ceiling & not_empty

    return df.dropna(subset=["x", "y"]).reset_index(drop=True)


def load_grid(src, columns: dict | None = None) -> pd.DataFrame:
    return standardize_grid(read_table(src), columns)


# ---------------------------------------------------------------------------
# 통합 CAD (실 경계 + 실명 + 측정점 라벨)
# ---------------------------------------------------------------------------
@dataclass
class Room:
    room_id: str
    name: str
    polygon: np.ndarray  # (n, 2), CAD 좌표
    label_xy: np.ndarray  # 실명 표시 위치, CAD 좌표

    @property
    def area(self) -> float:
        x, y = self.polygon[:, 0], self.polygon[:, 1]
        return 0.5 * abs(np.dot(x, np.roll(y, 1)) - np.dot(y, np.roll(x, 1)))


@dataclass
class CadPlan:
    rooms: list[Room]
    room_layer: str | None
    polygon_layers: list[str]
    labels: dict[str, np.ndarray]  # 측정점 번호 -> CAD 좌표
    raw: bytes = field(repr=False)


def _text_entities(msp):
    for e in msp.query("TEXT MTEXT"):
        if e.dxftype() == "TEXT":
            s = e.dxf.text
            use_align = (e.dxf.halign or e.dxf.valign) and e.dxf.hasattr("align_point")
            p = e.dxf.align_point if use_align else e.dxf.insert
        else:
            s = e.plain_text()
            p = e.dxf.insert
        s = s.strip()
        if s:
            yield e.dxf.layer, s, np.array([p.x, p.y])


def _closed_polygons(msp):
    for e in msp.query("LWPOLYLINE POLYLINE"):
        if e.dxftype() == "LWPOLYLINE":
            pts = np.array([p[:2] for p in e.get_points("xy")], dtype=float)
            closed = e.closed
        else:
            pts = np.array([[v.dxf.location.x, v.dxf.location.y] for v in e.vertices], dtype=float)
            closed = e.is_closed
        if len(pts) >= 4 and np.allclose(pts[0], pts[-1]):
            pts, closed = pts[:-1], True
        if closed and len(pts) >= 3:
            yield e.dxf.layer, pts


def _pick_room_layer(layers: list[str], counts: dict[str, int]) -> str | None:
    if not layers:
        return None
    for name in layers:
        if "ROOM" in name.upper() or "실" in name:
            return name
    return max(layers, key=lambda n: counts[n])


def load_cad(src, room_layer: str | None = None) -> CadPlan:
    """DXF에서 실 경계 폴리라인과 내부 실명 문자, 측정점 라벨(P001...)을 읽는다."""
    _, data = _read_bytes(src)
    doc, _ = recover.read(io.BytesIO(data))
    msp = doc.modelspace()

    polys = list(_closed_polygons(msp))
    texts = list(_text_entities(msp))
    counts: dict[str, int] = {}
    for layer, _ in polys:
        counts[layer] = counts.get(layer, 0) + 1
    poly_layers = sorted(counts)
    room_layer = room_layer if room_layer in counts else _pick_room_layer(poly_layers, counts)

    rooms: list[Room] = []
    room_polys = [pts for layer, pts in polys if layer == room_layer]
    if room_polys:
        paths = [MplPath(p) for p in room_polys]
        areas = [Room("", "", p, p.mean(0)).area for p in room_polys]
        names: list[list[tuple[str, np.ndarray]]] = [[] for _ in room_polys]
        for layer, s, xy in texts:
            if layer != room_layer or POINT_LABEL_RE.match(s):
                continue
            inside = [i for i, path in enumerate(paths) if path.contains_point(xy)]
            if inside:  # 중첩된 경계는 가장 작은 실에 배정
                names[min(inside, key=lambda i: areas[i])].append((s, xy))
        for i, pts in enumerate(room_polys):
            rid = f"R{i + 1:02d}"
            if names[i]:
                name = " / ".join(s for s, _ in names[i])
                label_xy = names[i][0][1]
            else:
                name, label_xy = f"실_{i + 1:02d}", pts.mean(0)
            rooms.append(Room(rid, name, pts, label_xy))

    # 측정점 라벨: 라벨 문자 가장 가까운 원(CIRCLE) 중심을 점 위치로 본다
    circles = np.array([[c.dxf.center.x, c.dxf.center.y] for c in msp.query("CIRCLE")])
    labels: dict[str, np.ndarray] = {}
    for _, s, xy in texts:
        if POINT_LABEL_RE.match(s) and s not in labels:
            if len(circles):
                xy = circles[np.argmin(((circles - xy) ** 2).sum(1))]
            labels[s] = xy

    return CadPlan(rooms, room_layer, poly_layers, labels, data)


# ---------------------------------------------------------------------------
# CAD 좌표 <-> 측량 좌표
# ---------------------------------------------------------------------------
@dataclass
class Transform:
    """측량좌표 = scale * R @ CAD좌표 + translation"""

    scale: float
    rotation: np.ndarray
    translation: np.ndarray
    rms_m: float
    n_points: int
    method: str

    @property
    def rotation_deg(self) -> float:
        return float(np.degrees(np.arctan2(self.rotation[1, 0], self.rotation[0, 0])))

    def to_survey(self, xy: np.ndarray) -> np.ndarray:
        return self.scale * np.asarray(xy) @ self.rotation.T + self.translation

    def to_cad(self, xy: np.ndarray) -> np.ndarray:
        return (np.asarray(xy) - self.translation) @ self.rotation / self.scale

    @classmethod
    def identity(cls, method: str) -> "Transform":
        return cls(1.0, np.eye(2), np.zeros(2), 0.0, 0, method)


def fit_similarity(cad_xy: np.ndarray, survey_xy: np.ndarray) -> Transform:
    """대응점으로 2D 상사변환(축척+회전+이동)을 최소제곱으로 구한다 (Umeyama)."""
    P, Q = np.asarray(cad_xy, float), np.asarray(survey_xy, float)
    mp, mq = P.mean(0), Q.mean(0)
    Pc, Qc = P - mp, Q - mq
    U, S, Vt = np.linalg.svd(Pc.T @ Qc)
    D = np.diag([1.0, np.sign(np.linalg.det(Vt.T @ U.T))])
    R = Vt.T @ D @ U.T
    s = float((S * np.diag(D)).sum() / (Pc**2).sum())
    t = mq - s * R @ mp
    resid = np.linalg.norm(s * P @ R.T + t - Q, axis=1)
    return Transform(s, R, t, float(np.sqrt((resid**2).mean())), len(P), "측정점 라벨 정합")


def estimate_transform(plan: CadPlan, grid: pd.DataFrame) -> Transform:
    """도면의 측정점 라벨과 같은 층 그리드의 점 번호를 맞춰 좌표 변환을 구한다.

    라벨이 부족하면 도면이 이미 측량 좌표인지(점이 실 경계 범위 안에 있는지) 확인한다.
    """
    ids = [pid for pid in grid["point_id"] if pid in plan.labels]
    if len(ids) >= 3:
        g = grid.set_index("point_id").loc[ids]
        cad = np.array([plan.labels[i] for i in ids])
        return fit_similarity(cad, g[["x", "y"]].to_numpy())

    if plan.rooms:
        allpts = np.vstack([r.polygon for r in plan.rooms])
        lo, hi = allpts.min(0), allpts.max(0)
        xy = grid[["x", "y"]].to_numpy()
        if (((xy >= lo) & (xy <= hi)).all(1)).mean() > 0.5:
            return Transform.identity("도면이 측량 좌표와 동일")
    raise ValueError(
        "도면 좌표와 측량 좌표를 맞출 수 없습니다. 도면에 상부층 측정점 라벨(P001 등)이 "
        "3개 이상 있거나, 도면이 측량 좌표로 작성되어 있어야 합니다."
    )


def assign_rooms(cad_xy: np.ndarray, rooms: list[Room]) -> list[Room | None]:
    """각 점이 속한 실 (여러 실에 걸리면 면적이 가장 작은 실)."""
    out: list[Room | None] = [None] * len(cad_xy)
    for room in sorted(rooms, key=lambda r: r.area, reverse=True):
        inside = MplPath(room.polygon).contains_points(cad_xy)
        for i in np.flatnonzero(inside):
            out[i] = room
    return out


# ---------------------------------------------------------------------------
# 두께 산출
# ---------------------------------------------------------------------------
@dataclass
class Settings:
    design_mm: float = 135.0  # 설계 슬래브 두께
    tolerance_mm: float = 0.0  # 허용 부족량: 두께 >= 설계 - 허용 이면 적합 (현장 기준: 135mm 이상만 통과, 0 고정)
    method: str = "nearest"  # nearest: 최근접 대응점 / interpolate: 하부 천장면 보간
    max_match_dist_m: float = 0.2  # 대응점 최대 수평 거리
    max_surface_error_mm: float = 30.0  # 층 기준면 대비 편차가 이보다 크면 제외(물체·돌출물)
    outlier_mad_k: float = 5.0  # 두께 통계 이상치 기준 (0 = 사용 안 함)


@dataclass
class AnalysisResult:
    points: pd.DataFrame
    rooms: pd.DataFrame
    summary: dict
    settings: Settings
    plan: CadPlan | None
    transform: Transform | None


def compute_thickness(upper: pd.DataFrame, lower: pd.DataFrame, s: Settings) -> pd.DataFrame:
    """상부층 각 점에 하부층 천장 Z를 대응시키고 두께와 제외 사유를 계산한다."""
    lower_ok = lower[lower["valid_ceiling"]].reset_index(drop=True)
    if lower_ok.empty:
        raise ValueError("하부층에 유효한 천장 측정값이 없습니다.")
    up_xy = upper[["x", "y"]].to_numpy()
    dist, idx = cKDTree(lower_ok[["x", "y"]].to_numpy()).query(up_xy)
    near = lower_ok.iloc[idx].reset_index(drop=True)

    ceiling = near["ceiling_z"].to_numpy(dtype=float)
    no_surface = np.zeros(len(upper), dtype=bool)
    if s.method == "interpolate":
        # 이상 천장점(설비·돌출물)은 빼고 나머지 점으로 천장면을 만들어 보간한다
        clean = lower_ok[lower_ok["ceiling_error"].abs() <= s.max_surface_error_mm / 1000]
        if len(clean) >= 3:
            clean_xy = clean[["x", "y"]].to_numpy()
            clean_z = clean["ceiling_z"].to_numpy()
            z = LinearNDInterpolator(clean_xy, clean_z)(up_xy)
            # 보간면(볼록 껍질) 바로 밖의 점은 가까운 정상 천장점 값을 쓴다
            cd, ci = cKDTree(clean_xy).query(up_xy)
            fallback = np.isnan(z) & (cd <= s.max_match_dist_m)
            z[fallback] = clean_z[ci[fallback]]
            no_surface = np.isnan(z)
            ceiling = z

    res = pd.DataFrame(
        {
            "point_id": upper["point_id"].to_numpy(),
            "x": upper["x"].to_numpy(),
            "y": upper["y"].to_numpy(),
            "upper_floor_z": upper["floor_z"].to_numpy(),
            "lower_point_id": near["point_id"].to_numpy(),
            "lower_ceiling_z": ceiling,
            "match_dist_m": dist,
            "upper_floor_error_mm": upper["floor_error"].to_numpy() * 1000,
            "lower_ceiling_error_mm": near["ceiling_error"].to_numpy() * 1000,
        }
    )
    res["thickness_mm"] = (res["upper_floor_z"] - res["lower_ceiling_z"]) * 1000

    reasons: list[list[str]] = [[] for _ in range(len(res))]

    def flag(mask, text):
        for i in np.flatnonzero(np.asarray(mask)):
            reasons[i].append(text)

    thr = s.max_surface_error_mm
    flag(~upper["valid_floor"].to_numpy(), "위층 바닥 측정 없음")
    flag((res["match_dist_m"] > s.max_match_dist_m) | no_surface, "아래층에 같은 위치 측정 없음")
    # 기준면보다 높은지 낮은지에 따라 짐작되는 원인이 다르다
    flag(res["upper_floor_error_mm"] > thr, "위층 바닥이 높게 측정(바닥 위 물건 등)")
    flag(res["upper_floor_error_mm"] < -thr, "위층 바닥이 낮게 측정(단차·개구부 등)")
    if s.method != "interpolate":
        flag(res["lower_ceiling_error_mm"] < -thr, "아래층 천장이 낮게 측정(배관·설비 등)")
        flag(res["lower_ceiling_error_mm"] > thr, "아래층 천장이 높게 측정(우물천장·개구부 등)")

    if s.outlier_mad_k > 0:
        ok = np.array([not r for r in reasons])
        t = res.loc[ok, "thickness_mm"]
        if len(t) >= 5:
            med = t.median()
            mad = 1.4826 * (t - med).abs().median()
            if mad > 0:
                flag(ok & ((res["thickness_mm"] - med).abs() > s.outlier_mad_k * mad), "두께가 다른 점들과 크게 다름")

    res["excluded"] = [bool(r) for r in reasons]
    res["exclude_reason"] = [", ".join(r) for r in reasons]
    res["deviation_mm"] = res["thickness_mm"] - s.design_mm
    limit = s.design_mm - s.tolerance_mm
    res["judgement"] = np.where(
        res["excluded"], "제외", np.where(res["thickness_mm"] >= limit, "적합", "미달")
    )
    return res


def summarize_rooms(points: pd.DataFrame, s: Settings) -> pd.DataFrame:
    rows = []
    for room, g in points.groupby("room", sort=False):
        v = g.loc[~g["excluded"], "thickness_mm"]
        mean = v.mean() if len(v) else np.nan
        if not len(v):
            judgement = "판정불가"
        else:
            judgement = "적합" if mean >= s.design_mm - s.tolerance_mm else "미달"
        rows.append(
            {
                "room": room,
                "n_points": len(g),
                "n_valid": len(v),
                "mean_mm": mean,
                "min_mm": v.min() if len(v) else np.nan,
                "max_mm": v.max() if len(v) else np.nan,
                "std_mm": v.std() if len(v) > 1 else np.nan,
                "design_mm": s.design_mm,
                "mean_dev_mm": mean - s.design_mm,
                "n_below": int((g["judgement"] == "미달").sum()),
                "judgement": judgement,
            }
        )
    return pd.DataFrame(rows)


def analyze(
    upper: pd.DataFrame,
    lower: pd.DataFrame,
    plan: CadPlan | None = None,
    settings: Settings | None = None,
    room_names: dict[str, str] | None = None,
) -> AnalysisResult:
    """전체 산출: 대응점 매칭 → 두께 → 이상값 제외 → 실 배정 → 실별 통계."""
    s = settings or Settings()
    pts = compute_thickness(upper, lower, s)

    transform = None
    survey_xy = pts[["x", "y"]].to_numpy()
    if plan is not None:
        transform = estimate_transform(plan, upper)
        cad_xy = transform.to_cad(survey_xy)
        names = room_names or {}
        assigned = assign_rooms(cad_xy, plan.rooms)
        pts["room_id"] = [r.room_id if r else "" for r in assigned]
        pts["room"] = [names.get(r.room_id, r.name) if r else OUTSIDE_ROOM for r in assigned]
    else:
        cad_xy = survey_xy
        pts["room_id"] = ""
        pts["room"] = NO_CAD
    pts["cad_x"], pts["cad_y"] = cad_xy[:, 0], cad_xy[:, 1]

    rooms = summarize_rooms(pts, s)
    valid = pts.loc[~pts["excluded"], "thickness_mm"]
    summary = {
        "n_points": len(pts),
        "n_valid": len(valid),
        "n_excluded": int(pts["excluded"].sum()),
        "n_below": int((pts["judgement"] == "미달").sum()),
        "mean_mm": valid.mean(),
        "median_mm": valid.median(),
        "min_mm": valid.min(),
        "max_mm": valid.max(),
        "std_mm": valid.std(),
        "pass_rate": (pts["judgement"] == "적합").sum() / len(valid) if len(valid) else np.nan,
    }
    return AnalysisResult(pts, rooms, summary, s, plan, transform)
