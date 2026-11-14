"""포인트 위치도 (도면 좌표 기준 평면도 위에 두께 표시)."""
from __future__ import annotations

import io

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
from matplotlib import font_manager
from matplotlib.colors import TwoSlopeNorm
from matplotlib.patches import Polygon

from .core import AnalysisResult

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


def figure_png(fig) -> bytes:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150, bbox_inches="tight")
    plt.close(fig)
    return buf.getvalue()
