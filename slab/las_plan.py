"""LAS 변환 결과로 층별 DXF 평면도를 그린다 (건물 축 기준 좌표, 단위 mm).

- 벽선: 바닥에서 1.0~1.5 m 높이 점(벽 단면, las.WALL_Z)이 있는 칸에서 건물 축에 나란한 곧은 벽만 뽑아
  직사각형(두 줄 선)으로 그린다. 가로·세로로 WALL_MIN_LEN 넘게 이어지고 두께가 WALL_MAX_THICK 이하인 띠만 벽으로 본다
  (가구·사람·잡음 덩어리는 빠진다). 창·문이 뚫린 곳은 끊긴다.
- 격자점: 점(원) + 이름(G001-001) + 바닥·천장 높이(m)와 층고(mm).

칸 자료(plan)는 las.sample_floor 가 LAS 를 읽으면서 채운다 (las._PlanRaster).
"""
from __future__ import annotations

import io

import numpy as np
import pandas as pd

WALL_MIN_POINTS = 3  # 벽 칸으로 볼 최소 점 수 (흩어진 잡음 제외)
WALL_MIN_LEN = 0.5  # 이보다 짧게 이어진 띠는 벽으로 보지 않는다 (m)
WALL_MAX_THICK = 0.6  # 이보다 두꺼운 덩어리는 벽이 아니다 (가구 등, m)
FACE_GAP = 0.3  # 벽 양쪽 면 사이가 이보다 좁으면 한 벽으로 메운다 (m)
ROW_COVER = 0.5  # 벽 띠의 가장 긴 줄의 이 비율 넘게 차 있는 줄만 벽 두께로 친다

LAYERS = {  # 이름: (색 번호, 설명)
    "벽선": (7, "바닥 위 1.0~1.5 m 단면에서 뽑은 곧은 벽"),
    "격자점": (1, "격자점 위치"),
    "점번호": (2, "격자점 이름"),
    "높이": (8, "바닥·천장 높이(m), 층고(mm)"),
    "제목": (7, ""),
}


def _walls_one_way(mask: np.ndarray, min_cells: int, max_thick: int) -> list[tuple[int, int, int, int]]:
    """가로로 곧은 벽 띠 → [(열0, 열1, 행0, 행1)] (칸 번호, 끝 포함)."""
    from scipy import ndimage

    runs, n = ndimage.label(mask, structure=[[0, 0, 0], [1, 1, 1], [0, 0, 0]])  # 줄마다 이어진 칸
    if not n:
        return []
    long_run = np.bincount(runs.ravel())[1:] >= min_cells
    keep = np.zeros(n + 1, bool)
    keep[1:] = long_run
    band = keep[runs]
    lab, m = ndimage.label(band)  # 위아래로 겹친 긴 줄 = 한 벽 띠
    out = []
    for k, sl in enumerate(ndimage.find_objects(lab), start=1):
        sub = lab[sl] == k
        cover = sub.sum(1)
        rows = np.flatnonzero(cover >= ROW_COVER * cover.max())
        r0, r1 = rows[0], rows[-1]
        if r1 - r0 + 1 > max_thick:
            continue
        cols = np.flatnonzero(sub[r0:r1 + 1].any(0))
        c0, c1 = int(np.percentile(cols, 1)), int(np.percentile(cols, 99))
        if c1 - c0 + 1 < min_cells:
            continue
        out.append((sl[1].start + c0, sl[1].start + c1, sl[0].start + r0, sl[0].start + r1))
    return out


def plan_lines(plan: dict) -> dict[str, list[np.ndarray]]:
    """칸 자료 → {벽선: [건물 축 좌표(m) 닫힌 직사각형, ...]}."""
    from scipy import ndimage

    res, u0, v0 = plan["res"], plan["u0"], plan["v0"]
    wall = ndimage.binary_closing(plan["wall"] >= WALL_MIN_POINTS, iterations=1)
    min_cells = max(2, int(round(WALL_MIN_LEN / res)))
    max_thick = max(1, int(round(WALL_MAX_THICK / res)))
    k = max(2, int(round(FACE_GAP / res)) + 1)
    # 스캐너는 벽의 양쪽 면만 본다: 벽과 수직 방향으로만 메워 마주 본 두 면을 한 벽으로 (가로 벽은 위아래로)
    across_h = ndimage.binary_closing(wall, structure=np.ones((k, 1), bool))
    across_v = ndimage.binary_closing(wall, structure=np.ones((1, k), bool))
    rects = []
    for c0, c1, r0, r1 in _walls_one_way(across_h, min_cells, max_thick):  # 가로 벽
        rects.append((c0, c1, r0, r1))
    for r0, r1, c0, c1 in _walls_one_way(across_v.T, min_cells, max_thick):  # 세로 벽 (전치)
        rects.append((c0, c1, r0, r1))
    lines = []
    for c0, c1, r0, r1 in rects:
        x0, x1 = u0 + c0 * res, u0 + (c1 + 1) * res
        y0, y1 = v0 + r0 * res, v0 + (r1 + 1) * res
        lines.append(np.array([[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]]))
    return {"벽선": lines}


def plan_dxf(df: pd.DataFrame, plan: dict, label: str) -> bytes:
    """층별 DXF 평면도 (R2010, 단위 mm, 건물 축 좌표)."""
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
    for r in df.itertuples(index=False):
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


def plan_figure(dxf_bytes: bytes, df: pd.DataFrame):
    """화면 미리보기: DXF 의 벽선 + 격자점(마우스를 올리면 이름·높이). plotly 그림 (단위 m)."""
    import ezdxf
    import plotly.graph_objects as go

    doc = ezdxf.read(io.StringIO(dxf_bytes.decode("utf-8")))
    fig = go.Figure()
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

    hover = [f"<b>{r.point_id}</b><br>바닥 {fmt(r.floor_z, '{:.3f}')} m<br>천장 {fmt(r.ceiling_z, '{:.3f}')} m"
             f"<br>층고 {fmt(r.height_mm, '{:.0f}')} mm" for r in df.itertuples(index=False)]
    ok = df["floor_z"].notna() & df["ceiling_z"].notna()
    fig.add_trace(go.Scatter(x=df["local_x"], y=df["local_y"], mode="markers+text", name="격자점",
                             text=df["point_id"], textposition="top right", textfont=dict(size=9, color="#64748b"),
                             marker=dict(size=7, color=np.where(ok, "#dc2626", "#cbd5e1")),
                             hovertext=hover, hoverinfo="text"))
    fig.update_layout(margin=dict(l=10, r=10, t=10, b=10), plot_bgcolor="white", dragmode="pan",
                      legend=dict(orientation="h", y=1.02, x=0), hoverlabel=dict(bgcolor="white"))
    fig.update_xaxes(showgrid=False, zeroline=False, title="건물 축 X (m)")
    fig.update_yaxes(showgrid=False, zeroline=False, title="건물 축 Y (m)", scaleanchor="x", scaleratio=1)
    return fig
