"""벽 편집기 (Streamlit 커스텀 컴포넌트 v2, 캔버스): 방 배치 화면에서 벽을 작은 CAD 처럼 고친다.

벽 하나 = {k: "line" | "arc", a: [x, y], b: [x, y], m: [x, y](곡선의 가운데 점), t: 두께} (건물 축 m).
- 고르기: 벽 클릭 → 끌면 통째로 이동, 끝점(□)을 끌면 그 끝만, 곡선은 가운데 점(◇)을 끌면 휘는 정도.
  끝점은 다른 벽 끝에 붙고(SNAP_PX), 직선은 수평·수직 근처(ORTHO_DEG)면 딱 맞춘다 (Shift 를 누르면 자유롭게).
- 직선 벽: 시작점 클릭 → 끝점 클릭 (하나 그리면 고르기로 돌아가 방금 그린 벽이 골라진다). 그리는 중 숫자+Enter = 그 길이(mm)로.
- 선(t = 0): 스캔에서 찾은 벽 면 선도 같은 목록에 두께 0 으로 들어 있어 고르기·옮기기·지우기가 되고, 「─ 선」으로 새로 그린다.
- 고른 직선 + 숫자 + Enter = 마우스에 가까운 끝 쪽으로 그만큼(mm) 늘이기 (앞에 - 를 치면 줄이기).
- 곡선 벽: 시작점 → 끝점 → 휘는 정도 클릭.
- 오른쪽 위 칸: 고른 벽의 두께·길이(mm)를 바로 입력 (두께는 새 벽의 기본값도 된다).
- Delete = 지우기, Ctrl+Z = 되돌리기, 오른쪽 버튼·Space+끌기 = 화면 이동, 휠 = 확대.
배경: 스캔에서 찾은 벽 면(검은 가는 선)과 격자점. 편집은 브라우저 안에서만 하고 「저장」 때만 Python 으로 보낸다.
"""
from __future__ import annotations

import hashlib
import json

import streamlit as st

HTML = """
<div class="we" tabindex="0">
  <canvas></canvas>
  <div class="bar">
    <button data-t="select" class="on" title="벽 고르기·옮기기 (Esc)">↖ 고르기</button>
    <button data-t="line" title="직선 벽: 시작점 클릭 → 끝점 클릭. 그리는 중 숫자+Enter = 길이(mm)">／ 직선 벽</button>
    <button data-t="arc" title="곡선 벽: 시작점 → 끝점 → 휘는 정도 클릭">◠ 곡선 벽</button>
    <button data-t="seg" title="선(두께 없는 벽 면 선): 시작점 클릭 → 끝점 클릭. 그리는 중 숫자+Enter = 길이(mm)">─ 선</button>
    <button data-a="del" title="고른 벽 지우기 (Delete)">지우기</button>
    <button data-a="undo" title="되돌리기 (Ctrl+Z)">↶ 되돌리기</button>
    <button data-a="fit" title="전체 보기">전체 보기</button>
    <span class="sep"></span>
    <button data-a="save" class="save" title="바꾼 벽을 저장해요">저장</button>
  </div>
  <div class="panel">
    <label>두께 <input data-f="t" type="number" min="10" step="10"> mm</label>
    <label>길이 <input data-f="len" type="number" min="10" step="10"> mm</label>
  </div>
  <div class="status"></div>
  <div class="help">벽·선 클릭 = 고르기 · 고른 뒤 숫자+Enter = 그만큼 늘이기(- 줄이기) · 끌기 = 이동 · □ 끝점 끌기 = 길이·방향 (다른 벽 끝에 붙고 수평·수직은 딱 맞춤, Shift = 자유) · ◇ = 곡선 휘기 · 그리는 중 숫자+Enter = 길이(mm) · 오른쪽 버튼 끌기 또는 Space+끌기 = 화면 이동 · 휠 = 확대</div>
</div>
"""

CSS = """
.we{position:relative;width:100%;height:var(--h,600px);border:1px solid #dde4ee;border-radius:10px;overflow:hidden;
background:#fff;outline:none;touch-action:none;user-select:none;
font-family:'Malgun Gothic','Apple SD Gothic Neo','Noto Sans KR',sans-serif}
.we canvas{position:absolute;inset:0;width:100%;height:100%;cursor:default}
.bar{position:absolute;left:8px;top:8px;display:flex;flex-wrap:wrap;gap:4px;max-width:calc(100% - 240px)}
.bar button{font:inherit;font-size:12px;padding:4px 9px;border:1px solid #dde4ee;border-radius:7px;background:rgba(255,255,255,.94);
color:#1e293b;cursor:pointer}
.bar button:hover{background:#eef3fa;border-color:#2563eb}
.bar button.on{background:#2563eb;border-color:#2563eb;color:#fff}
.bar button.save{font-weight:700}
.bar button.save.dirty{background:#ea580c;border-color:#ea580c;color:#fff}
.bar .sep{flex:1}
.panel{position:absolute;right:8px;top:8px;display:flex;flex-direction:column;gap:4px;background:rgba(255,255,255,.94);
border:1px solid #dde4ee;border-radius:8px;padding:6px 8px;font-size:12px;color:#1e293b}
.panel input{width:72px;font:inherit;font-size:12px;padding:2px 4px;border:1px solid #cbd5e1;border-radius:5px;text-align:right}
.panel input:disabled{background:#f1f5f9;color:#94a3b8}
.status{position:absolute;left:10px;bottom:46px;font-size:12px;color:#1e293b;background:rgba(255,255,255,.9);padding:2px 6px;border-radius:6px}
.help{position:absolute;left:10px;right:10px;bottom:8px;font-size:11px;color:#64748b;line-height:1.4}
"""

JS = r"""
export default function(component) {
  const { data, parentElement, setTriggerValue } = component
  const root = parentElement.querySelector('.we')
  if (!root || !data) return
  if (!root.__we) root.__we = make(root)
  root.__we.trig = setTriggerValue
  root.__we.update(data)
}

function make(root) {
  const cv = root.querySelector('canvas'), ctx = cv.getContext('2d')
  const status = root.querySelector('.status'), saveBtn = root.querySelector('[data-a=save]')
  const tIn = root.querySelector('[data-f=t]'), lenIn = root.querySelector('[data-f=len]')
  const S = { z: 40, c: [0, 0], W: 0, H: 0, d: null, walls: [], sel: -1, undo: [], dirty: false, tool: 'select',
              drag: null, rev: null, fitted: false, draft: null, typed: '', defT: 0.2, mouse: [0, 0], self: null }
  const SNAP_PX = 10, ORTHO_DEG = 6
  const toS = (x, y) => [S.W / 2 + (x - S.c[0]) * S.z, S.H / 2 - (y - S.c[1]) * S.z]
  const toW = (sx, sy) => [S.c[0] + (sx - S.W / 2) / S.z, S.c[1] - (sy - S.H / 2) / S.z]
  const copy = o => JSON.parse(JSON.stringify(o))
  const r3 = v => Math.round(v * 1000) / 1000
  const P = p => p.map(r3)

  function resize() {
    const r = root.getBoundingClientRect(), dpr = window.devicePixelRatio || 1
    S.W = r.width; S.H = r.height
    cv.width = S.W * dpr; cv.height = S.H * dpr
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
    if (!S.fitted && S.d) fit()
    draw()
  }
  new ResizeObserver(resize).observe(root)
  function fit() {
    if (!S.W || !S.d) return
    let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity
    const add = (x, y) => { x0 = Math.min(x0, x); x1 = Math.max(x1, x); y0 = Math.min(y0, y); y1 = Math.max(y1, y) }
    for (const f of S.d.faces) { add(f[0], f[1]); add(f[2], f[3]) }
    for (const p of S.d.pts) add(p[0], p[1])
    for (const w of S.walls) { add(...w.a); add(...w.b) }
    if (!isFinite(x0)) return
    S.z = Math.min(S.W / Math.max(x1 - x0, 1), (S.H - 70) / Math.max(y1 - y0, 1)) / 1.12
    S.c = [(x0 + x1) / 2, (y0 + y1) / 2 - 10 / S.z]
    S.fitted = true
  }

  // ---- 기하
  function circle3(a, m, b) {  // 세 점을 지나는 원 (중심, 반지름) 또는 null(일직선)
    const d = 2 * (a[0] * (m[1] - b[1]) + m[0] * (b[1] - a[1]) + b[0] * (a[1] - m[1]))
    if (Math.abs(d) < 1e-9) return null
    const s = p => p[0] * p[0] + p[1] * p[1]
    const cx = (s(a) * (m[1] - b[1]) + s(m) * (b[1] - a[1]) + s(b) * (a[1] - m[1])) / d
    const cy = (s(a) * (b[0] - m[0]) + s(m) * (a[0] - b[0]) + s(b) * (m[0] - a[0])) / d
    return { c: [cx, cy], r: Math.hypot(a[0] - cx, a[1] - cy) }
  }
  function arcInfo(w) {  // 시작각·끝각·방향 (a → m → b)
    const C = circle3(w.a, w.m, w.b)
    if (!C) return null
    const ang = p => Math.atan2(p[1] - C.c[1], p[0] - C.c[0])
    const sa = ang(w.a), ma = ang(w.m), ea = ang(w.b)
    const norm = x => (x % (2 * Math.PI) + 2 * Math.PI) % (2 * Math.PI)
    const ccw = norm(ma - sa) < norm(ea - sa)  // a 에서 반시계로 가다 m 을 먼저 만나면 반시계
    return { ...C, sa, ea, ccw, span: ccw ? norm(ea - sa) : norm(sa - ea) }
  }
  function wallLen(w) {
    if (w.k !== 'arc') return Math.hypot(w.b[0] - w.a[0], w.b[1] - w.a[1])
    const A = arcInfo(w); return A ? A.r * A.span : Math.hypot(w.b[0] - w.a[0], w.b[1] - w.a[1])
  }
  function distTo(w, p) {  // 중심선까지 거리 (m)
    if (w.k === 'arc') {
      const A = arcInfo(w)
      if (A) {
        const t = Math.atan2(p[1] - A.c[1], p[0] - A.c[0])
        const norm = x => (x % (2 * Math.PI) + 2 * Math.PI) % (2 * Math.PI)
        const inside = A.ccw ? norm(t - A.sa) <= A.span : norm(A.sa - t) <= A.span
        if (inside) return Math.abs(Math.hypot(p[0] - A.c[0], p[1] - A.c[1]) - A.r)
        return Math.min(Math.hypot(p[0] - w.a[0], p[1] - w.a[1]), Math.hypot(p[0] - w.b[0], p[1] - w.b[1]))
      }
    }
    const [ax, ay] = w.a, [bx, by] = w.b, dx = bx - ax, dy = by - ay, L2 = dx * dx + dy * dy || 1e-12
    const t = Math.max(0, Math.min(1, ((p[0] - ax) * dx + (p[1] - ay) * dy) / L2))
    return Math.hypot(p[0] - ax - t * dx, p[1] - ay - t * dy)
  }
  function wallAt(p) {
    let best = -1, bd = Infinity
    S.walls.forEach((w, i) => { const d = distTo(w, p); if (d <= w.t / 2 + 5 / S.z && d < bd) { bd = d; best = i } })
    return best
  }
  function handleAt(sx, sy) {  // 고른 벽의 손잡이 'a' | 'b' | 'm'
    if (S.sel < 0) return null
    const w = S.walls[S.sel]
    for (const h of (w.k === 'arc' ? ['m', 'a', 'b'] : ['a', 'b'])) {
      const [x, y] = toS(...w[h]); if (Math.hypot(sx - x, sy - y) < 9) return h
    }
    return null
  }
  function snapPoint(p, from, free, skip) {  // 다른 벽 끝점에 붙이고, from 이 있으면 수평·수직 맞춤
    let best = null, bd = SNAP_PX / S.z
    S.walls.forEach((w, i) => {
      if (i === skip) return
      for (const q of [w.a, w.b]) { const d = Math.hypot(q[0] - p[0], q[1] - p[1]); if (d < bd) { bd = d; best = [...q] } }
    })
    if (best) return best
    if (from && !free) {
      const dx = p[0] - from[0], dy = p[1] - from[1], ang = Math.abs(Math.atan2(dy, dx) * 180 / Math.PI)
      if (Math.min(ang, 180 - ang) < ORTHO_DEG) return [p[0], from[1]]
      if (Math.abs(ang - 90) < ORTHO_DEG) return [from[0], p[1]]
    }
    return p
  }

  // ---- 그리기
  function strokeWall(w, style, extra = 0) {
    ctx.strokeStyle = style; ctx.lineWidth = (w.t > 0 ? Math.max(2, w.t * S.z) : 1.4) + extra; ctx.lineCap = 'butt'
    ctx.beginPath()
    if (w.k === 'arc' && arcInfo(w)) {
      const A = arcInfo(w), [cx, cy] = toS(...A.c)
      ctx.arc(cx, cy, A.r * S.z, -A.sa, -A.ea, A.ccw)  // 화면은 y 가 아래로: 각도 부호가 바뀌고, 세계의 반시계 = 화면의 반시계 표시(anticlockwise)
    } else { ctx.moveTo(...toS(...w.a)); ctx.lineTo(...toS(...w.b)) }
    ctx.stroke()
  }
  function draw() {
    if (!S.d || !S.W) return
    ctx.clearRect(0, 0, S.W, S.H)
    ctx.fillStyle = '#cbd5e1'
    for (const p of S.d.pts) { const [x, y] = toS(...p); ctx.beginPath(); ctx.arc(x, y, 2.5, 0, 6.3); ctx.fill() }
    S.walls.forEach((w, i) => {  // 벽(두께 있음)은 회색 띠, 선(두께 0)은 검은 가는 선
      if (i === S.sel) strokeWall(w, 'rgba(234,88,12,0.9)', w.t > 0 ? 4 : 3)
      strokeWall(w, i === S.sel ? (w.t > 0 ? 'rgba(251,146,60,0.65)' : '#ea580c') : (w.t > 0 ? 'rgba(100,116,139,0.6)' : '#0f172a'))
    })
    if (S.sel >= 0) {  // 손잡이
      const w = S.walls[S.sel]
      ctx.fillStyle = '#fff'; ctx.strokeStyle = '#ea580c'; ctx.lineWidth = 1.5
      for (const h of ['a', 'b']) { const [x, y] = toS(...w[h]); ctx.fillRect(x - 4, y - 4, 8, 8); ctx.strokeRect(x - 4, y - 4, 8, 8) }
      if (w.k === 'arc') { const [x, y] = toS(...w.m); ctx.beginPath(); ctx.moveTo(x, y - 6); ctx.lineTo(x + 6, y); ctx.lineTo(x, y + 6); ctx.lineTo(x - 6, y); ctx.closePath(); ctx.fill(); ctx.stroke() }
      const [mx, my] = toS(...(w.k === 'arc' ? w.m : [(w.a[0] + w.b[0]) / 2, (w.a[1] + w.b[1]) / 2]))
      ctx.fillStyle = '#9a3412'; ctx.font = '700 12px sans-serif'; ctx.textAlign = 'center'
      ctx.fillText(`${Math.round(wallLen(w) * 1000)} mm · 두께 ${Math.round(w.t * 1000)}`, mx, my - 12)
    }
    if (S.draft) {  // 그리는 중
      const d = S.draft, w = { k: d.k === 'seg' ? 'line' : d.k, a: d.a, b: d.b || S.mouseW, m: d.m || d.b, t: d.k === 'seg' ? 0 : S.defT }
      if (d.k === 'arc' && d.b && !d.m) w.m = S.mouseW
      if (d.k === 'arc' && !d.b) w.k = 'line'
      ctx.setLineDash([6, 4]); strokeWall(w, 'rgba(22,163,74,0.5)'); ctx.setLineDash([])
      const [mx, my] = toS(...S.mouseW)
      ctx.fillStyle = '#166534'; ctx.font = '700 12px sans-serif'; ctx.textAlign = 'left'
      ctx.fillText(`${Math.round(Math.hypot(w.b[0] - w.a[0], w.b[1] - w.a[1]) * 1000)} mm`, mx + 10, my - 10)
    }
    const tool = { select: '고르기', line: '직선 벽', arc: '곡선 벽', seg: '선' }[S.tool]
    const step = S.draft ? (S.draft.k === 'arc' ? (S.draft.b ? '휘는 정도를 클릭하세요' : '끝점을 클릭하세요') : '끝점을 클릭하거나 길이(mm)를 치고 Enter · Esc = 끝')
                         : S.tool === 'select' ? (S.sel >= 0 ? `${S.walls[S.sel].t > 0 ? '벽' : '선'} 고름 — 숫자를 치고 Enter = 마우스 쪽 끝으로 그만큼 늘이기(- 는 줄이기)` : '벽·선을 클릭해 고르세요') : '시작점을 클릭하세요'
    const typedMsg = S.typed ? (S.draft ? ` · 입력한 길이 ${S.typed} mm (Enter)` : ` · ${S.typed} mm ${S.typed.startsWith('-') ? '줄이기' : '늘이기'} (Enter, Esc = 취소)`) : ''
    status.textContent = `${tool}: ${step}` + typedMsg +
                         ` · 벽 ${S.walls.length}개` + (S.dirty ? ' · 저장 안 한 변경이 있어요' : '')
    saveBtn.classList.toggle('dirty', S.dirty)
    root.querySelectorAll('[data-t]').forEach(b => b.classList.toggle('on', b.dataset.t === S.tool))
    syncPanel()
  }
  function syncPanel() {
    if (document.activeElement === tIn || document.activeElement === lenIn) return
    const w = S.sel >= 0 ? S.walls[S.sel] : null
    tIn.value = Math.round((w ? w.t : S.defT) * 1000)
    lenIn.disabled = !w || w.k === 'arc'
    lenIn.value = w ? Math.round(wallLen(w) * 1000) : ''
  }

  function pushUndo() { S.undo.push(copy(S.walls)); if (S.undo.length > 80) S.undo.shift() }
  function changed() { S.dirty = true; draw() }
  function setTool(t) { S.tool = t; S.draft = null; S.typed = ''; if (t !== 'select') S.sel = -1; draw() }

  const pos = e => { const r = cv.getBoundingClientRect(); return [e.clientX - r.left, e.clientY - r.top] }
  let space = false
  root.addEventListener('keyup', e => { if (e.code === 'Space') space = false })
  cv.addEventListener('contextmenu', e => e.preventDefault())
  cv.addEventListener('pointerdown', e => {
    root.focus(); cv.setPointerCapture(e.pointerId)
    const [sx, sy] = pos(e), w = toW(sx, sy)
    if (e.button !== 0 || space) { S.drag = { t: 'pan', s: [sx, sy], c: [...S.c] }; return }
    if (S.tool !== 'select') {
      const d = S.draft
      if (!d) { S.draft = { k: S.tool, a: P(snapPoint(w, null, e.shiftKey)) }; S.typed = ''; draw(); return }
      if (!d.b) {
        const b = P(snapPoint(w, d.a, e.shiftKey))
        if (Math.hypot(b[0] - d.a[0], b[1] - d.a[1]) < 0.05) return
        if (d.k !== 'arc') { finishStraight(d.a, b); return }
        d.b = b; draw(); return
      }
      addWall({ k: 'arc', a: d.a, b: d.b, m: P(w), t: S.defT }); S.draft = null; S.tool = 'select'; draw(); return
    }
    const h = handleAt(sx, sy)
    if (h) { pushUndo(); S.drag = { t: 'handle', h, o: copy(S.walls[S.sel]), moved: false }; return }
    const k = wallAt(w)
    S.sel = k
    if (k >= 0) { pushUndo(); S.drag = { t: 'move', s: w, o: copy(S.walls[k]), moved: false } }
    draw()
  })
  cv.addEventListener('pointermove', e => {
    const [sx, sy] = pos(e), w = toW(sx, sy), d = S.drag
    S.mouseW = w
    if (!d) {
      if (S.draft && !S.draft.b) S.mouseW = snapPoint(w, S.draft.a, e.shiftKey)
      cv.style.cursor = space ? 'grab' : S.tool !== 'select' ? 'crosshair' : handleAt(sx, sy) ? 'crosshair' : wallAt(w) >= 0 ? 'move' : 'default'
      draw(); return
    }
    if (d.t === 'pan') { S.c = [d.c[0] - (sx - d.s[0]) / S.z, d.c[1] + (sy - d.s[1]) / S.z]; draw(); return }
    d.moved = true
    const W = S.walls[S.sel]
    if (d.t === 'move') {
      const dx = w[0] - d.s[0], dy = w[1] - d.s[1]
      for (const k of ['a', 'b', 'm']) if (d.o[k]) W[k] = P([d.o[k][0] + dx, d.o[k][1] + dy])
    } else if (d.h === 'm') W.m = P(w)
    else {
      const other = d.h === 'a' ? d.o.b : d.o.a
      W[d.h] = P(snapPoint(w, W.k === 'line' ? other : null, e.shiftKey, S.sel))
      if (W.k === 'arc') {  // 끝점을 옮겨도 휘는 정도는 그대로: 가운데 점을 새 현의 수직 이등분선 위로
        const A = d.o, mid0 = [(A.a[0] + A.b[0]) / 2, (A.a[1] + A.b[1]) / 2], L0 = Math.hypot(A.b[0] - A.a[0], A.b[1] - A.a[1]) || 1
        const sag = ((A.m[0] - mid0[0]) * -(A.b[1] - A.a[1]) + (A.m[1] - mid0[1]) * (A.b[0] - A.a[0])) / L0
        const L = Math.hypot(W.b[0] - W.a[0], W.b[1] - W.a[1]) || 1, n = [-(W.b[1] - W.a[1]) / L, (W.b[0] - W.a[0]) / L]
        W.m = P([(W.a[0] + W.b[0]) / 2 + n[0] * sag * L / L0, (W.a[1] + W.b[1]) / 2 + n[1] * sag * L / L0])
      }
    }
    draw()
  })
  cv.addEventListener('pointerup', () => {
    const d = S.drag; S.drag = null
    if (d && d.t !== 'pan') { if (d.moved) changed(); else S.undo.pop() }
  })
  cv.addEventListener('wheel', e => {
    e.preventDefault()
    const [sx, sy] = pos(e), before = toW(sx, sy)
    S.z = Math.min(3000, Math.max(2, S.z * Math.exp(-e.deltaY * 0.0015)))
    const after = toW(sx, sy)
    S.c = [S.c[0] + before[0] - after[0], S.c[1] + before[1] - after[1]]
    draw()
  }, { passive: false })

  function finishStraight(a, b) {  // 직선 벽·선 하나를 넣고 고르기로 돌아간다 (방금 그린 것을 고른 채)
    addWall({ k: 'line', a, b, t: S.draft && S.draft.k === 'seg' ? 0 : S.defT })
    S.draft = null; S.typed = ''; S.tool = 'select'; draw()
  }
  function extendSel(mm) {  // 고른 직선을 마우스에 가까운 끝 쪽으로 mm 만큼 늘인다 (음수 = 줄임)
    const w = S.walls[S.sel]
    if (!w || w.k === 'arc') { window.alert('곡선 벽은 길이를 숫자로 바꿀 수 없어요. 끝점(□)을 끌어 주세요.'); return }
    const m = S.mouseW || w.b, end = Math.hypot(m[0] - w.a[0], m[1] - w.a[1]) < Math.hypot(m[0] - w.b[0], m[1] - w.b[1]) ? 'a' : 'b'
    const o = end === 'a' ? w.b : w.a, p = w[end], L = Math.hypot(p[0] - o[0], p[1] - o[1]) || 1, nl = L + mm / 1000
    if (nl < 0.05) { window.alert('그만큼 줄이면 벽이 없어져요.'); return }
    pushUndo(); w[end] = P([o[0] + (p[0] - o[0]) / L * nl, o[1] + (p[1] - o[1]) / L * nl]); changed()
  }
  function addWall(w) { pushUndo(); S.walls.push(w); S.sel = S.walls.length - 1; changed() }
  function del() { if (S.sel < 0) return; pushUndo(); S.walls.splice(S.sel, 1); S.sel = -1; changed() }
  function undo() { if (S.undo.length) { S.walls = S.undo.pop(); S.sel = -1; S.dirty = true; draw() } }

  root.addEventListener('keydown', e => {
    if (e.target === tIn || e.target === lenIn) return
    if (e.code === 'Space') { space = true; e.preventDefault(); return }
    const typing = (S.draft && !S.draft.b) || (S.tool === 'select' && S.sel >= 0)
    if (typing && (/^[0-9]$/.test(e.key) || (e.key === '-' && !S.typed && !S.draft))) { S.typed += e.key; e.preventDefault(); draw(); return }
    if (S.typed && e.key === 'Backspace') { S.typed = S.typed.slice(0, -1); e.preventDefault(); draw(); return }
    if (!S.draft && S.sel >= 0 && S.typed && e.key === 'Enter') {  // 고른 벽 + 숫자 + Enter = 그만큼 늘이기
      e.preventDefault(); const v = Number(S.typed); S.typed = ''
      if (v) extendSel(v); else draw()
      return
    }
    if (S.draft && !S.draft.b && S.typed && e.key === 'Enter') {  // 길이 입력: 마우스 쪽 방향으로 그 길이만큼
      e.preventDefault()
      const a = S.draft.a, m = S.mouseW || [a[0] + 1, a[1]], L = Math.hypot(m[0] - a[0], m[1] - a[1]) || 1
      const len = Number(S.typed) / 1000, b = P([a[0] + (m[0] - a[0]) / L * len, a[1] + (m[1] - a[1]) / L * len])
      S.typed = ''
      if (S.draft.k !== 'arc') { finishStraight(a, b); return }
      S.draft.b = b
      draw(); return
    }
    if (e.key === 'Escape') { if (S.typed) S.typed = ''; else if (S.draft) S.draft = null; else { S.tool = 'select'; S.sel = -1 } draw(); return }
    if ((e.key === 'Delete' || e.key === 'Backspace') && S.sel >= 0) { e.preventDefault(); del(); return }
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'z') { e.preventDefault(); undo() }
  })
  function applyPanel(inp) {
    const v = Number(inp.value) / 1000
    if (!(v > 0)) return
    if (inp === tIn) {
      S.defT = v
      if (S.sel >= 0 && Math.abs(S.walls[S.sel].t - v) > 1e-9) { pushUndo(); S.walls[S.sel].t = r3(v); changed() } else draw()
    } else if (S.sel >= 0 && S.walls[S.sel].k === 'line') {  // 길이: 시작점(a)을 두고 끝점(b)을 옮긴다
      const w = S.walls[S.sel], L = Math.hypot(w.b[0] - w.a[0], w.b[1] - w.a[1]) || 1
      pushUndo(); w.b = P([w.a[0] + (w.b[0] - w.a[0]) / L * v, w.a[1] + (w.b[1] - w.a[1]) / L * v]); changed()
    }
  }
  for (const inp of [tIn, lenIn]) {
    inp.addEventListener('keydown', e => { if (e.key === 'Enter') { applyPanel(inp); inp.blur() } e.stopPropagation() })
    inp.addEventListener('change', () => applyPanel(inp))
  }
  root.querySelector('.bar').addEventListener('click', e => {
    const b = e.target.closest('button'); if (!b) return
    if (b.dataset.t) return setTool(b.dataset.t)
    const a = b.dataset.a
    if (a === 'del') del()
    else if (a === 'undo') undo()
    else if (a === 'fit') { fit(); draw() }
    else if (a === 'save' && S.trig) { S.trig('save', { walls: S.walls, t: Date.now() }); S.dirty = false; draw() }
  })

  return {
    trig: null,
    update(d) {
      if (this.trig) S.trig = this.trig
      root.style.setProperty('--h', d.h + 'px')
      const first = !S.d
      S.d = d
      if (d.rev !== S.rev) { S.rev = d.rev; S.walls = copy(d.walls); S.undo = []; S.dirty = false; S.sel = -1; S.draft = null }
      if (d.defT && first) S.defT = d.defT
      if (first || d.fitKey !== S.fitKey) { S.fitKey = d.fitKey; S.fitted = false; if (S.W) fit() }
      draw()
    },
  }
}
"""

_EDITOR = st.components.v2.component("lsats_wall_editor", html=HTML, css=CSS, js=JS)


def wall_editor(*, key: str, faces: list, points: list, walls: list[dict], fit_key: str, default_t: float = 0.2,
                height: int = 600):
    """벽 편집기를 그리고, 「저장」을 누른 실행에서만 {walls: [...]} 를 돌려준다 (그 밖엔 None)."""
    data = {"faces": faces, "pts": points, "walls": walls, "h": height, "fitKey": fit_key, "defT": default_t,
            "rev": hashlib.md5(json.dumps(walls, sort_keys=True).encode()).hexdigest()}
    res = _EDITOR(key=key, data=data, height=height + 2, on_save_change=lambda: None)
    return getattr(res, "save", None) if res is not None else None
