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
from .core import REVIEW_STATES, STATE_LOW, STATE_NONE, STATE_OUTLIER, STATE_OUTSIDE, STATE_RANGE, AnalysisResult
from .plot import figure_svg, histogram, plot_point_map, plot_rooms
from .report import METHOD_LABELS, points_table, state_rules

HOW_IT_WORKS = (Path(__file__).parent / "assets" / "how_it_works.svg").read_text(encoding="utf-8")

# 영역 key → (이름, 설명)
SECTIONS: dict[str, tuple[str, str]] = {
    "summary": ("두께 현황", "평균·최소·최대 두께와 측정점 상태별 개수"),
    "point_map": ("측정점 위치도", "측정점마다 'ID / 두께'를 쓴 평면도 (메인 자료)"),
    "room_map": ("방별 두께도", "방을 방 평균 두께 색으로 칠한 평면도 (서브 자료)"),
    "review": ("검토가 필요한 점", "두께 범위·이상치·하한 이하와 미산출 점"),
    "room_table": ("방별 현황 표", "모든 방의 평균·최소·최대 두께"),
    "distribution": ("두께 분포", "측정점 두께 막대그래프"),
    "method": ("측정·계산 방법", "원리 그림과 결과 상태 기준"),
    "notes": ("검토 의견", "직접 쓴 의견 (내용이 있을 때만)"),
    "signoff": ("확인란", "작성·검토·확인 서명 칸"),
    "points_table": ("부록: 전체 측정점 표", "모든 측정점의 상세 값"),
}
PRESETS: dict[str, list[str]] = {
    "간단 보고서": ["summary", "point_map", "room_map", "review", "notes", "signoff"],
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


def _table(df: pd.DataFrame, status_col: str | None = None, cls: str = "") -> str:
    head = "".join(f"<th>{_e(c)}</th>" for c in df.columns)
    rows = []
    for _, r in df.iterrows():
        st_ = r[status_col] if status_col else ""
        tr = {STATE_RANGE: ' class="rev"', STATE_OUTLIER: ' class="rev"', STATE_LOW: ' class="bad"',
              STATE_NONE: ' class="unk"', STATE_OUTSIDE: ' class="exc"'}.get(st_, "")
        cells = "".join(f"<td>{'' if pd.isna(v) else _e(v)}</td>" for v in r)
        rows.append(f"<tr{tr}>{cells}</tr>")
    return f'<table class="{cls}"><thead><tr>{head}</tr></thead><tbody>{"".join(rows)}</tbody></table>'


# ------------------------------------------------------------------ 영역별 내용
def _sec_summary(result, meta):
    sm = result.summary
    n_in = sm["n_points"] - sm["n_outside"]
    kpis = [
        ("평균 두께", f"{_num(sm['mean_mm'])}<small>mm</small>", f"중앙값 {_num(sm['median_mm'])}mm"),
        ("가장 얇은 곳 / 두꺼운 곳", f"{_num(sm['min_mm'])}<small>/{_num(sm['max_mm'])}mm</small>",
         f"표준편차 {_num(sm['std_mm'], '{:.1f}')}mm"),
        ("산출 완료", f"{sm['n_valid']}<small>/{n_in}</small>", f"직접 대응 {sm['n_direct']} · TIN {sm['n_tin']}"),
        ("검토 필요 / 미산출", f"{sm['n_review']}<small>/{sm['n_no_value']}</small>",
         f"범위 {sm['n_range']} · 이상치 {sm['n_outlier']} · 하한 {sm['n_low']}"),
    ]
    kpi_html = "".join(f'<div class="kpi"><div class="kl">{a}</div><div class="kv">{b}</div>'
                       f'<div class="ks">{c}</div></div>' for a, b, c in kpis)
    extra = f" · 방 경계 밖(영역 외) {sm['n_outside']}개는 따로 셉니다" if sm["n_outside"] else ""
    return (f'<div class="kpis">{kpi_html}</div><p class="muted">평균·최소·최대는 \'산출 완료\' 점으로만 냈습니다. '
            f'측정점 {sm["n_points"]}개{extra}.</p>')


def _sec_point_map(result, meta):
    svg = figure_svg(plot_point_map(result, px_per_m=70))
    return (f'<figure>{svg}<figcaption>측정점마다 \'포인트 ID / 두께(mm)\'를 썼습니다. 색: 초록일수록 얇고 주황일수록 '
            '두껍습니다. 검토가 필요한 점은 아래 \'검토가 필요한 점\' 표에 있습니다. 회색 ×는 미산출(사유 표시), 회색 ○는 방 경계 밖(영역 외)입니다.'
            '</figcaption></figure>')


def _sec_room_map(result, meta):
    if result.plan is None:
        return '<p class="muted">도면(DXF)이 없어 방별 두께도를 그리지 않았습니다.</p>'
    svg = figure_svg(plot_rooms(result, title=" "))
    return (f'<figure>{svg}<figcaption>방 색은 방 안 \'산출 완료\' 점들의 평균 두께입니다. '
            '검토·미산출 점은 평균에 넣지 않았습니다.</figcaption></figure>')


def _sec_review(result, meta):
    p = result.points
    sel = p[p["status"].isin([*REVIEW_STATES, STATE_NONE])]
    if sel.empty:
        return '<p class="ok-line">검토가 필요한 점이 없습니다.</p>'
    counts = sel["status"].value_counts().rename_axis("결과 상태").reset_index(name="개수")
    df = pd.DataFrame({
        "포인트 ID": sel["point_id"], "실명": sel["room"], "결과 상태": sel["status"],
        "두께(mm)": sel["thickness_mm"].map(_num), "미산출 사유": sel["no_reason"],
        "참고": [n or r for n, r in zip(sel["review_note"], sel["exclude_reason"])],
    }).sort_values(["결과 상태", "포인트 ID"])
    return (f'<p>값이 있어도 다시 볼 점(두께 범위·이상치·하한 이하)과 두께를 못 구한 점입니다. 미산출 점은 0mm로 채우지 '
            f'않습니다.</p>{_table(counts, cls="narrow")}{_table(df, "결과 상태")}')


def _sec_room_table(result, meta):
    r = result.rooms.sort_values(["unit", "room"])
    df = pd.DataFrame({
        "세대": r["unit"], "방": r["room"], "평균(mm)": r["mean_mm"].map(_num), "최소(mm)": r["min_mm"].map(_num),
        "최대(mm)": r["max_mm"].map(_num), "산출 완료/전체": r["n_valid"].astype(str) + " / " + r["n_points"].astype(str),
        "검토": r["n_review"], "미산출": r["n_no_value"],
    })
    return _table(df, cls="num")


def _sec_distribution(result, meta):
    svg = figure_svg(histogram(result))
    sm = result.summary
    return (f'<figure>{svg}<figcaption>\'산출 완료\' {sm["n_valid"]}개 측정점. 중앙값 {_num(sm["median_mm"])}mm, '
            f'표준편차 {_num(sm["std_mm"], "{:.1f}")}mm.</figcaption></figure>')


def _sec_method(result, meta):
    s, t = result.settings, result.transform
    rows = [
        ("두께 계산", "위층 바닥 높이(콘크리트 윗면) − 아래층 천장 높이"),
        ("위·아래층 점 맞추기", f"{METHOD_LABELS.get(s.method, s.method)} (직접 대응 최대 {s.max_match_dist_m:g}m, "
                         f"하부점 {'재사용 허용' if s.allow_reuse else '1:1 배정'}, TIN 외삽 안 함)"),
        *state_rules(s),
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
    pt = points_table(result)[["세대", "실명", "상부점 ID", "두께(mm)", "산출방법", "사용 하부점", "거리(m)", "결과 상태",
                               "미산출 사유", "검토 메모"]]
    return _table(pt, "결과 상태", "small")


_BUILDERS = {
    "summary": _sec_summary, "point_map": _sec_point_map, "room_map": _sec_room_map, "review": _sec_review,
    "room_table": _sec_room_table, "distribution": _sec_distribution, "method": _sec_method,
    "points_table": _sec_points_table,
}


def build_html(result: AnalysisResult, meta: dict, spec: ReportSpec | None = None) -> str:
    spec = spec or ReportSpec()
    s = result.settings
    title = f"{meta.get('동', '')} {meta.get('상부층', '')}-{meta.get('하부층', '')} 슬래브 두께 현황 보고서".strip()
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

    sm = result.summary
    d = _dt.date.today()
    today = f"{d.year}년 {d.month:02d}월 {d.day:02d}일"  # Windows 의 strftime 은 한글을 못 쓴다
    facts = [("동", meta.get("동", "") or "-"), ("검사 층", f"{meta.get('상부층', '')} 바닥 / {meta.get('하부층', '')} 천장"),
             ("평균 두께", f"{_num(sm['mean_mm'])}mm"), ("작성일", today)]
    fact_html = "".join(f"<div><span>{a}</span><b>{_e(b)}</b></div>" for a, b in facts)
    return f"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_e(title)}</title><style>{CSS}</style></head>
<body><main class="page">
{f'<div class="draft">{_e(s.report_draft_text)}</div>' if s.report_draft else ""}
<header class="cover">
  <div class="tag">{_e(spec.kind)}</div>
  <h1>{_e(title)}</h1>
  <div class="facts">{fact_html}</div>
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
.draft{margin:0 0 12px;padding:10px 14px;border:2px dashed var(--bad);border-radius:10px;color:var(--bad);
font-weight:700;text-align:center;background:#fff}
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
tr.exc td{color:#9aa0a6}tr.rev td{background:#fff7e6;color:#8a4b00}
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
@media (max-width:720px){.kpis{grid-template-columns:repeat(2,1fr)}.print{display:none}.toc ol{columns:1}}
@media (prefers-reduced-motion:reduce){*{animation:none!important;transition:none!important}}
@page{size:A4;margin:12mm}
@media print{body{background:#fff;font-size:12px}.page{margin:0;max-width:none;padding:0}
*{animation:none!important}.print{display:none}
.cover{-webkit-print-color-adjust:exact;print-color-adjust:exact;border-radius:10px}
.sec,.toc{border:none;padding:8px 0;margin:10px 0;break-inside:auto}.sec h2{break-after:avoid}
figure,.kpis,.signs,.keep{break-inside:avoid}.appendix{break-before:page}
tr,td,.no,th{-webkit-print-color-adjust:exact;print-color-adjust:exact}}
"""
