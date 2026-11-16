"""현장 원본(sample_data/, 커밋 안 함)으로 출력끼리 맞는지 검사한다. 두께 값 자체는 보지 않는다.

폴더가 없으면(공개 저장소·CI) 건너뛴다.
"""
import io
from pathlib import Path

import numpy as np
import pytest
from ezdxf import recover
from openpyxl import load_workbook

from slab import Settings, analyze, load_cad, load_grid
from slab.report import build_dxf, build_excel, points_table
from slab.report_html import PRESETS, ReportSpec, build_html

DATA = Path(__file__).resolve().parents[1] / "sample_data"
pytestmark = pytest.mark.skipif(not (DATA / "report_merge_8F.dxf").exists(), reason="sample_data 없음")


@pytest.fixture(scope="module", params=["auto", "nearest", "interpolate"])
def result(request):
    return analyze(load_grid(DATA / "grid_analysis_floor_level_8F.csv"),
                   load_grid(DATA / "grid_analysis_floor_level_7F.csv"),
                   load_cad(DATA / "report_merge_8F.dxf"), Settings(method=request.param))


STATES = ["산출 완료", "두께 범위 검토", "이상치 검토", "두께 비정상(하한 이하)", "미산출", "영역 외"]


def test_point_states_are_consistent(result):
    p, s = result.points, result.settings
    assert p["status"].isin(STATES).all()
    gone = p["status"].isin(["미산출", "영역 외"])
    assert p.loc[gone, "thickness_mm"].isna().all()  # 0으로 채우지 않는다
    assert p.loc[~gone, "thickness_mm"].notna().all()
    assert (p.loc[p["status"] == "미산출", "no_reason"].isin(["대응점 없음", "Z값 확인 필요"])).all()
    assert (p.loc[p["status"] != "미산출", "no_reason"] == "").all()
    assert (p.loc[p["status"] == "두께 범위 검토", "thickness_mm"] >= s.review_above_mm).all()
    assert (p.loc[p["status"] == "산출 완료", "thickness_mm"] < s.review_above_mm).all()
    assert (p.loc[p["status"] == "산출 완료", "thickness_mm"] > s.low_limit_mm).all()
    assert (p["status"] == "영역 외").eq(~p["in_room"]).all()
    tin = p[p["calc_method"] == "TIN 보간"]
    w = tin[["tin_w1", "tin_w2", "tin_w3"]].to_numpy()
    assert np.allclose(w.sum(1), 1) and (w >= -1e-9).all()  # 외삽 없음
    z = (w * tin[["tin_z1", "tin_z2", "tin_z3"]].to_numpy()).sum(1)
    assert np.allclose(z, tin["lower_ceiling_z"])
    direct = p[p["calc_method"] == "직접 대응"]
    assert (direct["match_dist_m"] <= result.settings.max_match_dist_m + 1e-9).all()
    assert np.allclose(p["calc_thickness_mm"], (p["upper_floor_z"] - p["lower_ceiling_z"]) * 1000, equal_nan=True)


def test_room_stats_match_points(result):
    p, rooms, sm = result.points, result.rooms, result.summary
    assert rooms["room_id"].is_unique
    inside = p[p["in_room"]]
    assert rooms["n_points"].sum() == len(inside)
    assert sm["n_outside"] == (~p["in_room"]).sum()
    assert sm["n_valid"] + sm["n_review"] + sm["n_no_value"] == len(inside)
    for r in rooms.itertuples():
        v = inside.loc[(inside["room_id"] == r.room_id) & (inside["status"] == "산출 완료"), "thickness_mm"]
        assert r.n_valid == len(v)
        if len(v):
            assert r.mean_mm == pytest.approx(v.mean())


def test_outputs_agree(result):
    # 엑셀 '슬라브 두께 결과' 표 = 화면 포인트표
    wb = load_workbook(io.BytesIO(build_excel(result, {"동": "샘플"})))
    ws = wb["슬라브 두께 결과"]
    header = [c.value for c in ws[40]]
    rows = list(ws.iter_rows(min_row=41, values_only=True))
    pt = points_table(result, True)
    assert len(rows) == len(pt)
    xl = {r[header.index("포인트 ID")]: (r[header.index("결과 상태")], r[header.index("슬라브 두께(mm)")]) for r in rows}
    for pid, j, t in zip(pt["상부점 ID"], pt["결과 상태"], pt["두께(mm)"]):
        assert xl[pid][0] == j
        assert (xl[pid][1] is None) if np.isnan(t) else xl[pid][1] == pytest.approx(t, abs=0.06)

    # DXF: 점 하나당 원 하나, 방 평균 글자는 방별 현황과 같다
    doc, _ = recover.read(io.BytesIO(build_dxf(result)))
    msp = doc.modelspace()
    layers = {"두께_산출", "두께_검토", "두께_미산출", "두께_영역외"}
    assert len([c for c in msp.query("CIRCLE") if c.dxf.layer in layers]) == len(result.points)
    texts = {t.dxf.text for t in msp.query("TEXT") if t.dxf.layer == "두께_실평균"}
    want = {f"평균 {r.mean_mm:.0f}mm ({r.n_valid}점)" for r in result.rooms.itertuples() if np.isfinite(r.mean_mm)}
    assert texts == want

    # HTML: 검토·미산출 점은 모두 보고서에 나온다
    html = build_html(result, {}, ReportSpec("상세 보고서", PRESETS["상세 보고서"]))
    p = result.points
    for pid in p.loc[p["status"].isin(["두께 범위 검토", "이상치 검토", "미산출"]), "point_id"]:
        assert pid in html
