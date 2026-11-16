"""현장 원본(sample_data/, 커밋 안 함)으로 출력끼리 맞는지 검사한다. 판정 결과(통과/미달) 자체는 보지 않는다.

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


def test_point_states_are_consistent(result):
    p = result.points
    assert p["status"].isin(["산출", "제외", "미산출"]).all()
    assert p.loc[p["status"] == "미산출", "thickness_mm"].isna().all()  # 0으로 채우지 않는다
    assert p.loc[p["status"] != "미산출", "thickness_mm"].notna().all()
    assert (p.loc[p["status"] != "산출", "exclude_reason"] != "").all()  # 사유가 항상 있다
    assert (p.loc[p["status"] == "산출", "exclude_reason"] == "").all()
    tin = p[p["calc_method"] == "TIN 보간"]
    w = tin[["tin_w1", "tin_w2", "tin_w3"]].to_numpy()
    assert np.allclose(w.sum(1), 1) and (w >= -1e-9).all()  # 외삽 없음
    z = (w * tin[["tin_z1", "tin_z2", "tin_z3"]].to_numpy()).sum(1)
    assert np.allclose(z, tin["lower_ceiling_z"])
    direct = p[p["calc_method"] == "직접 대응"]
    assert (direct["match_dist_m"] <= result.settings.max_match_dist_m + 1e-9).all()
    assert np.allclose(p["thickness_mm"], (p["upper_floor_z"] - p["lower_ceiling_z"]) * 1000, equal_nan=True)


def test_room_stats_match_points(result):
    p, rooms, sm = result.points, result.rooms, result.summary
    assert rooms["room_id"].is_unique
    inside = p[p["in_room"]]
    assert rooms["n_points"].sum() == len(inside)
    assert sm["n_outside"] == (~p["in_room"]).sum()
    assert sm["n_valid"] + sm["n_excluded"] + sm["n_no_value"] == len(inside)
    for r in rooms.itertuples():
        v = inside.loc[(inside["room_id"] == r.room_id) & ~inside["excluded"], "thickness_mm"]
        assert r.n_valid == len(v)
        if len(v):
            assert r.mean_mm == pytest.approx(v.mean())
            assert r.judgement == ("적합" if r.mean_mm >= 135 else "미달")


def test_outputs_agree(result):
    # 엑셀 포인트 결과 = 화면 포인트표
    wb = load_workbook(io.BytesIO(build_excel(result, {"동": "샘플"})))
    ws = wb["포인트 결과"]
    rows = list(ws.iter_rows(min_row=4, values_only=True))
    header = [c.value for c in ws[3]]
    pt = points_table(result, True)
    assert len(rows) == len(pt)
    xl = {r[header.index("상부점 ID")]: (r[header.index("판정")], r[header.index("두께(mm)")]) for r in rows}
    for pid, j, t in zip(pt["상부점 ID"], pt["판정"], pt["두께(mm)"]):
        assert xl[pid][0] == j
        assert (xl[pid][1] is None) if np.isnan(t) else xl[pid][1] == pytest.approx(t)

    # DXF: 점 하나당 원 하나, 방 평균 글자는 실별 결과와 같다
    doc, _ = recover.read(io.BytesIO(build_dxf(result)))
    msp = doc.modelspace()
    layers = {"두께_적합", "두께_미달", "두께_제외", "두께_미산출"}
    assert len([c for c in msp.query("CIRCLE") if c.dxf.layer in layers]) == len(result.points)
    texts = {t.dxf.text for t in msp.query("TEXT") if t.dxf.layer == "두께_실평균"}
    want = {f"평균 {r.mean_mm:.0f}mm ({r.judgement})" for r in result.rooms.itertuples() if np.isfinite(r.mean_mm)}
    assert texts == want

    # HTML: 미달 방은 모두 보고서에 나온다
    html = build_html(result, {}, ReportSpec("상세 보고서", PRESETS["상세 보고서"]))
    for name in result.rooms.loc[result.rooms["judgement"] == "미달", "room"]:
        assert name in html
