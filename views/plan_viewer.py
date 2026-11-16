"""도면 보기 (Streamlit 커스텀 컴포넌트 v2, 캔버스).

plotly 로는 마우스로 조금씩 돌리기가 안 되고, 점 크기가 화면 픽셀로 고정이라 축소하면 점이 벽을 넘어 보였다.
여기서는 방 경계와 측정점을 같은 변환으로 캔버스에 그리고, 점 크기·글자를 확대 정도에 맞춘다.

- 휠: 확대·축소(가장 축소 = 도면 전체 + 여백 30%, 가장 확대 = 가장 작은 방 하나) / 끌기: 이동(도면 밖으로는 안 나감) / Shift+끌기 또는 오른쪽 위 나침반 끌기: 회전 (1° 단위 버튼도 있음)
- 기본 방향은 CAD 도면 그대로(0°). '북쪽 위'는 측량 좌표 방향(도면↔측량 정합 회전각)이다.
- 회전·점 글자·점 상세 카드는 모두 이 안(브라우저)에서만 처리한다. 버튼을 누를 때마다 Python 으로 값을 보내면
  화면 전체가 다시 실행되며 깜빡이므로, 회전 각도와 글자 방식은 브라우저 sessionStorage 에 두고
  같은 화면의 두 보기(측정점 위치도·방별 두께도)가 함께 쓴다.
"""
from __future__ import annotations

import numpy as np
import streamlit as st

from slab.core import STATE_NONE, STATE_OUTSIDE, AnalysisResult
from slab.plot import (
    ROOM_SOFTEN, THICK_COLORS, VALUE_STATES, norm_of, point_label, room_cells, room_display, thickness_color, unit_scale,
)

HTML = """
<div class="pv" tabindex="0">
  <canvas></canvas>
  <div class="bar">
    <button data-a="ccw1" title="왼쪽으로 1° (키보드 [ )">↺ 1°</button>
    <button data-a="cw1" title="오른쪽으로 1° (키보드 ] )">↻ 1°</button>
    <button data-a="ccw90" title="왼쪽으로 90°">↺ 90°</button>
    <button data-a="cw90" title="오른쪽으로 90°">↻ 90°</button>
    <button data-a="plan" title="CAD 도면 방향으로 (0°)">도면 방향</button>
    <button data-a="north" title="측량 좌표 방향 (북쪽이 위)">북쪽 위</button>
    <button data-a="fit" title="전체 보기 (두 번 눌러도 됨)">전체 보기</button>
    <span class="sep"></span>
    <button data-l="off" title="점 글자 끄기">글자 끄기</button>
    <button data-l="value" title="두께만 (확대하면 보여요)">두께</button>
    <button data-l="full" title="번호 + 두께 (더 확대하면 보여요)">번호+두께</button>
  </div>
  <div class="dial" title="끌어서 돌리기"><div class="needle"></div><span>N</span></div>
  <div class="status"></div>
  <div class="legend"><div class="grad"></div><div class="lab"><span class="lo"></span><span class="ttl"></span><span class="hi"></span></div></div>
  <div class="tip"></div>
  <div class="card"><button class="x" title="닫기">×</button><div class="ct"></div><table></table></div>
</div>
"""

CSS = """
.pv{position:relative;width:100%;height:var(--h,640px);border:1px solid #dde4ee;border-radius:10px;overflow:hidden;
background:#fff;outline:none;touch-action:none;font-family:'Malgun Gothic','Apple SD Gothic Neo','Noto Sans KR',sans-serif}
.pv canvas{position:absolute;inset:0;width:100%;height:100%;cursor:grab}
.pv canvas.drag{cursor:grabbing}
.bar{position:absolute;left:8px;top:8px;display:flex;flex-wrap:wrap;gap:4px;max-width:calc(100% - 90px)}
.bar button{font:inherit;font-size:12px;padding:3px 8px;border:1px solid #dde4ee;border-radius:7px;background:rgba(255,255,255,.92);
color:#1e293b;cursor:pointer}
.bar button:hover{background:#eef3fa;border-color:#2563eb}
.bar button.on{background:#2563eb;border-color:#2563eb;color:#fff}
.bar .sep{width:6px}
.dial{position:absolute;right:10px;top:10px;width:58px;height:58px;border-radius:50%;border:2px solid #9aa7b8;
background:rgba(255,255,255,.92);cursor:grab;user-select:none}
.dial .needle{position:absolute;left:50%;top:6px;width:2px;height:23px;margin-left:-1px;background:#c62f2f;transform-origin:50% 23px}
.dial span{position:absolute;left:0;right:0;top:-1px;text-align:center;font-size:10px;font-weight:700;color:#c62f2f;
transform-origin:50% 29px}
.status{position:absolute;right:10px;bottom:8px;font-size:11px;color:#5b6470;background:rgba(255,255,255,.85);
padding:2px 6px;border-radius:6px;pointer-events:none}
.legend{position:absolute;left:10px;bottom:8px;width:210px;background:rgba(255,255,255,.85);padding:4px 6px;border-radius:6px;
pointer-events:none}
.legend .grad{height:8px;border-radius:4px}
.legend .lab{display:flex;justify-content:space-between;font-size:10px;color:#5b6470;margin-top:2px}
.tip{position:absolute;display:none;pointer-events:none;background:#1f2328;color:#fff;font-size:12px;line-height:1.45;
padding:6px 8px;border-radius:6px;white-space:pre;z-index:3;max-width:320px}
.card{position:absolute;display:none;z-index:4;background:rgba(255,255,255,.97);border:1px solid #c9d1db;border-radius:9px;
box-shadow:0 6px 18px rgba(15,42,74,.14);padding:7px 9px 6px;font-size:11.5px;color:#1e293b;width:230px}
.card .ct{font-weight:700;font-size:12.5px;margin:0 16px 4px 0}
.card .x{position:absolute;right:4px;top:2px;border:none;background:none;font-size:15px;color:#5b6470;cursor:pointer}
.card table{border-collapse:collapse;width:100%}
.card td{padding:1px 0;vertical-align:top}.card td:first-child{color:#5b6470;width:42%;padding-right:6px}
"""

JS = """
const D2R = Math.PI / 180
const FONT = "'Malgun Gothic','Apple SD Gothic Neo','Noto Sans KR',sans-serif"

function rotP(x, y, deg) {            // 시계 방향으로 deg 돌린 좌표
  const a = deg * D2R, c = Math.cos(a), s = Math.sin(a)
  return [x * c + y * s, -x * s + y * c]
}

// 같은 화면의 보기들이 함께 쓰는 회전·글자 방식 (브라우저에만 저장, Python 으로 보내지 않음 → 깜빡임 없음)
const BUS = globalThis.__lsatsPlan || (globalThis.__lsatsPlan = { views: new Set() })
function loadPref(k, d) { try { const v = sessionStorage.getItem('lsats.' + k); return v == null ? d : JSON.parse(v) } catch (e) { return d } }
function savePref(k, v) { try { sessionStorage.setItem('lsats.' + k, JSON.stringify(v)) } catch (e) {} }

function make(root) {
  const cv = root.querySelector('canvas'), ctx = cv.getContext('2d')
  const tip = root.querySelector('.tip'), status = root.querySelector('.status'), card = root.querySelector('.card')
  const dial = root.querySelector('.dial'), needle = dial.querySelector('.needle'), dialN = dial.querySelector('span')
  const v = { z: 1, wc: [0, 0], rot: loadPref('rot', 0), labels: loadPref('labels', 'value'), W: 0, H: 0,
              data: null, fitKey: null, card: null, lastSel: undefined }
  BUS.views.add(v)

  function toScreen(x, y) {
    const [rx, ry] = rotP(x - v.wc[0], y - v.wc[1], v.rot)
    return [v.W / 2 + rx * v.z, v.H / 2 - ry * v.z]
  }
  function toWorld(sx, sy) {
    const dx = (sx - v.W / 2) / v.z, dy = -(sy - v.H / 2) / v.z
    const [x, y] = rotP(dx, dy, -v.rot)
    return [x + v.wc[0], y + v.wc[1]]
  }
  // 확대·축소 한계: 가장 축소 = 도면 전체가 화면에 들어오고 여백 30%, 가장 확대 = 가장 작은 방 하나가 화면을 채움.
  // 이동도 도면 범위 밖으로는 못 나가게 한다.
  function geom() {
    const d = v.data, out = []
    for (const r of d.rooms) out.push(...r.p)
    for (const p of d.pts) out.push([p.x, p.y])
    return out
  }
  function limits() {
    const g = geom()
    if (!g.length || !v.W) return
    let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity, bx0 = Infinity, by0 = Infinity, bx1 = -Infinity, by1 = -Infinity
    for (const [x, y] of g) {
      const [rx, ry] = rotP(x, y, v.rot)
      x0 = Math.min(x0, rx); x1 = Math.max(x1, rx); y0 = Math.min(y0, ry); y1 = Math.max(y1, ry)
      bx0 = Math.min(bx0, x); bx1 = Math.max(bx1, x); by0 = Math.min(by0, y); by1 = Math.max(by1, y)
    }
    const full = Math.min(v.W / Math.max(x1 - x0, 1e-6), v.H / Math.max(y1 - y0, 1e-6))
    v.zMin = full / 1.3
    v.zMax = Math.max(v.zMin * 1.5, Math.min(v.W, v.H) / Math.max(v.data.minRoom || 3, 1))
    v.box = [bx0, by0, bx1, by1]
  }
  function clampView() {
    limits()
    if (v.zMin == null) return
    v.z = Math.min(v.zMax, Math.max(v.zMin, v.z))
    const b = v.box
    v.wc = [Math.min(b[2], Math.max(b[0], v.wc[0])), Math.min(b[3], Math.max(b[1], v.wc[1]))]
  }

  function fit(box) {
    const d = v.data
    let pts = []
    if (box) pts = [[box[0], box[1]], [box[2], box[1]], [box[2], box[3]], [box[0], box[3]]]
    else pts = geom()
    if (!pts.length) return
    let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity, cx = 0, cy = 0
    for (const [x, y] of pts) { cx += x; cy += y }
    cx /= pts.length; cy /= pts.length
    for (const [x, y] of pts) {
      const [rx, ry] = rotP(x - cx, y - cy, v.rot)
      x0 = Math.min(x0, rx); x1 = Math.max(x1, rx); y0 = Math.min(y0, ry); y1 = Math.max(y1, ry)
    }
    const [mx, my] = rotP((x0 + x1) / 2, (y0 + y1) / 2, -v.rot)   // 회전된 화면에서 상자 가운데를 화면 가운데로
    v.wc = [cx + mx, cy + my]
    v.z = 0.9 * Math.min(v.W / Math.max(x1 - x0, 1e-6), (v.H - 40) / Math.max(y1 - y0, 1e-6))
  }

  function placeCard() {
    if (!v.card) { card.style.display = 'none'; return }
    const [sx, sy] = toScreen(v.card.x, v.card.y)
    card.style.display = 'block'
    const w = card.offsetWidth, h = card.offsetHeight
    let x = sx + 14, y = sy + 10
    if (x + w > v.W - 6) x = sx - w - 14
    if (y + h > v.H - 30) y = Math.max(40, v.H - 30 - h)
    card.style.left = Math.max(6, x) + 'px'; card.style.top = Math.max(40, y) + 'px'
  }
  function openCard(p) {
    v.card = p
    if (!p) { placeCard(); return }
    card.querySelector('.ct').textContent = p.title
    const tb = card.querySelector('table'); tb.textContent = ''
    for (const [k, val] of p.det) {
      const tr = document.createElement('tr'), a = document.createElement('td'), b = document.createElement('td')
      a.textContent = k; b.textContent = val; tr.append(a, b); tb.append(tr)
    }
    tip.style.display = 'none'
    draw()
  }
  card.querySelector('.x').addEventListener('click', () => openCard(null))

  function draw() {
    const d = v.data
    if (!d || !v.W) return
    clampView()
    const dpr = window.devicePixelRatio || 1
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
    ctx.clearRect(0, 0, v.W, v.H)
    const path = (poly) => {
      ctx.beginPath()
      poly.forEach(([x, y], i) => { const [sx, sy] = toScreen(x, y); i ? ctx.lineTo(sx, sy) : ctx.moveTo(sx, sy) })
      ctx.closePath()
    }
    for (const r of d.rooms) {           // 방
      path(r.p)
      ctx.fillStyle = r.c || '#f7f9fc'; ctx.fill()
      ctx.lineWidth = 1.3; ctx.strokeStyle = '#3b4252'; ctx.stroke()
    }
    // 점 크기: 실제 약 0.22 m (축소하면 같이 작아져 벽을 넘어 보이지 않는다). 테두리는 모두 같은 얇은 선.
    const rad = Math.max(4, Math.min(10, v.z * 0.22))
    const rooms = d.mode === 'rooms'
    const sel = v.card ? v.card.id : null
    for (const p of d.pts) {
      const [sx, sy] = toScreen(p.x, p.y)
      if (sx < -20 || sy < -20 || sx > v.W + 20 || sy > v.H + 20) continue
      const rr = rooms ? Math.max(1.8, rad * 0.45) : rad
      if (p.k === 'v') {
        ctx.beginPath(); ctx.arc(sx, sy, rr, 0, 2 * Math.PI)
        ctx.fillStyle = rooms ? '#6b7280' : p.c; ctx.fill()
        if (!rooms) { ctx.lineWidth = 0.7; ctx.strokeStyle = 'rgba(59,66,82,.55)'; ctx.stroke() }
      } else if (p.k === 'n') {
        const q = rr * 0.8
        ctx.lineWidth = rooms ? 1 : 1.5; ctx.strokeStyle = '#6b7280'; ctx.beginPath()
        ctx.moveTo(sx - q, sy - q); ctx.lineTo(sx + q, sy + q); ctx.moveTo(sx + q, sy - q); ctx.lineTo(sx - q, sy + q)
        ctx.stroke()
      } else if (!rooms) {
        ctx.beginPath(); ctx.arc(sx, sy, rr * 0.85, 0, 2 * Math.PI); ctx.lineWidth = 1.3; ctx.strokeStyle = '#6b7280'; ctx.stroke()
      }
      if (sel && p.id === sel) {
        ctx.beginPath(); ctx.arc(sx, sy, rr + 4, 0, 2 * Math.PI); ctx.lineWidth = 2; ctx.strokeStyle = '#2563eb'; ctx.stroke()
      }
    }
    // 점 글자: 오른쪽 아래에 작게. 너무 축소해서 겹치면 그리지 않는다.
    let hint = ''
    if (!rooms && v.labels !== 'off') {
      const need = v.labels === 'full' ? 48 : 20      // 1 m 에 필요한 픽셀
      if (v.z >= need) {
        ctx.font = '10px ' + FONT; ctx.textBaseline = 'top'
        for (const p of d.pts) {
          const t = v.labels === 'full' ? p.lf : p.lv
          if (!t) continue
          const [sx, sy] = toScreen(p.x, p.y)
          if (sx < -10 || sy < -10 || sx > v.W || sy > v.H) continue
          ctx.fillStyle = p.k === 'v' ? '#1f2328' : '#6b7280'; ctx.fillText(t, sx + rad * 0.7 + 1, sy + rad * 0.7 + 1)
        }
      } else hint = ' · 확대하면 점 글자가 보여요'
    }
    ctx.textAlign = 'center'; ctx.textBaseline = 'middle'     // 방 이름 (방이 충분히 클 때만)
    for (const r of d.rooms) {
      if (!r.n) continue
      const [sx, sy] = toScreen(r.l[0], r.l[1])
      ctx.font = (rooms ? 'bold 12px ' : '11px ') + FONT
      const lines = rooms && r.t ? [r.n, r.t] : [r.n]
      const w = Math.max(...lines.map(s => ctx.measureText(s).width))
      if (w > r.w * v.z * 1.15) continue
      lines.forEach((s, i) => { ctx.fillStyle = '#3b4252'; ctx.fillText(s, sx, sy + (i - (lines.length - 1) / 2) * 14) })
    }
    ctx.textAlign = 'left'
    const na = (d.north == null ? 0 : -d.north) + v.rot      // 나침반: 측량 북쪽 (없으면 도면 위쪽)
    needle.style.transform = `rotate(${na}deg)`; dialN.style.transform = `rotate(${na}deg)`
    status.textContent = `회전 ${(((v.rot % 360) + 540) % 360 - 180).toFixed(1)}°` + hint
    root.querySelectorAll('[data-l]').forEach(b => b.classList.toggle('on', b.dataset.l === v.labels))
    placeCard()
  }

  function resize() {
    const b = root.getBoundingClientRect(), dpr = window.devicePixelRatio || 1
    if (!b.width) return
    const first = !v.W
    v.W = b.width; v.H = b.height
    cv.width = Math.round(v.W * dpr); cv.height = Math.round(v.H * dpr)
    if (first && v.data) fit(v.data.fit && v.data.fit.box)
    draw()
  }
  new ResizeObserver(resize).observe(root)

  function nearest(sx, sy) {
    if (!v.data) return null
    let best = null, bd = 14
    for (const p of v.data.pts) {
      const [px, py] = toScreen(p.x, p.y)
      const dd = Math.hypot(px - sx, py - sy)
      if (dd < bd) { bd = dd; best = p }
    }
    return best
  }
  // 회전: 같은 화면의 다른 보기도 같이 돌린다. 브라우저에만 저장하므로 화면이 다시 실행되지 않는다.
  function setRot(deg, save) {
    for (const o of BUS.views) { if (o.root && !o.root.isConnected) { BUS.views.delete(o); continue } o.rot = deg; o.draw() }
    if (save) savePref('rot', Math.round(deg * 10) / 10)
  }
  v.root = root; v.draw = draw

  let drag = null       // 끌기 = 이동, Shift+끌기 = 회전, 짧게 누르기 = 점 상세
  cv.addEventListener('pointerdown', e => {
    cv.setPointerCapture(e.pointerId); root.focus()
    drag = { x: e.clientX, y: e.clientY, wc: v.wc.slice(), rot: v.rot, moved: false, spin: e.shiftKey || e.button === 2 }
    cv.classList.add('drag')
  })
  cv.addEventListener('pointermove', e => {
    const b = cv.getBoundingClientRect(), sx = e.clientX - b.left, sy = e.clientY - b.top
    if (drag) {
      const dx = e.clientX - drag.x, dy = e.clientY - drag.y
      if (Math.hypot(dx, dy) > 3) drag.moved = true
      if (drag.spin) setRot(drag.rot + dx * 0.25, false)
      else { const [wx, wy] = rotP(-dx / v.z, dy / v.z, -v.rot); v.wc = [drag.wc[0] + wx, drag.wc[1] + wy]; draw() }
      tip.style.display = 'none'
      return
    }
    const p = nearest(sx, sy)
    if (p && !(v.card && v.card.id === p.id)) {
      tip.textContent = p.tip; tip.style.display = 'block'
      tip.style.left = Math.min(sx + 14, v.W - tip.offsetWidth - 4) + 'px'
      tip.style.top = Math.min(sy + 14, v.H - tip.offsetHeight - 4) + 'px'
    } else tip.style.display = 'none'
    cv.style.cursor = p ? 'pointer' : ''
  })
  cv.addEventListener('pointerup', e => {
    cv.classList.remove('drag')
    if (!drag) return
    const b = cv.getBoundingClientRect()
    if (!drag.moved) {
      const p = nearest(e.clientX - b.left, e.clientY - b.top)
      if (v.data.mode !== 'rooms') openCard(p && !(v.card && v.card.id === p.id) ? p : null)
    } else if (drag.spin) setRot(v.rot, true)
    drag = null
  })
  cv.addEventListener('pointerleave', () => { tip.style.display = 'none' })
  cv.addEventListener('contextmenu', e => e.preventDefault())
  cv.addEventListener('dblclick', () => { fit(null); draw() })
  cv.addEventListener('wheel', e => {
    e.preventDefault()
    const b = cv.getBoundingClientRect(), sx = e.clientX - b.left, sy = e.clientY - b.top
    const [wx, wy] = toWorld(sx, sy)
    limits()
    v.z = Math.max(v.zMin || 0.5, Math.min(v.zMax || 800, v.z * Math.exp(-e.deltaY * 0.0015)))
    const [nx, ny] = toWorld(sx, sy)
    v.wc = [v.wc[0] + wx - nx, v.wc[1] + wy - ny]
    draw()
  }, { passive: false })
  root.addEventListener('keydown', e => {
    if (e.key === '[') setRot(v.rot - 1, true)
    if (e.key === ']') setRot(v.rot + 1, true)
    if (e.key === 'Escape') openCard(null)
  })

  let dd = null         // 나침반 끌기 = 회전
  dial.addEventListener('pointerdown', e => {
    dial.setPointerCapture(e.pointerId)
    const b = dial.getBoundingClientRect(), cx = b.left + b.width / 2, cy = b.top + b.height / 2
    dd = { cx, cy, a0: Math.atan2(e.clientX - cx, cy - e.clientY) / D2R, rot: v.rot }
  })
  dial.addEventListener('pointermove', e => {
    if (!dd) return
    setRot(dd.rot + (Math.atan2(e.clientX - dd.cx, dd.cy - e.clientY) / D2R - dd.a0), false)
  })
  dial.addEventListener('pointerup', () => { if (dd) setRot(v.rot, true); dd = null })

  root.querySelector('.bar').addEventListener('click', e => {
    const t = e.target.closest('button')
    if (!t) return
    if (t.dataset.l) { v.labels = t.dataset.l; savePref('labels', v.labels); draw(); return }
    const a = t.dataset.a
    if (a === 'fit') { fit(null); draw(); return }
    const r = { ccw1: v.rot - 1, cw1: v.rot + 1, ccw90: v.rot - 90, cw90: v.rot + 90, plan: 0,
                north: v.data.north == null ? 0 : v.data.north }[a]
    if (r != null) setRot(r, true)
  })

  v.update = (d) => {
    const first = !v.data
    v.data = d
    root.style.setProperty('--h', d.h + 'px')
    root.querySelector('[data-a=north]').style.display = d.north == null ? 'none' : ''
    root.querySelectorAll('[data-l]').forEach(b => { b.style.display = d.mode === 'rooms' ? 'none' : '' })
    const lg = root.querySelector('.legend')
    lg.querySelector('.grad').style.background = `linear-gradient(90deg, ${d.legend.colors.join(',')})`
    lg.querySelector('.lo').textContent = d.legend.lo
    lg.querySelector('.hi').textContent = d.legend.hi
    lg.querySelector('.ttl').textContent = d.legend.title
    v.rot = loadPref('rot', v.rot)
    const key = d.fit ? d.fit.key : ''
    if (v.W && (first || key !== v.fitKey)) fit(d.fit && d.fit.box)
    v.fitKey = key
    if (d.sel !== v.lastSel) {            // '포인트 찾기'에서 고른 점은 상세 카드를 연다
      v.lastSel = d.sel
      openCard(d.sel ? d.pts.find(p => p.id === d.sel) || null : null)
    } else if (v.card) v.card = d.pts.find(p => p.id === v.card.id) || null
    draw()
  }
  return v
}

export default function (component) {
  const { data, parentElement } = component
  const root = parentElement.querySelector('.pv')
  if (!root || !data) return
  if (!root.__pv) root.__pv = make(root)
  root.__pv.update(data)
}
"""

_VIEWER = st.components.v2.component("lsats_plan_viewer", html=HTML, css=CSS, js=JS)


def _tip(p) -> str:
    head = f"{p['point_id']} · {room_display(p['room'])}\n{p['status']}"
    if p["status"] in VALUE_STATES:
        return head + f" · {p['thickness_mm']:.0f}mm\n{p['calc_method']}"
    if p["status"] == STATE_NONE:
        return head + f" · {p['no_reason']}"
    return head


def _num(v, fmt: str) -> str:
    return fmt.format(v) if v is not None and np.isfinite(v) else "-"


def _detail(p, room_mean: dict) -> list[list[str]]:
    """점 상세 카드에 보일 [항목, 값]."""
    rows = [["결과 상태", p["status"]], ["두께", _num(p["thickness_mm"], "{:.0f} mm")]]
    if p["no_reason"]:
        rows.append(["미산출 사유", p["no_reason"]])
    if np.isfinite(p["calc_thickness_mm"]) and not np.isfinite(p["thickness_mm"]):
        rows.append(["참고 계산값", _num(p["calc_thickness_mm"], "{:.0f} mm")])
    rows += [
        ["산출 방식", p["calc_method"] or "-"],
        ["위층 바닥 Z", _num(p["upper_floor_z"], "{:.4f} m")],
        ["아래층 천장 Z", _num(p["lower_ceiling_z"], "{:.4f} m")],
        ["사용한 아래층 점", p["lower_point_id"] or "-"],
        ["거리", _num(p["match_dist_m"], "{:.3f} m")],
        ["바닥 기준면 편차", _num(p["upper_floor_error_mm"], "{:+.0f} mm")],
        ["천장 기준면 편차", _num(p["lower_ceiling_error_mm"], "{:+.0f} mm")],
    ]
    if p["exclude_reason"]:
        rows.append(["상세 사유", p["exclude_reason"]])
    if p["review_note"]:
        rows.append(["검토 메모", p["review_note"]])
    if p["room_id"] in room_mean:
        rows.append(["이 방 평균", room_mean[p["room_id"]]])
    return rows


def north_rotation(result: AnalysisResult) -> float | None:
    """도면을 시계 방향으로 몇 도 돌리면 측량 좌표 방향(북쪽 위)이 되는지. 도면이 없으면 None."""
    t = result.transform
    if t is None or result.plan is None:
        return None
    return round(-t.rotation_deg, 2)


def plan_viewer(result: AnalysisResult, *, key: str, mode: str = "points", focus_xy: np.ndarray | None = None,
                focus_pad_m: float = 1.0, fit_key: str = "", selected: str | None = None, height: int = 640) -> None:
    """도면 보기를 그린다. mode: points(측정점 위치도) / rooms(방별 두께도).

    focus_xy: 이 도면 좌표 점들로 확대한다 (fit_key 가 바뀔 때만). selected: 상세 카드를 열 포인트 번호.
    회전·점 글자·점 누르기는 브라우저 안에서만 처리해 Python 이 다시 실행되지 않는다.
    """
    scale = unit_scale(result)
    pts = result.points
    all_xy = [pts[["cad_x", "cad_y"]].to_numpy(float)]
    if result.plan is not None:
        all_xy += [r.polygon for r in result.plan.rooms]
    origin = np.vstack(all_xy).min(0)

    def m(a):  # 도면 좌표 → m (원점 이동)
        return ((np.asarray(a, float) - origin) * scale).round(3)

    norm = norm_of(result)
    if mode == "rooms":
        cells = room_cells(result)
        rooms = [{"n": room_display(name), "p": m(room.polygon).tolist(), "l": m(room.label_xy).tolist(),
                  "c": thickness_color(mean, norm, ROOM_SOFTEN),
                  "t": f"{mean:.0f}mm" if np.isfinite(mean) else "값 없음",
                  "w": float(np.ptp(room.polygon[:, 0]) * scale)} for room, name, mean, n in cells]
    else:
        name_of = dict(zip(pts["room_id"], pts["room"]))
        rooms = [{"n": room_display(name_of.get(r.room_id, r.name)), "p": m(r.polygon).tolist(),
                  "l": m(r.label_xy).tolist(), "c": None, "t": "", "w": float(np.ptp(r.polygon[:, 0]) * scale)}
                 for r in (result.plan.rooms if result.plan is not None else [])]
    xy = m(pts[["cad_x", "cad_y"]].to_numpy(float))
    room_mean = {r.room_id: f"{r.mean_mm:.0f} mm (산출 완료 {r.n_valid}/{r.n_points}점)" if np.isfinite(r.mean_mm)
                 else f"값 없음 ({r.n_points}점)" for r in result.rooms.itertuples()} if mode != "rooms" else {}
    plist = []
    for (x, y), (_, p) in zip(xy, pts.iterrows()):
        st_ = p["status"]
        k = "v" if st_ in VALUE_STATES else "n" if st_ == STATE_NONE else "o"
        plist.append({
            "id": p["point_id"], "x": float(x), "y": float(y), "k": k,
            "c": thickness_color(p["thickness_mm"], norm) if k == "v" else None,
            "lv": f"{p['thickness_mm']:.0f}" if k == "v" else ("×" if k == "n" else ""),
            "lf": point_label(p) if st_ != STATE_OUTSIDE else f"{p['point_id']} / 영역 외",
            "tip": _tip(p),
            **({"title": f"{p['point_id']} · {room_display(p['room'])}", "det": _detail(p, room_mean)}
               if mode != "rooms" else {}),
        })
    # 가장 확대했을 때 화면을 채울 크기: 가장 작은 방(화장실 등)의 긴 변, 도면이 없으면 3 m
    sizes = [float(np.ptp(r.polygon, axis=0).max() * scale) for r in (result.plan.rooms if result.plan else [])]
    sizes = [x for x in sizes if x > 0.5]
    min_room = round(min(sizes), 2) if sizes else 3.0
    box = None
    if focus_xy is not None and len(focus_xy):
        f = m(focus_xy)
        box = [float(f[:, 0].min() - focus_pad_m), float(f[:, 1].min() - focus_pad_m),
               float(f[:, 0].max() + focus_pad_m), float(f[:, 1].max() + focus_pad_m)]
    s = result.settings
    lo, hi = sorted((s.color_min_mm, s.color_max_mm))
    data = {
        "h": height, "mode": mode, "minRoom": min_room, "rooms": rooms, "pts": plist,
        "north": north_rotation(result), "fit": {"key": fit_key, "box": box}, "sel": selected,
        "legend": {"lo": f"{lo:g}", "hi": f"{hi:g}mm", "colors": THICK_COLORS,
                   "title": "방 평균 두께" if mode == "rooms" else "두께 (초록 얇음 → 주황 두꺼움)"},
    }
    _VIEWER(key=key, data=data, height=height + 2)
