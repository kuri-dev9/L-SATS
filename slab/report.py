"""결과 저장: Excel 결과표(+위치도), 결과 DXF."""
from __future__ import annotations

import io

import ezdxf
import numpy as np
import pandas as pd
from ezdxf import recover
from openpyxl.drawing.image import Image as XLImage
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from scipy.spatial import cKDTree

from .core import AnalysisResult
from .plot import figure_png, plot_plan, plot_rooms

POINT_COLUMNS = {
    "point_id": "포인트",
    "room": "실명",
    "thickness_mm": "두께(mm)",
    "deviation_mm": "설계 대비(mm)",
    "judgement": "판정",
    "exclude_reason": "제외 사유",
    "x": "X(m)",
    "y": "Y(m)",
    "upper_floor_z": "상부 바닥 Z(m)",
    "lower_point_id": "하부 대응점",
    "lower_ceiling_z": "하부 천장 Z(m)",
    "match_dist_m": "대응 거리(m)",
    "upper_floor_error_mm": "상부 바닥 편차(mm)",
    "lower_ceiling_error_mm": "하부 천장 편차(mm)",
}

ROOM_COLUMNS = {
    "room": "실명",
    "n_points": "측정점",
    "n_valid": "유효점",
    "mean_mm": "평균(mm)",
    "min_mm": "최소(mm)",
    "max_mm": "최대(mm)",
    "std_mm": "표준편차(mm)",
    "design_mm": "설계(mm)",
    "mean_dev_mm": "평균-설계(mm)",
    "n_below": "미달점",
    "judgement": "판정",
}

METHOD_LABELS = {"nearest": "최근접 대응점", "interpolate": "하부 천장면 보간"}


def points_table(result: AnalysisResult) -> pd.DataFrame:
    df = result.points[list(POINT_COLUMNS)].rename(columns=POINT_COLUMNS)
    return df.round({"두께(mm)": 1, "설계 대비(mm)": 1, "대응 거리(m)": 3,
                     "상부 바닥 편차(mm)": 1, "하부 천장 편차(mm)": 1, "하부 천장 Z(m)": 4})


def rooms_table(result: AnalysisResult) -> pd.DataFrame:
    return result.rooms[list(ROOM_COLUMNS)].rename(columns=ROOM_COLUMNS).round(1)


def summary_rows(result: AnalysisResult, meta: dict) -> list[tuple[str, object]]:
    s, sm, t = result.settings, result.summary, result.transform
    rows = [
        ("동", meta.get("동", "")),
        ("상부층", meta.get("상부층", "")),
        ("하부층", meta.get("하부층", "")),
        ("", ""),
        ("기준 두께(mm)", s.design_mm - s.tolerance_mm),
        ("적합 기준", f"방 평균 두께 ≥ {s.design_mm - s.tolerance_mm:g} mm"),
        ("대응 방식", METHOD_LABELS.get(s.method, s.method)),
        ("대응점 최대 거리(m)", s.max_match_dist_m),
        ("기준면 편차 제외 기준(mm)", s.max_surface_error_mm),
        ("통계 이상치 기준(MAD 배수)", s.outlier_mad_k or "사용 안 함"),
        ("", ""),
        ("측정점", sm["n_points"]),
        ("유효점", sm["n_valid"]),
        ("제외점", sm["n_excluded"]),
        ("미달점", sm["n_below"]),
        ("평균 두께(mm)", round(sm["mean_mm"], 1)),
        ("중앙값(mm)", round(sm["median_mm"], 1)),
        ("최소(mm)", round(sm["min_mm"], 1)),
        ("최대(mm)", round(sm["max_mm"], 1)),
        ("표준편차(mm)", round(sm["std_mm"], 1)),
        ("적합률", f"{sm['pass_rate'] * 100:.1f}%"),
    ]
    if t is not None:
        rows += [
            ("", ""),
            ("도면 좌표 정합", t.method),
            ("정합 회전각(°)", round(t.rotation_deg, 4)),
            ("정합 축척", round(t.scale, 6)),
            ("정합 잔차 RMS(mm)", round(t.rms_m * 1000, 2)),
        ]
    return rows


_HEADER_FILL = PatternFill("solid", fgColor="DDE3EA")
_BAD_FILL = PatternFill("solid", fgColor="F8D7DA")
_EXCL_FONT = Font(color="8A8F98")


def _format_sheet(ws, judgement_col: str | None = None):
    for c in ws[1]:
        c.font = Font(bold=True)
        c.fill = _HEADER_FILL
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    for i, col in enumerate(ws.columns, 1):
        width = max(len(str(c.value or "")) for c in col)
        ws.column_dimensions[get_column_letter(i)].width = min(max(10, width * 1.6), 50)
    ws.freeze_panes = "A2"
    if judgement_col is None:
        return
    idx = [c.value for c in ws[1]].index(judgement_col)
    for row in ws.iter_rows(min_row=2):
        v = row[idx].value
        if v == "미달":
            for c in row:
                c.fill = _BAD_FILL
        elif v == "제외":
            for c in row:
                c.font = _EXCL_FONT


def build_excel(result: AnalysisResult, meta: dict) -> bytes:
    title = f"{meta.get('동', '')} {meta.get('상부층', '')}-{meta.get('하부층', '')} 슬래브 두께".strip()
    png = figure_png(plot_plan(result, title=title))

    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        pd.DataFrame(summary_rows(result, meta), columns=["항목", "값"]).to_excel(
            xw, sheet_name="요약", index=False)
        rooms_table(result).to_excel(xw, sheet_name="실별 결과", index=False)
        points_table(result).to_excel(xw, sheet_name="포인트별 결과", index=False)
        excl = points_table(result)
        excl[excl["판정"] == "제외"].to_excel(xw, sheet_name="제외 포인트", index=False)

        wb = xw.book
        _format_sheet(wb["요약"])
        wb["요약"].column_dimensions["A"].width = 30
        wb["요약"].column_dimensions["B"].width = 30
        _format_sheet(wb["실별 결과"], "판정")
        _format_sheet(wb["포인트별 결과"], "판정")
        _format_sheet(wb["제외 포인트"])

        if result.plan is not None:
            _add_image(wb.create_sheet("방별 판정도", 1), figure_png(plot_rooms(result, title=title)))
        _add_image(wb.create_sheet("위치도"), png)
    return buf.getvalue()


def _add_image(ws, png: bytes, width: int = 1400):
    img = XLImage(io.BytesIO(png))
    scale = width / img.width
    img.width, img.height = img.width * scale, img.height * scale
    ws.add_image(img, "A1")


_LAYERS = {"적합": ("두께_적합", 3), "미달": ("두께_미달", 1), "제외": ("두께_제외", 8)}


def build_dxf(result: AnalysisResult) -> bytes:
    """원본 도면에 두께 결과 레이어를 추가한 DXF (도면이 없으면 측량 좌표로 새로 작성)."""
    if result.plan is not None:
        doc, _ = recover.read(io.BytesIO(result.plan.raw))
    else:
        doc = ezdxf.new("R2018")
    msp = doc.modelspace()
    for name, color in [*_LAYERS.values(), ("두께_실평균", 5)]:
        if name not in doc.layers:
            doc.layers.add(name, color=color)

    pts = result.points
    xy = pts[["cad_x", "cad_y"]].to_numpy()
    if len(xy) > 1:
        d, _ = cKDTree(xy).query(xy, k=2)
        spacing = float(np.median(d[:, 1]))
    else:
        spacing = 1.0
    r, h = spacing * 0.08, spacing * 0.12

    for (x, y), (_, p) in zip(xy, pts.iterrows()):
        layer = _LAYERS[p["judgement"]][0]
        msp.add_circle((x, y), r, dxfattribs={"layer": layer})
        label = "제외" if p["excluded"] else f"{p['thickness_mm']:.0f}"
        msp.add_text(label, height=h, dxfattribs={"layer": layer}).set_placement(
            (x, y - r * 1.5), align=ezdxf.enums.TextEntityAlignment.TOP_CENTER)

    if result.plan is not None:
        by_room = result.rooms.set_index("room")
        for room in result.plan.rooms:
            names = pts.loc[pts["room_id"] == room.room_id, "room"]
            if not len(names) or names.iloc[0] not in by_room.index:
                continue
            row = by_room.loc[names.iloc[0]]
            if pd.isna(row["mean_mm"]):
                continue
            text = f"평균 {row['mean_mm']:.0f}mm ({row['judgement']})"
            msp.add_text(text, height=h * 1.2, dxfattribs={"layer": "두께_실평균"}).set_placement(
                (room.label_xy[0], room.label_xy[1] - h * 2.5),
                align=ezdxf.enums.TextEntityAlignment.TOP_CENTER)

    stream = io.StringIO()
    doc.write(stream)
    return stream.getvalue().encode(doc.output_encoding, errors="replace")
