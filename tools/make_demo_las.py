"""가상 LAS 데모 데이터: 측량 좌표에서 23.5° 기울어진 건물의 3개 층 점군 (층마다 한 파일).

LAS 변환(slab/las.py) 시험용이다. 좌표·수치는 모두 가상이다.
- 건물: 건물 축 기준 20 m × 10 m, 가운데(x=10 m)에 칸막이 벽. 층고 2.8 m.
- 슬래브 두께: 왼쪽 방 115 mm, 오른쪽 방 125 mm. 바닥·천장 면에 2 mm 잡음.
- 층마다 바닥 위 상자(높이 0.4 m)와 잡음 분류(7) 점을 섞는다. 스캔 범위는 층마다 조금씩 다르다.

    python tools/make_demo_las.py [출력 폴더]      # 기본: demo_las/
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

ANGLE_DEG = 23.5
ORIGIN = np.array([1000.0, 2000.0])
STOREY = 2.8
BASE_Z = 30.0
SIZE = (20.0, 10.0)
THICK = {"left": 0.115, "right": 0.125}
FLOORS = ("7F", "8F", "9F")
SEED = 3


def thickness(lx: np.ndarray) -> np.ndarray:
    return np.where(lx < 10.0, THICK["left"], THICK["right"])


def to_survey(lx: np.ndarray, ly: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    a = np.radians(ANGLE_DEG)
    return ORIGIN[0] + lx * np.cos(a) - ly * np.sin(a), ORIGIN[1] + lx * np.sin(a) + ly * np.cos(a)


def floor_points(k: int, rng: np.random.Generator, density: float = 120.0):
    """k 번째 층(0부터)의 점: 바닥면(콘크리트 윗면), 천장면(위 슬래브 아랫면), 벽, 상자, 잡음."""
    w, h = SIZE
    floor_z = BASE_Z + k * STOREY  # 이 층 바닥
    m = 0.3 * (k % 2)  # 층마다 스캔 범위를 조금 다르게
    n = int(w * h * density)
    parts = []

    lx, ly = rng.uniform(m, w - m, n), rng.uniform(m, h, n)  # 바닥
    parts.append((lx, ly, floor_z + rng.normal(0, 0.002, n), 2))
    lx, ly = rng.uniform(0, w, n), rng.uniform(0, h - m, n)  # 천장 = 위층 바닥 − 위 슬래브 두께
    parts.append((lx, ly, floor_z + STOREY - thickness(lx) + rng.normal(0, 0.002, n), 1))
    nw = int(2 * (w + h) * 2.4 * density / 4)  # 바깥 벽과 칸막이 벽
    t = rng.uniform(0, 1, nw)
    side = rng.integers(0, 5, nw)
    lx = np.select([side == 0, side == 1, side == 2, side == 3], [t * w, t * w, np.zeros(nw), np.full(nw, w)],
                   np.full(nw, 10.0))
    ly = np.select([side == 0, side == 1, side == 2, side == 3], [np.zeros(nw), np.full(nw, h), t * h, t * h], t * h)
    parts.append((lx, ly, floor_z + rng.uniform(0.05, STOREY - 0.3, nw), 6))
    nb = 1500  # 바닥 위 상자 윗면
    parts.append((rng.uniform(3, 4.2, nb), rng.uniform(3, 4.2, nb), floor_z + 0.4 + rng.normal(0, 0.002, nb), 1))
    nn = 300  # 잡음 점 (분류 7)
    parts.append((rng.uniform(0, w, nn), rng.uniform(0, h, nn), floor_z + rng.uniform(-1, 4, nn), 7))

    lx = np.concatenate([p[0] for p in parts])
    ly = np.concatenate([p[1] for p in parts])
    z = np.concatenate([p[2] for p in parts])
    cls = np.concatenate([np.full(len(p[0]), p[3]) for p in parts]).astype(np.uint8)
    x, y = to_survey(lx, ly)
    return x, y, z, cls


def write_las(path: Path, x, y, z, cls) -> None:
    import laspy

    header = laspy.LasHeader(point_format=3, version="1.2")
    header.scales = np.array([0.001, 0.001, 0.001])
    header.offsets = np.array([np.floor(x.min()), np.floor(y.min()), np.floor(z.min())])
    las = laspy.LasData(header)
    las.x, las.y, las.z = x, y, z
    las.classification = cls
    las.write(path)


def main(out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(SEED)
    for k, name in enumerate(FLOORS):
        write_las(out / f"scan_{name}.las", *floor_points(k, rng))
    print(f"{out} 에 {len(FLOORS)}개 층 LAS 를 만들었습니다 (건물 축 {ANGLE_DEG}°, 두께 115/125 mm).")


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[1] / "demo_las")
