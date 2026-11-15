"""포인트 위치도 (도면 좌표 기준 평면도 위에 두께 표시)."""
from __future__ import annotations

import io

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
from matplotlib import font_manager
from matplotlib.colors import TwoSlopeNorm
from matplotlib.lines import Line2D
from matplotlib.patches import Patch, Polygon

from .core import AnalysisResult, Room

# 판정 색: 넓은 면은 옅은 색, 테두리·글자는 진한 색 (색약이어도 '미달' 글자와 빗금으로 구분된다)
STATUS = {
    "적합": {"fill": "#bfe5cc", "edge": "#2e9d5b", "text": "#1d5e38", "label": "기준 통과"},
    "미달": {"fill": "#f6b8b8", "edge": "#c62f2f", "text": "#8f1d1d", "label": "기준 미달"},
    "판정불가": {"fill": "#e3e6ea", "edge": "#8a8f98", "text": "#4c525c", "label": "판정 못 함"},
    "측정없음": {"fill": "#ffffff", "edge": "#b8bec6", "text": "#8a8f98", "label": "측정점 없음"},
}

_KOREAN_FONTS = (
    "Malgun Gothic",
    "AppleGothic",
    "Apple SD Gothic Neo",
    "NanumGothic",
    "Noto Sans CJK KR",
    "Noto Sans KR",
)


def setup_korean_font() -> str | None:
    installed = {f.name for f in font_manager.fontManager.ttflist}
    plt.rcParams["axes.unicode_minus"] = False
    for name in _KOREAN_FONTS:
        if name in installed:
            plt.rcParams["font.family"] = name
            return name
    return None


setup_korean_font()


def plot_plan(result: AnalysisResult, show_values: bool = True, title: str = ""):
    """실 경계·실명과 측정점(설계 대비 편차 색상)을 그린 Figure를 반환한다."""
    pts = result.points
    s = result.settings
    rooms = result.plan.rooms if result.plan else []

    all_xy = [pts[["cad_x", "cad_y"]].to_numpy()] + [r.polygon for r in rooms]
    xy = np.vstack(all_xy)
    span = xy.max(0) - xy.min(0)
    width = 16
    height = float(np.clip(width * span[1] / max(span[0], 1e-9), 4, 16)) + 1.5
    fig, ax = plt.subplots(figsize=(width, height), dpi=110)

    for r in rooms:
        ax.add_patch(Polygon(r.polygon, closed=True, fill=False, ec="#8a8f98", lw=0.8))
    for r in rooms:
        name = pts.loc[pts["room_id"] == r.room_id, "room"]
        label = name.iloc[0] if len(name) else r.name
        ax.text(*r.label_xy, label, fontsize=7, color="#3b4252", ha="center", va="center",
                bbox=dict(boxstyle="round,pad=0.2", fc="white", ec="none", alpha=0.7))

    ok = pts[~pts["excluded"]]
    ex = pts[pts["excluded"]]
    span_mm = max(30.0, float(np.nanmax(np.abs(ok["deviation_mm"]))) if len(ok) else 30.0)
    norm = TwoSlopeNorm(vcenter=0.0, vmin=-span_mm, vmax=span_mm)
    sc = ax.scatter(ok["cad_x"], ok["cad_y"], c=ok["deviation_mm"], cmap="RdBu", norm=norm,
                    s=60, edgecolors="#333", linewidths=0.4, zorder=3)
    ax.scatter(ex["cad_x"], ex["cad_y"], marker="x", c="#9aa0a6", s=40, linewidths=1.2,
               zorder=3, label="제외")
    below = ok[ok["judgement"] == "미달"]
    ax.scatter(below["cad_x"], below["cad_y"], facecolors="none", edgecolors="#c0392b",
               s=150, linewidths=1.2, zorder=4, label="미달")

    if show_values:
        for _, p in ok.iterrows():
            ax.annotate(f"{p['thickness_mm']:.0f}", (p["cad_x"], p["cad_y"]), xytext=(0, 6),
                        textcoords="offset points", fontsize=6, ha="center", zorder=5)

    cb = fig.colorbar(sc, ax=ax, fraction=0.025, pad=0.01)
    cb.set_label(f"설계({s.design_mm:g}mm) 대비 편차 (mm)")
    ax.set_aspect("equal")
    ax.autoscale_view()
    ax.set_xticks([])
    ax.set_yticks([])
    ax.legend(loc="upper right", fontsize=8)
    ax.set_title(title or "슬래브 두께 포인트 위치도", fontsize=12)
    fig.tight_layout()
    return fig


def room_cells(result: AnalysisResult) -> list[tuple[Room, str, float, str]]:
    """도면의 방마다 (방, 화면에 쓸 이름, 평균 두께, 판정). 측정점이 없는 방은 판정 '측정없음'."""
    if result.plan is None:
        return []
    pts = result.points
    name_of = dict(zip(pts["room_id"], pts["room"]))
    by_name = result.rooms.set_index("room")
    cells = []
    for r in result.plan.rooms:
        name = name_of.get(r.room_id, r.name)
        if name in by_name.index:
            row = by_name.loc[name]
            cells.append((r, name, float(row["mean_mm"]), str(row["judgement"])))
        else:
            cells.append((r, name, float("nan"), "측정없음"))
    return cells


def plot_rooms(result: AnalysisResult, title: str = "", show_points: bool = True):
    """방별 판정도: 방을 판정 색으로 칠하고 방 이름과 평균 두께를 크게 쓴다. 보고서용."""
    pts = result.points
    s = result.settings
    limit = s.design_mm - s.tolerance_mm
    cells = room_cells(result)

    xy = np.vstack([pts[["cad_x", "cad_y"]].to_numpy()] + [c[0].polygon for c in cells])
    span = xy.max(0) - xy.min(0)
    width = 12
    height = float(np.clip(width * span[1] / max(span[0], 1e-9), 3.5, 14)) + 1.2
    fig, ax = plt.subplots(figsize=(width, height), dpi=110)
    diag = float(np.hypot(*span))

    for room, name, mean, j in cells:
        st_ = STATUS[j]
        ax.add_patch(Polygon(room.polygon, closed=True, fc=st_["fill"], ec=st_["edge"], lw=1.6,
                             hatch="///" if j == "미달" else None, zorder=1))
    if show_points:
        ok = pts[~pts["excluded"]]
        ax.scatter(ok["cad_x"], ok["cad_y"], s=9, c=np.where(ok["judgement"] == "미달", "#8f1d1d", "#5b6470"),
                   linewidths=0, zorder=2)
        ex = pts[pts["excluded"]]
        ax.scatter(ex["cad_x"], ex["cad_y"], marker="x", s=16, c="#9aa0a6", linewidths=1, zorder=2)

    # 글자 크기는 방 크기에 맞춘다 (작은 방에 큰 글자가 넘치지 않게)
    for room, name, mean, j in cells:
        st_ = STATUS[j]
        size = float(np.clip(np.sqrt(abs(room.area)) / diag * 60, 6, 12))
        value = f"{mean:.0f}mm" if np.isfinite(mean) else st_["label"]
        if j == "미달":
            value += " 미달"
        ax.text(*room.label_xy, f"{name}\n{value}", fontsize=size, color=st_["text"], ha="center",
                va="center", fontweight="bold", linespacing=1.3, zorder=4,
                bbox=dict(boxstyle="round,pad=0.25", fc="white", ec="none", alpha=0.75))

    used = {c[3] for c in cells}
    handles = [Patch(fc=STATUS[k]["fill"], ec=STATUS[k]["edge"], hatch="///" if k == "미달" else None,
                     label=STATUS[k]["label"] + (f" (평균 {limit:g}mm 이상)" if k == "적합" else
                                                 f" (평균 {limit:g}mm 미만)" if k == "미달" else ""))
               for k in STATUS if k in used]
    if show_points:
        handles += [Line2D([], [], ls="", marker="o", ms=4, color="#5b6470", label="측정점"),
                    Line2D([], [], ls="", marker="x", ms=5, color="#9aa0a6", label="제외된 점")]
    ax.legend(handles=handles, loc="upper center", bbox_to_anchor=(0.5, -0.01), ncol=len(handles),
              fontsize=9, frameon=False)
    ax.set_aspect("equal")
    ax.autoscale_view()
    ax.axis("off")
    ax.set_title(title or "방별 슬래브 두께 판정도", fontsize=13, fontweight="bold")
    fig.tight_layout()
    return fig


def histogram(result: AnalysisResult):
    """두께 분포: 기준선 왼쪽(미달)은 빨강, 오른쪽은 초록."""
    s = result.settings
    limit = s.design_mm - s.tolerance_mm
    v = result.points.loc[~result.points["excluded"], "thickness_mm"].to_numpy()
    fig, ax = plt.subplots(figsize=(10, 3.2), dpi=110)
    if len(v):
        lo, hi = np.floor(min(v.min(), limit - 5)), np.ceil(max(v.max(), s.design_mm + 5))
        bins = np.arange(lo, hi + 2, 2)
        n, edges, patches = ax.hist(v, bins=bins, ec="white", lw=0.6)
        for p, left in zip(patches, edges[:-1]):
            p.set_facecolor(STATUS["미달"]["edge"] if left < limit else STATUS["적합"]["edge"])
    ax.axvline(limit, color="#3b4252", lw=1.2)
    ax.text(limit, ax.get_ylim()[1] * 0.95, f" 기준 {limit:g}mm", va="top", fontsize=9, color="#3b4252")
    if s.tolerance_mm:
        ax.axvline(s.design_mm, color="#8a8f98", lw=1, ls=":")
        ax.text(s.design_mm, ax.get_ylim()[1] * 0.8, f" 설계 {s.design_mm:g}mm", va="top", fontsize=9,
                color="#8a8f98")
    ax.set_xlabel("두께 (mm)")
    ax.set_ylabel("측정점 수")
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    ax.grid(axis="y", color="#eceff3", lw=0.6)
    ax.set_axisbelow(True)
    fig.tight_layout()
    return fig


def figure_svg(fig) -> str:
    buf = io.StringIO()
    fig.savefig(buf, format="svg", bbox_inches="tight")
    plt.close(fig)
    text = buf.getvalue()
    return text[text.index("<svg"):]


def figure_png(fig) -> bytes:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150, bbox_inches="tight")
    plt.close(fig)
    return buf.getvalue()
