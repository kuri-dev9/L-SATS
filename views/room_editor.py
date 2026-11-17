"""방 편집기 (Streamlit 커스텀 컴포넌트 v2, 캔버스): 방 배치 화면에서 방을 직접 잡아 옮기고 경계를 끌어 맞춘다.

- 방 클릭 = 선택 / 선택한 방 안을 끌기 = 방 이동 / 선택한 방의 변을 끌기 = 그 경계만 이동 (가로 변은 위아래, 세로 변은 좌우)
- 옮길 때 가까운 벽 면(스캔에서 찾은 선)에 붙는다 (SNAP_PX 화면 픽셀 또는 0.15 m 안)
- 빈 곳 끌기 = 새 방(직사각형), 「방 위에 새 방 그리기」(또는 Shift+끌기)면 이미 있는 방 위에도 그린다
- 변 우클릭 → 「여기서 벽면 나누기」: 그 자리에 꼭짓점 두 개를 넣어 변을 둘로 나눈다 (한쪽만 끌면 ㄱ·ㄷ자로 꺾인다)
  선택한 방의 꼭짓점을 끌어 다른 꼭짓점에 놓기 = 두 점을 곧게 잇고 그 사이 점을 없앤다 (사이 점이 적은 쪽)
- 「방에서 빼기」를 켜고 끌면 그린 네모만큼 방에서 깎아 바로 저장한다 (Python: las_layout.subtract_rect)
- 더블클릭 = 이름 바꾸기, Delete = 지우기, Ctrl+Z = 되돌리기, 오른쪽 버튼·Space+끌기 = 화면 이동, 휠 = 확대·축소
- 새로 그리거나 마지막으로 고친 방을 목록 맨 뒤로 보내고, 저장할 때 겹친 칸은 뒤쪽 방이 갖는다 (las_layout.resolve_overlaps)
편집은 브라우저 안에서만 하고 「저장」을 누를 때만 Python 으로 보낸다 (누를 때마다 보내면 화면 전체가 다시 실행되며 깜빡임).
"""
from __future__ import annotations

import hashlib
import json

import streamlit as st

HTML = """
<div class="re" tabindex="0">
  <canvas></canvas>
  <div class="bar">
    <button data-a="draw" title="켜면 이미 있는 방 위에도 새 방을 그릴 수 있어요 (Shift+끌기도 돼요). 겹친 부분은 새 방 쪽으로 정리돼요">＋ 방 위에 새 방 그리기</button>
    <button data-a="cut" title="켜고 끌면 그린 네모만큼 방에서 빼요 (슬라브가 없는 곳 등). 바로 저장돼요">－ 방에서 빼기</button>
    <button data-a="rename" title="선택한 방 이름 바꾸기 (방 더블클릭도 돼요)">이름 바꾸기</button>
    <button data-a="del" title="선택한 방 지우기 (Delete 키)">방 지우기</button>
    <button data-a="undo" title="되돌리기 (Ctrl+Z)">↶ 되돌리기</button>
    <button data-a="fit" title="전체 보기">전체 보기</button>
    <span class="sep"></span>
    <button data-a="save" class="save" title="바꾼 방을 저장해요">저장</button>
  </div>
  <div class="status"></div>
  <div class="menu"></div>
  <div class="help">빈 곳 끌기 = 새 방 · 방 클릭 = 선택 · 방 안 끌기 = 이동 · 변 끌기 = 경계 이동 (벽에 붙어요) · 변 우클릭 = 벽면 나누기 · 꼭짓점을 다른 꼭짓점에 끌어 놓기 = 두 점 잇기(사이 점 없앰) · 오른쪽 버튼 끌기 또는 Space+끌기 = 화면 이동 · 휠 = 확대</div>
</div>
"""

CSS = """
.re{position:relative;width:100%;height:var(--h,600px);border:1px solid #dde4ee;border-radius:10px;overflow:hidden;
background:#fff;outline:none;touch-action:none;user-select:none;
font-family:'Malgun Gothic','Apple SD Gothic Neo','Noto Sans KR',sans-serif}
.re canvas{position:absolute;inset:0;width:100%;height:100%;cursor:grab}
.bar{position:absolute;left:8px;top:8px;display:flex;flex-wrap:wrap;gap:4px;pointer-events:none;max-width:calc(100% - 16px)}
.bar button{pointer-events:auto;font:inherit;font-size:12px;padding:4px 9px;border:1px solid #dde4ee;border-radius:7px;background:rgba(255,255,255,.94);
color:#1e293b;cursor:pointer}
.bar button:hover{background:#eef3fa;border-color:#2563eb}
.bar button.on{background:#2563eb;border-color:#2563eb;color:#fff}
.bar button[data-a=cut].on{background:#dc2626;border-color:#dc2626}
.bar button.save{font-weight:700}
.bar button.save.dirty{background:#ea580c;border-color:#ea580c;color:#fff}
.bar .sep{flex:1}
.status{position:absolute;left:10px;bottom:46px;font-size:12px;color:#1e293b;background:rgba(255,255,255,.9);padding:2px 6px;border-radius:6px}
.help{position:absolute;left:10px;right:10px;bottom:8px;font-size:11px;color:#64748b;line-height:1.4}
.menu{display:none;position:absolute;z-index:5;min-width:180px;background:#fff;border:1px solid #cbd5e1;border-radius:8px;
box-shadow:0 6px 18px rgba(15,23,42,.15);padding:4px}
.menu button{display:block;width:100%;text-align:left;font:inherit;font-size:13px;padding:6px 10px;border:0;background:none;
border-radius:6px;cursor:pointer;color:#1e293b}
.menu button:hover{background:#eef3fa}
"""

JS = r"""
export default function(component) {
  const { data, parentElement, setTriggerValue } = component
  const root = parentElement.querySelector('.re')
  if (!root || !data) return
  if (!root.__re) root.__re = make(root)
  root.__re.trig = setTriggerValue
  root.__re.update(data)
}

function make(root) {
  const cv = root.querySelector('canvas'), ctx = cv.getContext('2d')
  const status = root.querySelector('.status'), saveBtn = root.querySelector('[data-a=save]')
  const drawBtn = root.querySelector('[data-a=draw]'), cutBtn = root.querySelector('[data-a=cut]')
  const S = { z: 40, c: [0, 0], W: 0, H: 0, d: null, rooms: [], sel: -1, undo: [], dirty: false, draw: false,
              drag: null, rev: null, fitted: false, hoverEdge: -1, trig: null, cut: false }
  const SNAP_PX = 12, SNAP_M = 0.15

  const toS = (x, y) => [S.W / 2 + (x - S.c[0]) * S.z, S.H / 2 - (y - S.c[1]) * S.z]
  const toW = (sx, sy) => [S.c[0] + (sx - S.W / 2) / S.z, S.c[1] - (sy - S.H / 2) / S.z]
  const copy = o => JSON.parse(JSON.stringify(o))
  const r3 = v => Math.round(v * 1000) / 1000

  function resize() {
    const r = root.getBoundingClientRect(), dpr = window.devicePixelRatio || 1
    S.W = r.width; S.H = r.height
    cv.width = S.W * dpr; cv.height = S.H * dpr
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
    if (!S.fitted && S.d) fit()
    draw()
  }
  new ResizeObserver(resize).observe(root)

  function bbox() {
    let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity
    const add = (x, y) => { x0 = Math.min(x0, x); x1 = Math.max(x1, x); y0 = Math.min(y0, y); y1 = Math.max(y1, y) }
    for (const w of S.d.walls) { add(w[0], w[1]); add(w[2], w[3]) }
    for (const p of S.d.pts) add(p[0], p[1])
    for (const r of S.rooms) for (const p of r.poly) add(p[0], p[1])
    return [x0, y0, x1, y1]
  }
  function fit() {
    if (!S.W || !S.d) return
    const [x0, y0, x1, y1] = bbox()
    if (!isFinite(x0)) return
    S.z = Math.min(S.W / Math.max(x1 - x0, 1) , (S.H - 70) / Math.max(y1 - y0, 1)) / 1.12
    S.c = [(x0 + x1) / 2, (y0 + y1) / 2 - 10 / S.z]
    S.fitted = true
  }

  function inPoly(x, y, poly) {
    let inside = false
    for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
      const [xi, yi] = poly[i], [xj, yj] = poly[j]
      if ((yi > y) !== (yj > y) && x < (xj - xi) * (y - yi) / (yj - yi) + xi) inside = !inside
    }
    return inside
  }
  function area(poly) {
    let s = 0
    for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) s += (poly[j][0] + poly[i][0]) * (poly[j][1] - poly[i][1])
    return Math.abs(s) / 2
  }
  function roomAt(x, y) {  // 겹치면 작은 방
    let best = -1, ba = Infinity
    S.rooms.forEach((r, i) => { if (inPoly(x, y, r.poly)) { const a = area(r.poly); if (a < ba) { ba = a; best = i } } })
    return best
  }
  function edgeHit(k, sx, sy, tol = 7) {  // 방 k 의 변 중 화면 tol px 안에서 가장 가까운 것 {i, d, t}
    const p = S.rooms[k].poly, n = p.length
    let best = null
    for (let i = 0; i < n; i++) {
      const [ax, ay] = toS(...p[i]), [bx, by] = toS(...p[(i + 1) % n])
      const dx = bx - ax, dy = by - ay, L2 = dx * dx + dy * dy
      if (L2 < 1e-6) continue  // 나눈 자리의 길이 0 인 변은 잡지 않는다
      const t = Math.max(0, Math.min(1, ((sx - ax) * dx + (sy - ay) * dy) / L2))
      const d = Math.hypot(sx - ax - t * dx, sy - ay - t * dy)
      if (d < tol && (!best || d < best.d)) best = { i, d, t }
    }
    return best
  }
  function edgeAt(sx, sy) {  // 선택한 방의 변 (화면 7px 안)
    if (S.sel < 0) return -1
    const h = edgeHit(S.sel, sx, sy)
    return h ? h.i : -1
  }
  function edgeAtAny(sx, sy) {  // 선택한 방 먼저, 없으면 아무 방의 변 {k, i, t}
    if (S.sel >= 0) { const h = edgeHit(S.sel, sx, sy, 9); if (h) return { k: S.sel, ...h } }
    let best = null
    S.rooms.forEach((_, k) => { const h = edgeHit(k, sx, sy, 9); if (h && (!best || h.d < best.d)) best = { k, ...h } })
    return best
  }
  function cleanPoly(p) {  // 같은 점·한 줄 위 가운데 점 빼기
    let changed = true
    while (changed && p.length > 4) {
      changed = false
      for (let i = 0; i < p.length; i++) {
        const a = p[(i - 1 + p.length) % p.length], b = p[i], c = p[(i + 1) % p.length]
        const same = Math.abs(a[0] - b[0]) < 1e-9 && Math.abs(a[1] - b[1]) < 1e-9
        const between = (b[0] - a[0]) * (c[0] - b[0]) + (b[1] - a[1]) * (c[1] - b[1]) > 0  // 되돌아가는 점(구멍 다리)은 둔다
        const col = between && Math.abs((b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])) < 1e-9
        if (same || col) { p.splice(i, 1); changed = true; break }
      }
    }
    return p
  }
  function vertexAt(sx, sy, except = -1) {  // 선택한 방의 꼭짓점 (화면 8px 안)
    if (S.sel < 0) return -1
    let best = -1, bd = 8
    S.rooms[S.sel].poly.forEach((q, i) => {
      if (i === except) return
      const [x, y] = toS(...q), d = Math.hypot(sx - x, sy - y)
      if (d < bd) { bd = d; best = i }
    })
    return best
  }
  function straighten(p) {  // 거의 일자(기울기 1/10 미만, 어긋남 6 cm 미만)로 이어지는 변들을 길이 가중 평균 높이(위치) 하나로
    const n = p.length, flat = (a, b, ax) => {
      const d = Math.abs(b[ax] - a[ax]), L = Math.abs(b[1 - ax] - a[1 - ax])
      return d < 0.06 && d < 0.1 * L
    }
    for (const ax of [1, 0]) {  // 1 = 가로 변(y 맞춤), 0 = 세로 변(x 맞춤)
      let start = 0
      while (start < n && flat(p[(start - 1 + n) % n], p[start], ax)) start++  // 줄의 시작점에서 출발
      if (start === n) continue
      for (let t = 0; t < n;) {
        const i0 = (start + t) % n
        let m = 0, sw = 0, sv = 0
        while (m < n && flat(p[(i0 + m) % n], p[(i0 + m + 1) % n], ax)) {
          const a = p[(i0 + m) % n], b = p[(i0 + m + 1) % n], w = Math.abs(b[1 - ax] - a[1 - ax]) + 1e-9
          sw += w; sv += w * (a[ax] + b[ax]) / 2; m++
        }
        if (m >= 1) { const v = r3(sv / sw); for (let q = 0; q <= m; q++) p[(i0 + q) % n][ax] = v }
        t += Math.max(m, 1)
      }
    }
    return p
  }
  function connect(k, i, j) {  // 꼭짓점 i 와 j 를 곧게 잇고 그 사이 점을 없앤다 (사이 점이 적은 쪽, 같으면 넓이가 큰 쪽을 남긴다)
    const p = S.rooms[k].poly, n = p.length
    const between = (a, b) => { const out = []; for (let t = (a + 1) % n; t !== b; t = (t + 1) % n) out.push(t); return out }
    const A = between(i, j), B = between(j, i)
    const keepIf = rm => p.filter((_, t) => !rm.includes(t))
    let rm = A.length < B.length ? A : B.length < A.length ? B : (area(keepIf(A)) >= area(keepIf(B)) ? A : B)
    if (!rm.length) { window.alert('이미 바로 이웃한 점이에요. 사이에 없앨 점이 없어요.'); return }
    if (n - rm.length < 3) return
    pushUndo()
    S.rooms[k].poly = cleanPoly(straighten(keepIf(rm)))
    S.sel = k; S.mark = null; changed()
  }
  function split(k, i, t) {  // 방 k 의 변 i 를 t(0~1) 자리에서 둘로: 같은 점 두 개를 넣어, 한쪽만 끌면 그 사이가 꺾인다
    const p = S.rooms[k].poly, a = p[i], b = p[(i + 1) % p.length]
    const L = Math.hypot(b[0] - a[0], b[1] - a[1])
    if (L * Math.min(t, 1 - t) < 0.1) { window.alert('변 끝에서 너무 가까워요. 조금 더 안쪽에서 나눠 주세요.'); return }
    const q = [r3(a[0] + (b[0] - a[0]) * t), r3(a[1] + (b[1] - a[1]) * t)]
    pushUndo()
    p.splice(i + 1, 0, [...q], [...q])
    S.sel = k; S.mark = q; changed()
  }
  const horiz = (p, i) => Math.abs(p[i][1] - p[(i + 1) % p.length][1]) < 1e-9
  function snapV(v, cands) {  // 가까운 벽 면 위치로
    const tol = Math.max(SNAP_M, SNAP_PX / S.z)
    let best = v, bd = tol
    for (const c of cands) { const d = Math.abs(c - v); if (d < bd) { bd = d; best = c } }
    return best
  }
  function snapShift(vals, delta, cands) {  // 여러 변 중 하나라도 벽에 붙도록 이동량을 조금 고친다
    const tol = Math.max(SNAP_M, SNAP_PX / S.z)
    let best = delta, bd = tol
    for (const v of vals) for (const c of cands) {
      const d = Math.abs(v + delta - c)
      if (d < bd) { bd = d; best = c - v }
    }
    return best
  }
  function labelPt(poly) {
    const xs = poly.map(p => p[0]), ys = poly.map(p => p[1])
    const x0 = Math.min(...xs), x1 = Math.max(...xs), y0 = Math.min(...ys), y1 = Math.max(...ys)
    let cx = (x0 + x1) / 2, cy = (y0 + y1) / 2
    if (inPoly(cx, cy, poly)) return [cx, cy]
    let best = null, bd = Infinity
    for (let i = 1; i < 12; i++) for (let j = 1; j < 12; j++) {
      const x = x0 + (x1 - x0) * i / 12, y = y0 + (y1 - y0) * j / 12
      if (inPoly(x, y, poly)) { const d = Math.hypot(x - cx, y - cy); if (d < bd) { bd = d; best = [x, y] } }
    }
    return best || [cx, cy]
  }

  function draw() {
    if (!S.d || !S.W) return
    ctx.clearRect(0, 0, S.W, S.H)
    // 벽 띠 (추정)
    ctx.fillStyle = 'rgba(148,163,184,0.55)'
    for (const poly of (S.d.wallPolys || [])) {  // 벽 (방 배치에서 고친 벽, 없으면 자동 추정)
      ctx.beginPath(); poly.forEach((q, k) => { const s = toS(q[0], q[1]); k ? ctx.lineTo(...s) : ctx.moveTo(...s) }); ctx.closePath(); ctx.fill()
    }
    // 벽 면
    ctx.strokeStyle = '#334155'; ctx.lineWidth = 1.3; ctx.beginPath()
    for (const w of S.d.walls) { const a = toS(w[0], w[1]), b = toS(w[2], w[3]); ctx.moveTo(...a); ctx.lineTo(...b) }
    ctx.stroke()
    // 격자점
    ctx.fillStyle = '#cbd5e1'
    for (const p of S.d.pts) { const [x, y] = toS(p[0], p[1]); ctx.beginPath(); ctx.arc(x, y, 2.5, 0, 6.3); ctx.fill() }
    // 방
    S.rooms.forEach((r, i) => {
      const on = i === S.sel
      ctx.beginPath()
      r.poly.forEach((p, k) => { const s = toS(p[0], p[1]); k ? ctx.lineTo(...s) : ctx.moveTo(...s) })
      ctx.closePath()
      ctx.fillStyle = on ? 'rgba(234,88,12,0.14)' : 'rgba(37,99,235,0.08)'; ctx.fill()
      ctx.strokeStyle = on ? '#ea580c' : '#2563eb'; ctx.lineWidth = on ? 2.2 : 1.5; ctx.stroke()
    })
    // 선택한 방의 꼭짓점 (나눈 자리 포함)
    if (S.sel >= 0) {
      ctx.fillStyle = '#fff'; ctx.strokeStyle = '#ea580c'; ctx.lineWidth = 1.5
      for (const q of S.rooms[S.sel].poly) { const [x, y] = toS(...q); ctx.fillRect(x - 3, y - 3, 6, 6); ctx.strokeRect(x - 3, y - 3, 6, 6) }
    }
    if (S.mark) {  // 방금 나눈 자리
      const [x, y] = toS(...S.mark)
      ctx.strokeStyle = '#16a34a'; ctx.lineWidth = 2; ctx.beginPath(); ctx.arc(x, y, 7, 0, 6.3); ctx.stroke()
    }
    // 선택한 방의 잡은 변
    if (S.sel >= 0 && S.hoverEdge >= 0) {
      const p = S.rooms[S.sel].poly, i = S.hoverEdge
      ctx.strokeStyle = '#ea580c'; ctx.lineWidth = 5; ctx.beginPath()
      ctx.moveTo(...toS(...p[i])); ctx.lineTo(...toS(...p[(i + 1) % p.length])); ctx.stroke()
    }
    // 이름
    ctx.textAlign = 'center'; ctx.textBaseline = 'middle'
    S.rooms.forEach((r, i) => {
      const [x, y] = toS(...labelPt(r.poly))
      ctx.font = `700 ${i === S.sel ? 14 : 13}px 'Malgun Gothic','Apple SD Gothic Neo',sans-serif`
      ctx.fillStyle = i === S.sel ? '#9a3412' : '#1e3a8a'
      ctx.fillText(r.name, x, y)
      ctx.font = `11px sans-serif`; ctx.fillStyle = '#64748b'
      ctx.fillText(area(r.poly).toFixed(1) + '㎡', x, y + 15)
    })
    // 꼭짓점 잇는 중
    if (S.drag && S.drag.t === 'link' && S.sel >= 0) {
      const p = S.rooms[S.sel].poly, a = toS(...p[S.drag.i])
      const b = S.drag.j >= 0 ? toS(...p[S.drag.j]) : toS(...S.drag.b)
      ctx.setLineDash([5, 4]); ctx.strokeStyle = '#16a34a'; ctx.lineWidth = 2
      ctx.beginPath(); ctx.moveTo(...a); ctx.lineTo(...b); ctx.stroke(); ctx.setLineDash([])
      for (const [q, r] of [[a, 6], ...(S.drag.j >= 0 ? [[b, 8]] : [])]) {
        ctx.fillStyle = '#16a34a'; ctx.beginPath(); ctx.arc(q[0], q[1], r, 0, 6.3); ctx.fill()
      }
    }
    // 새 방 그리는 중
    if (S.drag && S.drag.t === 'new') {
      const [a, b] = [toS(...S.drag.a), toS(...S.drag.b)]
      ctx.setLineDash([5, 4]); ctx.strokeStyle = S.drag.cut ? '#dc2626' : '#16a34a'; ctx.lineWidth = 1.5
      if (S.drag.cut) { ctx.fillStyle = 'rgba(220,38,38,0.12)'; ctx.fillRect(Math.min(a[0], b[0]), Math.min(a[1], b[1]), Math.abs(b[0] - a[0]), Math.abs(b[1] - a[1])) }
      ctx.strokeRect(Math.min(a[0], b[0]), Math.min(a[1], b[1]), Math.abs(b[0] - a[0]), Math.abs(b[1] - a[1]))
      ctx.setLineDash([])
    }
    const sel = S.sel >= 0 ? `선택: ${S.rooms[S.sel].name} (${area(S.rooms[S.sel].poly).toFixed(1)}㎡)` : '방을 클릭해 고르세요'
    status.textContent = (S.cut ? '방에서 빼기: 뺄 범위를 끌어서 그리세요 · ' : S.draw ? '새 방 그리기: 끌어서 범위를 정하세요 (방 위에도 돼요) · ' : '') + sel +
                         (S.dirty ? ' · 저장 안 한 변경이 있어요' : '')
    saveBtn.classList.toggle('dirty', S.dirty)
    drawBtn.classList.toggle('on', S.draw)
    cutBtn.classList.toggle('on', S.cut)
  }

  function pushUndo() { S.undo.push(copy(S.rooms)); if (S.undo.length > 50) S.undo.shift() }
  function changed() { S.dirty = true; draw() }
  function rename(i) {
    if (i < 0) return
    const v = window.prompt('방 이름 (예: 2호_침실1 — 호수_실명으로 쓰면 세대별로 묶여요)', S.rooms[i].name)
    if (v && v.trim() && v.trim() !== S.rooms[i].name) { pushUndo(); S.rooms[i].name = v.trim(); changed() }
  }
  function del(i) {
    if (i < 0) return
    if (!window.confirm(`'${S.rooms[i].name}' 방을 지울까요?`)) return
    pushUndo(); S.rooms.splice(i, 1); S.sel = -1; changed()
  }
  function nextName() {
    let k = 1
    const names = new Set(S.rooms.map(r => r.name))
    while (names.has('실' + String(k).padStart(2, '0'))) k++
    return '실' + String(k).padStart(2, '0')
  }

  const pos = e => { const r = cv.getBoundingClientRect(); return [e.clientX - r.left, e.clientY - r.top] }
  let space = false
  root.addEventListener('keydown', e => { if (e.code === 'Space') { space = true; e.preventDefault() } })
  root.addEventListener('keyup', e => { if (e.code === 'Space') space = false })
  cv.addEventListener('contextmenu', e => e.preventDefault())
  cv.addEventListener('pointerdown', e => {
    root.focus()
    cv.setPointerCapture(e.pointerId)
    const [sx, sy] = pos(e), w = toW(sx, sy)
    hideMenu()
    if (e.button !== 0 || space) {  // 오른쪽·가운데 버튼, Space+끌기 = 화면 이동 (오른쪽 버튼을 끌지 않고 떼면 메뉴)
      S.drag = { t: 'pan', s: [sx, sy], c: [...S.c], right: e.button === 2, moved: false }; return
    }
    S.mark = null
    if (S.cut) { S.drag = { t: 'new', a: w, b: w, cut: true }; return }
    if (S.draw || e.shiftKey) { S.drag = { t: 'new', a: w, b: w }; return }
    const vi = vertexAt(sx, sy)
    if (vi >= 0) { S.drag = { t: 'link', i: vi, b: w, j: -1 }; return }  // 꼭짓점 끌기 = 다른 꼭짓점과 잇기
    const ei = edgeAt(sx, sy)
    if (ei >= 0) { pushUndo(); S.drag = { t: 'edge', i: ei, s: w, o: copy(S.rooms[S.sel].poly), moved: false }; return }
    const k = roomAt(...w)
    if (k >= 0) {
      S.sel = k; pushUndo()
      S.drag = { t: 'move', s: w, o: copy(S.rooms[k].poly), moved: false }
    } else {  // 빈 곳 끌기 = 새 방
      S.sel = -1
      S.drag = { t: 'new', a: w, b: w }
    }
    draw()
  })
  cv.addEventListener('pointermove', e => {
    const [sx, sy] = pos(e), w = toW(sx, sy), d = S.drag
    if (!d) {
      const hv = vertexAt(sx, sy)
      S.hoverEdge = hv >= 0 ? -1 : edgeAt(sx, sy)
      if (hv >= 0) cv.style.cursor = 'crosshair'
      else if (S.hoverEdge >= 0) cv.style.cursor = horiz(S.rooms[S.sel].poly, S.hoverEdge) ? 'ns-resize' : 'ew-resize'
      else cv.style.cursor = space ? 'grab' : S.draw ? 'crosshair' : roomAt(...w) >= 0 ? 'move' : 'crosshair'
      draw(); return
    }
    if (d.t === 'pan') {
      if (Math.hypot(sx - d.s[0], sy - d.s[1]) > 3) d.moved = true
      S.c = [d.c[0] - (sx - d.s[0]) / S.z, d.c[1] + (sy - d.s[1]) / S.z]; draw(); return
    }
    if (d.t === 'new') { d.b = w; draw(); return }
    if (d.t === 'link') { d.b = w; d.j = vertexAt(sx, sy, d.i); draw(); return }
    const dx = w[0] - d.s[0], dy = w[1] - d.s[1]
    if (Math.hypot(dx, dy) * S.z > 2) d.moved = true
    const r = S.rooms[S.sel]
    if (d.t === 'move') {
      const ddx = snapShift(d.o.map(p => p[0]), dx, S.d.wx), ddy = snapShift(d.o.map(p => p[1]), dy, S.d.wy)
      r.poly = d.o.map(p => [r3(p[0] + ddx), r3(p[1] + ddy)])
    } else {
      const n = d.o.length, i = d.i, j = (i + 1) % n, p = copy(d.o)
      if (horiz(d.o, i)) { const y = r3(snapV(d.o[i][1] + dy, S.d.wy)); p[i][1] = y; p[j][1] = y }
      else { const x = r3(snapV(d.o[i][0] + dx, S.d.wx)); p[i][0] = x; p[j][0] = x }
      if (area(p) > 0.2) r.poly = p
    }
    draw()
  })
  cv.addEventListener('pointerup', e => {
    const d = S.drag; S.drag = null
    if (!d) return
    if (d.t === 'pan') { if (d.right && !d.moved) showMenu(...pos(e)); return }
    if (d.t === 'link') { if (d.j >= 0) connect(S.sel, d.i, d.j); else draw(); return }
    if (d.t === 'new') {
      let [x0, x1] = [d.a[0], d.b[0]].sort((a, b) => a - b), [y0, y1] = [d.a[1], d.b[1]].sort((a, b) => a - b)
      x0 = snapV(x0, S.d.wx); x1 = snapV(x1, S.d.wx); y0 = snapV(y0, S.d.wy); y1 = snapV(y1, S.d.wy)
      if (d.cut) {
        if ((x1 - x0) * (y1 - y0) >= 0.05 && S.trig) {
          S.cut = false
          S.trig('save', { rooms: S.rooms, cut: [x0, x1, y0, y1].map(r3), t: Date.now() }); S.dirty = false
        }
        draw(); return
      }
      if ((x1 - x0) * (y1 - y0) >= 0.3) {
        const name = window.prompt('새 방 이름 (예: 2호_침실1)', nextName())
        if (name && name.trim()) {
          pushUndo()
          S.rooms.push({ name: name.trim(), poly: [[x0, y0], [x1, y0], [x1, y1], [x0, y1]].map(p => p.map(r3)) })
          S.sel = S.rooms.length - 1; S.draw = false; changed(); return  // 맨 뒤 = 겹치면 이 방이 우선
        }
      }
      draw(); return
    }
    if (d.t === 'move' || d.t === 'edge') {
      if (!d.moved) { S.undo.pop(); draw(); return }
      const [r] = S.rooms.splice(S.sel, 1); S.rooms.push(r); S.sel = S.rooms.length - 1  // 마지막에 고친 방이 겹침에서 우선
      changed()
    }
  })
  // 우클릭 메뉴: 변 위면 「여기서 벽면 나누기」, 방 안이면 이름 바꾸기·지우기
  const menu = root.querySelector('.menu')
  function hideMenu() { menu.style.display = 'none' }
  function showMenu(sx, sy) {
    const items = [], eh = edgeAtAny(sx, sy), k = roomAt(...toW(sx, sy))
    if (eh) {
      items.push(['여기서 벽면 나누기', () => split(eh.k, eh.i, eh.t)])
    }
    const rk = eh ? eh.k : k
    if (rk >= 0) {
      items.push([`'${S.rooms[rk].name}' 이름 바꾸기`, () => { S.sel = rk; rename(rk) }])
      items.push([`'${S.rooms[rk].name}' 지우기`, () => del(rk)])
    }
    if (!items.length) items.push(['여기엔 방이 없어요 (빈 곳을 끌면 새 방)', () => {}])
    menu.innerHTML = ''
    for (const [label, fn] of items) {
      const b = document.createElement('button'); b.textContent = label
      b.onclick = ev => { ev.stopPropagation(); hideMenu(); fn() }
      menu.appendChild(b)
    }
    menu.style.display = 'block'
    menu.style.left = Math.min(sx, S.W - 190) + 'px'; menu.style.top = Math.min(sy, S.H - 30 * items.length - 10) + 'px'
    if (rk >= 0) { S.sel = rk; draw() }
  }
  cv.addEventListener('dblclick', e => { const [sx, sy] = pos(e); const k = roomAt(...toW(sx, sy)); if (k >= 0) { S.sel = k; rename(k) } })
  cv.addEventListener('wheel', e => {
    e.preventDefault()
    const [sx, sy] = pos(e), before = toW(sx, sy)
    S.z = Math.min(2000, Math.max(2, S.z * Math.exp(-e.deltaY * 0.0015)))
    const after = toW(sx, sy)
    S.c = [S.c[0] + before[0] - after[0], S.c[1] + before[1] - after[1]]
    draw()
  }, { passive: false })
  root.addEventListener('keydown', e => {
    if ((e.key === 'Delete' || e.key === 'Backspace') && S.sel >= 0) { e.preventDefault(); del(S.sel) }
    else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'z') { e.preventDefault(); undo() }
    else if (e.key === 'Escape') { hideMenu(); S.draw = false; S.cut = false; S.sel = -1; draw() }
  })
  function undo() { if (S.undo.length) { S.rooms = S.undo.pop(); S.sel = -1; S.dirty = true; draw() } }
  root.querySelector('.bar').addEventListener('click', e => {
    const a = e.target.closest('button')?.dataset.a
    if (a === 'draw') { S.draw = !S.draw; S.cut = false; draw() }
    else if (a === 'cut') { S.cut = !S.cut; S.draw = false; draw() }
    else if (a === 'rename') rename(S.sel)
    else if (a === 'del') del(S.sel)
    else if (a === 'undo') undo()
    else if (a === 'fit') { fit(); draw() }
    else if (a === 'save' && S.trig) { S.trig('save', { rooms: S.rooms, t: Date.now() }); S.dirty = false; draw() }
  })

  return {
    trig: null,
    update(d) {
      this.trig && (S.trig = this.trig)
      root.style.setProperty('--h', d.h + 'px')
      const first = !S.d
      S.d = d
      if (d.rev !== S.rev) { S.rev = d.rev; S.rooms = copy(d.rooms); S.undo = []; S.dirty = false; S.sel = -1 }
      if (first || d.fitKey !== S.fitKey) { S.fitKey = d.fitKey; S.fitted = false; if (S.W) fit() }
      draw()
    },
    set trigFn(f) { S.trig = f },
  }
}
"""

_EDITOR = st.components.v2.component("lsats_room_editor", html=HTML, css=CSS, js=JS)


def room_editor(*, key: str, walls: list, wall_x, wall_y, points: list, rooms: list[dict], fit_key: str,
                height: int = 600, wall_polys: list | None = None):
    """방 편집기를 그리고, 「저장」을 누른 실행에서만 {rooms: [...]} 를 돌려준다 (그 밖엔 None)."""
    data = {"walls": walls, "wallPolys": wall_polys or [], "wx": [float(v) for v in wall_x], "wy": [float(v) for v in wall_y], "pts": points,
            "rooms": rooms, "h": height, "fitKey": fit_key,
            "rev": hashlib.md5(json.dumps(rooms, ensure_ascii=False, sort_keys=True).encode()).hexdigest()}
    res = _EDITOR(key=key, data=data, height=height + 2, on_save_change=lambda: None)
    return getattr(res, "save", None) if res is not None else None
