"""화면용 그림 (plotly): 방별 판정 평면도와 3D 보기.

두 그림 모두 '방 평균 두께로 판정한 결과'를 색으로 칠한다. 결과표와 그림의 색이 항상 같아서
"빨간 점이 있는데 왜 통과야?" 같은 혼동이 없다. 개별 측정점은 마우스를 올리면 볼 수 있다.

3D 보기는 방마다 판을 세운다. 높이는 방 평균 두께가 기준보다 얼마나 두꺼운지(+) / 얇은지(−)이고,
얇은 방은 기준 높이 아래로 꺼진다. 평면 좌표는 m, 높이는 mm 라 축척이 달라 높이 축을 따로 늘린다.
"""
from __future__ import annotations

import numpy as np
import plotly.graph_objects as go

from .core import AnalysisResult
from .plot import STATUS, room_cells

MAX_ROOM_LABELS = 40
FONT = "Malgun Gothic, Apple SD Gothic Neo, Noto Sans KR, sans-serif"
TRANSITION = dict(duration=450, easing="cubic-in-out")


def _hover(name: str, mean: float, j: str, limit: float) -> str:
    if not np.isfinite(mean):
        return f"<b>{name}</b><br>{STATUS[j]['label']}"
    return (f"<b>{name}</b><br>평균 두께 {mean:.0f}mm · 기준보다 {mean - limit:+.0f}mm"
            f"<br>{STATUS[j]['label']}")


def _font_size(area: float, total: float, lo: int = 9, hi: int = 15) -> int:
    return int(np.clip(np.sqrt(abs(area) / max(total, 1e-9)) * 40, lo, hi))


# ------------------------------------------------------------------ 방별 판정 평면도
def plot_room_map(result: AnalysisResult, show_points: bool = True) -> go.Figure:
    pts = result.points
    s = result.settings
    limit = s.design_mm - s.tolerance_mm
    cells = room_cells(result)
    total = sum(abs(c[0].area) for c in cells) or 1.0

    fig = go.Figure()
    for room, name, mean, j in cells:
        st_ = STATUS[j]
        poly = np.vstack([room.polygon, room.polygon[:1]])
        fig.add_trace(go.Scatter(
            x=poly[:, 0], y=poly[:, 1], mode="lines", fill="toself", fillcolor=st_["fill"],
            fillpattern=dict(shape="/", fgcolor=st_["edge"], fgopacity=0.25, size=10) if j == "미달" else None,
            line=dict(color=st_["edge"], width=2), hoveron="fills", hoverinfo="text",
            text=_hover(name, mean, j, limit), name=name, showlegend=False))

    if show_points:
        ok = pts[~pts["excluded"]]
        fig.add_trace(go.Scatter(
            x=ok["cad_x"], y=ok["cad_y"], mode="markers", name="측정점",
            marker=dict(size=5, color=np.where(ok["judgement"] == "미달", "#8f1d1d", "#5b6470")),
            text=[f"{p} · {r}<br>두께 {t:.0f}mm" for p, r, t in
                  zip(ok["point_id"], ok["room"], ok["thickness_mm"])],
            hovertemplate="%{text}<extra></extra>"))
        ex = pts[pts["excluded"]]
        if len(ex):
            fig.add_trace(go.Scatter(
                x=ex["cad_x"], y=ex["cad_y"], mode="markers", name="제외된 점",
                marker=dict(size=7, color="#9aa0a6", symbol="x-thin", line=dict(width=1.5, color="#9aa0a6")),
                text=[f"{p} · 제외: {r}" for p, r in zip(ex["point_id"], ex["exclude_reason"])],
                hovertemplate="%{text}<extra></extra>"))

    if len(cells) <= MAX_ROOM_LABELS:
        for room, name, mean, j in cells:
            value = f"{mean:.0f}mm" if np.isfinite(mean) else STATUS[j]["label"]
            size = _font_size(room.area, total)
            fig.add_annotation(
                x=room.label_xy[0], y=room.label_xy[1], showarrow=False,
                text=f"{name}<br><b style='font-size:{size + 3}px'>{value}</b>",
                font=dict(size=size, color=STATUS[j]["text"], family=FONT),
                bgcolor="rgba(255,255,255,0.72)", borderpad=3)

    # 범례: 실제로 쓰인 판정만
    for k in STATUS:
        if any(c[3] == k for c in cells):
            fig.add_trace(go.Scatter(
                x=[None], y=[None], mode="markers", name=STATUS[k]["label"], legendrank=1,
                marker=dict(size=14, symbol="square", color=STATUS[k]["fill"],
                            line=dict(color=STATUS[k]["edge"], width=2))))

    fig.update_xaxes(visible=False)
    fig.update_yaxes(visible=False, scaleanchor="x", scaleratio=1)
    fig.update_layout(
        height=560, margin=dict(l=0, r=0, t=8, b=0), plot_bgcolor="white",
        legend=dict(orientation="h", yanchor="bottom", y=1.0, x=0, font=dict(size=13)),
        hoverlabel=dict(font=dict(size=14, family=FONT)), font=dict(family=FONT),
        transition=TRANSITION, dragmode="pan")
    return fig


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
        # 윗면과 아랫면(z=0)을 모두 막아 속이 비어 보이지 않게 한다 (꺼진 방은 z=0 쪽이 위로 보인다)
        faces += [(base + n + a, base + n + b, base + n + c) for a, b, c in tris]
        faces += [(base + a, base + c, base + b) for a, b, c in tris]
        for k in range(n):
            k1 = (k + 1) % n
            faces += [(base + k, base + k1, base + n + k1), (base + k, base + n + k1, base + n + k)]
        base += 2 * n
    return np.array(xs), np.array(ys), np.array(zs), np.array(faces).reshape(-1, 3)


def plot_3d(result: AnalysisResult) -> go.Figure:
    pts = result.points
    s = result.settings
    limit = s.design_mm - s.tolerance_mm
    unit = result.transform.scale if result.transform is not None else 1.0
    cells = room_cells(result)
    fig = go.Figure()

    if cells:
        allxy = np.vstack([c[0].polygon for c in cells])
    else:
        allxy = pts[["cad_x", "cad_y"]].to_numpy()
    origin = allxy.min(0)

    def to_m(a):
        return (np.asarray(a) - origin) * unit

    devs = []
    for k in ("적합", "미달", "판정불가"):
        sel = [c for c in cells if c[3] == k]
        if not sel:
            continue
        polys = [to_m(c[0].polygon) for c in sel]
        # 판정 못 한 방은 기준 높이에 얇은 판으로만
        hs = [c[2] - limit if np.isfinite(c[2]) else 0.6 for c in sel]
        devs += hs
        x, y, z, f = _prisms(polys, hs)
        hover = np.concatenate([[_hover(c[1], c[2], k, limit)] * (2 * len(c[0].polygon)) for c in sel])
        fig.add_trace(go.Mesh3d(
            x=x, y=y, z=z, i=f[:, 0], j=f[:, 1], k=f[:, 2], color=STATUS[k]["edge"],
            opacity=1.0, flatshading=True, name=f"{STATUS[k]['label']} ({len(sel)}개 방)", showlegend=True,
            text=hover, hovertemplate="%{text}<extra></extra>",
            lighting=dict(ambient=0.55, diffuse=0.9, specular=0.15, roughness=0.6),
            lightposition=dict(x=-2000, y=-4000, z=8000)))

    # 방 경계선 (기준 높이)
    if cells:
        lx, ly = [], []
        for c in cells:
            poly = to_m(np.vstack([c[0].polygon, c[0].polygon[:1]]))
            lx += [*poly[:, 0], None]
            ly += [*poly[:, 1], None]
        fig.add_trace(go.Scatter3d(
            x=lx, y=ly, z=[0 if v is not None else None for v in lx], mode="lines",
            line=dict(color="#3b4252", width=2), name="방 경계 (기준 높이)", hoverinfo="skip"))
        if len(cells) <= MAX_ROOM_LABELS:
            tops = [max(c[2] - limit, 0) if np.isfinite(c[2]) else 0 for c in cells]
            lab = np.array([to_m(c[0].label_xy) for c in cells])
            fig.add_trace(go.Scatter3d(
                x=lab[:, 0], y=lab[:, 1], z=np.array(tops) + 1.5, mode="text",
                text=[f"<b>{c[1]}</b><br>{c[2]:.0f}mm" if np.isfinite(c[2]) else f"<b>{c[1]}</b>"
                      for c in cells],
                textfont=dict(size=12, color="#1f2328", family=FONT), hoverinfo="skip", showlegend=False))
    else:  # 도면이 없으면 측정점을 기둥 대신 점으로
        ok = pts[~pts["excluded"]]
        xy = to_m(ok[["cad_x", "cad_y"]].to_numpy())
        d = ok["thickness_mm"].to_numpy() - limit
        devs += list(d)
        fig.add_trace(go.Scatter3d(
            x=xy[:, 0], y=xy[:, 1], z=d, mode="markers", name="측정점",
            marker=dict(size=4, color=np.where(d < 0, STATUS["미달"]["edge"], STATUS["적합"]["edge"]))))

    # 기준 높이 판 (아주 옅게: 아래로 꺼진 방이 비쳐 보이도록)
    m = to_m(allxy)
    (x0, y0), (x1, y1) = m.min(0), m.max(0)
    pad = 0.03 * max(x1 - x0, y1 - y0)
    x0, y0, x1, y1 = x0 - pad, y0 - pad, x1 + pad, y1 + pad
    fig.add_trace(go.Mesh3d(
        x=[x0, x1, x1, x0], y=[y0, y0, y1, y1], z=[0] * 4, i=[0, 0], j=[1, 2], k=[2, 3],
        color="#2f6fd6", opacity=0.10, name=f"기준 높이 = {limit:g}mm", showlegend=True, hoverinfo="skip"))

    span = max(x1 - x0, y1 - y0)
    zlo = min(min(devs, default=0.0), -10.0) * 1.2
    zhi = max(max(devs, default=0.0), 10.0) * 1.2
    fig.update_layout(
        height=600, margin=dict(l=0, r=0, t=10, b=0), font=dict(family=FONT),
        legend=dict(orientation="h", yanchor="bottom", y=0.97, x=0, font=dict(size=13)),
        hoverlabel=dict(font=dict(size=14, family=FONT)), transition=TRANSITION,
        scene=dict(
            xaxis=dict(visible=False), yaxis=dict(visible=False),
            zaxis=dict(title=dict(text=f"기준({limit:g}mm)보다<br>두꺼움 + / 얇음 − (mm)"),
                       range=[zlo, zhi], zeroline=True, zerolinecolor="#2f6fd6",
                       backgroundcolor="#f7f9fc", gridcolor="#e3e8ef"),
            aspectmode="manual",
            aspectratio=dict(x=(x1 - x0) / span, y=(y1 - y0) / span, z=0.2),
            # 위에서 비스듬히: 꺼진(미달) 방이 다른 방에 가리지 않는다
            camera=dict(eye=dict(x=0.05, y=-0.6, z=1.05)),
        ),
    )
    return fig
