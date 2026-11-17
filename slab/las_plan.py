"""LAS 변환 결과로 층별 DXF 평면도를 그린다 (건물 축 기준 좌표, 단위 mm).

- 벽선: 바닥에서 1.0~1.5 m 높이 점(벽 단면, las.WALL_Z)이 있는 칸에서 건물 축에 나란하게 곧게 이어진 벽 면을
  그 자리 그대로 선으로 그린다 (두께를 지어내지 않는다). 칸막이벽은 양쪽 면이 보여 두 줄, 외벽은 안쪽 면만 보여 한 줄.
  WALL_MIN_LEN 보다 짧거나, 두꺼운 덩어리이거나, 점이 성긴 면(가구 등)은 뺀다. 창·문이 뚫린 곳은 끊긴다.
- 격자점: 점(원) + 이름(G001-001) + 바닥·천장 높이(m)와 층고(mm).

칸 자료(plan)는 las.sample_floor 가 LAS 를 읽으면서 채운다 (las._PlanRaster).
"""
from __future__ import annotations

import io

import numpy as np
import pandas as pd

WALL_MIN_POINTS = 3  # 벽 칸으로 볼 최소 점 수 (흩어진 잡음 제외)
WALL_MIN_LEN = 0.5  # 이보다 짧게 이어진 면은 벽으로 보지 않는다 (m)
FACE_MAX_THICK = 0.25  # 면 하나(또는 붙어 보이는 얇은 벽)의 최대 두께. 더 두꺼운 덩어리는 가구 등 (m)
FACE_MIN_DENSITY = 0.25  # 면의 칸당 점 수가 벽 칸 상위 10 % 값의 이 비율보다 적으면 가구 등으로 보고 뺀다
ROW_COVER = 0.5  # 면 띠에서 가장 긴 줄의 이 비율 넘게 차 있는 줄만 면 두께로 친다

ROOM_LAYER = "ROOM_BOUNDARY"  # 두께 분석이 실 경계로 읽는 레이어 (slab.core.load_cad)

LAYERS = {  # 이름: (색 번호, 설명)
    ROOM_LAYER: (5, "실 경계와 실 이름 (방 배치 화면에서 정함)"),
    "벽": (8, "벽 (추정 띠: 칸막이벽은 두 면 사이, 외벽은 바깥쪽으로 추정 두께만큼)"),
    "벽선": (7, "바닥 위 1.0~1.5 m 단면에서 스캔된 곧은 벽 면"),
    "격자점": (1, "격자점 위치"),
    "점번호": (2, "격자점 이름"),
    "높이": (8, "바닥·천장 높이(m), 층고(mm)"),
    "제목": (7, ""),
}


def _faces_one_way(cnt: np.ndarray, mask: np.ndarray, min_cells: int, max_thick: int,
                   min_density: float) -> list[tuple[float, int, int]]:
    """가로로 곧은 벽 면 → [(행 위치(칸, 점 수 가중 평균), 열0, 열1)]."""
    from scipy import ndimage

    runs, n = ndimage.label(mask, structure=[[0, 0, 0], [1, 1, 1], [0, 0, 0]])  # 줄마다 이어진 칸
    if not n:
        return []
    keep = np.zeros(n + 1, bool)
    keep[1:] = np.bincount(runs.ravel())[1:] >= min_cells
    lab, _ = ndimage.label(keep[runs])  # 위아래로 붙은 긴 줄 = 한 면
    out = []
    for k, sl in enumerate(ndimage.find_objects(lab), start=1):
        sub = lab[sl] == k
        cover = sub.sum(1)
        rows = np.flatnonzero(cover >= ROW_COVER * cover.max())
        r0, r1 = rows[0], rows[-1]
        if r1 - r0 + 1 > max_thick:
            continue
        band = sub[r0:r1 + 1]
        c = np.where(band, cnt[sl][r0:r1 + 1], 0)
        if c.sum() / band.sum() < min_density:
            continue
        cols = np.flatnonzero(band.any(0))
        c0, c1 = int(np.percentile(cols, 1)), int(np.percentile(cols, 99))
        if c1 - c0 + 1 < min_cells:
            continue
        row = sl[0].start + r0 + (c.sum(1) @ np.arange(r1 - r0 + 1)) / c.sum()
        out.append((float(row), sl[1].start + c0, sl[1].start + c1))
    return out


def plan_lines(plan: dict) -> dict[str, list[np.ndarray]]:
    """칸 자료 → {벽선: [건물 축 좌표(m) 선분, ...]}. 스캔된 벽 면을 그대로 곧은 선으로 (두께를 지어내지 않는다)."""
    from scipy import ndimage

    res, u0, v0 = plan["res"], plan["u0"], plan["v0"]
    cnt = plan["wall"]
    mask = cnt >= WALL_MIN_POINTS
    if not mask.any():
        return {"벽선": []}
    ref = np.percentile(cnt[mask], 90)
    min_cells = max(2, int(round(WALL_MIN_LEN / res)))
    max_thick = max(1, int(round(FACE_MAX_THICK / res)))
    dens = FACE_MIN_DENSITY * ref
    lines = []
    # 면을 따라 한 칸짜리 빈틈만 잇는다 (가로 면은 가로로, 세로 면은 세로로)
    mh = ndimage.binary_closing(mask, structure=np.ones((1, 3), bool))
    for row, c0, c1 in _faces_one_way(cnt, mh, min_cells, max_thick, dens):
        y = v0 + (row + 0.5) * res
        lines.append(np.array([[u0 + c0 * res, y], [u0 + (c1 + 1) * res, y]]))
    mv = ndimage.binary_closing(mask, structure=np.ones((3, 1), bool))
    for col, r0, r1 in _faces_one_way(cnt.T, mv.T, min_cells, max_thick, dens):
        x = u0 + (col + 0.5) * res
        lines.append(np.array([[x, v0 + r0 * res], [x, v0 + (r1 + 1) * res]]))
    return {"벽선": lines}


def plan_dxf(df: pd.DataFrame, plan: dict, label: str, rooms: list[dict] | None = None,
             walls: list[dict] | None = None) -> bytes:
    """층별 DXF 평면도 (R2010, 단위 mm, 건물 축 좌표).

    rooms([{name, poly} 건물 축 m])를 주면 ROOM_BOUNDARY 레이어에 실 경계와 이름을 넣는다.
    격자점 이름(G001-001)이 CSV 의 point_id 와 같아서, 두께 분석이 이 도면을 측량 좌표에 자동으로 맞춘다.
    """
    import ezdxf

    doc = ezdxf.new("R2010", setup=True)
    doc.header["$INSUNITS"] = 4  # mm
    for name, (color, desc) in LAYERS.items():
        doc.layers.add(name, color=color).description = desc
    msp = doc.modelspace()
    mm = 1000.0

    if plan:
        for layer, lines in plan_lines(plan).items():
            for ln in lines:
                msp.add_lwpolyline((ln * mm).tolist(), close=bool(np.allclose(ln[0], ln[-1])),
                                   dxfattribs={"layer": layer})

    s_mm = float(df["grid_spacing_m"].iloc[0]) * mm if len(df) and "grid_spacing_m" in df else 1500.0
    th = s_mm * 0.08  # 글자 높이 (격자 간격에 맞춤)
    from .las_layout import label_point, room_poly

    for r in rooms or []:
        poly = room_poly(r)
        msp.add_lwpolyline((poly * mm).tolist(), close=True, dxfattribs={"layer": ROOM_LAYER})
        msp.add_text(str(r["name"]), height=th * 1.3, dxfattribs={"layer": ROOM_LAYER}).set_placement(
            tuple(label_point(poly) * mm), align=ezdxf.enums.TextEntityAlignment.MIDDLE_CENTER)
    for poly in wall_shapes(plan, walls):  # 해치만 (닫힌 선을 쓰면 두께 분석이 방으로 읽음)
        h = msp.add_hatch(color=8, dxfattribs={"layer": "벽"})
        h.paths.add_polyline_path([(float(x) * mm, float(y) * mm) for x, y in poly], is_closed=True)
    for r in df[has_data(df)].itertuples(index=False):
        x, y = r.local_x * mm, r.local_y * mm
        msp.add_circle((x, y), th * 0.4, dxfattribs={"layer": "격자점"})
        msp.add_text(r.point_id, height=th, dxfattribs={"layer": "점번호"}).set_placement((x + th * 0.6, y + th * 0.3))
        f = "-" if pd.isna(r.floor_z) else f"{r.floor_z:.3f}"
        c = "-" if pd.isna(r.ceiling_z) else f"{r.ceiling_z:.3f}"
        h = "" if pd.isna(r.height_mm) else f" H{r.height_mm:.0f}"
        msp.add_text(f"F{f} C{c}{h}", height=th * 0.7,
                     dxfattribs={"layer": "높이"}).set_placement((x + th * 0.6, y - th * 0.9))

    if len(df):
        top = df["local_y"].max() * mm + s_mm
        left = df["local_x"].min() * mm
        angle = df["grid_angle_deg"].iloc[0] if "grid_angle_deg" in df else 0
        msp.add_text(f"{label} LAS 평면도 (건물 축 기준, 단위 mm, 측량 좌표에서 {angle:g}° 회전)",
                     height=th * 2, dxfattribs={"layer": "제목"}).set_placement((left, top))

    buf = io.StringIO()
    doc.write(buf)
    return buf.getvalue().encode("utf-8")


def has_data(df: pd.DataFrame) -> pd.Series:
    """바닥·천장 중 하나라도 값이 있는 격자점 (그림·도면에는 이것만 그린다; 값 없는 점은 CSV 에만 남는다)."""
    return df["floor_z"].notna() | df["ceiling_z"].notna()


def wall_shapes(plan: dict | None, walls: list[dict] | None = None) -> list[np.ndarray]:
    """벽 그림용 다각형들: 실무자가 고친 벽(walls)이 있으면 그것, 없으면 자동 추정 띠."""
    if walls is not None:
        from .las_layout import wall_polygon

        return [wall_polygon(w) for w in walls]
    return [np.array([[x0, y0], [x1, y0], [x1, y1], [x0, y1]]) for x0, x1, y0, y1 in (wall_bands(plan)[0] if plan else [])]


def plan_figure(dxf_bytes: bytes, df: pd.DataFrame, plan: dict | None = None, walls: list[dict] | None = None):
    """화면 미리보기: 벽 띠(회색) + DXF 의 벽선 + 값이 있는 격자점(마우스를 올리면 이름·높이). plotly 그림 (단위 m)."""
    import ezdxf
    import plotly.graph_objects as go

    doc = ezdxf.read(io.StringIO(dxf_bytes.decode("utf-8")))
    fig = go.Figure()
    shapes = wall_shapes(plan, walls)
    if shapes:
        bx, by = [], []
        for poly in shapes:
            ring = np.vstack([poly, poly[:1]])
            bx += list(ring[:, 0]) + [None]
            by += list(ring[:, 1]) + [None]
        name = "벽 (방 배치에서 고친 벽)" if walls is not None else f"벽 (추정, 두께 약 {wall_bands(plan)[1] * 1000:.0f} mm)"
        fig.add_trace(go.Scatter(x=bx, y=by, mode="lines", fill="toself", fillcolor="rgba(148,163,184,0.55)",
                                 line=dict(width=0), name=name, hoverinfo="skip"))
    style = {"벽선": dict(color="#334155", width=1.2)}
    for layer, line in style.items():
        xs, ys = [], []
        for e in doc.modelspace().query(f'LWPOLYLINE[layer=="{layer}"]'):
            pts = [(x / 1000, y / 1000) for x, y, *_ in e.get_points()]
            if e.closed and pts:
                pts.append(pts[0])
            xs += [p[0] for p in pts] + [None]
            ys += [p[1] for p in pts] + [None]
        if xs:
            fig.add_trace(go.Scatter(x=xs, y=ys, mode="lines", line=line, name=layer, hoverinfo="skip"))

    def fmt(v, f):
        return "-" if pd.isna(v) else f.format(v)

    df = df[has_data(df)]
    hover = [f"<b>{r.point_id}</b><br>바닥 {fmt(r.floor_z, '{:.3f}')} m<br>천장 {fmt(r.ceiling_z, '{:.3f}')} m"
             f"<br>층고 {fmt(r.height_mm, '{:.0f}')} mm"
             + ("<br><b>벽 위 — 슬라브 면을 잴 수 없어 값을 비움</b>" if getattr(r, "on_wall", False) else "")
             for r in df.itertuples(index=False)]
    ok = df["floor_z"].notna() & df["ceiling_z"].notna()
    fig.add_trace(go.Scatter(x=df["local_x"], y=df["local_y"], mode="markers+text", name="격자점",
                             text=df["point_id"], textposition="top right", textfont=dict(size=9, color="#64748b"),
                             marker=dict(size=7, color="#dc2626", symbol=np.where(ok, "circle", "circle-open")),
                             customdata=df["point_id"], hovertext=hover, hoverinfo="text"))
    fig.update_layout(margin=dict(l=10, r=10, t=10, b=10), plot_bgcolor="white", dragmode="select",
                      legend=dict(orientation="h", y=1.02, x=0), hoverlabel=dict(bgcolor="white"))
    fig.update_xaxes(showgrid=False, zeroline=False, title="건물 축 X (m)")
    fig.update_yaxes(showgrid=False, zeroline=False, title="건물 축 Y (m)", scaleanchor="x", scaleratio=1)
    return fig


FACE_PAIR_GAP = (0.05, 0.40)  # 마주 본 두 벽 면 사이가 이 범위면 한 벽 (m)
OUTER_WALL_MIN = 0.15  # 외벽 띠 두께의 최소값 (칸막이벽 두께 중앙값이 이보다 얇으면 이 값)


def wall_bands(plan: dict) -> tuple[list[list[float]], float]:
    """벽을 회색 띠로: ([x0, x1, y0, y1] 건물 축 m, 추정 벽 두께 m).

    마주 본 두 벽 면(간격 FACE_PAIR_GAP)은 그 사이를 띠로, 짝이 없는 면(외벽처럼 한쪽만 스캔된 면)은 바닥면이 적은 쪽
    (= 바깥)으로 칸막이벽 두께 중앙값만큼 띠를 그린다. 그림용 추정이며 계산에는 쓰지 않는다.
    """
    lines = plan_lines(plan)["벽선"] if plan else []
    if not lines:
        return [], OUTER_WALL_MIN
    res, u0, v0 = plan["res"], plan["u0"], plan["v0"]
    floor = plan["floor"] > 0
    H = [(ln[0, 1], min(ln[0, 0], ln[-1, 0]), max(ln[0, 0], ln[-1, 0])) for ln in lines if abs(ln[0, 1] - ln[-1, 1]) < 1e-9]
    V = [(ln[0, 0], min(ln[0, 1], ln[-1, 1]), max(ln[0, 1], ln[-1, 1])) for ln in lines if abs(ln[0, 0] - ln[-1, 0]) < 1e-9]

    def pairs(F):
        used, out, gaps = set(), [], []
        for i, (c1, a1, b1) in enumerate(F):
            best = None
            for j, (c2, a2, b2) in enumerate(F):
                if j == i or j in used or i in used:
                    continue
                gap, ov = c2 - c1, min(b1, b2) - max(a1, a2)
                if FACE_PAIR_GAP[0] <= gap <= FACE_PAIR_GAP[1] and ov >= 0.5 * min(b1 - a1, b2 - a2):
                    if best is None or gap < best[0]:
                        best = (gap, j, max(a1, a2), min(b1, b2))
            if best:
                gap, j, a, b = best
                used |= {i, j}
                out.append((c1, c1 + gap, a, b))
                gaps.append(gap)
        return out, [f for k, f in enumerate(F) if k not in used], gaps

    hp, hs, g1 = pairs(H)
    vp, vs, g2 = pairs(V)
    gaps = g1 + g2
    t = max(OUTER_WALL_MIN, float(np.median(gaps))) if gaps else 0.2

    def floor_near(x0, x1, y0, y1):
        i0, i1 = int((x0 - u0) / res), int(np.ceil((x1 - u0) / res))
        j0, j1 = int((y0 - v0) / res), int(np.ceil((y1 - v0) / res))
        a = floor[max(j0, 0):max(j1, 0), max(i0, 0):max(i1, 0)]
        return a.mean() if a.size else 0.0

    bands = [[a, b, c1, c2] for c1, c2, a, b in hp] + [[c1, c2, a, b] for c1, c2, a, b in vp]
    for c, a, b in hs:  # 가로 면 하나: 위·아래 중 바닥이 적은 쪽으로
        up, dn = floor_near(a, b, c + 0.1, c + 0.4), floor_near(a, b, c - 0.4, c - 0.1)
        bands.append([a, b, c, c + t] if up < dn else [a, b, c - t, c])
    for c, a, b in vs:
        rt, lf = floor_near(c + 0.1, c + 0.4, a, b), floor_near(c - 0.4, c - 0.1, a, b)
        bands.append([c, c + t, a, b] if rt < lf else [c - t, c, a, b])
    return [[round(float(v), 3) for v in bd] for bd in bands], round(t, 3)
