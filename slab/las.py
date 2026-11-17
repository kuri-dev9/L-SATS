"""LAS/LAZ 점군(층마다 한 파일, 측량 좌표) → 모든 층에 같은 격자를 놓고 바닥·천장 높이를 뽑는다.

결과는 두께 분석에 그대로 쓰는 grid_analysis_floor_level_<층>.csv 형식이다. 원본이 1GB 넘어도 조금씩 나눠 읽는다.

1) 층마다 한 번 훑기: 높이 분포에서 바닥면·천장면 높이(가장 많이 몰린 두 수평면)를 찾고,
   벽 높이의 점으로 건물 축 방향(측량 좌표에서 기울어진 각도)을 찾는다.
2) 격자 정하기: 모든 층에 같은 격자(건물 축 방향, 간격 1.5 m 기본)를 놓는다. 격자 정의는 grid.json 에 저장해
   다음에 다른 층을 변환해도 같은 격자를 쓴다 (매층 고정).
3) 층마다 다시 훑기: 격자점마다 가로·세로 window 안의 점 중 바닥면 근처(±band) 점이 가장 많이 몰린 높이를 바닥 Z,
   천장면 근처에서 같은 방법으로 천장 Z 로 한다 (벽·가구의 세로 점에 덜 끌려간다). 바닥 위 물건·천장 설비가 섞이면 기준면 편차(floor_error 등)가 커져
   두께 분석에서 'Z값 확인 필요'로 걸러진다.

결과 CSV 에는 격자 정의(grid_angle_deg, grid_origin_x/y)를 함께 넣어, 두께 분석이 도면 없이도 건물 축에 맞춰
정렬해 그린다 (측량 좌표는 기울어져 있으므로).

명령줄: python -m slab.las <LAS 폴더> [--spacing 1.5] [--out 출력 폴더] [--new-grid]
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import pandas as pd

LAS_TYPES = (".las", ".laz")
GRID_FILE = "grid.json"
OUT_DIR = "LSATS_grid"
CSV_NAME = "grid_analysis_floor_level_{}.csv"
NOISE_CLASSES = (7, 18)  # LAS 분류의 잡음 점
CHUNK = 2_000_000
SAMPLE_MAX = 400_000  # 1차 훑기에서 벽 방향을 찾을 때 쓰는 최대 점 수


@dataclass
class LasParams:
    """변환 설정. 화면에서는 설정(Settings 의 las_*)에서 만든다 (from_settings)."""

    spacing_m: float = 1.5  # 격자 간격
    window_m: float = 0.4  # 격자점 둘레에서 점을 모으는 정사각형 한 변
    band_m: float = 0.3  # 바닥·천장 기준면에서 이 거리 안의 점만 그 면으로 본다
    min_points: int = 10  # 이보다 적으면 그 면은 측정 없음

    @classmethod
    def from_settings(cls, s) -> "LasParams":
        return cls(s.las_spacing_m, s.las_window_m, s.las_band_m, s.las_min_points)


@dataclass
class GridSpec:
    """모든 층에 같은 격자. 측량 = R(angle) @ 건물축 좌표 + origin. 격자점은 건물축 좌표 ((i+½)·s, (j+½)·s)."""

    angle_deg: float
    origin_x: float
    origin_y: float
    spacing_m: float
    nx: int
    ny: int

    def rot(self) -> np.ndarray:
        a = np.radians(self.angle_deg)
        return np.array([[np.cos(a), -np.sin(a)], [np.sin(a), np.cos(a)]])

    def to_local(self, x: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        a = np.radians(self.angle_deg)
        dx, dy = x - self.origin_x, y - self.origin_y
        return dx * np.cos(a) + dy * np.sin(a), -dx * np.sin(a) + dy * np.cos(a)

    def nodes(self) -> pd.DataFrame:
        j, i = np.mgrid[0:self.ny, 0:self.nx]
        lx, ly = (i.ravel() + 0.5) * self.spacing_m, (j.ravel() + 0.5) * self.spacing_m
        sx, sy = (self.rot() @ np.vstack([lx, ly])) + np.array([[self.origin_x], [self.origin_y]])
        return pd.DataFrame({"col": i.ravel(), "row": j.ravel(), "local_x": lx, "local_y": ly, "x": sx, "y": sy})

    def save(self, path: Path) -> None:
        path.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> "GridSpec | None":
        try:
            d = json.loads(path.read_text(encoding="utf-8"))
            return cls(**{k: d[k] for k in ("angle_deg", "origin_x", "origin_y", "spacing_m", "nx", "ny")})
        except (OSError, ValueError, KeyError, TypeError):
            return None


@dataclass
class FloorScan:
    """1차 훑기 결과."""

    path: Path
    label: str
    n_points: int
    floor_level: float  # 바닥면 높이 (m)
    ceiling_level: float  # 천장면 높이 (m)
    angle_deg: float  # 건물 축 방향 (−45~45°)
    lo: np.ndarray  # 바닥면 점의 XY 범위 (측량)
    hi: np.ndarray
    xy_sample: np.ndarray  # 바닥면 점 표본 (격자 범위 정하기용)


# ------------------------------------------------------------------ 읽기
def _laspy():
    try:
        import laspy
    except ImportError as e:  # pragma: no cover - 설치 안내
        raise RuntimeError("LAS 를 읽는 패키지(laspy)가 없습니다. 전체 ZIP 을 새로 받거나 "
                           "pip install \"laspy[lazrs]\" 로 설치하세요.") from e
    return laspy


def find_las(folder: Path) -> list[Path]:
    return sorted(p for p in Path(folder).iterdir() if p.is_file() and p.suffix.lower() in LAS_TYPES)


def las_info(path: Path) -> dict:
    """머리글만 읽는다 (빠름)."""
    laspy = _laspy()
    with laspy.open(path) as f:
        h = f.header
        return {"file": Path(path).name, "size_mb": round(Path(path).stat().st_size / 2**20, 1),
                "points": int(h.point_count), "version": str(h.version), "format": int(h.point_format.id),
                "x": (float(h.mins[0]), float(h.maxs[0])), "y": (float(h.mins[1]), float(h.maxs[1])),
                "z": (float(h.mins[2]), float(h.maxs[2])), "scale": tuple(float(v) for v in h.scales)}


def iter_points(path: Path, chunk: int = CHUNK):
    """(x, y, z) m 배열을 조금씩. 잡음 분류(7, 18) 점은 뺀다."""
    laspy = _laspy()
    with laspy.open(path) as f:
        has_cls = "classification" in f.header.point_format.dimension_names
        for pts in f.chunk_iterator(chunk):
            x, y, z = np.asarray(pts.x, float), np.asarray(pts.y, float), np.asarray(pts.z, float)
            if has_cls:
                keep = ~np.isin(np.asarray(pts.classification), NOISE_CLASSES)
                x, y, z = x[keep], y[keep], z[keep]
            yield x, y, z


# ------------------------------------------------------------------ 1차 훑기
def find_levels(z_hist: np.ndarray, z0: float, bin_m: float) -> tuple[float, float]:
    """높이 분포에서 바닥면·천장면. 층고 1.8~4.5 m 로 떨어진 두 봉우리 중 점이 가장 많은 쌍."""
    k = np.ones(5) / 5
    h = np.convolve(z_hist, k, mode="same")
    peaks = [i for i in range(1, len(h) - 1) if h[i] >= h[i - 1] and h[i] >= h[i + 1] and h[i] > 0]
    peaks = sorted(peaks, key=lambda i: -h[i])[:15]
    best, score = None, -1.0
    for a in peaks:
        for b in peaks:
            gap = (b - a) * bin_m
            if 1.8 <= gap <= 4.5 and h[a] + h[b] > score:
                best, score = (a, b), h[a] + h[b]
    if best is None:  # 수평면을 못 찾으면 아래·위 5% 높이
        c = np.cumsum(z_hist) / max(z_hist.sum(), 1)
        best = (int(np.searchsorted(c, 0.05)), int(np.searchsorted(c, 0.95)))

    def refine(i):  # 봉우리 둘레 가중 평균 (1 cm 칸보다 정밀하게)
        lo, hi = max(i - 2, 0), min(i + 3, len(z_hist))
        w = z_hist[lo:hi]
        return z0 + (np.arange(lo, hi) + 0.5) @ w / max(w.sum(), 1) * bin_m

    return float(refine(best[0])), float(refine(best[1]))


def find_axis(xy: np.ndarray, bin_m: float = 0.05) -> float:
    """벽 점들을 여러 각도로 돌려 X·Y 로 투영했을 때 가장 뾰족해지는 각도 (건물 축). −45~45°."""
    if len(xy) < 100:
        return 0.0
    xy = xy - xy.mean(0)

    def sharp(deg):
        a = np.radians(deg)
        u = xy[:, 0] * np.cos(a) + xy[:, 1] * np.sin(a)
        v = -xy[:, 0] * np.sin(a) + xy[:, 1] * np.cos(a)
        s = 0.0
        for w in (u, v):
            c = np.bincount(((w - w.min()) / bin_m).astype(int)).astype(float)
            s += (c ** 2).sum()
        return s

    coarse = np.arange(-45, 45, 1.0)
    best = coarse[np.argmax([sharp(a) for a in coarse])]
    fine = np.arange(best - 1, best + 1.001, 0.05)
    a = float(fine[np.argmax([sharp(a) for a in fine])])
    return ((a + 45) % 90) - 45


def scan_floor(path: Path, label: str, progress=None) -> FloorScan:
    """1차 훑기: 높이 분포 → 바닥·천장 높이, 벽 점 → 건물 축, 바닥면 점 → 범위."""
    info = las_info(path)
    z0, z1 = info["z"]
    bin_m = 0.01
    nb = max(int((z1 - z0) / bin_m) + 2, 2)
    hist = np.zeros(nb)
    rng = np.random.default_rng(0)
    keep_p = min(1.0, SAMPLE_MAX * 3 / max(info["points"], 1))
    samp = []
    done = 0
    for x, y, z in iter_points(path):
        hist += np.bincount(((z - z0) / bin_m).astype(int).clip(0, nb - 1), minlength=nb)
        m = rng.random(len(x)) < keep_p
        samp.append(np.column_stack([x[m], y[m], z[m]]))
        done += len(x)
        if progress:
            progress(min(done / max(info["points"], 1), 1.0))
    s = np.vstack(samp) if samp else np.zeros((0, 3))
    fl, cl = find_levels(hist, z0, bin_m)
    walls = s[(s[:, 2] > fl + 0.5) & (s[:, 2] < cl - 0.5)][:SAMPLE_MAX, :2]
    floor_pts = s[np.abs(s[:, 2] - fl) < 0.15][:, :2]
    if not len(floor_pts):
        floor_pts = s[:, :2]
    lo, hi = np.percentile(floor_pts, 0.2, axis=0), np.percentile(floor_pts, 99.8, axis=0)
    return FloorScan(Path(path), label, info["points"], fl, cl, find_axis(walls), lo, hi, floor_pts[:SAMPLE_MAX])


# ------------------------------------------------------------------ 격자
def make_grid(scans: list[FloorScan], spacing_m: float) -> GridSpec:
    """모든 층의 바닥면을 덮는 격자. 방향은 층별 건물 축의 중앙값, 원점은 건물 축으로 돌린 범위의 왼쪽 아래."""
    angles = np.array([s.angle_deg for s in scans])
    ref = angles[0]
    angles = ref + ((angles - ref + 45) % 90 - 45)  # 90° 차이는 같은 축으로
    angle = float(np.round(np.median(angles), 2))
    a = np.radians(angle)
    pts = np.vstack([s.xy_sample for s in scans])
    u = pts[:, 0] * np.cos(a) + pts[:, 1] * np.sin(a)
    v = -pts[:, 0] * np.sin(a) + pts[:, 1] * np.cos(a)
    u0, u1 = np.percentile(u, [0.2, 99.8])
    v0, v1 = np.percentile(v, [0.2, 99.8])
    u0, v0 = np.floor(u0 / spacing_m) * spacing_m, np.floor(v0 / spacing_m) * spacing_m
    nx = int(np.ceil((u1 - u0) / spacing_m))
    ny = int(np.ceil((v1 - v0) / spacing_m))
    ox, oy = np.array([[np.cos(a), -np.sin(a)], [np.sin(a), np.cos(a)]]) @ np.array([u0, v0])
    return GridSpec(angle, round(float(ox), 4), round(float(oy), 4), spacing_m, max(nx, 1), max(ny, 1))


# ------------------------------------------------------------------ 2차 훑기
def sample_floor(scan: FloorScan, grid: GridSpec, p: LasParams, progress=None) -> pd.DataFrame:
    """격자점마다 바닥·천장 높이. grid_analysis_floor_level_*.csv 와 같은 열 + 격자 정의 열."""
    s, half = grid.spacing_m, p.window_m / 2
    nn = grid.nx * grid.ny
    count = np.zeros(nn, int)
    parts_f, parts_c = [], []  # (격자점 번호, z)
    done = 0
    for x, y, z in iter_points(scan.path):
        lx, ly = grid.to_local(x, y)
        i, j = np.floor(lx / s).astype(int), np.floor(ly / s).astype(int)
        inside = (i >= 0) & (i < grid.nx) & (j >= 0) & (j < grid.ny)
        inside &= (np.abs(lx - (i + 0.5) * s) <= half) & (np.abs(ly - (j + 0.5) * s) <= half)
        k = (j * grid.nx + i)[inside]
        zz = z[inside]
        count += np.bincount(k, minlength=nn)
        fm = np.abs(zz - scan.floor_level) <= p.band_m
        cm = np.abs(zz - scan.ceiling_level) <= p.band_m
        parts_f.append(np.column_stack([k[fm], zz[fm]]))
        parts_c.append(np.column_stack([k[cm], zz[cm]]))
        done += len(x)
        if progress:
            progress(min(done / max(scan.n_points, 1), 1.0))

    def stats(parts):
        """격자점마다 면 높이: 5 mm 칸으로 나눠 점이 가장 많이 몰린 높이(±10 mm)의 평균.
        벽·가구처럼 세로로 퍼진 점이 섞여도 수평면 높이만 잡는다 (중앙값보다 덜 끌려간다)."""
        a = np.vstack(parts) if parts else np.zeros((0, 2))
        df = pd.DataFrame({"k": a[:, 0].astype(int), "z": a[:, 1]})
        if df.empty:
            return pd.DataFrame(columns=["med", "q05", "n"])
        df["b"] = np.floor(df["z"] / 0.005).astype(np.int64)
        cnt = df.groupby(["k", "b"]).size().rename("c").reset_index()
        top = cnt.loc[cnt.groupby("k")["c"].idxmax(), ["k", "b"]].rename(columns={"b": "bt"})
        df = df.merge(top, on="k")
        near = df[(df["b"] - df["bt"]).abs() <= 2]
        g = df.groupby("k")["z"]
        return pd.DataFrame({"med": near.groupby("k")["z"].mean(), "q05": g.quantile(0.05), "n": g.size()})

    fs, cs = stats(parts_f), stats(parts_c)
    nodes = grid.nodes()
    nodes["k"] = np.arange(nn)
    nodes["buffer_points"] = count
    nodes = nodes[nodes["buffer_points"] > 0].copy()  # 스캔 범위 밖 격자점은 뺀다
    f, c = fs.reindex(nodes["k"]), cs.reindex(nodes["k"])
    nf, nc = f["n"].fillna(0).to_numpy(), c["n"].fillna(0).to_numpy()
    floor_z = np.where(nf >= p.min_points, f["med"].to_numpy(), np.nan)
    ceil_z = np.where(nc >= p.min_points, c["med"].to_numpy(), np.nan)
    gf, gh = scan.floor_level, scan.ceiling_level
    out = pd.DataFrame({
        "point_number": np.arange(1, len(nodes) + 1),
        "point_id": [f"G{r + 1:03d}-{c_ + 1:03d}" for r, c_ in zip(nodes["row"], nodes["col"])],
        "x": nodes["x"].round(3).to_numpy(), "y": nodes["y"].round(3).to_numpy(),
        "Global_Floor_m": round(gf, 3), "Global_Floor_mm": round(gf * 1000, 3),
        "Global_Height_m": round(gh, 3), "Global_Height_mm": round(gh * 1000, 3),
        "floor_z": np.round(floor_z, 4), "floor_z_min": np.round(np.where(nf >= p.min_points, f["q05"], np.nan), 4),
        "ceiling_z": np.round(ceil_z, 4),
        "height": np.round(ceil_z - floor_z, 4), "height_mm": np.round((ceil_z - floor_z) * 1000, 1),
        "floor_error": np.round(floor_z - gf, 4), "ceiling_error": np.round(ceil_z - gh, 4),
        "buffer_points": nodes["buffer_points"].to_numpy(),
        "is_empty": False, "has_floor": nf >= p.min_points, "has_ceiling": nc >= p.min_points,
        "floor_points": nf.astype(int), "ceiling_points": nc.astype(int),
        "grid_row": nodes["row"].to_numpy() + 1, "grid_col": nodes["col"].to_numpy() + 1,
        "local_x": nodes["local_x"].round(3).to_numpy(), "local_y": nodes["local_y"].round(3).to_numpy(),
        "grid_angle_deg": grid.angle_deg, "grid_origin_x": grid.origin_x, "grid_origin_y": grid.origin_y,
        "grid_spacing_m": grid.spacing_m,
    })
    return out


# ------------------------------------------------------------------ 한꺼번에
def floor_label(path: Path) -> str:
    from .batch import guess_floor

    return guess_floor(path.name) or path.stem


def convert(files: list[Path], out_dir: Path, params: LasParams | None = None, labels: dict | None = None,
            new_grid: bool = False, progress=None) -> tuple[GridSpec, pd.DataFrame, list[Path]]:
    """LAS 들을 격자 CSV 로. progress(전체 진행 0~1, 글) 로 진행을 알린다. (격자, 층별 요약, CSV 경로들)."""
    p = params or LasParams()
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    labels = labels or {}
    n = len(files)
    total = 2 * n

    def step(k, msg):
        return (lambda f: progress((k + f) / total, msg)) if progress else None

    scans = []
    for k, f in enumerate(files):
        lab = labels.get(f.name) or floor_label(f)
        scans.append(scan_floor(f, lab, step(k, f"{lab}: 바닥·천장 높이와 건물 방향 찾는 중")))
    grid = None if new_grid else GridSpec.load(out_dir / GRID_FILE)
    if grid is None or abs(grid.spacing_m - p.spacing_m) > 1e-9:
        grid = make_grid(scans, p.spacing_m)
        grid.save(out_dir / GRID_FILE)
    rows, paths = [], []
    for k, s in enumerate(scans):
        df = sample_floor(s, grid, p, step(n + k, f"{s.label}: 격자점 높이 뽑는 중"))
        path = out_dir / CSV_NAME.format(s.label)
        df.to_csv(path, index=False, encoding="utf-8")
        paths.append(path)
        rows.append({"층": s.label, "LAS 파일": s.path.name, "점 수": s.n_points,
                     "바닥면 높이(m)": round(s.floor_level, 3), "천장면 높이(m)": round(s.ceiling_level, 3),
                     "층고(m)": round(s.ceiling_level - s.floor_level, 3), "건물 축(°)": round(s.angle_deg, 2),
                     "격자점": len(df), "바닥 측정": int(df["has_floor"].sum()),
                     "천장 측정": int(df["has_ceiling"].sum()), "CSV": path.name})
    if progress:
        progress(1.0, "완료")
    return grid, pd.DataFrame(rows), paths


def find_las_files(folder: Path, recursive: bool = False) -> list[Path]:
    """폴더 안의 LAS/LAZ (확장자 대소문자 무시). recursive 면 하위 폴더까지 (결과 폴더 LSATS_grid 는 뺀다)."""
    folder = Path(folder)
    if not recursive:
        return find_las(folder)
    out = [p for p in folder.rglob("*") if p.is_file() and p.suffix.lower() in LAS_TYPES and OUT_DIR not in p.parts]
    return sorted(out)


def export_results(csv_paths: list[Path], labels: list[str], mode: str = "floor", fmt: str = "csv",
                   summary: pd.DataFrame | None = None) -> dict[str, bytes]:
    """변환 결과를 저장용 파일로. mode: floor(층마다 파일) / single(한 파일). fmt: csv / xlsx.

    한 파일 CSV 는 맨 앞에 '층' 열을 붙여 모든 층을 이어 붙이고, 한 파일 엑셀은 '요약' 시트 + 층마다 시트.
    CSV 는 엑셀에서 한글이 깨지지 않게 UTF-8 BOM 으로 쓴다. {파일 이름: 내용}.
    """
    import io

    frames = [pd.read_csv(p) for p in csv_paths]
    out: dict[str, bytes] = {}
    if mode == "single":
        if fmt == "csv":
            allf = pd.concat([f.assign(**{"층": lab})[["층", *f.columns]] for f, lab in zip(frames, labels)],
                             ignore_index=True)
            out["LAS_격자높이_전체.csv"] = allf.to_csv(index=False).encode("utf-8-sig")
        else:
            buf = io.BytesIO()
            with pd.ExcelWriter(buf, engine="openpyxl") as xw:
                if summary is not None and not summary.empty:
                    summary.to_excel(xw, sheet_name="요약", index=False)
                for f, lab in zip(frames, labels):
                    f.to_excel(xw, sheet_name=_sheet_name(lab), index=False)
            out["LAS_격자높이_전체.xlsx"] = buf.getvalue()
    else:
        for f, lab in zip(frames, labels):
            if fmt == "csv":
                out[CSV_NAME.format(lab)] = f.to_csv(index=False).encode("utf-8-sig")
            else:
                buf = io.BytesIO()
                with pd.ExcelWriter(buf, engine="openpyxl") as xw:
                    f.to_excel(xw, sheet_name=_sheet_name(lab), index=False)
                out[f"LAS_격자높이_{lab}.xlsx"] = buf.getvalue()
    return out


def _sheet_name(label: str) -> str:
    bad = '[]:*?/\\'
    return "".join("_" if c in bad else c for c in str(label))[:31] or "층"


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(prog="python -m slab.las",
                                 description="층마다 한 개인 LAS/LAZ 파일에서 같은 격자의 바닥·천장 높이 CSV 를 만든다")
    ap.add_argument("folder", help="LAS/LAZ 파일이 있는 폴더")
    ap.add_argument("--out", help=f"출력 폴더 (기본: <폴더>/{OUT_DIR})")
    ap.add_argument("--spacing", type=float, default=LasParams.spacing_m, help="격자 간격 m (기본 1.5)")
    ap.add_argument("--new-grid", action="store_true", help="저장된 grid.json 을 무시하고 격자를 새로 정한다")
    a = ap.parse_args(argv)
    sys.stdout.reconfigure(errors="replace")
    folder = Path(a.folder)
    files = find_las(folder)
    if not files:
        raise SystemExit(f"{folder} 에 LAS/LAZ 파일이 없습니다.")
    out = Path(a.out) if a.out else folder / OUT_DIR
    last = [-1]

    def prog(f, msg):
        pct = int(f * 100)
        if pct != last[0]:
            last[0] = pct
            print(f"\r{pct:3d}%  {msg:<40}", end="", flush=True)

    grid, summary, paths = convert(files, out, LasParams(spacing_m=a.spacing), new_grid=a.new_grid, progress=prog)
    print()
    print(summary.to_string(index=False))
    print(f"격자: 간격 {grid.spacing_m} m, 건물 축 {grid.angle_deg}°, {grid.nx} x {grid.ny}")
    print(f"저장: {out}")


if __name__ == "__main__":
    main()
