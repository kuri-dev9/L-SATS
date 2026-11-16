"""결과 저장: 층별 결과 엑셀(받은 결과 양식), 전체 층 요약 엑셀, 결과 DXF, ZIP 묶음."""
from __future__ import annotations

import io
import zipfile

import ezdxf
import numpy as np
import pandas as pd
from ezdxf import recover
from openpyxl import Workbook
from openpyxl.drawing.image import Image as XLImage
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from scipy.spatial import cKDTree

from .core import STATE_LOW, STATE_NONE, STATE_OK, STATE_OUTLIER, STATE_OUTSIDE, STATE_RANGE, AnalysisResult
from .plot import figure_png, plot_distribution, plot_point_map, plot_rooms

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
    "calc_thickness_mm": "계산값(mm)",
    "calc_method": "산출방법",
    "lower_point_id": "사용 하부점",
    "match_dist_m": "거리(m)",
    "status": "결과 상태",
    "no_reason": "미산출 사유",
    "exclude_reason": "상세 사유",
    "review_note": "검토 메모",
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
    "n_valid": "산출 완료",
    "n_review": "검토 점",
    "n_no_value": "미산출",
    "mean_mm": "평균(mm)",
    "min_mm": "최소(mm)",
    "max_mm": "최대(mm)",
    "std_mm": "표준편차(mm)",
}

# 받은 결과 엑셀과 같은 열
RESULT_COLUMNS = ["세대·구역명", "실명", "포인트 ID", "X(m)", "Y(m)", "슬라브 두께(mm)", "산출 방식", "결과 상태",
                  "미산출 사유"]
RESULT_WIDTHS = [16, 18, 20, 16, 16, 20, 16, 24, 30]

METHOD_LABELS = {"auto": "직접 대응 우선 → 실패 시 TIN 보간", "nearest": "직접 대응만",
                 "interpolate": "TIN 보간만"}
OUTLIER_LABELS = {"none": "사용 안 함", "mad": "MAD", "iqr": "IQR"}
NAVY, ZEBRA = "24476B", "F3F6FA"


def points_table(result: AnalysisResult, tin_detail: bool = False) -> pd.DataFrame:
    cols = {**POINT_COLUMNS, **(TIN_COLUMNS if tin_detail else {})}
    df = result.points[list(cols)].rename(columns=cols)
    rnd = {"두께(mm)": 1, "계산값(mm)": 1, "거리(m)": 3, "상부 바닥 편차(mm)": 1, "하부 천장 편차(mm)": 1,
           "하부 천장 Z(m)": 4}
    if tin_detail:
        rnd.update({c: 4 for c in TIN_COLUMNS.values() if "가중치" in c})
    return df.round(rnd)


def rooms_table(result: AnalysisResult) -> pd.DataFrame:
    return result.rooms[list(ROOM_COLUMNS)].rename(columns=ROOM_COLUMNS).round(1)


def short_room(room: str, unit: str) -> str:
    """'7호_침실1' (세대 7호) → '침실1'."""
    room = str(room)
    if unit and room.startswith(unit):
        rest = room[len(unit):].lstrip("_ -")
        return rest or room
    return room


def result_rows(result: AnalysisResult) -> pd.DataFrame:
    """받은 결과 엑셀과 같은 순서·열: 값이 있는 점(세대·실 순) → 미산출 → 영역 외."""
    p = result.points
    order = p["status"].map(lambda v: 2 if v == STATE_OUTSIDE else 1 if v == STATE_NONE else 0)
    df = pd.DataFrame({
        "세대·구역명": np.where(p["in_room"], p["unit"], None),
        "실명": [short_room(r, u) if inr else None for r, u, inr in zip(p["room"], p["unit"], p["in_room"])],
        "포인트 ID": p["point_id"],
        "X(m)": p["x"],
        "Y(m)": p["y"],
        "슬라브 두께(mm)": p["thickness_mm"],
        "산출 방식": np.where(p["thickness_mm"].notna(), p["calc_method"], "—"),
        "결과 상태": p["status"],
        "미산출 사유": p["no_reason"].replace("", None),
        "_o": order,
        "_u": np.where(order == 0, p["unit"], ""),
        "_r": np.where(order == 0, p["room_id"], ""),
    })
    df = df.sort_values(["_o", "_u", "_r", "포인트 ID"], kind="stable")
    return df.drop(columns=["_o", "_u", "_r"]).reset_index(drop=True)


def _outlier_text(s) -> str:
    if s.outlier_method == "iqr" and s.outlier_iqr_k > 0:
        k = f"IQR × {s.outlier_iqr_k:g}"
    elif s.outlier_method == "mad" and s.outlier_mad_k > 0:
        k = f"MAD × {s.outlier_mad_k:g}"
    else:
        return "사용 안 함"
    scope = "같은 방 점끼리" if s.outlier_scope == "room" else "층 전체"
    return f"{k} ({scope}, {s.outlier_min_points}점 이상)" + (" 두꺼운 쪽만" if s.outlier_side == "thick" else "")


def state_rules(s) -> list[tuple[str, str]]:
    return [
        ("산출 완료", "아래 검토 대상이 아닌 두께. 방 평균·최소·최대는 이 점들로만 냅니다."),
        ("두께 범위 검토", f"{s.review_above_mm:g}mm 이상"),
        ("두께 비정상(하한 이하)", f"{s.low_limit_mm:g}mm 이하"),
        ("이상치 검토", _outlier_text(s)),
        ("미산출 · 대응점 없음", "아래층에 같은 위치 천장점이 없고 TIN 보간도 안 됨"),
        ("미산출 · Z값 확인 필요", f"바닥·천장이 층 기준면에서 {s.max_surface_error_mm:g}mm 넘게 벗어나거나 측정 없음"),
        ("영역 외", "도면의 방 경계 밖 (방 집계에 넣지 않음)"),
    ]


def summary_rows(result: AnalysisResult, meta: dict) -> list[tuple[str, object]]:
    s, sm, t = result.settings, result.summary, result.transform
    units = sm.get("units", {})

    def r1(v):
        return round(float(v), 1) if v is not None and np.isfinite(v) else "-"

    rows = [
        ("동", meta.get("동", "")),
        ("상부층", meta.get("상부층", "")),
        ("하부층", meta.get("하부층", "")),
        ("", ""),
        ("대응 방식", METHOD_LABELS.get(s.method, s.method)),
        ("직접 대응 최대 거리(m)", s.max_match_dist_m),
        ("하부점 재사용", "허용" if s.allow_reuse else "1:1 배정"),
        ("TIN 최대 변(m)", s.tin_max_edge_m or "제한 없음"),
    ]
    rows += [(f"상태: {a}", b) for a, b in state_rules(s)]
    for k, label in (("upper", "위층 단위"), ("lower", "아래층 단위")):
        if k in units:
            u = units[k]
            rows.append((label, f"XY {u['xy']}{' (자동)' if u['auto_xy'] else ''}, "
                                f"Z {u['z']}{' (자동)' if u['auto_z'] else ''}"))
    rows += [
        ("", ""),
        ("측정점", sm["n_points"]),
        ("산출 완료", sm["n_valid"]),
        ("  직접 대응 / TIN 보간", f"{sm.get('n_direct', '-')} / {sm.get('n_tin', '-')}"),
        ("두께 범위 검토", sm["n_range"]),
        ("이상치 검토", sm["n_outlier"]),
        ("두께 비정상(하한 이하)", sm["n_low"]),
        ("미산출", sm["n_no_value"]),
        ("영역 외", sm["n_outside"]),
        ("평균 두께(mm)", r1(sm["mean_mm"])),
        ("중앙값(mm)", r1(sm["median_mm"])),
        ("최소(mm)", r1(sm["min_mm"])),
        ("최대(mm)", r1(sm["max_mm"])),
        ("표준편차(mm)", r1(sm["std_mm"])),
    ]
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
_NAVY_FILL = PatternFill("solid", fgColor=NAVY)
_ZEBRA_FILL = PatternFill("solid", fgColor=ZEBRA)
_STATE_FONT = {STATE_RANGE: Font(size=10, color="B45309", bold=True), STATE_OUTLIER: Font(size=10, color="B45309",
                                                                                           bold=True),
               STATE_LOW: Font(size=10, color="C62F2F", bold=True), STATE_NONE: Font(size=10, color="6B7280"),
               STATE_OUTSIDE: Font(size=10, color="6B7280")}


def _format_sheet(ws, freeze: bool = False, header_row: int = 1):
    for c in ws[header_row]:
        c.font = Font(bold=True)
        c.fill = _HEADER_FILL
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    for i, col in enumerate(ws.iter_cols(min_row=header_row), 1):
        width = max(len(str(c.value or "")) for c in col)
        ws.column_dimensions[get_column_letter(i)].width = min(max(10, width * 1.6), 50)
    ws.freeze_panes = f"A{header_row + 1}" if freeze else None


def floor_title(meta: dict) -> str:
    return " / ".join(x for x in (meta.get("동", ""), meta.get("상부층", ""), meta.get("하부층", "")) if x)


def _title(ws, text: str, meta: dict, width: int, banner: bool = True):
    ws["A1"] = text
    if banner:
        ws["A1"].font = Font(size=18, bold=True, color="FFFFFF")
        ws["A1"].fill = _NAVY_FILL
    else:
        ws["A1"].font = Font(size=20, bold=True, color=NAVY)
    ws["A1"].alignment = Alignment(vertical="center", indent=1 if banner else 0)
    ws.row_dimensions[1].height = 34
    ws["A2"] = floor_title(meta)
    for r in (1, 2):
        ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=width)


def _draft(ws, s, row: int, width: int):
    if s.report_draft:
        ws.cell(row, 1, s.report_draft_text).font = Font(bold=True, color="C62F2F")
        ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=width)


def _image(ws, png: bytes, anchor: str, width_px: int | None = None):
    img = XLImage(io.BytesIO(png))
    if width_px:
        k = width_px / img.width
        img.width, img.height = width_px, img.height * k
    ws.add_image(img, anchor)
    return img


def _sheet_result(wb, result: AnalysisResult, meta: dict):
    """받은 결과 엑셀의 첫 시트: 제목 · 분포도 · 포인트별 표."""
    s = result.settings
    ws = wb.create_sheet("슬라브 두께 결과")
    n = len(RESULT_COLUMNS)
    _title(ws, "포인트별 슬라브 두께 산출 결과", meta, n)
    _draft(ws, s, 3, n)
    for r in (4, 5, 6):
        ws.row_dimensions[r].height = 3
    ws["A7"] = "위치별 슬라브 두께 분포도  |  색상=두께, 회색 ×=미산출, 회색 ○=영역 외"
    ws.merge_cells("A7:I7")
    _image(ws, figure_png(plot_distribution(result), dpi=100), "A8", 1000)
    head = 40
    for j, (name, w) in enumerate(zip(RESULT_COLUMNS, RESULT_WIDTHS), 1):
        c = ws.cell(head, j, name)
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = _NAVY_FILL
        c.alignment = Alignment(horizontal="center", vertical="center")
        ws.column_dimensions[get_column_letter(j)].width = w
    ws.row_dimensions[head].height = 30
    rows = result_rows(result)
    fmt = {4: "0.000000", 5: "0.000000", 6: "0.0"}
    for i, row in enumerate(rows.itertuples(index=False), head + 1):
        zebra = (i - head) % 2 == 0
        for j, v in enumerate(row, 1):
            c = ws.cell(i, j, None if (v is None or (isinstance(v, float) and not np.isfinite(v))) else v)
            c.font = Font(size=10)
            if j in fmt:
                c.number_format = fmt[j]
            if zebra:
                c.fill = _ZEBRA_FILL
        st_ = row[7]
        if st_ in _STATE_FONT:
            ws.cell(i, 8).font = _STATE_FONT[st_]
    ws.auto_filter.ref = f"A{head}:I{head + len(rows)}"
    ws.page_setup.orientation = "landscape"
    ws.print_options.horizontalCentered = True
    ws.sheet_view.showGridLines = False
    return ws


def _sheet_point_map(wb, result: AnalysisResult, meta: dict):
    """메인 자료: 포인트 위치도 (ID / 두께 이름표). 큰 그림이라 40% 로 열린다."""
    ws = wb.create_sheet("포인트 위치도")
    _title(ws, "포인트 위치도", meta, 12, banner=False)
    ws["A3"] = ("포인트 ID / 두께(mm) · 색상=두께 · 회색 × 미산출 · 회색 ○ 영역 외 · "
                "검토 대상(두께 범위·이상치·하한)은 '슬라브 두께 결과' 표의 결과 상태 참고")
    ws.merge_cells("A3:L3")
    _draft(ws, result.settings, 4, 12)
    _image(ws, figure_png(plot_point_map(result)), "A5")
    ws.sheet_view.zoomScale = 40
    ws.sheet_view.showGridLines = False
    return ws


def _sheet_room_map(wb, result: AnalysisResult, meta: dict):
    """서브 자료: 방별 두께도 + 방별 현황 표."""
    ws = wb.create_sheet("방별 두께도")
    _title(ws, "방별 슬라브 두께 (서브 자료)", meta, 11, banner=False)
    ws["A3"] = "방 색 = 방 평균 두께('산출 완료' 점만). 검토·미산출 점은 평균에 넣지 않았습니다."
    ws.merge_cells("A3:K3")
    _draft(ws, result.settings, 4, 11)
    img = _image(ws, figure_png(plot_rooms(result, title=" ")), "A5", 1100)
    top = 5 + int(img.height / 20) + 2
    t = rooms_table(result).drop(columns=["실 ID"]).sort_values(["세대", "실명"])
    for j, name in enumerate(t.columns, 1):
        c = ws.cell(top, j, name)
        c.font, c.fill = Font(bold=True, color="FFFFFF"), _NAVY_FILL
        c.alignment = Alignment(horizontal="center")
        ws.column_dimensions[get_column_letter(j)].width = 14
    for i, row in enumerate(t.itertuples(index=False), top + 1):
        for j, v in enumerate(row, 1):
            ok = not (isinstance(v, float) and not np.isfinite(v))
            ws.cell(i, j, v if ok else None).font = Font(size=10)
    ws.sheet_view.showGridLines = False
    return ws


def build_excel(result: AnalysisResult, meta: dict) -> bytes:
    """층 하나의 결과 엑셀. 받은 결과 엑셀과 같은 '슬라브 두께 결과'·'포인트 위치도' 시트에
    방별 두께도(서브)를 더하고, 전체 구성이면 방별 현황·계산 상세·설정 시트를 더한다."""
    s = result.settings
    wb = Workbook()
    wb.remove(wb.active)
    _sheet_result(wb, result, meta)
    _sheet_point_map(wb, result, meta)
    if result.plan is not None and s.excel_room_map:
        _sheet_room_map(wb, result, meta)
    buf = io.BytesIO()
    wb.save(buf)
    if s.excel_layout != "full":
        return buf.getvalue()
    with pd.ExcelWriter(buf, engine="openpyxl", mode="a") as xw:
        rooms_table(result).to_excel(xw, sheet_name="방별 현황", index=False)
        points_table(result, s.excel_tin_detail).to_excel(xw, sheet_name="계산 상세", index=False)
        pd.DataFrame(summary_rows(result, meta), columns=["항목", "값"]).astype(str).to_excel(
            xw, sheet_name="설정·요약", index=False)
        for name in ("방별 현황", "계산 상세", "설정·요약"):
            _format_sheet(xw.book[name])
        xw.book["설정·요약"].column_dimensions["A"].width = 30
        xw.book["설정·요약"].column_dimensions["B"].width = 70
    return buf.getvalue()


# ------------------------------------------------------------------ 여러 층
def floor_summary(results: list[tuple[dict, AnalysisResult | None, str]]) -> pd.DataFrame:
    """[(meta, 결과 또는 None, 문제)] → 층별 요약 표 (위층부터)."""
    rows = []
    for meta, r, problem in results:
        sm = r.summary if r is not None else {}

        def g(k):
            v = sm.get(k)
            return round(float(v), 1) if v is not None and np.isfinite(v) else None

        rows.append({
            "층": meta.get("상부층", ""), "아래층": meta.get("하부층", ""),
            "측정점": sm.get("n_points"), "산출 완료": sm.get("n_valid"), "두께 범위 검토": sm.get("n_range"),
            "이상치 검토": sm.get("n_outlier"), "하한 이하": sm.get("n_low"), "미산출": sm.get("n_no_value"),
            "영역 외": sm.get("n_outside"), "평균(mm)": g("mean_mm"), "최소(mm)": g("min_mm"),
            "최대(mm)": g("max_mm"), "표준편차(mm)": g("std_mm"),
            "비고": problem or ("; ".join(sm.get("warnings", [])) if r is not None else ""),
        })
    return pd.DataFrame(rows)


def all_rooms(results: list[tuple[dict, AnalysisResult | None, str]]) -> pd.DataFrame:
    frames = []
    for meta, r, _ in results:
        if r is None or r.plan is None:
            continue
        t = rooms_table(r).drop(columns=["실 ID"])
        t.insert(0, "층", meta.get("상부층", ""))
        frames.append(t)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def build_summary_excel(results: list[tuple[dict, AnalysisResult | None, str]], dong: str = "",
                        draft: str = "") -> bytes:
    """전체 층 요약 엑셀: 층별 요약 + 방별 현황(모든 층)."""
    buf = io.BytesIO()
    start = 3 + (1 if draft else 0)
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        floor_summary(results).to_excel(xw, sheet_name="층별 요약", index=False, startrow=start)
        rooms = all_rooms(results)
        if not rooms.empty:
            rooms.to_excel(xw, sheet_name="방별 현황(전체 층)", index=False, startrow=start)
        for ws in xw.book.worksheets:
            _format_sheet(ws, True, start + 1)
            ws["A1"] = f"{dong} 슬라브 두께 현황 — 층별 요약".strip() if ws.title == "층별 요약" else \
                f"{dong} 슬라브 두께 현황 — 방별 (모든 층)".strip()
            ws["A1"].font = Font(size=16, bold=True, color=NAVY)
            ws["A2"] = "평균·최소·최대는 '산출 완료' 점으로만 냈습니다. 위층 바닥 − 아래층 천장."
            ws["A2"].font = Font(color="5B6470")
            if draft:
                ws["A3"] = draft
                ws["A3"].font = Font(bold=True, color="C62F2F")
    return buf.getvalue()


_LAYERS = {STATE_OK: ("두께_산출", 3), STATE_RANGE: ("두께_검토", 30), STATE_OUTLIER: ("두께_검토", 30),
           STATE_LOW: ("두께_검토", 30), STATE_NONE: ("두께_미산출", 8), STATE_OUTSIDE: ("두께_영역외", 9)}


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
        layer = _LAYERS[p["status"]][0]
        msp.add_circle((x, y), r, dxfattribs={"layer": layer})
        if pd.notna(p["thickness_mm"]):
            label = f"{p['thickness_mm']:.0f}"
        else:
            label = p["no_reason"] or p["status"]
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
            text = f"평균 {row['mean_mm']:.0f}mm ({row['n_valid']}점)"
            msp.add_text(text, height=h * 1.2, dxfattribs={"layer": "두께_실평균"}).set_placement(
                (room.label_xy[0], room.label_xy[1] - h * 2.5),
                align=ezdxf.enums.TextEntityAlignment.TOP_CENTER)

    stream = io.StringIO()
    doc.write(stream)
    return stream.getvalue().encode(doc.output_encoding, errors="replace")


def build_bundle(result: AnalysisResult, meta: dict, stem: str, html: str | None = None) -> bytes:
    """층 하나: 엑셀·DXF·포인트 CSV(+HTML 보고서)를 한 ZIP 으로 묶는다."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(f"{stem}.xlsx", build_excel(result, meta))
        z.writestr(f"{stem}.dxf", build_dxf(result))
        z.writestr(f"{stem}_포인트.csv", points_table(result, True).to_csv(index=False).encode("utf-8-sig"))
        if html:
            z.writestr(f"{stem}_보고서.html", html.encode("utf-8"))
    return buf.getvalue()


def build_all(results: list[tuple[dict, AnalysisResult | None, str]], dong: str, stem_of, progress=None,
              with_dxf: bool = True) -> bytes:
    """전체 층: 요약 엑셀 + 층마다 결과 엑셀(+DXF)을 한 ZIP 으로. progress(i, n, 층 이름) 로 진행을 알린다."""
    buf = io.BytesIO()
    ok = [(m, r) for m, r, _ in results if r is not None]
    draft = ok[0][1].settings.report_draft_text if ok and ok[0][1].settings.report_draft else ""
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(f"{(dong + '_') if dong else ''}전체층_요약.xlsx", build_summary_excel(results, dong, draft))
        for i, (meta, r) in enumerate(ok):
            if progress:
                progress(i, len(ok), meta.get("상부층", ""))
            stem = stem_of(meta)
            z.writestr(f"층별/{stem}.xlsx", build_excel(r, meta))
            if with_dxf:
                z.writestr(f"층별/{stem}.dxf", build_dxf(r))
    return buf.getvalue()
