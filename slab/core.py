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
from scipy.spatial import Delaunay, QhullError, cKDTree

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




# ---------------------------------------------------------------------------
# 실 배정
# ---------------------------------------------------------------------------
def _edge_distance(xy: np.ndarray, polygon: np.ndarray) -> np.ndarray:
    """각 점에서 다각형 테두리까지의 최단 거리."""
    a = polygon
    b = np.roll(polygon, -1, axis=0)
    ab = b - a
    ap = xy[:, None, :] - a[None, :, :]
    t = np.clip((ap * ab).sum(-1) / np.maximum((ab**2).sum(-1), 1e-12), 0, 1)
    proj = a[None] + t[..., None] * ab[None]
    return np.sqrt(((xy[:, None, :] - proj) ** 2).sum(-1)).min(1)


@dataclass
class RoomHit:
    room: Room | None
    note: str = ""  # 경계선 위·경계 중첩 같은 검토 메모
    overlap: bool = False


def locate_rooms(cad_xy: np.ndarray, rooms: list[Room], tol: float = 0.0) -> list[RoomHit]:
    """각 점이 속한 실을 찾는다.

    - 한 실 안에만 있으면 그 실.
    - 여러 실 안에 있으면(경계 중첩) 면적이 가장 작은 실에 넣고 중첩으로 표시한다.
    - 어느 실 안에도 없지만 테두리에서 tol 이내면 '경계선 위'로 보고 가장 작은 실에 넣는다.
    - 그 밖은 영역외(None).
    """
    cad_xy = np.asarray(cad_xy, float).reshape(-1, 2)
    if not rooms or not len(cad_xy):
        return [RoomHit(None) for _ in range(len(cad_xy))]
    inside = np.column_stack([MplPath(r.polygon).contains_points(cad_xy) for r in rooms])
    if tol > 0:
        near = np.column_stack([_edge_distance(cad_xy, r.polygon) <= tol for r in rooms])
    else:
        near = np.zeros_like(inside)
    areas = np.array([r.area for r in rooms])
    strict = inside & ~near  # 테두리 근처는 '경계선 위'로 따로 본다 (벽을 같이 쓰는 두 방은 중첩이 아니다)
    out = []
    for i in range(len(cad_xy)):
        ins = np.flatnonzero(strict[i])
        if len(ins) == 1:
            out.append(RoomHit(rooms[ins[0]]))
        elif len(ins) > 1:
            pick = ins[np.argmin(areas[ins])]
            names = ", ".join(rooms[j].name for j in ins)
            out.append(RoomHit(rooms[pick], f"방 경계 중첩({names})", True))
        else:
            nb = np.flatnonzero(near[i] | inside[i])
            if len(nb):
                pick = nb[np.argmin(areas[nb])]
                out.append(RoomHit(rooms[pick], "방 경계선 위"))
            else:
                out.append(RoomHit(None))
    return out


def assign_rooms(cad_xy: np.ndarray, rooms: list[Room]) -> list[Room | None]:
    """각 점이 속한 실 (여러 실에 걸리면 면적이 가장 작은 실)."""
    return [h.room for h in locate_rooms(cad_xy, rooms)]


def unit_of(name: str, pattern: str, fallback: str) -> str:
    """실명에서 세대 ID를 뽑는다 (예: '101호_거실' → '101호'). 맞지 않으면 fallback."""
    if pattern:
        try:
            m = re.search(pattern, name)
        except re.error:
            m = None
        if m:
            return (m.group(1) if m.groups() else m.group(0)).strip() or fallback
    return fallback


# ---------------------------------------------------------------------------
# 단위
# ---------------------------------------------------------------------------
UNIT_FACTOR = {"m": 1.0, "mm": 0.001}


def detect_units(grid: pd.DataFrame) -> dict:
    """좌표(XY)와 높이(Z)의 단위를 추정한다.

    XY: 이웃한 측정점 간격이 20 넘으면 mm (m 로 20m 간격 격자는 없다고 본다).
    Z: 같은 점의 천장-바닥 높이 차(층고)가 100 넘으면 mm.
    바닥·천장 열의 크기가 수백 배 다르면 한 파일 안에서 단위가 섞인 것으로 본다.
    """
    info = {"xy": "m", "z": "m", "mixed": ""}
    xy = grid[["x", "y"]].dropna().to_numpy(float)
    if len(xy) > 1:
        d, _ = cKDTree(xy).query(xy, k=2)
        if np.median(d[:, 1]) > 20:
            info["xy"] = "mm"
    both = grid[["floor_z", "ceiling_z"]].dropna()
    if len(both):
        f, c = both["floor_z"].abs().median(), both["ceiling_z"].abs().median()
        lo, hi = min(f, c), max(f, c)
        if lo > 1 and hi / lo > 300:
            info["mixed"] = "바닥 높이와 천장 높이 열의 단위가 서로 다른 것 같습니다"
        elif (both["ceiling_z"] - both["floor_z"]).abs().median() > 100:
            info["z"] = "mm"
    return info


def to_meters(grid: pd.DataFrame, xy_unit: str = "auto", z_unit: str = "auto") -> tuple[pd.DataFrame, dict]:
    """표준 그리드의 좌표·높이를 m 로 바꾼다. (변환된 표, 사용한 단위 정보)."""
    found = detect_units(grid)
    if found["mixed"] and z_unit == "auto":
        raise ValueError(found["mixed"] + ". 설정 페이지에서 높이 단위를 직접 지정하거나 파일을 확인해 주세요.")
    used = {"xy": found["xy"] if xy_unit == "auto" else xy_unit,
            "z": found["z"] if z_unit == "auto" else z_unit,
            "auto_xy": xy_unit == "auto", "auto_z": z_unit == "auto"}
    out = grid.copy()
    if used["xy"] != "m":
        out[["x", "y"]] = out[["x", "y"]] * UNIT_FACTOR[used["xy"]]
    if used["z"] != "m":
        k = UNIT_FACTOR[used["z"]]
        for col in ("floor_z", "ceiling_z", "floor_error", "ceiling_error"):
            out[col] = out[col] * k
    return out, used


# ---------------------------------------------------------------------------
# 두께 산출
# ---------------------------------------------------------------------------
@dataclass
class Settings:
    """계산·출력 설정. 판정 기준(design_mm, tolerance_mm)은 현장 기준으로 고정이고 화면에서 바꾸지 않는다.

    나머지 값은 설정 페이지(user_settings.json)에서 바꿀 수 있다. 의미는 slab/settings_store.py 참고.
    """

    design_mm: float = 135.0  # 설계 슬래브 두께
    tolerance_mm: float = 0.0  # 허용 부족량: 두께 >= 설계 - 허용 이면 적합 (현장 기준: 135mm 이상만 통과, 0 고정)
    method: str = "auto"  # auto: 직접 대응 우선→실패 시 TIN / nearest: 직접 대응만 / interpolate: TIN만
    max_match_dist_m: float = 1.2  # 상부 격자 교차점 → 가장 가까운 하부 격자 교차점 최대 수평 거리 (담당자 확인값)
    max_surface_error_mm: float = 30.0  # 층 기준면 대비 편차가 이보다 크면 제외(물체·돌출물)
    outlier_mad_k: float = 5.0  # MAD 이상치 배수 (0 = 사용 안 함)
    # 대응
    allow_reuse: bool = True  # 하부점 하나를 여러 상부점에 써도 되는지 (False: 가까운 쌍부터 1:1 배정)
    tin_max_edge_m: float = 0.0  # TIN 삼각형 가장 긴 변 한도 (0 = 제한 없음)
    tin_cross_room: str = "warn"  # TIN·대응점이 다른 방 점을 쓸 때: warn(메모만) / exclude(제외)
    # 단위
    xy_unit: str = "auto"  # auto / m / mm
    z_unit: str = "auto"  # auto / m / mm
    # 이상치
    outlier_method: str = "mad"  # none / mad / iqr
    outlier_iqr_k: float = 1.5  # IQR 배수
    outlier_side: str = "both"  # both: 두껍고 얇은 쪽 모두 / thick: 두꺼운 쪽만 (얇은 점은 지우지 않음)
    min_thickness_mm: float = 0.0  # 이보다 얇으면 제외 (0 = 사용 안 함)
    max_thickness_mm: float = 0.0  # 이보다 두꺼우면 제외 (0 = 사용 안 함)
    # 실
    unit_pattern: str = r"^(\d+호|코아\d*)"  # 실명에서 세대 ID를 뽑는 정규식 (첫 괄호)
    unit_fallback: str = "공용"  # 세대 ID가 없는 영역(코아 등)의 이름
    overlap_policy: str = "smallest"  # 경계 중첩: smallest(작은 방에 넣고 메모) / exclude(제외)
    boundary_tol_mm: float = 1.0  # 경계선 위로 볼 거리 (측량 좌표 기준)
    # 출력
    excel_layout: str = "simple"  # simple: 포인트 결과+위치도 2시트 / full: 요약·방별 등 전체
    excel_map_scale_pct: int = 40  # 엑셀 위치도 그림 크기(%) - CAD 축척과 무관
    excel_freeze_panes: bool = False  # 엑셀 첫 행 틀고정
    excel_show_pass_rate: bool = False  # 엑셀에 적합률 표시 (앱 화면에는 항상 표시)
    excel_tin_detail: bool = True  # 포인트 결과에 TIN 세 점·가중치 열 펼치기
    report_draft: bool = True  # 보고서·엑셀에 '검토 전 초안' 표시
    report_draft_text: str = "검토 전 참고용 초안 — 실측 기준점 확인 전에는 판정 근거로 쓰지 마세요"


@dataclass
class AnalysisResult:
    points: pd.DataFrame
    rooms: pd.DataFrame
    summary: dict
    settings: Settings
    plan: CadPlan | None
    transform: Transform | None


STATUS_OK, STATUS_EXCLUDED, STATUS_NONE = "산출", "제외", "미산출"
METHOD_DIRECT, METHOD_TIN = "직접 대응", "TIN 보간"
EPS_M = 1e-9  # 허용 거리 경계(예: 정확히 0.2m)가 부동소수 오차로 빠지지 않게
TIN_COLS = [f"tin_{k}{i}" for i in (1, 2, 3) for k in ("id", "x", "y", "z", "w")]


def _greedy_pairs(up_xy: np.ndarray, lo_xy: np.ndarray, max_d: float) -> tuple[np.ndarray, np.ndarray]:
    """가까운 쌍부터 1:1로 배정한다 (전역 최적은 아니지만 결과가 항상 같다)."""
    idx = np.full(len(up_xy), -1)
    dist = np.full(len(up_xy), np.inf)
    pairs = cKDTree(up_xy).sparse_distance_matrix(cKDTree(lo_xy), max_d, output_type="ndarray")
    if len(pairs):
        pairs = np.sort(pairs, order=["v", "i", "j"])
        used_u, used_l = set(), set()
        for i, j, v in zip(pairs["i"], pairs["j"], pairs["v"]):
            if i in used_u or j in used_l:
                continue
            used_u.add(i)
            used_l.add(j)
            idx[i], dist[i] = j, v
    return idx, dist


def _tin(clean: pd.DataFrame, q: np.ndarray, max_edge: float):
    """하부 정상 천장점으로 만든 삼각망(TIN)에서 각 질의점의 천장 Z를 구한다. 외삽하지 않는다.

    반환: (z, 세 꼭짓점 행 번호 (n,3), 가중치 (n,3), 실패 사유 목록)
    """
    n = len(q)
    z = np.full(n, np.nan)
    verts = np.full((n, 3), -1)
    w = np.full((n, 3), np.nan)
    why = [""] * n
    if len(clean) < 3:
        return z, verts, w, ["보간용 하부점 3개 미만"] * n
    xy = clean[["x", "y"]].to_numpy(float)
    try:
        tri = Delaunay(xy)
    except QhullError:
        return z, verts, w, ["하부점이 한 줄로 놓여 삼각형을 만들 수 없음"] * n
    simp = tri.find_simplex(q)
    cz = clean["ceiling_z"].to_numpy(float)
    for i in range(n):
        if simp[i] < 0:
            why[i] = "TIN 삼각형 밖(외삽 안 함)"
            continue
        v = tri.simplices[simp[i]]
        p = xy[v]
        edges = np.linalg.norm(p - np.roll(p, -1, axis=0), axis=1)
        longest = edges.max()
        (ax, ay), (bx, by) = p[1] - p[0], p[2] - p[0]
        area = 0.5 * abs(ax * by - ay * bx)
        if area < 1e-3 * longest**2:
            why[i] = "TIN 퇴화 삼각형(세 점이 거의 한 줄)"
            continue
        if max_edge > 0 and longest > max_edge:
            why[i] = f"TIN 삼각형이 너무 큼(변 {longest:.2f}m > {max_edge:g}m)"
            continue
        T = tri.transform[simp[i]]
        b = T[:2] @ (q[i] - T[2])
        wi = np.array([b[0], b[1], 1 - b.sum()])
        verts[i], w[i] = v, wi
        z[i] = float(wi @ cz[v])
    return z, verts, w, why


def match_points(upper: pd.DataFrame, lower: pd.DataFrame, s: Settings) -> pd.DataFrame:
    """상부층 각 점에 하부층 천장 Z를 대응시킨다 (판정 전 단계).

    auto: 직접 대응(허용 거리 안·정상 천장점)을 먼저 쓰고, 실패하면 TIN 보간, 그래도 안 되면 미산출.
    reasons 열(목록)에 제외 사유, notes 열(목록)에 검토 메모를 담는다.
    """
    lower_ok = lower[lower["valid_ceiling"]].reset_index(drop=True)
    if lower_ok.empty:
        raise ValueError("하부층에 유효한 천장 측정값이 없습니다.")
    n = len(upper)
    up_xy = upper[["x", "y"]].to_numpy(float)
    lo_xy = lower_ok[["x", "y"]].to_numpy(float)
    thr = s.max_surface_error_mm / 1000
    lo_err = lower_ok["ceiling_error"].to_numpy(float)
    lo_clean = np.abs(lo_err) <= thr

    near_d, _ = cKDTree(lo_xy).query(up_xy)
    if s.allow_reuse:
        d_idx = cKDTree(lo_xy).query(up_xy)[1]
        d_dist = near_d.copy()
        d_idx = np.where(d_dist <= s.max_match_dist_m + EPS_M, d_idx, -1)
    else:
        d_idx, d_dist = _greedy_pairs(up_xy, lo_xy, s.max_match_dist_m + EPS_M)
    has_direct = d_idx >= 0

    reasons: list[list[str]] = [[] for _ in range(n)]
    notes: list[list[str]] = [[] for _ in range(n)]
    method = np.array([""] * n, dtype=object)
    ceiling = np.full(n, np.nan)
    ceil_err = np.full(n, np.nan)
    lower_id = np.array([""] * n, dtype=object)
    lower_x = np.full(n, np.nan)
    lower_y = np.full(n, np.nan)
    dist = np.where(has_direct, d_dist, np.nan)
    tin = {c: np.full(n, np.nan) if not c.startswith("tin_id") else np.array([""] * n, dtype=object)
           for c in TIN_COLS}

    def use_direct(i):
        j = d_idx[i]
        method[i] = METHOD_DIRECT
        ceiling[i] = lower_ok.at[j, "ceiling_z"]
        ceil_err[i] = lo_err[j] * 1000
        lower_id[i] = lower_ok.at[j, "point_id"]
        lower_x[i], lower_y[i] = lo_xy[j]

    if s.method == "nearest":
        for i in np.flatnonzero(has_direct):
            use_direct(i)
        tin_need = np.zeros(n, bool)
    elif s.method == "interpolate":
        tin_need = np.ones(n, bool)
    else:  # auto
        good = has_direct & lo_clean[np.maximum(d_idx, 0)]
        for i in np.flatnonzero(good):
            use_direct(i)
        tin_need = ~good
        for i in np.flatnonzero(has_direct & ~good):
            notes[i].append(f"가장 가까운 하부점({lower_ok.at[d_idx[i], 'point_id']})이 기준면을 벗어나 TIN 시도")

    def _no_match_reason(i, tin_why=""):
        if s.method == "interpolate":
            return tin_why
        parts = ["아래층에 같은 위치 측정 없음"]
        if not s.allow_reuse and near_d[i] <= s.max_match_dist_m + EPS_M:
            parts.append("가까운 하부점이 다른 점에 먼저 배정됨(1:1)")
        if tin_why:
            parts.append(tin_why)
        return " · ".join(parts)

    if tin_need.any():
        clean = lower_ok[lo_clean]
        rounded = clean[["x", "y"]].round(4)
        dup = rounded.duplicated()
        if dup.any():
            clean = clean[~dup]
        clean = clean.reset_index(drop=True)
        qi = np.flatnonzero(tin_need)
        z, verts, w, why = _tin(clean, up_xy[qi], s.tin_max_edge_m)
        cxy = clean[["x", "y"]].to_numpy(float)
        cerr = clean["ceiling_error"].to_numpy(float)
        for k, i in enumerate(qi):
            if np.isfinite(z[k]):
                v = verts[k]
                method[i] = METHOD_TIN
                ceiling[i] = z[k]
                ceil_err[i] = float(w[k] @ cerr[v]) * 1000
                lower_id[i] = "/".join(clean["point_id"].iloc[v])
                dist[i] = float(np.linalg.norm(cxy[v] - up_xy[i], axis=1).min())
                for m in range(3):
                    tin[f"tin_id{m + 1}"][i] = clean.at[v[m], "point_id"]
                    tin[f"tin_x{m + 1}"][i], tin[f"tin_y{m + 1}"][i] = cxy[v[m]]
                    tin[f"tin_z{m + 1}"][i] = clean.at[v[m], "ceiling_z"]
                    tin[f"tin_w{m + 1}"][i] = w[k][m]
            elif has_direct[i] and s.method == "auto":
                # 직접 대응 점은 있으나 이상 천장점이고 TIN 도 안 되면, 그 값으로 계산하고 이상값으로 제외
                use_direct(i)
                notes[i].append(why[k])
            else:
                reasons[i].append(_no_match_reason(i, why[k]))
    elif s.method == "nearest":
        for i in np.flatnonzero(~has_direct):
            reasons[i].append(_no_match_reason(i))

    res = pd.DataFrame(
        {
            "point_id": upper["point_id"].to_numpy(),
            "x": up_xy[:, 0],
            "y": up_xy[:, 1],
            "upper_floor_z": upper["floor_z"].to_numpy(float),
            "lower_point_id": lower_id,
            "lower_ceiling_z": ceiling,
            "calc_method": method,
            "match_dist_m": dist,
            "nearest_dist_m": near_d,
            "lower_x": lower_x,
            "lower_y": lower_y,
            "upper_floor_error_mm": upper["floor_error"].to_numpy(float) * 1000,
            "lower_ceiling_error_mm": ceil_err,
            **tin,
        }
    )
    # 부동소수 잡음(예: 134.99999999)이 135mm 판정을 뒤집지 않도록 1nm 단위로 반올림
    res["thickness_mm"] = ((res["upper_floor_z"] - res["lower_ceiling_z"]) * 1000).round(6)

    no_floor = ~upper["valid_floor"].to_numpy()
    for i in np.flatnonzero(no_floor):
        reasons[i].insert(0, "위층 바닥 측정 없음")
    res.loc[no_floor, "thickness_mm"] = np.nan
    res["no_value"] = res["thickness_mm"].isna() | np.array([bool(r) for r in reasons])
    res.loc[res["no_value"], "thickness_mm"] = np.nan

    # 같은 좌표에 상부점이 여러 개
    dup_up = pd.DataFrame(up_xy).round(4).duplicated(keep=False).to_numpy()
    for i in np.flatnonzero(dup_up):
        notes[i].append("같은 좌표의 위층 점이 여러 개")

    flags = [[] for _ in range(n)]

    def flag(mask, text):
        for i in np.flatnonzero(np.asarray(mask) & ~res["no_value"].to_numpy()):
            flags[i].append(text)

    t = s.max_surface_error_mm
    flag(res["upper_floor_error_mm"] > t, "위층 바닥이 높게 측정(바닥 위 물건 등)")
    flag(res["upper_floor_error_mm"] < -t, "위층 바닥이 낮게 측정(단차·개구부 등)")
    direct = (res["calc_method"] == METHOD_DIRECT).to_numpy()
    flag(direct & (res["lower_ceiling_error_mm"] < -t), "아래층 천장이 낮게 측정(배관·설비 등)")
    flag(direct & (res["lower_ceiling_error_mm"] > t), "아래층 천장이 높게 측정(우물천장·개구부 등)")

    res["reasons"] = [r + f for r, f in zip(reasons, flags)]
    res["notes"] = notes
    return res


def _outlier_mask(t: pd.Series, s: Settings) -> pd.Series:
    """유효 두께 중 통계 이상치. 얇은 쪽을 지우지 않는 설정이면 두꺼운 쪽만."""
    out = pd.Series(False, index=t.index)
    if len(t) < 5 or s.outlier_method == "none":
        return out
    if s.outlier_method == "iqr":
        if s.outlier_iqr_k <= 0:
            return out
        q1, q3 = t.quantile(0.25), t.quantile(0.75)
        iqr = q3 - q1
        if iqr <= 0:
            return out
        hi, lo = t > q3 + s.outlier_iqr_k * iqr, t < q1 - s.outlier_iqr_k * iqr
    else:
        if s.outlier_mad_k <= 0:
            return out
        med = t.median()
        mad = 1.4826 * (t - med).abs().median()
        if mad <= 0:
            return out
        hi = t - med > s.outlier_mad_k * mad
        lo = med - t > s.outlier_mad_k * mad
    return hi | lo if s.outlier_side == "both" else hi


def finalize_points(res: pd.DataFrame, s: Settings) -> pd.DataFrame:
    """이상치·범위 제외를 더하고 상태(산출/제외/미산출)와 판정을 정한다."""
    res = res.copy()
    reasons = [list(r) for r in res["reasons"]]
    t = res["thickness_mm"]

    def flag(mask, text):
        for i in np.flatnonzero(np.asarray(mask)):
            reasons[i].append(text)

    if s.min_thickness_mm > 0:
        flag(t < s.min_thickness_mm, f"두께가 하한({s.min_thickness_mm:g}mm)보다 얇음")
    if s.max_thickness_mm > 0:
        flag(t > s.max_thickness_mm, f"두께가 상한({s.max_thickness_mm:g}mm)보다 두꺼움")
    ok = np.array([not r for r in reasons]) & t.notna().to_numpy()
    if "in_room" in res:
        ok &= res["in_room"].to_numpy()  # 영역외 점은 이상치 통계에 넣지 않는다
    mask = _outlier_mask(t[ok], s).reindex(res.index, fill_value=False)
    flag(mask, "두께가 다른 점들과 크게 다름")

    res["status"] = np.where(res["no_value"], STATUS_NONE,
                             np.where([bool(r) for r in reasons], STATUS_EXCLUDED, STATUS_OK))
    res["excluded"] = res["status"] != STATUS_OK
    res["exclude_reason"] = [", ".join(r) for r in reasons]
    res["review_note"] = [", ".join(dict.fromkeys(n)) for n in res["notes"]]
    res["deviation_mm"] = res["thickness_mm"] - s.design_mm
    limit = s.design_mm - s.tolerance_mm
    res["judgement"] = np.where(
        res["status"] == STATUS_NONE, STATUS_NONE,
        np.where(res["status"] == STATUS_EXCLUDED, "제외",
                 np.where(res["thickness_mm"] >= limit, "적합", "미달")))
    return res.drop(columns=["reasons", "notes"])


def compute_thickness(upper: pd.DataFrame, lower: pd.DataFrame, s: Settings) -> pd.DataFrame:
    """상부층 각 점의 두께와 상태를 계산한다 (도면 없이)."""
    return finalize_points(match_points(upper, lower, s), s)


def summarize_rooms(points: pd.DataFrame, s: Settings) -> pd.DataFrame:
    """고유 실 ID 별 통계. 이름이 같은 다른 실은 합치지 않는다. 영역외 점은 넣지 않는다."""
    rows = []
    pts = points[points["in_room"]] if "in_room" in points else points
    for rid, g in pts.groupby("room_id", sort=False):
        v = g.loc[~g["excluded"], "thickness_mm"]
        mean = round(float(v.mean()), 6) if len(v) else np.nan
        if not len(v):
            judgement = "판정불가"
        else:
            judgement = "적합" if mean >= s.design_mm - s.tolerance_mm else "미달"
        rows.append(
            {
                "room_id": rid,
                "unit": g["unit"].iloc[0] if "unit" in g else "",
                "room": g["room"].iloc[0],
                "n_points": len(g),
                "n_valid": len(v),
                "n_excluded": int((g["status"] == STATUS_EXCLUDED).sum()),
                "n_no_value": int((g["status"] == STATUS_NONE).sum()),
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
    cols = ["room_id", "unit", "room", "n_points", "n_valid", "n_excluded", "n_no_value", "mean_mm", "min_mm",
            "max_mm", "std_mm", "design_mm", "mean_dev_mm", "n_below", "judgement"]
    return pd.DataFrame(rows, columns=cols)


def analyze(
    upper: pd.DataFrame,
    lower: pd.DataFrame,
    plan: CadPlan | None = None,
    settings: Settings | None = None,
    room_names: dict[str, str] | None = None,
) -> AnalysisResult:
    """전체 산출: 단위 확인 → 대응(직접→TIN) → 실 배정 → 제외·판정 → 실별 통계."""
    s = settings or Settings()
    upper, u_units = to_meters(upper, s.xy_unit, s.z_unit)
    lower, l_units = to_meters(lower, s.xy_unit, s.z_unit)
    warnings = []
    if (u_units["xy"], u_units["z"]) != (l_units["xy"], l_units["z"]):
        warnings.append(f"위층(XY {u_units['xy']}, Z {u_units['z']})과 아래층(XY {l_units['xy']}, "
                        f"Z {l_units['z']}) 파일의 단위가 다릅니다. 모두 m 로 바꿔 계산했습니다.")
    pts = match_points(upper, lower, s)

    transform = None
    survey_xy = pts[["x", "y"]].to_numpy()
    if plan is not None:
        transform = estimate_transform(plan, upper)
        cad_xy = transform.to_cad(survey_xy)
        tol = s.boundary_tol_mm / 1000 / transform.scale
        names = room_names or {}
        hits = locate_rooms(cad_xy, plan.rooms, tol)
        pts["room_id"] = [h.room.room_id if h.room else "" for h in hits]
        pts["room"] = [names.get(h.room.room_id, h.room.name) if h.room else OUTSIDE_ROOM for h in hits]
        pts["in_room"] = [h.room is not None for h in hits]
        reasons, notes = pts["reasons"].tolist(), pts["notes"].tolist()
        for i, h in enumerate(hits):
            if h.note:
                notes[i] = notes[i] + [h.note]
            if h.overlap and s.overlap_policy == "exclude" and not pts.at[i, "no_value"]:
                reasons[i] = reasons[i] + ["방 경계 중첩"]

        # 대응점·TIN 꼭짓점이 다른 방에 있으면 경계(벽)를 넘었을 수 있다
        by_id = {r.room_id: r for r in plan.rooms}
        for i in range(len(pts)):
            rid = pts.at[i, "room_id"]
            if not rid:
                continue
            if pts.at[i, "calc_method"] == METHOD_TIN:
                vx = np.array([[pts.at[i, f"tin_x{k}"], pts.at[i, f"tin_y{k}"]] for k in (1, 2, 3)])
            elif pts.at[i, "calc_method"] == METHOD_DIRECT:
                vx = np.array([[pts.at[i, "lower_x"], pts.at[i, "lower_y"]]])
            else:
                continue
            vin = MplPath(by_id[rid].polygon).contains_points(transform.to_cad(vx), radius=0)
            near = _edge_distance(transform.to_cad(vx), by_id[rid].polygon) <= tol
            if not (vin | near).all():
                text = "사용한 하부점이 다른 방에 있음(경계 넘음 가능)"
                notes[i] = notes[i] + [text]
                if s.tin_cross_room == "exclude" and not pts.at[i, "no_value"]:
                    reasons[i] = reasons[i] + [text]
        pts["reasons"], pts["notes"] = reasons, notes
    else:
        cad_xy = survey_xy
        pts["room_id"] = "ALL"
        pts["room"] = NO_CAD
        pts["in_room"] = True
    pts["unit"] = [unit_of(r, s.unit_pattern, s.unit_fallback) if inr else ""
                   for r, inr in zip(pts["room"], pts["in_room"])]
    pts["cad_x"], pts["cad_y"] = cad_xy[:, 0], cad_xy[:, 1]
    pts = finalize_points(pts, s)

    rooms = summarize_rooms(pts, s)
    inside = pts[pts["in_room"]]
    valid = inside.loc[~inside["excluded"], "thickness_mm"]
    summary = {
        "n_points": len(pts),
        "n_valid": len(valid),
        "n_excluded": int((inside["status"] == STATUS_EXCLUDED).sum()),
        "n_no_value": int((inside["status"] == STATUS_NONE).sum()),
        "n_outside": int((~pts["in_room"]).sum()),
        "n_direct": int((inside.loc[~inside["excluded"], "calc_method"] == METHOD_DIRECT).sum()),
        "n_tin": int((inside.loc[~inside["excluded"], "calc_method"] == METHOD_TIN).sum()),
        "n_below": int((inside["judgement"] == "미달").sum()),
        "mean_mm": valid.mean(),
        "median_mm": valid.median(),
        "min_mm": valid.min(),
        "max_mm": valid.max(),
        "std_mm": valid.std(),
        "pass_rate": (inside["judgement"] == "적합").sum() / len(valid) if len(valid) else np.nan,
        "units": {"upper": u_units, "lower": l_units},
        "warnings": warnings,
    }
    return AnalysisResult(pts, rooms, summary, s, plan, transform)
