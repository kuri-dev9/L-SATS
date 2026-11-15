"""한 장으로 보는 HTML 보고서 (브라우저에서 열고 인쇄 → PDF 저장 가능).

보고서는 영역(섹션) 단위로 만든다. 간단/상세 보고서는 기본으로 켜 두는 영역 묶음일 뿐이고,
사용자가 영역을 자유롭게 넣고 빼거나 직접 쓴 영역을 추가할 수 있다.
"""
from __future__ import annotations

import datetime as _dt
import html
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from . import __version__
from .core import OUTSIDE_ROOM, AnalysisResult
from .plot import STATUS, figure_svg, histogram, plot_plan, plot_rooms
from .report import METHOD_LABELS, points_table

HOW_IT_WORKS = (Path(__file__).parent / "assets" / "how_it_works.svg").read_text(encoding="utf-8")

# 영역 key → (이름, 설명)
SECTIONS: dict[str, tuple[str, str]] = {
    "summary": ("종합 판정", "통과/미달 결론과 핵심 숫자"),
    "room_map": ("방별 판정도", "방을 판정 색으로 칠한 평면도"),
    "action": ("조치가 필요한 방", "미달·판정 못 한 방과 권장 조치"),
    "room_table": ("방별 결과 표", "모든 방의 평균·최소·최대 두께"),
    "distribution": ("두께 분포", "측정점 두께 막대그래프"),
    "point_map": ("측정점 위치도", "측정점마다 두께 숫자를 쓴 평면도"),
    "excluded": ("제외된 측정점", "계산에서 뺀 점과 이유"),
    "method": ("측정·계산 방법", "원리 그림과 계산 설정"),
    "notes": ("검토 의견", "직접 쓴 의견 (내용이 있을 때만)"),
    "signoff": ("확인란", "작성·검토·확인 서명 칸"),
    "points_table": ("부록: 전체 측정점 표", "모든 측정점의 상세 값"),
}
PRESETS: dict[str, list[str]] = {
    "간단 보고서": ["summary", "room_map", "action", "notes", "signoff"],
    "상세 보고서": list(SECTIONS),
}


@dataclass
class ReportSpec:
    kind: str = "간단 보고서"
    sections: list[str] = field(default_factory=lambda: list(PRESETS["간단 보고서"]))
    notes: str = ""
    custom: list[tuple[str, str]] = field(default_factory=list)  # 직접 추가한 영역 (제목, 내용)
    author: str = ""


def _e(v) -> str:
    return html.escape(str(v))


def _text(v: str) -> str:
    return "<br>".join(_e(line) for line in str(v).splitlines())


def _num(v, fmt="{:.0f}", empty="-") -> str:
    return fmt.format(v) if v is not None and np.isfinite(v) else empty


def _judged(result: AnalysisResult) -> pd.DataFrame:
    return result.rooms[result.rooms["room"] != OUTSIDE_ROOM]


def _verdict(result: AnalysisResult) -> tuple[str, str, str]:
    """(상태 key, 큰 제목, 설명)"""
    s, sm = result.settings, result.summary
    limit = s.design_mm - s.tolerance_mm
    if result.plan is None:
        ok = sm["mean_mm"] >= limit
        return ("적합" if ok else "미달", "통과" if ok else "미달",
                f"전체 평균 {sm['mean_mm']:.0f}mm (기준 {limit:g}mm 이상)")
    j = _judged(result)
    bad = j[j["judgement"] == "미달"].sort_values("mean_mm")
    n = int(j["judgement"].isin(["적합", "미달"]).sum())
    if bad.empty:
        return "적합", "모든 방 통과", f"검사한 방 {n}개가 모두 기준({limit:g}mm 이상)을 통과했습니다."
    names = ", ".join(f"{r.room}({r.mean_mm:.0f}mm)" for r in bad.head(5).itertuples())
    more = f" 외 {len(bad) - 5}개" if len(bad) > 5 else ""
    return "미달", f"{len(bad)}개 방 미달 (전체 {n}개 중)", f"가장 얇은 방부터: {names}{more}"


def _table(df: pd.DataFrame, status_col: str | None = None, cls: str = "") -> str:
    head = "".join(f"<th>{_e(c)}</th>" for c in df.columns)
    rows = []
    for _, r in df.iterrows():
        st_ = r[status_col] if status_col else ""
        tr = {"미달": ' class="bad"', "판정불가": ' class="unk"', "제외": ' class="exc"'}.get(st_, "")
        cells = "".join(f"<td>{'' if pd.isna(v) else _e(v)}</td>" for v in r)
        rows.append(f"<tr{tr}>{cells}</tr>")
    return f'<table class="{cls}"><thead><tr>{head}</tr></thead><tbody>{"".join(rows)}</tbody></table>'


# ------------------------------------------------------------------ 영역별 내용
def _sec_summary(result, meta):
    s, sm = result.settings, result.summary
    limit = s.design_mm - s.tolerance_mm
    key, head, desc = _verdict(result)
    j = _judged(result)
    n_judged = int(j["judgement"].isin(["적합", "미달"]).sum())
    n_ok = int((j["judgement"] == "적합").sum())
    ratio = n_ok / n_judged if n_judged else (1.0 if key == "적합" else 0.0)
    # 통과 비율 고리 (원둘레 2πr, r=42)
    circ = 2 * np.pi * 42
    ring = (f'<svg class="ring" viewBox="0 0 100 100"><circle cx="50" cy="50" r="42" class="ring-bg"/>'
            f'<circle cx="50" cy="50" r="42" class="ring-fg" style="stroke-dasharray:{circ:.1f};'
            f'--off:{circ * (1 - ratio):.1f}"/><text x="50" y="47">{ratio * 100:.0f}%</text>'
            f'<text x="50" y="64" class="ring-sub">통과</text></svg>')
    kpis = [
        ("평균 두께", f"{sm['mean_mm']:.0f}<small>mm</small>", f"기준 대비 {sm['mean_mm'] - limit:+.0f}mm"),
        ("기준 통과한 방" if result.plan is not None else "기준 통과한 점",
         f"{n_ok}<small>/{n_judged}</small>" if result.plan is not None else f"{sm['pass_rate'] * 100:.0f}<small>%</small>",
         f"기준 {limit:g}mm 이상"),
        ("가장 얇은 곳", f"{sm['min_mm']:.0f}<small>mm</small>", f"가장 두꺼운 곳 {sm['max_mm']:.0f}mm"),
        ("사용한 측정점", f"{sm['n_valid']}<small>/{sm['n_points']}</small>", f"이상값 {sm['n_excluded']}개 자동 제외"),
    ]
    kpi_html = "".join(f'<div class="kpi"><div class="kl">{a}</div><div class="kv">{b}</div>'
                       f'<div class="ks">{c}</div></div>' for a, b, c in kpis)
    return (f'<div class="verdict v-{ "ok" if key == "적합" else "bad"}">{ring}<div>'
            f'<div class="vh">{_e(head)}</div><div class="vd">{_e(desc)}</div>'
            f'<div class="vc">기준 두께 {limit:g}mm — 방 평균이 <b>{limit:g}mm 이상</b>이면 통과</div></div></div>'
            f'<div class="kpis">{kpi_html}</div>')


def _sec_room_map(result, meta):
    if result.plan is None:
        return '<p class="muted">도면(DXF)이 없어 방별 판정도를 그리지 않았습니다.</p>'
    svg = figure_svg(plot_rooms(result, title=" "))
    return (f'<figure>{svg}<figcaption>방 안 측정점들의 평균 두께로 판정했습니다. '
            '빗금 친 빨간 방이 기준 미달입니다.</figcaption></figure>')


def _sec_action(result, meta):
    j = _judged(result)
    bad = j[j["judgement"] == "미달"].sort_values("mean_mm")
    unk = j[j["judgement"] == "판정불가"]
    few = j[(j["judgement"] != "판정불가") & (j["n_valid"] < 3)]
    if bad.empty and unk.empty:
        out = '<p class="ok-line">조치가 필요한 방이 없습니다.</p>'
    else:
        limit = result.settings.design_mm - result.settings.tolerance_mm
        rows = [{"방": r.room, "평균(mm)": _num(r.mean_mm), "가장 얇은 곳(mm)": _num(r.min_mm),
                 "기준보다(mm)": _num(r.mean_mm - limit, "{:+.0f}"), "판정": "미달",
                 "권장 조치": "코어 채취·천공으로 실제 두께 확인"} for r in bad.itertuples()]
        rows += [{"방": r.room, "평균(mm)": "-", "가장 얇은 곳(mm)": "-", "기준보다(mm)": "-",
                  "판정": "판정불가", "권장 조치": "쓸 수 있는 측정값 없음 — 현장 확인·재측정"}
                 for r in unk.itertuples()]
        out = _table(pd.DataFrame(rows), "판정")
    if len(few):
        out += (f'<p class="muted">참고: 쓸 수 있는 측정점이 3개 미만인 방 {len(few)}개 '
                f'({_e(", ".join(few["room"]))})는 판정의 신뢰도가 낮습니다.</p>')
    return out


def _sec_room_table(result, meta):
    r = result.rooms.copy()
    r["order"] = r["judgement"].map({"미달": 0, "판정불가": 1, "적합": 2})
    r = r.sort_values(["order", "mean_mm"])
    df = pd.DataFrame({
        "방": r["room"], "판정": r["judgement"],
        "평균(mm)": r["mean_mm"].map(_num), "최소(mm)": r["min_mm"].map(_num),
        "최대(mm)": r["max_mm"].map(_num), "설계 대비(mm)": r["mean_dev_mm"].map(lambda v: _num(v, "{:+.0f}")),
        "측정점(사용/전체)": r["n_valid"].astype(str) + " / " + r["n_points"].astype(str),
    })
    return _table(df, "판정", "num")


def _sec_distribution(result, meta):
    svg = figure_svg(histogram(result))
    sm = result.summary
    return (f'<figure>{svg}<figcaption>제외된 점을 뺀 {sm["n_valid"]}개 측정점. 중앙값 {sm["median_mm"]:.0f}mm, '
            f'표준편차 {sm["std_mm"]:.1f}mm.</figcaption></figure>')


def _sec_point_map(result, meta):
    svg = figure_svg(plot_plan(result, True, " "))
    return (f'<figure>{svg}<figcaption>점의 색: 빨간색일수록 설계보다 얇고 파란색일수록 두껍습니다. '
            '빨간 동그라미는 기준 미달인 점, 회색 X는 제외된 점, 숫자는 두께(mm)입니다.</figcaption></figure>')


def _sec_excluded(result, meta):
    ex = result.points[result.points["excluded"]]
    if ex.empty:
        return '<p class="muted">제외된 측정점이 없습니다.</p>'
    reasons = ex["exclude_reason"].str.split(", ").explode().value_counts()
    rs = _table(reasons.rename_axis("이유").reset_index(name="개수"), cls="narrow")
    pt = points_table(result).loc[ex.index, ["포인트", "실명", "두께(mm)", "제외 사유"]]
    return (f'<p>전체 {len(result.points)}개 중 {len(ex)}개를 계산에서 뺐습니다. 바닥 위 물건, 천장 배관, '
            f'단차처럼 슬래브가 아닌 곳을 잰 값입니다.</p>{rs}{_table(pt)}')


def _sec_method(result, meta):
    s, t = result.settings, result.transform
    rows = [
        ("두께 계산", "위층 바닥 높이(콘크리트 윗면) − 아래층 천장 높이"),
        ("위·아래층 점 맞추기", f"{METHOD_LABELS.get(s.method, s.method)} (최대 {s.max_match_dist_m:g}m 이내)"),
        ("이상값 자동 제외", f"바닥·천장이 기준면에서 {s.max_surface_error_mm:g}mm 넘게 벗어난 점, "
                       + (f"다른 점들과 크게 다른 점(MAD×{s.outlier_mad_k:g})" if s.outlier_mad_k else "통계 이상치 기준 사용 안 함")),
        ("방 판정", f"방 안 측정점 평균이 {s.design_mm - s.tolerance_mm:g}mm 이상이면 통과"),
    ]
    if t is not None:
        rows.append(("도면 ↔ 측량 좌표 맞춤", f"{t.method}, 회전 {t.rotation_deg:.2f}°, "
                                         f"오차 {t.rms_m * 1000:.1f}mm"))
    df = pd.DataFrame(rows, columns=["항목", "내용"])
    return f'<figure class="how">{HOW_IT_WORKS}</figure>{_table(df, cls="facts-table")}'


def _sec_notes(spec: ReportSpec):
    return f'<div class="note">{_text(spec.notes)}</div>'


def _sec_signoff(spec: ReportSpec):
    cells = "".join(f'<div class="sign"><div class="sl">{n}</div><div class="sb">'
                    f'{_e(spec.author) if n == "작성" else ""}</div></div>' for n in ("작성", "검토", "확인"))
    return f'<div class="signs">{cells}</div>'


def _sec_points_table(result, meta):
    pt = points_table(result)[["포인트", "실명", "두께(mm)", "설계 대비(mm)", "판정", "제외 사유", "대응 거리(m)"]]
    return _table(pt, "판정", "small")


_BUILDERS = {
    "summary": _sec_summary, "room_map": _sec_room_map, "action": _sec_action,
    "room_table": _sec_room_table, "distribution": _sec_distribution, "point_map": _sec_point_map,
    "excluded": _sec_excluded, "method": _sec_method, "points_table": _sec_points_table,
}


def build_html(result: AnalysisResult, meta: dict, spec: ReportSpec | None = None) -> str:
    spec = spec or ReportSpec()
    s = result.settings
    title = f"{meta.get('동', '')} {meta.get('상부층', '')}-{meta.get('하부층', '')} 슬래브 두께 검사 보고서".strip()
    chosen = [k for k in SECTIONS if k in spec.sections]
    body, toc = [], []
    no = 0

    def add(sec_title: str, content: str, cls: str = ""):
        nonlocal no
        no += 1
        toc.append(f"<li>{_e(sec_title)}</li>")
        body.append(f'<section class="sec {cls}" style="--i:{no}"><h2><span class="no">{no}</span>'
                    f'{_e(sec_title)}</h2>{content}</section>')

    for k in chosen:
        if k == "notes":
            if spec.notes.strip():
                add(SECTIONS[k][0], _sec_notes(spec))
            continue
        if k == "signoff":
            continue  # 확인란은 맨 끝 (직접 추가한 영역 다음)
        if k == "points_table":
            continue  # 부록도 맨 끝
        add(SECTIONS[k][0], _BUILDERS[k](result, meta), "wide" if k in ("room_map", "point_map") else "")
    for t, c in spec.custom:
        if str(t).strip() or str(c).strip():
            add(str(t).strip() or "추가 내용", f'<div class="note">{_text(c)}</div>')
    if "points_table" in chosen:
        add(SECTIONS["points_table"][0], _sec_points_table(result, meta), "appendix")
    if "signoff" in chosen:
        add(SECTIONS["signoff"][0], _sec_signoff(spec), "keep")

    key, head, _ = _verdict(result)
    d = _dt.date.today()
    today = f"{d.year}년 {d.month:02d}월 {d.day:02d}일"  # Windows 의 strftime 은 한글을 못 쓴다
    facts = [("동", meta.get("동", "") or "-"), ("검사 층", f"{meta.get('상부층', '')} 바닥 / {meta.get('하부층', '')} 천장"),
             ("기준 두께", f"{s.design_mm - s.tolerance_mm:g}mm 이상"), ("작성일", today)]
    fact_html = "".join(f"<div><span>{a}</span><b>{_e(b)}</b></div>" for a, b in facts)
    return f"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_e(title)}</title><style>{CSS}</style></head>
<body><main class="page">
<header class="cover">
  <div class="tag">{_e(spec.kind)}</div>
  <h1>{_e(title)}</h1>
  <div class="facts">{fact_html}</div>
  <div class="badge b-{"ok" if key == "적합" else "bad"}">{_e(head)}</div>
  <button class="print" onclick="window.print()">인쇄 / PDF로 저장</button>
</header>
<nav class="toc"><b>목차</b><ol>{"".join(toc)}</ol></nav>
{"".join(body)}
<footer>레이저 스캔 기반 슬래브 두께 자동 산출 · 슬래브 두께 분석기 v{__version__} · {today}</footer>
</main></body></html>"""


CSS = """
:root{--ok:#2e9d5b;--ok-l:#e6f5ec;--bad:#c62f2f;--bad-l:#fdecec;--unk:#8a8f98;--ink:#1f2328;--mut:#5b6470;
--line:#e3e8ef;--bg:#f3f5f8;--acc:#2f6fd6}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
font-family:'Malgun Gothic','Apple SD Gothic Neo','Noto Sans KR',sans-serif;font-size:14px;line-height:1.55}
.page{max-width:1000px;margin:24px auto;padding:0 16px 40px}
.cover{position:relative;background:linear-gradient(135deg,#24324a,#3a4f73);color:#fff;border-radius:18px;
padding:28px 32px 24px;overflow:hidden;animation:rise .6s cubic-bezier(.2,.8,.2,1) both}
.cover:after{content:"";position:absolute;right:-60px;top:-60px;width:240px;height:240px;border-radius:50%;
background:radial-gradient(circle,rgba(255,255,255,.18),transparent 70%)}
.cover h1{margin:6px 0 16px;font-size:26px;letter-spacing:-.3px}
.tag{display:inline-block;font-size:12px;padding:3px 10px;border-radius:99px;background:rgba(255,255,255,.16)}
.facts{display:flex;flex-wrap:wrap;gap:10px 28px}
.facts div{display:flex;flex-direction:column}.facts span{font-size:12px;opacity:.7}.facts b{font-size:15px}
.badge{position:absolute;right:28px;bottom:24px;font-weight:700;font-size:16px;padding:8px 16px;border-radius:12px;
animation:pop .5s .35s cubic-bezier(.2,1.4,.4,1) both}
.b-ok{background:var(--ok)}.b-bad{background:var(--bad)}
.print{position:absolute;right:28px;top:24px;border:1px solid rgba(255,255,255,.4);background:transparent;color:#fff;
border-radius:10px;padding:6px 12px;cursor:pointer;font:inherit;font-size:13px;transition:background .2s}
.print:hover{background:rgba(255,255,255,.15)}
.toc{background:#fff;border-radius:14px;padding:14px 22px;margin:16px 0;border:1px solid var(--line);
animation:rise .6s .1s both}
.toc ol{margin:6px 0 0;padding-left:20px;columns:2;column-gap:40px}
.sec{background:#fff;border-radius:14px;padding:20px 24px;margin:16px 0;border:1px solid var(--line);
animation:rise .55s calc(.12s + var(--i)*.06s) cubic-bezier(.2,.8,.2,1) both}
.sec h2{display:flex;align-items:center;gap:10px;margin:0 0 14px;font-size:18px}
.no{display:inline-grid;place-items:center;width:26px;height:26px;border-radius:8px;background:var(--acc);color:#fff;
font-size:13px}
.verdict{display:flex;gap:22px;align-items:center;border-radius:14px;padding:16px 20px}
.v-ok{background:var(--ok-l)}.v-bad{background:var(--bad-l)}
.vh{font-size:22px;font-weight:800}.v-ok .vh{color:var(--ok)}.v-bad .vh{color:var(--bad)}
.vd{margin:4px 0;font-size:15px}.vc{color:var(--mut);font-size:13px}
.ring{width:110px;height:110px;flex:none}
.ring circle{fill:none;stroke-width:10;transform:rotate(-90deg);transform-origin:50% 50%}
.ring-bg{stroke:#fff}.ring-fg{stroke-linecap:round;stroke-dashoffset:var(--off);animation:ring 1.1s .3s ease-out both}
.v-ok .ring-fg{stroke:var(--ok)}.v-bad .ring-fg{stroke:var(--bad)}
.ring text{text-anchor:middle;font-size:20px;font-weight:800;fill:var(--ink)}.ring .ring-sub{font-size:10px;font-weight:400;fill:var(--mut)}
.kpis{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-top:14px}
.kpi{border:1px solid var(--line);border-radius:12px;padding:12px 14px;transition:transform .2s,box-shadow .2s}
.kpi:hover{transform:translateY(-2px);box-shadow:0 6px 18px rgba(31,35,40,.08)}
.kl{font-size:12px;color:var(--mut)}.kv{font-size:26px;font-weight:800}.kv small{font-size:13px;color:var(--mut);margin-left:2px}
.ks{font-size:12px;color:var(--mut)}
figure{margin:0}figure svg{width:100%;height:auto}figcaption{color:var(--mut);font-size:12.5px;margin-top:6px}
.how svg{max-height:260px}
table{width:100%;border-collapse:collapse;font-size:13px;margin:6px 0 10px}
th{background:#eef2f7;text-align:left;padding:7px 9px;font-weight:700;border-bottom:1px solid var(--line)}
td{padding:6px 9px;border-bottom:1px solid #f0f2f5}tbody tr{transition:background .15s}tbody tr:hover{background:#f7f9fc}
tr.bad td{background:var(--bad-l);color:#8f1d1d;font-weight:600}tr.unk td{color:var(--mut);background:#f4f5f7}
tr.exc td{color:#9aa0a6}
table.num td:nth-child(n+3){text-align:right}table.narrow{width:auto;min-width:50%}
table.small{font-size:11.5px}table.facts-table td:first-child{width:28%;font-weight:600;color:var(--mut)}
.note{white-space:normal;background:#f7f9fc;border-left:4px solid var(--acc);border-radius:8px;padding:12px 16px}
.muted{color:var(--mut)}.ok-line{color:var(--ok);font-weight:700}
.signs{display:grid;grid-template-columns:repeat(3,1fr);gap:0;border:1px solid #c9d1db;border-radius:8px;overflow:hidden;
max-width:520px;margin-left:auto}
.sign{border-left:1px solid #c9d1db}.sign:first-child{border-left:none}
.sl{background:#eef2f7;text-align:center;padding:5px;font-weight:700;font-size:13px}.sb{height:64px;display:grid;place-items:center}
footer{text-align:center;color:var(--mut);font-size:12px;margin-top:24px}
@keyframes rise{from{opacity:0;transform:translateY(14px)}to{opacity:1;transform:none}}
@keyframes pop{from{opacity:0;transform:scale(.6)}to{opacity:1;transform:none}}
@keyframes ring{from{stroke-dashoffset:264}}
@media (max-width:720px){.kpis{grid-template-columns:repeat(2,1fr)}.badge{position:static;display:inline-block;margin-top:14px}
.print{display:none}.toc ol{columns:1}}
@media (prefers-reduced-motion:reduce){*{animation:none!important;transition:none!important}}
@page{size:A4;margin:12mm}
@media print{body{background:#fff;font-size:12px}.page{margin:0;max-width:none;padding:0}
*{animation:none!important}.print{display:none}
.cover{-webkit-print-color-adjust:exact;print-color-adjust:exact;border-radius:10px}
.sec,.toc{border:none;padding:8px 0;margin:10px 0;break-inside:auto}.sec h2{break-after:avoid}
figure,.verdict,.kpis,.signs,.keep{break-inside:avoid}.appendix{break-before:page}
tr,td,.verdict,.badge,.no,th{-webkit-print-color-adjust:exact;print-color-adjust:exact}}
"""
