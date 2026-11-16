"""결과 저장: Excel 결과표(+위치도), 결과 DXF."""
from __future__ import annotations

import io
import zipfile

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
    "unit": "세대",
    "room_id": "실 ID",
    "room": "실명",
    "point_id": "상부점 ID",
    "x": "X(m)",
    "y": "Y(m)",
    "upper_floor_z": "상부 바닥 Z(m)",
    "lower_ceiling_z": "하부 천장 Z(m)",
    "thickness_mm": "두께(mm)",
    "calc_method": "산출방법",
    "lower_point_id": "사용 하부점",
    "match_dist_m": "거리(m)",
    "status": "상태",
    "judgement": "판정",
    "exclude_reason": "제외·미산출 사유",
    "review_note": "검토 메모",
    "deviation_mm": "설계 대비(mm)",
    "upper_floor_error_mm": "상부 바닥 편차(mm)",
    "lower_ceiling_error_mm": "하부 천장 편차(mm)",
}
TIN_COLUMNS = {f"tin_{k}{i}": f"TIN{i} {label}" for i in (1, 2, 3)
               for k, label in (("id", "점"), ("x", "X(m)"), ("y", "Y(m)"), ("z", "Z(m)"), ("w", "가중치"))}

ROOM_COLUMNS = {
    "unit": "세대",
    "room_id": "실 ID",
    "room": "실명",
    "n_points": "측정점",
    "n_valid": "유효점",
    "n_excluded": "제외점",
    "n_no_value": "미산출점",
    "mean_mm": "평균(mm)",
    "min_mm": "최소(mm)",
    "max_mm": "최대(mm)",
    "std_mm": "표준편차(mm)",
    "design_mm": "설계(mm)",
    "mean_dev_mm": "평균-설계(mm)",
    "n_below": "미달점",
    "judgement": "판정",
}

METHOD_LABELS = {"auto": "직접 대응 우선 → 실패 시 TIN 보간", "nearest": "직접 대응만",
                 "interpolate": "TIN 보간만"}
OUTLIER_LABELS = {"none": "사용 안 함", "mad": "MAD", "iqr": "IQR"}


def points_table(result: AnalysisResult, tin_detail: bool = False) -> pd.DataFrame:
    cols = {**POINT_COLUMNS, **(TIN_COLUMNS if tin_detail else {})}
    df = result.points[list(cols)].rename(columns=cols)
    rnd = {"두께(mm)": 1, "설계 대비(mm)": 1, "거리(m)": 3, "상부 바닥 편차(mm)": 1, "하부 천장 편차(mm)": 1,
           "하부 천장 Z(m)": 4}
    if tin_detail:
        rnd.update({c: 4 for c in TIN_COLUMNS.values() if "가중치" in c})
    return df.round(rnd)


def rooms_table(result: AnalysisResult) -> pd.DataFrame:
    return result.rooms[list(ROOM_COLUMNS)].rename(columns=ROOM_COLUMNS).round(1)


def _outlier_text(s) -> str:
    if s.outlier_method == "iqr":
        k = f"IQR × {s.outlier_iqr_k:g}"
    elif s.outlier_method == "mad" and s.outlier_mad_k > 0:
        k = f"MAD × {s.outlier_mad_k:g}"
    else:
        return "사용 안 함"
    return k + (" (두꺼운 쪽만)" if s.outlier_side == "thick" else "")


def summary_rows(result: AnalysisResult, meta: dict, pass_rate: bool = True) -> list[tuple[str, object]]:
    s, sm, t = result.settings, result.summary, result.transform
    units = sm.get("units", {})
    rows = [
        ("동", meta.get("동", "")),
        ("상부층", meta.get("상부층", "")),
        ("하부층", meta.get("하부층", "")),
        ("", ""),
        ("기준 두께(mm)", s.design_mm - s.tolerance_mm),
        ("적합 기준", f"방 평균 두께 ≥ {s.design_mm - s.tolerance_mm:g} mm"),
        ("대응 방식", METHOD_LABELS.get(s.method, s.method)),
        ("직접 대응 최대 거리(m)", s.max_match_dist_m),
        ("하부점 재사용", "허용" if s.allow_reuse else "1:1 배정"),
        ("TIN 최대 변(m)", s.tin_max_edge_m or "제한 없음"),
        ("기준면 편차 제외 기준(mm)", s.max_surface_error_mm),
        ("통계 이상치 기준", _outlier_text(s)),
        ("두께 하한/상한(mm)", f"{s.min_thickness_mm or '-'} / {s.max_thickness_mm or '-'}"),
    ]
    for k, label in (("upper", "위층 단위"), ("lower", "아래층 단위")):
        if k in units:
            u = units[k]
            rows.append((label, f"XY {u['xy']}{' (자동)' if u['auto_xy'] else ''}, "
                                f"Z {u['z']}{' (자동)' if u['auto_z'] else ''}"))
    rows += [
        ("", ""),
        ("측정점", sm["n_points"]),
        ("유효점", sm["n_valid"]),
        ("  직접 대응 / TIN 보간", f"{sm.get('n_direct', '-')} / {sm.get('n_tin', '-')}"),
        ("제외점", sm["n_excluded"]),
        ("미산출점", sm.get("n_no_value", 0)),
        ("영역외 점", sm.get("n_outside", 0)),
        ("미달점", sm["n_below"]),
        ("평균 두께(mm)", round(sm["mean_mm"], 1)),
        ("중앙값(mm)", round(sm["median_mm"], 1)),
        ("최소(mm)", round(sm["min_mm"], 1)),
        ("최대(mm)", round(sm["max_mm"], 1)),
        ("표준편차(mm)", round(sm["std_mm"], 1)),
    ]
    if pass_rate:
        rows.append(("적합률", f"{sm['pass_rate'] * 100:.1f}%"))
    if t is not None:
        rows += [
            ("", ""),
            ("도면 좌표 정합", t.method),
            ("정합 회전각(°)", round(t.rotation_deg, 4)),
            ("정합 축척", round(t.scale, 6)),
            ("정합 잔차 RMS(mm)", round(t.rms_m * 1000, 2)),
        ]
    for w in sm.get("warnings", []):
        rows.append(("주의", w))
    return rows


_HEADER_FILL = PatternFill("solid", fgColor="DDE3EA")
_BAD_FILL = PatternFill("solid", fgColor="F8D7DA")
_EXCL_FONT = Font(color="8A8F98")


_NONE_FONT = Font(color="8A8F98", italic=True)


def _format_sheet(ws, judgement_col: str | None = None, freeze: bool = False, header_row: int = 1):
    for c in ws[header_row]:
        c.font = Font(bold=True)
        c.fill = _HEADER_FILL
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    for i, col in enumerate(ws.iter_cols(min_row=header_row), 1):
        width = max(len(str(c.value or "")) for c in col)
        ws.column_dimensions[get_column_letter(i)].width = min(max(10, width * 1.6), 50)
    ws.freeze_panes = f"A{header_row + 1}" if freeze else None
    if judgement_col is None:
        return
    idx = [c.value for c in ws[header_row]].index(judgement_col)
    for row in ws.iter_rows(min_row=header_row + 1):
        v = row[idx].value
        if v == "미달":
            for c in row:
                c.fill = _BAD_FILL
        elif v == "제외":
            for c in row:
                c.font = _EXCL_FONT
        elif v == "미산출":
            for c in row:
                c.font = _NONE_FONT


def build_excel(result: AnalysisResult, meta: dict) -> bytes:
    """엑셀 결과. 설정의 excel_layout 이 simple 이면 '포인트 결과'·'위치도' 2시트."""
    s = result.settings
    title = f"{meta.get('동', '')} {meta.get('상부층', '')}-{meta.get('하부층', '')} 슬래브 두께".strip()
    png = figure_png(plot_plan(result, title=title))
    draft = s.report_draft_text if s.report_draft else ""
    start = 2 if draft else 0  # 초안 문구를 맨 위에 쓰고 표는 그 아래부터

    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        pts = points_table(result, s.excel_tin_detail)
        if s.excel_layout == "full":
            pd.DataFrame(summary_rows(result, meta, s.excel_show_pass_rate), columns=["항목", "값"]).to_excel(
                xw, sheet_name="요약", index=False, startrow=start)
            rooms_table(result).to_excel(xw, sheet_name="실별 결과", index=False, startrow=start)
        pts.to_excel(xw, sheet_name="포인트 결과", index=False, startrow=start)
        if s.excel_layout == "full":
            pts[pts["상태"] != "산출"].to_excel(xw, sheet_name="제외·미산출", index=False, startrow=start)

        wb = xw.book
        hr = start + 1
        if s.excel_layout == "full":
            _format_sheet(wb["요약"], header_row=hr)
            wb["요약"].column_dimensions["A"].width = 30
            wb["요약"].column_dimensions["B"].width = 60
            _format_sheet(wb["실별 결과"], "판정", s.excel_freeze_panes, hr)
            _format_sheet(wb["제외·미산출"], None, s.excel_freeze_panes, hr)
        _format_sheet(wb["포인트 결과"], "판정", s.excel_freeze_panes, hr)

        if s.excel_layout == "full" and result.plan is not None:
            _add_image(wb.create_sheet("방별 판정도", 2), figure_png(plot_rooms(result, title=title)),
                       s.excel_map_scale_pct, draft)
        _add_image(wb.create_sheet("위치도"), png, s.excel_map_scale_pct, draft,
                   f"그림 크기 {s.excel_map_scale_pct}% (CAD 도면 축척과 무관) · 점 색과 숫자는 개별 측정점 두께, "
                   f"방 판정은 방 평균 {s.design_mm - s.tolerance_mm:g}mm 기준")
        if draft:
            for ws in wb.worksheets:
                ws["A1"] = draft
                ws["A1"].font = Font(bold=True, color="C62F2F")
    return buf.getvalue()


def _add_image(ws, png: bytes, scale_pct: int = 40, draft: str = "", caption: str = ""):
    img = XLImage(io.BytesIO(png))
    scale = scale_pct / 100
    img.width, img.height = img.width * scale, img.height * scale
    row = 3 if draft else 1
    if caption:
        ws.cell(row, 1, caption).font = Font(color="4C525C")
        row += 1
    ws.add_image(img, f"A{row}")


_LAYERS = {"적합": ("두께_적합", 3), "미달": ("두께_미달", 1), "제외": ("두께_제외", 8),
           "미산출": ("두께_미산출", 9)}


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
        label = p["judgement"] if p["excluded"] else f"{p['thickness_mm']:.0f}"
        msp.add_text(label, height=h, dxfattribs={"layer": layer}).set_placement(
            (x, y - r * 1.5), align=ezdxf.enums.TextEntityAlignment.TOP_CENTER)

    if result.plan is not None:
        by_room = result.rooms.set_index("room_id")
        for room in result.plan.rooms:
            if room.room_id not in by_room.index:
                continue
            row = by_room.loc[room.room_id]
            if pd.isna(row["mean_mm"]):
                continue
            text = f"평균 {row['mean_mm']:.0f}mm ({row['judgement']})"
            msp.add_text(text, height=h * 1.2, dxfattribs={"layer": "두께_실평균"}).set_placement(
                (room.label_xy[0], room.label_xy[1] - h * 2.5),
                align=ezdxf.enums.TextEntityAlignment.TOP_CENTER)

    stream = io.StringIO()
    doc.write(stream)
    return stream.getvalue().encode(doc.output_encoding, errors="replace")


def build_bundle(result: AnalysisResult, meta: dict, stem: str, html: str | None = None) -> bytes:
    """엑셀·DXF·포인트 CSV(+HTML 보고서)를 한 ZIP 으로 묶는다."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(f"{stem}.xlsx", build_excel(result, meta))
        z.writestr(f"{stem}.dxf", build_dxf(result))
        z.writestr(f"{stem}_포인트.csv", points_table(result, True).to_csv(index=False).encode("utf-8-sig"))
        if html:
            z.writestr(f"{stem}_보고서.html", html.encode("utf-8"))
    return buf.getvalue()
