"""여러 층 시험용 파일 만들기: 현장 원본 7F·8F(sample_data/)로 5F·6F·9F 를 가상으로 만든다.

실제처럼 위·아래층의 격자 배치가 서로 다르게, 층마다 7F 배치와 8F 배치를 번갈아 쓴다.
    9F ← 7F 배치 + 2층 높이      8F, 7F ← 원본 그대로
    6F ← 8F 배치 − 2층 높이      5F ← 7F 배치 − 2층 높이
층 높이(층고)는 원본 7F·8F 의 Global_Floor_m 차이(약 2.602 m)를 쓰고, 바닥 높이에 작은 잡음(표준편차 3 mm)을 더해
층마다 두께가 조금씩 다르게 한다. floor_error·height 같은 딸린 열도 같이 고친다.

도면: 원본은 8F 도면(report_merge_8F.dxf)뿐이다. 8F 배치 층(6F)은 그대로 복사하고, 7F 배치 층(5F·7F·9F)은
8F 도면의 방 경계는 두고 측정점 라벨만 7F 점 위치로 옮긴 도면을 만든다.

    python tools/make_test_floors.py              # test_floors/ 에 생성 (원본 좌표가 들어 있어 커밋하지 않음)
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

import ezdxf
import numpy as np
import pandas as pd
from ezdxf import recover

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from slab import load_cad, load_grid  # noqa: E402
from slab.core import POINT_LABEL_RE, estimate_transform  # noqa: E402

SRC = ROOT / "sample_data"
OUT = ROOT / "test_floors"
CSV = "grid_analysis_floor_level_{}.csv"
DXF = "report_merge_{}.dxf"
SEED = 11
NOISE_M = 0.003
# 만들 층: (층, 원본 배치, 원본 대비 몇 층 위/아래)
PLAN = [("9F", "7F", 2), ("6F", "8F", -2), ("5F", "7F", -2)]
LABEL_LAYERS = ("분석 - LABELS", "분석 - MEASUREMENTS", "분석 - DIMENSIONS", "분석 - EXCLUDED")


def storey_height() -> float:
    lv = {f: pd.read_csv(SRC / CSV.format(f))["Global_Floor_m"].median() for f in ("7F", "8F")}
    return float(lv["8F"] - lv["7F"])


def shift_floor(df: pd.DataFrame, dz: float, rng: np.random.Generator) -> pd.DataFrame:
    """Z 열을 dz 만큼 옮기고, 바닥 높이에 잡음을 더한 뒤 딸린 열(편차·층고)을 다시 맞춘다."""
    out = df.copy()
    for c in ("Global_Floor_m", "Global_Height_m", "floor_z", "floor_z_min", "ceiling_z"):
        out[c] = out[c] + dz
    for c in ("Global_Floor_mm", "Global_Height_mm"):
        out[c] = out[c] + dz * 1000
    noise = rng.normal(0, NOISE_M, len(out))
    out["floor_z"] = out["floor_z"] + noise
    out["floor_error"] = out["floor_error"] + noise
    out["height"] = out["ceiling_z"] - out["floor_z"]
    out["height_mm"] = out["height"] * 1000
    rnd = {c: 3 for c in ("Global_Floor_m", "Global_Height_m", "floor_z", "floor_z_min", "ceiling_z", "height",
                          "floor_error", "ceiling_error")}
    rnd.update({c: 3 for c in ("Global_Floor_mm", "Global_Height_mm", "height_mm")})
    return out.round(rnd)


def relabel_dxf(src: Path, dst: Path, grid_7f: pd.DataFrame) -> None:
    """8F 도면에서 측정점 표시를 지우고, 7F 점 위치에 라벨(P001…)과 원을 새로 그린다 (방 경계는 그대로)."""
    plan = load_cad(src)
    t = estimate_transform(plan, load_grid(SRC / CSV.format("8F")))  # 8F 라벨로 도면 ↔ 측량 변환
    doc, _ = recover.read(open(src, "rb"))
    msp = doc.modelspace()
    for e in list(msp):
        if e.dxf.layer in LABEL_LAYERS or (e.dxftype() == "TEXT" and POINT_LABEL_RE.match(e.dxf.text.strip())):
            msp.delete_entity(e)
    cad = t.to_cad(grid_7f[["x", "y"]].to_numpy(float))
    for layer in ("분석 - LABELS", "분석 - MEASUREMENTS"):
        if layer not in doc.layers:
            doc.layers.add(layer)
    for pid, (x, y) in zip(grid_7f["point_id"], cad):
        msp.add_circle((x, y), 60, dxfattribs={"layer": "분석 - MEASUREMENTS"})
        msp.add_text(pid, height=120, dxfattribs={"layer": "분석 - LABELS"}).set_placement(
            (x, y + 90), align=ezdxf.enums.TextEntityAlignment.BOTTOM_CENTER)
    doc.saveas(dst)


def main(out: Path = OUT) -> None:
    if not (SRC / CSV.format("8F")).exists():
        raise SystemExit("sample_data/ 에 7F·8F 원본이 없습니다.")
    out.mkdir(exist_ok=True)
    rng = np.random.default_rng(SEED)
    h = storey_height()
    src = {f: pd.read_csv(SRC / CSV.format(f)) for f in ("7F", "8F")}

    # 원본 7F·8F 와 8F 도면은 그대로
    for f in ("7F", "8F"):
        shutil.copy(SRC / CSV.format(f), out / CSV.format(f))
    shutil.copy(SRC / DXF.format("8F"), out / DXF.format("8F"))
    relabel_dxf(SRC / DXF.format("8F"), out / DXF.format("7F"), load_grid(SRC / CSV.format("7F")))

    for floor, base, n in PLAN:
        shift_floor(src[base], n * h, rng).to_csv(out / CSV.format(floor), index=False)
        if base == "8F":
            shutil.copy(SRC / DXF.format("8F"), out / DXF.format(floor))
        else:
            shutil.copy(out / DXF.format("7F"), out / DXF.format(floor))
    print(f"층고 {h:.3f} m · {out} 에 만들었습니다:")
    for p in sorted(out.iterdir()):
        print(f"  {p.name}")


if __name__ == "__main__":
    main()
