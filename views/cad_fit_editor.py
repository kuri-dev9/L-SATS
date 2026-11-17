"""도면 맞추기 편집기 (Streamlit 커스텀 컴포넌트 v2, 캔버스): 세 층을 겹쳐 도면을 격자점에 맞춘다.

- 도면 층 (파란 선·글자, 올린 DXF 그대로) — 움직이는 층
- LAS 벽 층 (회색 띠 + 검은 선, 스캔에서 추정한 참고 자료) · 격자점 층 (주황 점) — LAS 좌표에 고정
- 층마다 보이기·숨기기. 도면이 보일 때 끌기 = 도면 이동, 숨겼을 때 끌기 = 화면 이동 (숨긴 도면은 점에 붙은 채 안 움직임)
- 화살표 키 = 1 cm (Shift 10 cm) / ⟲·⟳ = 90° 돌리기 / 오른쪽 버튼·Space+끌기 = 화면 이동, 휠 = 확대·축소
편집은 브라우저 안에서만 하고 「저장」을 누를 때만 Python 으로 {k, t} 를 보낸다.
"""
from __future__ import annotations

import hashlib
import json

import streamlit as st

HTML = """
<div class="cf" tabindex="0">
  <canvas></canvas>
  <div class="bar">
    <button data-a="ccw" title="왼쪽으로 90° 돌리기">⟲ 90°</button>
    <button data-a="cw" title="오른쪽으로 90° 돌리기">⟳ 90°</button>
    <button data-l="draw" title="도면 보이기·숨기기 (숨기면 끌어도 도면이 안 움직여요)">도면</button>
    <button data-l="las" title="LAS 스캔 벽 보이기·숨기기 (참고 자료)">LAS 벽</button>
    <button data-l="pts" title="LAS 격자점 보이기·숨기기">격자점</button>
    <button data-a="undo" title="되돌리기 (Ctrl+Z)">↶ 되돌리기</button>
    <button data-a="fit" title="전체 보기">전체 보기</button>
    <span class="sep"></span>
    <button data-a="save" class="save" title="지금 자리로 방을 넣은 도면(DXF)을 만들어요">저장</button>
  </div>
  <div class="status"></div>
  <div class="help">도면 끌기 = 도면을 격자점 위로 이동 (도면을 숨기면 화면 이동) · 화살표 키 = 1 cm (Shift 10 cm) · ⟲·⟳ = 90° 돌리기 · 오른쪽 버튼 끌기 또는 Space+끌기 = 화면 이동 · 휠 = 확대</div>
</div>
"""

CSS = """
.cf{position:relative;width:100%;height:var(--h,600px);border:1px solid #dde4ee;border-radius:10px;overflow:hidden;
background:#fff;outline:none;touch-action:none;user-select:none;
font-family:'Malgun Gothic','Apple SD Gothic Neo','Noto Sans KR',sans-serif}
.cf canvas{position:absolute;inset:0;width:100%;height:100%;cursor:move}
.bar{position:absolute;left:8px;top:8px;display:flex;flex-wrap:wrap;gap:4px;pointer-events:none;max-width:calc(100% - 16px)}
.bar button{pointer-events:auto;font:inherit;font-size:12px;padding:4px 9px;border:1px solid #dde4ee;border-radius:7px;background:rgba(255,255,255,.94);
color:#1e293b;cursor:pointer}
.bar button:hover{background:#eef3fa;border-color:#2563eb}
.bar button[data-l]{color:#94a3b8}
.bar button[data-l].on{color:#1e293b;border-color:#94a3b8}
.bar button.save{font-weight:700}
.bar button.save.dirty{background:#ea580c;border-color:#ea580c;color:#fff}
.bar .sep{flex:1}
.status{position:absolute;left:10px;bottom:30px;font-size:12px;color:#1e293b;background:rgba(255,255,255,.9);padding:2px 6px;border-radius:6px}
.help{position:absolute;left:10px;right:10px;bottom:8px;font-size:11px;color:#64748b;line-height:1.4}
"""

JS = r"""
export default function(component) {
  const { data, parentElement, setTriggerValue } = component
  const root = parentElement.querySelector('.cf')
  if (!root || !data) return
  if (!root.__cf) root.__cf = make(root)
  root.__cf.update(data, setTriggerValue)
}

function make(root) {
  const cv = root.querySelector('canvas'), ctx = cv.getContext('2d')
  const status = root.querySelector('.status'), saveBtn = root.querySelector('[data-a=save]')
  const S = { z: 40, c: [0, 0], W: 0, H: 0, d: null, k: 0, t: [0, 0], undo: [], dirty: false, drag: null, rev: null,
              fitted: false, trig: null, show: { draw: true, las: true, pts: true } }
  const ROT = [[1, 0], [0, 1], [-1, 0], [0, -1]]
  const toS = (x, y) => [S.W / 2 + (x - S.c[0]) * S.z, S.H / 2 - (y - S.c[1]) * S.z]
  const toW = (sx, sy) => [S.c[0] + (sx - S.W / 2) / S.z, S.c[1] - (sy - S.H / 2) / S.z]
  const r3 = v => Math.round(v * 1000) / 1000
  const rot = (p, k) => { const [c, s] = ROT[(k % 4 + 4) % 4]; return [c * p[0] - s * p[1], s * p[0] + c * p[1]] }
  const place = p => { const q = rot([p[0] * S.d.s, p[1] * S.d.s], S.k); return [q[0] + S.t[0], q[1] + S.t[1]] }

  function resize() {
    const r = root.getBoundingClientRect(), dpr = window.devicePixelRatio || 1
    S.W = r.width; S.H = r.height
    cv.width = S.W * dpr; cv.height = S.H * dpr
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
    if ((!S.fitted || !S.user) && S.d) fit()  // 직접 확대·이동하기 전에는 크기가 바뀌면(탭 전환 등) 다시 전체 보기
    draw()
  }
  new ResizeObserver(resize).observe(root)

  function center() {  // 도면 방들의 가운데 (지금 자리)
    let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity
    for (const ln of S.d.lines) for (const p of ln) {
      const [x, y] = place(p); x0 = Math.min(x0, x); x1 = Math.max(x1, x); y0 = Math.min(y0, y); y1 = Math.max(y1, y)
    }
    return [(x0 + x1) / 2, (y0 + y1) / 2]
  }
  function fit() {
    if (!S.W || !S.d) return
    let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity
    const add = (x, y) => { x0 = Math.min(x0, x); x1 = Math.max(x1, x); y0 = Math.min(y0, y); y1 = Math.max(y1, y) }
    for (const p of S.d.pts) add(p[0], p[1])
    for (const p of (S.d.states || [])) add(p[0], p[1])
    for (const ln of S.d.lines) for (const p of ln) add(...place(p))
    if (!isFinite(x0)) return
    S.z = Math.min(S.W / Math.max(x1 - x0, 1), (S.H - 60) / Math.max(y1 - y0, 1)) / 1.1
    S.c = [(x0 + x1) / 2, (y0 + y1) / 2]
    S.fitted = true
  }
  function nearEdge(x, y, poly, tol = 0.001) {  // 두께 분석의 '경계선 위'(1 mm)도 방 안으로
    for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
      const [ax, ay] = poly[j], [bx, by] = poly[i], dx = bx - ax, dy = by - ay, L2 = dx * dx + dy * dy || 1e-12
      const t = Math.max(0, Math.min(1, ((x - ax) * dx + (y - ay) * dy) / L2))
      if (Math.hypot(x - ax - t * dx, y - ay - t * dy) <= tol) return true
    }
    return false
  }
  function inPoly(x, y, poly) {
    let inside = false
    for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
      const [xi, yi] = poly[i], [xj, yj] = poly[j]
      if ((yi > y) !== (yj > y) && x < (xj - xi) * (y - yi) / (yj - yi) + xi) inside = !inside
    }
    return inside
  }

  function draw() {
    if (!S.d || !S.W) return
    ctx.clearRect(0, 0, S.W, S.H)
    if (S.show.las) {  // LAS 스캔 벽 (참고, 고정)
      ctx.fillStyle = 'rgba(148,163,184,0.5)'
      for (const poly of S.d.lasPolys) {
        ctx.beginPath(); poly.forEach((q, k) => { const s = toS(q[0], q[1]); k ? ctx.lineTo(...s) : ctx.moveTo(...s) }); ctx.closePath(); ctx.fill()
      }
      ctx.strokeStyle = '#334155'; ctx.lineWidth = 1.2; ctx.beginPath()
      for (const w of S.d.lasLines) { ctx.moveTo(...toS(w[0], w[1])); ctx.lineTo(...toS(w[2], w[3])) }
      ctx.stroke()
    }
    if (S.show.pts) {  // 격자점 (고정): 두께 분석과 같은 표시 — 방 밖 ○ · 방 안 미산출 × · 방 안 산출 ●
      const rooms = (S.d.rooms || []).map(r => r.map(place))
      const inside = (x, y) => rooms.some(r => inPoly(x, y, r) || nearEdge(x, y, r))
      for (const p of (S.d.states || S.d.pts.map(q => [q[0], q[1], 1]))) {
        const [x, y] = toS(p[0], p[1])
        if (rooms.length && !inside(p[0], p[1])) {
          ctx.strokeStyle = '#94a3b8'; ctx.lineWidth = 1.3; ctx.beginPath(); ctx.arc(x, y, 3.5, 0, 6.3); ctx.stroke()
        } else if (!p[2]) {
          ctx.strokeStyle = '#64748b'; ctx.lineWidth = 1.5; ctx.beginPath()
          ctx.moveTo(x - 3.5, y - 3.5); ctx.lineTo(x + 3.5, y + 3.5); ctx.moveTo(x + 3.5, y - 3.5); ctx.lineTo(x - 3.5, y + 3.5); ctx.stroke()
        } else {
          ctx.fillStyle = '#ea580c'; ctx.beginPath(); ctx.arc(x, y, 3, 0, 6.3); ctx.fill()
        }
      }
    }
    if (S.show.draw) {  // 도면 (움직이는 층)
      ctx.strokeStyle = '#2563eb'; ctx.lineWidth = 1.4; ctx.beginPath()
      for (const ln of S.d.lines) ln.forEach((p, k) => { const s = toS(...place(p)); k ? ctx.lineTo(...s) : ctx.moveTo(...s) })
      ctx.stroke()
      ctx.textAlign = 'left'; ctx.textBaseline = 'bottom'
      ctx.font = "700 11px 'Malgun Gothic','Apple SD Gothic Neo',sans-serif"; ctx.fillStyle = '#1e3a8a'
      if (S.z > 8) for (const t of S.d.texts) ctx.fillText(t[2], ...toS(...place(t)))
    }
    const o = S.d.t0, dx = (S.t[0] - o[0]) * 1000, dy = (S.t[1] - o[1]) * 1000
    status.textContent = (S.show.draw ? '' : '도면 숨김 — 끌면 화면만 움직여요 · ') + `돌림 ${S.k * 90}° · 저장한 자리에서 x ${dx.toFixed(0)} mm, y ${dy.toFixed(0)} mm` +
                         (S.dirty ? ' · 저장 안 한 변경이 있어요' : '')
    saveBtn.classList.toggle('dirty', S.dirty)
    for (const b of root.querySelectorAll('[data-l]')) b.classList.toggle('on', S.show[b.dataset.l])
  }

  function pushUndo() { S.undo.push({ k: S.k, t: [...S.t] }); if (S.undo.length > 50) S.undo.shift() }
  function turn(dk) {
    pushUndo()
    const c = center()
    S.k = ((S.k + dk) % 4 + 4) % 4
    const c2 = center()
    S.t = [r3(S.t[0] + c[0] - c2[0]), r3(S.t[1] + c[1] - c2[1])]
    S.dirty = true; draw()
  }
  function nudge(dx, dy) { pushUndo(); S.t = [r3(S.t[0] + dx), r3(S.t[1] + dy)]; S.dirty = true; draw() }

  const pos = e => { const r = cv.getBoundingClientRect(); return [e.clientX - r.left, e.clientY - r.top] }
  let space = false
  cv.addEventListener('contextmenu', e => e.preventDefault())
  cv.addEventListener('pointerdown', e => {
    root.focus(); cv.setPointerCapture(e.pointerId)
    const [sx, sy] = pos(e)
    if (e.button !== 0 || space || !S.show.draw) { S.user = true; S.drag = { t: 'pan', s: [sx, sy], c: [...S.c] }; return }
    pushUndo()
    S.drag = { t: 'move', s: toW(sx, sy), o: [...S.t], moved: false }
  })
  cv.addEventListener('pointermove', e => {
    const d = S.drag
    if (!d) return
    const [sx, sy] = pos(e)
    if (d.t === 'pan') { S.c = [d.c[0] - (sx - d.s[0]) / S.z, d.c[1] + (sy - d.s[1]) / S.z]; draw(); return }
    const w = toW(sx, sy)
    if (Math.hypot(w[0] - d.s[0], w[1] - d.s[1]) * S.z > 2) d.moved = true
    S.t = [r3(d.o[0] + w[0] - d.s[0]), r3(d.o[1] + w[1] - d.s[1])]
    draw()
  })
  cv.addEventListener('pointerup', () => {
    const d = S.drag; S.drag = null
    if (d && d.t === 'move') { if (!d.moved) S.undo.pop(); else S.dirty = true; draw() }
  })
  cv.addEventListener('wheel', e => {
    e.preventDefault(); S.user = true
    const [sx, sy] = pos(e), before = toW(sx, sy)
    S.z = Math.min(2000, Math.max(2, S.z * Math.exp(-e.deltaY * 0.0015)))
    const after = toW(sx, sy)
    S.c = [S.c[0] + before[0] - after[0], S.c[1] + before[1] - after[1]]
    draw()
  }, { passive: false })
  root.addEventListener('keydown', e => {
    if (e.code === 'Space') { space = true; e.preventDefault(); return }
    const st = e.shiftKey ? 0.1 : 0.01
    const mv = { ArrowLeft: [-st, 0], ArrowRight: [st, 0], ArrowUp: [0, st], ArrowDown: [0, -st] }[e.key]
    if (mv && S.show.draw) { e.preventDefault(); nudge(...mv) }
    else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'z') { e.preventDefault(); undo() }
  })
  root.addEventListener('keyup', e => { if (e.code === 'Space') space = false })
  function undo() { const u = S.undo.pop(); if (u) { S.k = u.k; S.t = u.t; S.dirty = true; draw() } }
  root.querySelector('.bar').addEventListener('click', e => {
    const btn = e.target.closest('button'), a = btn?.dataset.a
    if (btn?.dataset.l) { S.show[btn.dataset.l] = !S.show[btn.dataset.l]; draw(); return }
    if (a === 'ccw' && S.show.draw) turn(1)
    else if (a === 'cw' && S.show.draw) turn(-1)
    else if (a === 'undo') undo()
    else if (a === 'fit') { S.user = false; fit(); draw() }
    else if (a === 'save' && S.trig) { S.trig('save', { k: S.k, t: S.t, at: Date.now() }); S.dirty = false; draw() }
  })

  return {
    update(d, trig) {
      S.trig = trig
      root.style.setProperty('--h', d.h + 'px')
      const first = !S.d
      S.d = d
      if (d.rev !== S.rev) { S.rev = d.rev; S.k = d.k; S.t = [...d.t0]; S.undo = []; S.dirty = false }
      if (first || d.fitKey !== S.fitKey) { S.fitKey = d.fitKey; S.fitted = false; S.user = false; if (S.W) fit() }
      draw()
    },
  }
}
"""

_EDITOR = st.components.v2.component("lsats_cad_fit", html=HTML, css=CSS, js=JS)


def cad_fit_editor(*, key: str, drawing: dict, tf: dict, las_polys: list, las_lines: list, points: list, points_none: list | None = None,
                   states: list | None = None, rooms: list | None = None,
                   fit_key: str, height: int = 640):
    """도면(drawing: lines·texts, m 단위·돌림 전)을 tf({k, t}) 자리에 그려 LAS 벽·격자점 층에 맞춘다.
    「저장」을 누른 실행에서만 {k, t} 를 돌려준다 (그 밖엔 None)."""
    data = {"lines": drawing["lines"], "texts": drawing["texts"], "s": 1.0, "k": int(tf["k"]),
            "t0": [float(v) for v in tf["t"]], "lasPolys": las_polys, "lasLines": las_lines, "pts": points, "pts0": points_none or [], "states": states, "rooms": rooms or [],
            "h": height, "fitKey": fit_key}
    data["rev"] = hashlib.md5(json.dumps([data["k"], data["t0"], len(data["lines"])]).encode()).hexdigest()
    res = _EDITOR(key=key, data=data, height=height + 2, on_save_change=lambda: None)
    return getattr(res, "save", None) if res is not None else None
