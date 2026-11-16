"""화면용 그림 (plotly): 측정점 위치도(메인), 방별 두께도(서브), 3D 보기.

색은 slab/plot.py 의 두께 색 막대(THICK_CMAP)와 같다. 휠로 확대·축소, 끌어서 이동, 점을 누르면 선택된다.
"""
from __future__ import annotations

import numpy as np
import plotly.graph_objects as go

from .core import STATE_NONE, STATE_OUTSIDE, AnalysisResult
from .plot import (
    GRAY_DARK, ROOM_EDGE, ROOM_FILL, ROOM_SOFTEN, STATUS, THICK_COLORS, VALUE_STATES, norm_of, point_label, room_cells,
    room_display, thickness_color, unit_scale,
)

MAX_ROOM_LABELS = 80
FONT = "Malgun Gothic, Apple SD Gothic Neo, Noto Sans KR, sans-serif"
COLORSCALE = [[i / (len(THICK_COLORS) - 1), c] for i, c in enumerate(THICK_COLORS)]


LABEL_MODES = {"off": "끄기", "value": "두께만", "full": "번호 + 두께"}
ROTATIONS = (0, 90, 180, 270)  # 도면 돌리기 (시계 방향, 도)


def rotate(xy, deg: int) -> np.ndarray:
    """도면 좌표를 시계 방향으로 deg(0·90·180·270)만큼 돌린다. 화면에서 도면 방향만 바꾸는 용도."""
    a = np.asarray(xy, float)
    x, y = a[..., 0], a[..., 1]
    k = (int(deg) // 90) % 4
    out = (x, y) if k == 0 else (y, -x) if k == 1 else (-x, -y) if k == 2 else (-y, x)
    return np.stack(out, axis=-1)


def _room_outlines(fig: go.Figure, result: AnalysisResult, rot: int = 0, fills: dict | None = None,
                   hover: dict | None = None):
    for room, name, mean, n in room_cells(result):
        poly = rotate(np.vstack([room.polygon, room.polygon[:1]]), rot)
        fig.add_trace(go.Scatter(
            x=poly[:, 0], y=poly[:, 1], mode="lines", fill="toself",
            fillcolor=(fills or {}).get(room.room_id, ROOM_FILL), line=dict(color=ROOM_EDGE, width=1.5),
            hoveron="fills", hoverinfo="text" if hover else "skip",
            text=(hover or {}).get(room.room_id, ""), name=name, showlegend=False))


def _extent(result: AnalysisResult, rot: int) -> tuple[np.ndarray, np.ndarray]:
    xy = [result.points[["cad_x", "cad_y"]].to_numpy(float)]
    if result.plan is not None:
        xy += [r.polygon for r in result.plan.rooms]
    a = rotate(np.vstack(xy), rot)
    return a.min(0), a.max(0)


def _layout(fig: go.Figure, height: int, lo=None, hi=None, label_pad: float = 0.0) -> go.Figure:
    """축을 숨기고 같은 축척으로. lo/hi 가 있으면 여백을 두어 이름표가 그림 밖으로 잘리지 않게 한다."""
    fig.update_xaxes(visible=False)
    fig.update_yaxes(visible=False, scaleanchor="x", scaleratio=1)
    if lo is not None:
        pad = 0.03 * float(max(hi - lo))
        fig.update_xaxes(range=[lo[0] - pad, hi[0] + pad + label_pad])
        fig.update_yaxes(range=[lo[1] - pad - label_pad * 0.25, hi[1] + pad])
    fig.update_layout(
        height=height, margin=dict(l=0, r=0, t=30, b=0), plot_bgcolor="white", dragmode="pan",
        legend=dict(orientation="h", yanchor="bottom", y=1.0, x=0, font=dict(size=13)),
        hoverlabel=dict(font=dict(size=14, family=FONT)), font=dict(family=FONT), uirevision="keep")
    return fig


def _hover_point(p) -> str:
    head = f"<b>{p['point_id']}</b> · {room_display(p['room'])}<br>{p['status']}"
    if p["status"] in VALUE_STATES:
        return head + f" · <b>{p['thickness_mm']:.0f}mm</b><br>{p['calc_method']}"
    if p["status"] == STATE_NONE:
        return head + f" · {p['no_reason']}"
    return head


def _label(p, mode: str) -> str:
    if mode == "full":
        return point_label(p)
    if p["status"] in VALUE_STATES:
        return f"{p['thickness_mm']:.0f}"
    return "×" if p["status"] == STATE_NONE else ""


def plot_point_map(result: AnalysisResult, labels: str = "off", rot: int = 0, height: int = 640) -> go.Figure:
    """측정점 위치도. labels: off(끄기)·value(두께만)·full(번호 + 두께). 이름표는 점의 오른쪽 아래에 작게 둔다.
    rot: 도면을 시계 방향으로 돌리는 각도(0·90·180·270). 점의 customdata 는 point_id."""
    pts = result.points
    fig = go.Figure()
    _room_outlines(fig, result, rot)
    if result.plan is not None and len(result.plan.rooms) <= MAX_ROOM_LABELS:
        name_of = dict(zip(pts["room_id"], pts["room"]))
        for r in result.plan.rooms:
            x, y = rotate(r.label_xy, rot)
            fig.add_annotation(x=x, y=y, showarrow=False, text=room_display(name_of.get(r.room_id, r.name)),
                               font=dict(size=10, color=ROOM_EDGE),
                               opacity=0.9)

    s = result.settings
    lo_c, hi_c = sorted((s.color_min_mm, s.color_max_mm))
    show = labels in ("value", "full")
    mode = "markers+text" if show else "markers"
    text_style = dict(textposition="bottom right", textfont=dict(size=9 if labels == "full" else 10))

    val = pts[pts["status"].isin(VALUE_STATES)]
    xy = rotate(val[["cad_x", "cad_y"]].to_numpy(float), rot)
    review = val["status"].map(lambda v: STATUS[v]["review"]).to_numpy(bool)
    fig.add_trace(go.Scatter(
        x=xy[:, 0], y=xy[:, 1], mode=mode, name="산출 (색 = 두께)", cliponaxis=False,
        text=[_label(p, labels) for _, p in val.iterrows()] if show else None, **text_style,
        customdata=val["point_id"], hovertext=[_hover_point(p) for _, p in val.iterrows()],
        hovertemplate="%{hovertext}<extra></extra>",
        marker=dict(size=11, color=val["thickness_mm"].clip(lo_c, hi_c), colorscale=COLORSCALE, cmin=lo_c, cmax=hi_c,
                    line=dict(color=np.where(review, "#1f2328", "#5b6470"), width=np.where(review, 2.5, 0.5)),
                    colorbar=dict(title=dict(text="두께(mm)", side="right"), thickness=12, len=0.6))))
    for state, symbol, name in ((STATE_NONE, "x-thin", "미산출 (회색 ×)"),
                                (STATE_OUTSIDE, "circle-open", "영역 외 (회색 ○)")):
        g = pts[pts["status"] == state]
        if g.empty:
            continue
        gxy = rotate(g[["cad_x", "cad_y"]].to_numpy(float), rot)
        fig.add_trace(go.Scatter(
            x=gxy[:, 0], y=gxy[:, 1], mode=mode if labels == "full" else "markers", name=name, cliponaxis=False,
            text=[_label(p, labels) for _, p in g.iterrows()] if labels == "full" else None,
            textposition="bottom right", textfont=dict(size=9, color=GRAY_DARK), customdata=g["point_id"],
            hovertext=[_hover_point(p) for _, p in g.iterrows()], hovertemplate="%{hovertext}<extra></extra>",
            marker=dict(size=9, symbol=symbol, color=GRAY_DARK, line=dict(width=2, color=GRAY_DARK))))
    lo, hi = _extent(result, rot)
    # 이름표가 오른쪽 아래로 나가는 몫 (1m 남짓) 만큼 여백
    pad = (1.4 if labels == "full" else 0.5 if labels == "value" else 0.0) / unit_scale(result)
    return _layout(fig, height, lo, hi, pad)


def zoom_to(fig: go.Figure, xy: np.ndarray, pad: float, rot: int = 0) -> go.Figure:
    """xy(도면 좌표) 점들을 둘러싼 범위로 확대한다. 그림이 돌아가 있으면 같은 각도로 돌려서 맞춘다."""
    a = rotate(xy, rot)
    lo, hi = np.min(a, 0) - pad, np.max(a, 0) + pad
    fig.update_xaxes(range=[lo[0], hi[0] + pad])  # 오른쪽은 이름표 몫
    fig.update_yaxes(range=[lo[1] - pad * 0.5, hi[1]])
    fig.update_layout(uirevision=f"{lo.round(1)}{hi.round(1)}")
    return fig


def plot_room_map(result: AnalysisResult, rot: int = 0, height: int = 560) -> go.Figure:
    """방별 두께도: 방을 방 평균 두께 색으로 칠한다."""
    norm = norm_of(result)
    cells = room_cells(result)
    fills = {c[0].room_id: thickness_color(c[2], norm, ROOM_SOFTEN) for c in cells}
    hover = {c[0].room_id: (f"<b>{room_display(c[1])}</b><br>평균 {c[2]:.0f}mm · 산출 완료 {c[3]}점"
                            if np.isfinite(c[2]) else f"<b>{room_display(c[1])}</b><br>값 없음") for c in cells}
    fig = go.Figure()
    _room_outlines(fig, result, rot, fills, hover)
    if len(cells) <= MAX_ROOM_LABELS:
        for room, name, mean, n in cells:
            x, y = rotate(room.label_xy, rot)
            fig.add_annotation(
                x=x, y=y, showarrow=False,
                text=f"{room_display(name)}<br><b>{mean:.0f}mm</b>" if np.isfinite(mean) else room_display(name),
                font=dict(size=11, color="#1f2328"))
    s = result.settings
    lo, hi = sorted((s.color_min_mm, s.color_max_mm))
    fig.add_trace(go.Scatter(x=[None], y=[None], mode="markers", showlegend=False, hoverinfo="skip",
                             marker=dict(colorscale=COLORSCALE, cmin=lo, cmax=hi, color=[lo], showscale=True,
                                         colorbar=dict(title=dict(text="방 평균(mm)", side="right"), thickness=12,
                                                       len=0.6))))
    elo, ehi = _extent(result, rot)
    return _layout(fig, height, elo, ehi)


# ------------------------------------------------------------------ 3D 보기
def _triangulate(poly: np.ndarray) -> list[tuple[int, int, int]]:
    """단순 다각형(오목 포함)을 귀 자르기로 삼각형 분할한다."""
    n = len(poly)
    x, y = poly[:, 0], poly[:, 1]
    ccw = (np.dot(x, np.roll(y, -1)) - np.dot(np.roll(x, -1), y)) > 0
    idx = list(range(n)) if ccw else list(range(n))[::-1]

    def cross(a, b, c):
        return (poly[b, 0] - poly[a, 0]) * (poly[c, 1] - poly[a, 1]) - \
               (poly[b, 1] - poly[a, 1]) * (poly[c, 0] - poly[a, 0])

    def inside(p, a, b, c):
        return cross(a, b, p) >= 0 and cross(b, c, p) >= 0 and cross(c, a, p) >= 0

    tris = []
    guard = 0
    while len(idx) > 3 and guard < n * n:
        guard += 1
        for k in range(len(idx)):
            a, b, c = idx[k - 1], idx[k], idx[(k + 1) % len(idx)]
            if cross(a, b, c) <= 0:
                continue
            if any(inside(p, a, b, c) for p in idx if p not in (a, b, c)):
                continue
            tris.append((a, b, c))
            idx.pop(k)
            break
        else:  # 귀를 못 찾으면(자기 교차 등) 남은 부분은 부채꼴로
            break
    tris += [(idx[0], idx[k], idx[k + 1]) for k in range(1, len(idx) - 1)]
    return tris


def _prisms(polys: list[np.ndarray], heights: list[float]):
    """방 바닥(z=0)에서 높이 h 까지 세운 닫힌 기둥들을 Mesh3d 한 개 분량의 꼭짓점·면으로."""
    xs, ys, zs, faces = [], [], [], []
    base = 0
    for poly, h in zip(polys, heights):
        n = len(poly)
        xs += [*poly[:, 0], *poly[:, 0]]
        ys += [*poly[:, 1], *poly[:, 1]]
        zs += [0.0] * n + [h] * n
        tris = _triangulate(poly)
        faces += [(base + n + a, base + n + b, base + n + c) for a, b, c in tris]
        faces += [(base + a, base + c, base + b) for a, b, c in tris]
        for k in range(n):
            k1 = (k + 1) % n
            faces += [(base + k, base + k1, base + n + k1), (base + k, base + n + k1, base + n + k)]
        base += 2 * n
    return np.array(xs), np.array(ys), np.array(zs), np.array(faces).reshape(-1, 3)


def plot_3d(result: AnalysisResult) -> go.Figure:
    """방마다 판을 세운다. 높이는 방 평균 두께가 층 평균보다 두꺼운지(+) / 얇은지(−)."""
    pts = result.points
    norm = norm_of(result)
    unit = unit_scale(result)
    base_mm = float(result.summary["mean_mm"]) if np.isfinite(result.summary["mean_mm"]) else 0.0
    cells = [c for c in room_cells(result) if np.isfinite(c[2])]
    fig = go.Figure()
    allxy = np.vstack([c[0].polygon for c in cells]) if cells else pts[["cad_x", "cad_y"]].to_numpy()
    origin = allxy.min(0)

    def to_m(a):
        return (np.asarray(a) - origin) * unit

    devs = []
    for room, name, mean, n in cells:
        h = mean - base_mm
        devs.append(h)
        x, y, z, f = _prisms([to_m(room.polygon)], [h if abs(h) > 0.3 else 0.3])
        fig.add_trace(go.Mesh3d(
            x=x, y=y, z=z, i=f[:, 0], j=f[:, 1], k=f[:, 2], color=thickness_color(mean, norm), opacity=1.0,
            flatshading=True, showlegend=False, hovertemplate=(f"<b>{room_display(name)}</b><br>평균 {mean:.0f}mm · "
                                                               f"층 평균보다 {h:+.0f}mm<extra></extra>"),
            lighting=dict(ambient=0.6, diffuse=0.9, specular=0.1, roughness=0.6)))
    if not cells:
        ok = pts[pts["status"].isin(VALUE_STATES)]
        xy = to_m(ok[["cad_x", "cad_y"]].to_numpy())
        d = ok["thickness_mm"].to_numpy() - base_mm
        devs += list(d)
        fig.add_trace(go.Scatter3d(x=xy[:, 0], y=xy[:, 1], z=d, mode="markers", name="측정점",
                                   marker=dict(size=4, color=[thickness_color(v, norm) for v in ok["thickness_mm"]])))
    m = to_m(allxy)
    (x0, y0), (x1, y1) = m.min(0), m.max(0)
    fig.add_trace(go.Mesh3d(x=[x0, x1, x1, x0], y=[y0, y0, y1, y1], z=[0] * 4, i=[0, 0], j=[1, 2], k=[2, 3],
                            color="#2f6fd6", opacity=0.10, name=f"층 평균 {base_mm:.0f}mm", showlegend=True,
                            hoverinfo="skip"))
    span = max(x1 - x0, y1 - y0, 1e-9)
    zlo = min(min(devs, default=0.0), -10.0) * 1.2
    zhi = max(max(devs, default=0.0), 10.0) * 1.2
    fig.update_layout(
        height=600, margin=dict(l=0, r=0, t=10, b=0), font=dict(family=FONT),
        legend=dict(orientation="h", yanchor="bottom", y=0.97, x=0, font=dict(size=13)),
        hoverlabel=dict(font=dict(size=14, family=FONT)),
        scene=dict(xaxis=dict(visible=False), yaxis=dict(visible=False),
                   zaxis=dict(title=dict(text="층 평균보다<br>두꺼움 + / 얇음 − (mm)"), range=[zlo, zhi],
                              backgroundcolor="#f7f9fc", gridcolor="#e3e8ef"),
                   aspectmode="manual", aspectratio=dict(x=(x1 - x0) / span, y=(y1 - y0) / span, z=0.2),
                   camera=dict(eye=dict(x=0.05, y=-0.6, z=1.05))))
    return fig
