"""3D 보기: 기준 두께 높이에 반투명 판을 깔고, 측정점마다 기준과의 차이만큼 막대를 세운다.

통과한 점은 판 위로 솟고(초록), 미달인 점은 판 아래로 내려간다(빨강). 0부터 세우면 120mm 와
125mm 가 거의 같아 보여서 기준 판을 0으로 둔다. 평면 좌표는 m, 높이는 mm 로 축척이 달라
(차이가 평면보다 수천 배 작다) 높이 축을 따로 늘려 보여준다.
"""
from __future__ import annotations

import numpy as np
import plotly.graph_objects as go
from scipy.spatial import cKDTree

from .core import AnalysisResult

COLORS = {"적합": "#2e9d5b", "미달": "#d64545"}
LABELS = {"적합": "기준 통과", "미달": "기준 미달"}
MAX_ROOM_LABELS = 12

# 직육면체 한 개의 삼각형 12개 (꼭짓점 0~3 바닥, 4~7 윗면)
_FACES = np.array([
    (0, 1, 2), (0, 2, 3), (4, 5, 6), (4, 6, 7),
    (0, 1, 5), (0, 5, 4), (1, 2, 6), (1, 6, 5),
    (2, 3, 7), (2, 7, 6), (3, 0, 4), (3, 4, 7),
])


def _boxes(xy: np.ndarray, heights: np.ndarray, half: float):
    """z=0 에서 heights 까지(음수면 아래로) 막대 여러 개를 Mesh3d 한 개로 합친 꼭짓점·면 배열."""
    n = len(xy)
    dx = np.array([-half, half, half, -half] * 2)
    dy = np.array([-half, -half, half, half] * 2)
    x = (xy[:, :1] + dx).ravel()
    y = (xy[:, 1:] + dy).ravel()
    z = np.column_stack([np.zeros((n, 4)), np.repeat(heights[:, None], 4, axis=1)]).ravel()
    faces = (_FACES[None, :, :] + 8 * np.arange(n)[:, None, None]).reshape(-1, 3)
    return x, y, z, faces


def plot_3d(result: AnalysisResult) -> go.Figure:
    pts = result.points
    s = result.settings
    limit = s.design_mm - s.tolerance_mm
    # 도면 좌표를 m 단위로 (변환 축척이 도면 단위 → m)
    unit = result.transform.scale if result.transform is not None else 1.0
    origin = pts[["cad_x", "cad_y"]].min().to_numpy()
    xy_all = (pts[["cad_x", "cad_y"]].to_numpy() - origin) * unit

    if len(xy_all) > 1:
        d, _ = cKDTree(xy_all).query(xy_all, k=2)
        spacing = float(np.median(d[:, 1]))
    else:
        spacing = 1.0
    half = spacing * 0.22

    fig = go.Figure()

    # 방 경계선과 방 이름 (바닥면 z=0)
    if result.plan is not None and result.plan.rooms:
        lx, ly = [], []
        names_x, names_y, names = [], [], []
        name_of = dict(zip(pts["room_id"], pts["room"]))
        for room in result.plan.rooms:
            poly = (np.vstack([room.polygon, room.polygon[:1]]) - origin) * unit
            lx += [*poly[:, 0], None]
            ly += [*poly[:, 1], None]
            c = (room.label_xy - origin) * unit
            names_x.append(c[0])
            names_y.append(c[1])
            names.append(name_of.get(room.room_id, room.name))
        fig.add_trace(go.Scatter3d(
            x=lx, y=ly, z=[0 if v is not None else None for v in lx], mode="lines",
            line=dict(color="#8a8f98", width=2), name="방 경계", hoverinfo="skip"))
        # 방이 많으면 이름 글자가 겹쳐 읽을 수 없다 — 그때는 막대에 마우스를 올려 본다
        if len(names) <= MAX_ROOM_LABELS:
            fig.add_trace(go.Scatter3d(
                x=names_x, y=names_y, z=[0] * len(names), mode="text", text=names,
                textfont=dict(size=11, color="#3b4252"), name="방 이름", hoverinfo="skip",
                showlegend=False))

    # 두께 막대 (통과 / 미달)
    for judgement in ("적합", "미달"):
        sel = (pts["judgement"] == judgement).to_numpy()
        if not sel.any():
            continue
        sub = pts[sel]
        x, y, z, faces = _boxes(xy_all[sel], sub["thickness_mm"].to_numpy() - limit, half)
        hover = [f"{p} · {r}<br>두께 {t:.0f}mm · 기준보다 {t - limit:+.0f}mm ({LABELS[judgement]})"
                 for p, r, t in zip(sub["point_id"], sub["room"], sub["thickness_mm"])]
        fig.add_trace(go.Mesh3d(
            x=x, y=y, z=z, i=faces[:, 0], j=faces[:, 1], k=faces[:, 2],
            color=COLORS[judgement], flatshading=True, name=f"{LABELS[judgement]} ({sel.sum()}점)",
            showlegend=True, text=np.repeat(hover, 8), hovertemplate="%{text}<extra></extra>",
            lighting=dict(ambient=0.6, diffuse=0.8)))

    # 제외된 점: 바닥에 회색 점
    ex = pts["excluded"].to_numpy()
    if ex.any():
        fig.add_trace(go.Scatter3d(
            x=xy_all[ex, 0], y=xy_all[ex, 1], z=np.zeros(ex.sum()), mode="markers",
            marker=dict(size=3, color="#9aa0a6", symbol="x"), name=f"제외된 점 ({ex.sum()}점)",
            text=[f"{p} · 제외: {r}" for p, r in zip(pts.loc[ex, "point_id"], pts.loc[ex, "exclude_reason"])],
            hovertemplate="%{text}<extra></extra>"))

    # 기준 두께 판 (반투명)
    (x0, y0), (x1, y1) = xy_all.min(0) - spacing, xy_all.max(0) + spacing
    fig.add_trace(go.Mesh3d(
        x=[x0, x1, x1, x0], y=[y0, y0, y1, y1], z=[0] * 4, i=[0, 0], j=[1, 2], k=[2, 3],
        color="#2f6fd6", opacity=0.22, name=f"기준 판 {limit:g}mm (설계 {s.design_mm:g} − 허용 {s.tolerance_mm:g})",
        showlegend=True, hoverinfo="skip"))

    span = max(x1 - x0, y1 - y0)
    dev = pts.loc[~pts["excluded"], "thickness_mm"].to_numpy() - limit
    zlo = min(float(np.nanmin(dev, initial=0.0)), -10.0) * 1.15
    zhi = max(float(np.nanmax(dev, initial=0.0)), 10.0) * 1.15
    fig.update_layout(
        height=620,
        margin=dict(l=0, r=0, t=10, b=0),
        legend=dict(orientation="h", yanchor="bottom", y=0.98, x=0),
        scene=dict(
            xaxis=dict(title="", showticklabels=False, showbackground=False),
            yaxis=dict(title="", showticklabels=False, showbackground=False),
            zaxis=dict(title="기준보다 (mm)", range=[zlo, zhi], zeroline=True),
            aspectmode="manual",
            aspectratio=dict(x=(x1 - x0) / span, y=(y1 - y0) / span, z=0.45),
            camera=dict(eye=dict(x=0.55, y=-1.05, z=0.6)),
        ),
    )
    return fig
