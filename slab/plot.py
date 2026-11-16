"""보고서·엑셀용 그림 (matplotlib).

- 포인트 위치도(메인): 측정점마다 'P013 / 338mm' 이름표를 두께 색으로 칠한다. 미산출은 회색 ×, 영역 외는 회색 ○.
- 분포도: 같은 내용을 작게 (이름표 없이 점 색만).
- 방별 두께도(서브): 방을 방 평균 두께 색으로 칠한다.
색은 이 파일의 THICK_COLORS(두께 색 막대)와 STATUS(상태별 표시) 한 곳에서 정한다.
"""
from __future__ import annotations

import io

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
from matplotlib import font_manager
from matplotlib.colors import LinearSegmentedColormap, Normalize, to_hex
from matplotlib.lines import Line2D
from matplotlib.patches import Polygon

from .core import (
    STATE_LOW, STATE_NONE, STATE_OK, STATE_OUTLIER, STATE_OUTSIDE, STATE_RANGE, AnalysisResult, Room,
)

# 두께 색 막대: 얇음(초록) → 연노랑 → 두꺼움(주황). 받은 결과 엑셀의 위치도와 같은 방향이다.
# 색 변화가 크면 보기 불편하다는 의견이 있어 채도를 낮추고 빨강은 빼 주황까지만 쓴다.
THICK_COLORS = ["#a9cfb1", "#ebe7c0", "#ecc8a6"]
ROOM_SOFTEN = 0.45  # 방처럼 넓은 면은 흰색을 이만큼 섞어 더 옅게
THICK_CMAP = LinearSegmentedColormap.from_list("thickness", THICK_COLORS)
GRAY, GRAY_DARK, INK = "#9aa0a6", "#6b7280", "#1f2328"
ROOM_FILL, ROOM_EDGE, ROOM_LABEL = "#f7f9fc", "#3b4252", "#eef3fa"

# 상태별 표시: marker 는 점 모양. review(검토 대상)는 표·보고서에서 구분하고, 그림에서는 테두리를 다르게 하지 않는다
# (진한 테두리가 축소하면 검은 점처럼 보여 헷갈린다는 의견)
STATUS = {
    STATE_OK: {"marker": "o", "review": False, "label": "산출 완료"},
    STATE_RANGE: {"marker": "o", "review": True, "label": "두께 범위 검토"},
    STATE_OUTLIER: {"marker": "o", "review": True, "label": "이상치 검토"},
    STATE_LOW: {"marker": "o", "review": True, "label": "두께 비정상(하한 이하)"},
    STATE_NONE: {"marker": "x", "review": False, "label": "미산출"},
    STATE_OUTSIDE: {"marker": "o", "review": False, "label": "영역 외"},
}
VALUE_STATES = (STATE_OK, STATE_RANGE, STATE_OUTLIER, STATE_LOW)

# 굵은 글꼴이 있는 것을 앞에 둔다 (AppleGothic 은 굵게가 없어 findfont 경고가 난다)
_KOREAN_FONTS = (
    "Malgun Gothic",
    "Apple SD Gothic Neo",
    "NanumGothic",
    "AppleGothic",
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


def norm_of(result: AnalysisResult) -> Normalize:
    s = result.settings
    lo, hi = sorted((s.color_min_mm, s.color_max_mm))
    return Normalize(lo, hi if hi > lo else lo + 1, clip=True)


def thickness_color(v: float, norm: Normalize, soften: float = 0.0) -> str:
    """두께 → 색. soften(0~1)만큼 흰색을 섞는다 (방 면적 칠하기용)."""
    if not np.isfinite(v):
        return "#eef0f3"
    rgb = np.array(THICK_CMAP(norm(v))[:3])
    return to_hex(rgb + (1 - rgb) * soften)


def point_label(p) -> str:
    """'P013 / 338mm', 'P071 / 대응점 없음', 'P070 / 영역 외'."""
    if p["status"] == STATE_OUTSIDE:
        return f"{p['point_id']} / 영역 외"
    if p["status"] == STATE_NONE:
        return f"{p['point_id']} / {p['no_reason'] or '미산출'}"
    return f"{p['point_id']} / {p['thickness_mm']:.0f}mm"


def room_display(name: str) -> str:
    """'4호_거실' → '4호 거실' (그림용)."""
    return str(name).replace("_", " ")


def unit_scale(result: AnalysisResult) -> float:
    """도면 좌표 1 단위가 몇 m 인지 (도면이 없으면 측량 좌표라 1)."""
    return result.transform.scale if result.transform is not None else 1.0


def _extent(result: AnalysisResult):
    pts = result.points
    rooms = result.plan.rooms if result.plan else []
    xy = np.vstack([pts[["cad_x", "cad_y"]].to_numpy()] + [r.polygon for r in rooms])
    return xy.min(0), xy.max(0)


def _draw_rooms(ax, result: AnalysisResult, fills: dict | None = None, labels: bool = True, size: float = 9,
                values: dict | None = None):
    if result.plan is None:
        return
    pts = result.points
    name_of = dict(zip(pts["room_id"], pts["room"]))
    for r in result.plan.rooms:
        fc = (fills or {}).get(r.room_id, ROOM_FILL)
        ax.add_patch(Polygon(r.polygon, closed=True, fc=fc, ec=ROOM_EDGE, lw=1.1, zorder=1))
    if not labels:
        return
    for r in result.plan.rooms:
        text = room_display(name_of.get(r.room_id, r.name))
        if values is not None:
            text += f"\n{values.get(r.room_id, '-')}"
        # 글자 뒤에 배경을 두지 않는다 (투명)
        ax.text(*r.label_xy, text, fontsize=size, color=ROOM_EDGE, ha="center", va="center", zorder=2,
                linespacing=1.3, fontweight="bold" if values is not None else "normal")


def _colorbar(fig, ax, result: AnalysisResult, label="슬래브 두께 (mm)"):
    sm = plt.cm.ScalarMappable(norm=norm_of(result), cmap=THICK_CMAP)
    cb = fig.colorbar(sm, ax=ax, orientation="horizontal", fraction=0.035, pad=0.02, aspect=50, shrink=0.35,
                      anchor=(0.0, 1.0), extend="both")
    cb.set_label(label + " · 색 막대 밖의 값은 끝 색", fontsize=9)
    cb.ax.tick_params(labelsize=8)


# ------------------------------------------------------------------ 포인트 위치도 (메인)
def plot_point_map(result: AnalysisResult, title: str = "", px_per_m: int | None = None):
    """측정점마다 'ID / 두께' 이름표를 단 큰 위치도. 해상도는 1m 당 px_per_m 픽셀 (확대해 읽는 용도)."""
    pts = result.points
    norm = norm_of(result)
    ppm = px_per_m or result.settings.map_px_per_m
    lo, hi = _extent(result)
    span_m = (hi - lo) * unit_scale(result)
    dpi = 100
    pad_m = 2.5  # 이름표가 오른쪽으로 삐져나가는 몫
    w_in = float(np.clip((span_m[0] + pad_m * 2) * ppm / dpi, 8, 200))
    h_in = float(np.clip((span_m[1] + pad_m) * ppm / dpi, 5, 200))
    fig, ax = plt.subplots(figsize=(w_in, h_in + 1.0), dpi=dpi)
    fs = float(np.clip(ppm * 0.075, 6, 24))  # 이름표 글자 (pt)
    _draw_rooms(ax, result, size=fs * 1.05)

    for _, p in pts.iterrows():
        x, y = p["cad_x"], p["cad_y"]
        st_ = p["status"]
        if st_ in VALUE_STATES:
            c = thickness_color(p["thickness_mm"], norm)
            ax.plot(x, y, "o", ms=fs * 0.45, color=c, mec="#5b6470", mew=0.3, zorder=3)
            box = dict(boxstyle="round,pad=0.25", fc=c, ec="none", lw=0)
            color = INK
        else:
            ax.plot(x, y, STATUS[st_]["marker"], ms=fs * 0.55, color=GRAY_DARK,
                    mfc="none" if st_ == STATE_OUTSIDE else GRAY_DARK, mew=1.4, zorder=3)
            box = dict(boxstyle="round,pad=0.25", fc="#f4f5f7", ec=GRAY, lw=0.8)
            color = GRAY_DARK
        ax.annotate(point_label(p), (x, y), xytext=(fs * 0.55, 0), textcoords="offset points", fontsize=fs,
                    ha="left", va="center", color=color, bbox=box, zorder=4,
                    arrowprops=dict(arrowstyle="-", color=GRAY, lw=0.6, shrinkA=0, shrinkB=0))

    ax.set_aspect("equal")
    ax.set_xlim(lo[0] - pad_m / unit_scale(result) * 0.4, hi[0] + pad_m / unit_scale(result))
    ax.set_ylim(lo[1] - pad_m / unit_scale(result) * 0.4, hi[1] + pad_m / unit_scale(result) * 0.4)
    ax.axis("off")
    if title:
        ax.set_title(title, fontsize=fs * 1.6, fontweight="bold", loc="left", color="#24476b")
    _colorbar(fig, ax, result)
    handles = [Line2D([], [], ls="", marker="x", color=GRAY_DARK, mew=1.4, ms=8, label="회색 × 미산출"),
               Line2D([], [], ls="", marker="o", mfc="none", color=GRAY_DARK, mew=1.4, ms=8, label="회색 ○ 영역 외")]
    ax.legend(handles=handles, loc="upper right", bbox_to_anchor=(1.0, 0.0), ncol=3, fontsize=max(fs * 0.8, 8),
              frameon=False)
    fig.subplots_adjust(left=0.01, right=0.99, top=0.97, bottom=0.04)
    return fig


# ------------------------------------------------------------------ 분포도 (작게)
def plot_distribution(result: AnalysisResult, title: str = "위치별 슬라브 두께 분포도"):
    """엑셀 첫 시트 위쪽에 넣는 작은 그림: 방 경계 + 두께 색 점 + 회색 ×/○."""
    pts = result.points
    norm = norm_of(result)
    fig, ax = plt.subplots(figsize=(15, 9), dpi=100)
    _draw_rooms(ax, result, size=9)
    val = pts[pts["status"].isin(VALUE_STATES)]
    ax.scatter(val["cad_x"], val["cad_y"], c=[thickness_color(v, norm) for v in val["thickness_mm"]], s=70,
               edgecolors="#5b6470", linewidths=0.4, zorder=3)
    none = pts[pts["status"] == STATE_NONE]
    ax.scatter(none["cad_x"], none["cad_y"], marker="x", c=GRAY_DARK, s=90, linewidths=2.2, zorder=3)
    out = pts[pts["status"] == STATE_OUTSIDE]
    ax.scatter(out["cad_x"], out["cad_y"], marker="o", facecolors="none", edgecolors=GRAY_DARK, s=70,
               linewidths=1.8, zorder=3)
    ax.set_aspect("equal")
    ax.autoscale_view()
    ax.set_xticks([])
    ax.set_yticks([])
    for side in ax.spines.values():
        side.set_color("#c9d1db")
    ax.set_title(title, fontsize=18, loc="left", color="#24324a", pad=14)
    _colorbar(fig, ax, result)
    handles = [Line2D([], [], ls="", marker="o", color=THICK_COLORS[1], mec="#5b6470", ms=9, label="산출 포인트(색상=두께)"),
               Line2D([], [], ls="", marker="x", color=GRAY_DARK, mew=2, ms=9, label="미산출 포인트"),
               Line2D([], [], ls="", marker="o", mfc="none", color=GRAY_DARK, mew=1.8, ms=9, label="영역 외")]
    ax.legend(handles=handles, loc="upper right", bbox_to_anchor=(1.0, 0.0), ncol=3, fontsize=10, frameon=False)
    fig.subplots_adjust(left=0.03, right=0.97, top=0.92, bottom=0.12)
    return fig


# ------------------------------------------------------------------ 방별 두께도 (서브)
def room_cells(result: AnalysisResult) -> list[tuple[Room, str, float, int]]:
    """도면의 방마다 (방, 화면에 쓸 이름, 평균 두께, 산출 완료 점 수). 값이 없으면 평균은 NaN."""
    if result.plan is None:
        return []
    pts = result.points
    name_of = dict(zip(pts["room_id"], pts["room"]))
    by_id = result.rooms.set_index("room_id")
    cells = []
    for r in result.plan.rooms:
        name = name_of.get(r.room_id, r.name)
        if r.room_id in by_id.index:
            row = by_id.loc[r.room_id]
            cells.append((r, name, float(row["mean_mm"]), int(row["n_valid"])))
        else:
            cells.append((r, name, float("nan"), 0))
    return cells


def plot_rooms(result: AnalysisResult, title: str = "", show_points: bool = True):
    """방별 두께도: 방을 방 평균 두께 색으로 칠하고 방 이름과 평균 두께를 쓴다."""
    pts = result.points
    norm = norm_of(result)
    cells = room_cells(result)
    lo, hi = _extent(result)
    span = hi - lo
    width = 14
    height = float(np.clip(width * span[1] / max(span[0], 1e-9), 3.5, 14)) + 1.5
    fig, ax = plt.subplots(figsize=(width, height), dpi=110)
    fills = {c[0].room_id: thickness_color(c[2], norm, ROOM_SOFTEN) for c in cells}
    values = {c[0].room_id: (f"평균 {c[2]:.0f}mm ({c[3]}점)" if np.isfinite(c[2]) else "값 없음") for c in cells}
    _draw_rooms(ax, result, fills=fills, size=8, values=values)
    if show_points:
        val = pts[pts["status"].isin(VALUE_STATES)]
        ax.scatter(val["cad_x"], val["cad_y"], s=8, c="#5b6470", linewidths=0, zorder=2)
        none = pts[pts["status"] == STATE_NONE]
        ax.scatter(none["cad_x"], none["cad_y"], marker="x", s=14, c=GRAY, linewidths=1, zorder=2)
    ax.set_aspect("equal")
    ax.autoscale_view()
    ax.axis("off")
    ax.set_title(title or "방별 슬래브 두께 (방 평균)", fontsize=13, fontweight="bold", loc="left")
    _colorbar(fig, ax, result, "방 평균 두께 (mm)")
    fig.subplots_adjust(left=0.01, right=0.99, top=0.95, bottom=0.08)
    return fig


def histogram(result: AnalysisResult):
    """'산출 완료' 측정점 두께 분포. 막대 색은 두께 색 막대와 같다."""
    v = result.points.loc[result.points["status"] == STATE_OK, "thickness_mm"].to_numpy()
    norm = norm_of(result)
    fig, ax = plt.subplots(figsize=(10, 3.2), dpi=110)
    if len(v):
        bins = np.arange(np.floor(v.min()), np.ceil(v.max()) + 3, 2)
        n, edges, patches = ax.hist(v, bins=bins, ec="white", lw=0.6)
        for p, left in zip(patches, edges[:-1]):
            p.set_facecolor(thickness_color(left + 1, norm))
        mean = float(v.mean())
        ax.axvline(mean, color="#3b4252", lw=1.2)
        ax.text(mean, ax.get_ylim()[1] * 0.95, f" 평균 {mean:.0f}mm", va="top", fontsize=9, color="#3b4252")
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


def figure_png(fig, dpi: int | None = None) -> bytes:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=dpi or fig.dpi, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return buf.getvalue()
