import { forwardRef, useEffect, useImperativeHandle, useRef } from 'react'
import { forceCollide, forceLink, forceManyBody, forceSimulation, forceX, forceY } from 'd3-force'
import { KIND_COLOR, aggregateEdges, short } from '../util'

const clamp = (x, a, b) => Math.max(a, Math.min(b, x))
const easeOutBack = (t) => { const c1 = 1.70158, c3 = c1 + 1; return 1 + c3 * Math.pow(t - 1, 3) + c1 * Math.pow(t - 1, 2) }
const hexA = (hex, a) => {
  const n = parseInt(hex.slice(1), 16)
  return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${a})`
}

/**
 * Animated transaction-flow graph. `steps` come from buildSteps(); the canvas shows steps[0..stepIndex].
 * Nodes and edges are revealed with a stagger, edges carry flow particles, and terminals (exchange, mixer, DEX, hub)
 * send out a pulse ring when the engine absorbs them. `nodeMeta` (from the final result) adds roles, labels and tags.
 */
const GraphCanvas = forwardRef(function GraphCanvas(
  { steps, stepIndex, nodeMeta, highlightEdges, selectedId, resetKey, onHover, onSelect, speed = 1 }, ref) {
  const wrapRef = useRef(null)
  const canvasRef = useRef(null)
  const S = useRef(null)          // all mutable animation state lives here
  // the draw loop is created once, so everything that changes is read through this ref on every frame
  const propsRef = useRef({})
  propsRef.current = { highlightEdges, selectedId, speed, nodeMeta }

  if (!S.current) {
    S.current = {
      nodes: new Map(), edgesRaw: [], edges: new Map(), links: [], depth: new Map(), pulses: [],
      tf: { k: 1, x: 0, y: 0 }, tfTarget: null, autoFit: true, ingested: -1, hover: null, source: null,
      w: 800, h: 600, dpr: 1, raf: 0, sim: null, drag: null,
    }
  }

  // ---------------------------------------------------------------- simulation
  useEffect(() => {
    const s = S.current
    s.sim = forceSimulation([])
      .alphaDecay(0.035)
      .force('link', forceLink([]).id((d) => d.id).distance((l) => 70 + 18 * Math.min(4, Math.log10(1 + (l.eth || 1)))).strength(0.55))
      .force('charge', forceManyBody().strength(-240).distanceMax(520))
      .force('x', forceX((d) => (s.depth.get(d.id) ?? 0) * 190).strength(0.22))
      .force('y', forceY(0).strength(0.05))
      .force('collide', forceCollide((d) => d.r + 8))
    return () => s.sim.stop()
  }, [])

  const metaOf = (id) => propsRef.current.nodeMeta?.get(id)

  const radiusOf = (n) => {
    const m = metaOf(n.id)
    if (n.id === S.current.source) return 13
    if (n.term || m?.terminal) return 12 + 10 * Math.sqrt(clamp(m?.share ?? n.share ?? 0.1, 0, 1))
    return 6 + 9 * Math.sqrt(clamp(m?.share ?? n.share ?? 0.03, 0, 1))
  }

  const colorOf = (n) => {
    const m = metaOf(n.id)
    if (n.id === S.current.source) return KIND_COLOR.source
    const kind = m?.terminal?.kind || n.term
    if (kind) return KIND_COLOR[kind] || KIND_COLOR.other
    return KIND_COLOR[m?.role] || KIND_COLOR.intermediate
  }

  // ---------------------------------------------------------------- ingest steps
  const rebuildDepth = () => {
    const s = S.current
    const adj = new Map()
    for (const e of s.edgesRaw) if (e.role === 'fwd') (adj.get(e.src) || adj.set(e.src, []).get(e.src)).push(e.dst)
    s.depth = new Map(); if (s.source) s.depth.set(s.source, 0)
    const q = s.source ? [s.source] : []
    while (q.length) {
      const u = q.shift()
      for (const v of adj.get(u) || []) if (!s.depth.has(v)) { s.depth.set(v, s.depth.get(u) + 1); q.push(v) }
    }
  }

  const ensureNode = (id, near, born) => {
    const s = S.current
    let n = s.nodes.get(id)
    if (!n) {
      const p = near && s.nodes.get(near)
      n = { id, x: (p ? p.x : 0) + (Math.random() - 0.5) * 40, y: (p ? p.y : 0) + (Math.random() - 0.5) * 40, vx: 0, vy: 0, born, r: 8 }
      s.nodes.set(id, n)
    }
    return n
  }

  const ingest = (step, instant) => {
    const s = S.current
    const now = performance.now()
    const stag = instant ? 0 : 70
    if (step.kind === 'start') {
      s.source = step.nodes[0]
      const n = ensureNode(s.source, null, instant ? now - 2000 : now)
      n.x = 0; n.y = 0; n.fx = null
    }
    step.edges.forEach((e, i) => {
      const born = instant ? now - 2000 : now + i * stag
      ensureNode(e.src, e.dst, born)
      ensureNode(e.dst, e.src, born)
      s.edgesRaw.push(e)
    })
    for (const a of step.absorbs || []) {
      const n = ensureNode(a.nodes[0], null, instant ? now - 2000 : now)
      n.term = a.info.kind_of
      n.termName = a.info.name
      n.termReason = a.info.reason
      if (!instant) s.pulses.push({ id: n.id, t0: now + 450, color: KIND_COLOR[a.info.kind_of] || '#fff' })
    }
    // re-aggregate and refresh simulation
    const agg = aggregateEdges(s.edgesRaw)
    const prev = s.edges
    s.edges = new Map()
    for (const a of agg) {
      const old = prev.get(a.key)
      a.born = old ? old.born : s.nodes.get(a.dst)?.born ?? now
      s.edges.set(a.key, a)
    }
    rebuildDepth()
    for (const n of s.nodes.values()) n.r = radiusOf(n)
    s.links = [...s.edges.values()].map((e) => ({ source: e.src, target: e.dst, eth: e.eth }))
    s.sim.nodes([...s.nodes.values()])
    s.sim.force('link').links(s.links)
    s.sim.force('x').x((d) => (s.depth.get(d.id) ?? 1) * 190)
    s.sim.force('collide').radius((d) => d.r + 8)
    s.sim.alpha(instant ? 0.9 : 0.7).restart()
  }

  const reset = () => {
    const s = S.current
    s.nodes = new Map(); s.edgesRaw = []; s.edges = new Map(); s.links = []; s.depth = new Map(); s.pulses = []
    s.ingested = -1; s.source = null; s.hover = null; s.autoFit = true
    s.sim.nodes([]); s.sim.force('link').links([])
  }

  useEffect(() => { reset() }, [resetKey])

  useEffect(() => {
    const s = S.current
    if (stepIndex < s.ingested) {          // scrubbing backwards: rebuild instantly
      reset()
    }
    for (let i = s.ingested + 1; i <= stepIndex && i < steps.length; i++) {
      ingest(steps[i], i < stepIndex - 1 && stepIndex - s.ingested > 2)
      s.ingested = i
    }
  }, [stepIndex, steps])

  useEffect(() => {            // metadata (labels, roles) may arrive after the animation starts
    for (const n of S.current.nodes.values()) n.r = radiusOf(n)
    S.current.sim?.force('collide').radius((d) => d.r + 8)
  }, [nodeMeta])

  useImperativeHandle(ref, () => ({ fit: () => { S.current.autoFit = true } }))

  // ---------------------------------------------------------------- drawing loop
  useEffect(() => {
    const canvas = canvasRef.current
    const ctx = canvas.getContext('2d')
    const s = S.current

    const resize = () => {
      const r = wrapRef.current.getBoundingClientRect()
      s.dpr = window.devicePixelRatio || 1
      s.w = r.width; s.h = r.height
      canvas.width = r.width * s.dpr; canvas.height = r.height * s.dpr
    }
    resize()
    const ro = new ResizeObserver(resize)
    ro.observe(wrapRef.current)

    const fitTarget = () => {
      const ns = [...s.nodes.values()].filter((n) => performance.now() > n.born - 100)
      if (!ns.length) return null
      let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity
      for (const n of ns) { x0 = Math.min(x0, n.x - n.r - 30); y0 = Math.min(y0, n.y - n.r - 30); x1 = Math.max(x1, n.x + n.r + 230); y1 = Math.max(y1, n.y + n.r + 30) }
      const k = clamp(Math.min((s.w - 60) / (x1 - x0), (s.h - 150) / (y1 - y0)), 0.25, 1.6)
      return { k, x: s.w / 2 - ((x0 + x1) / 2) * k, y: (s.h - 70) / 2 - ((y0 + y1) / 2) * k }
    }

    const curve = (a, b, idx) => {
      const mx = (a.x + b.x) / 2, my = (a.y + b.y) / 2
      const dx = b.x - a.x, dy = b.y - a.y
      const len = Math.hypot(dx, dy) || 1
      const bend = (idx || 0) * 0.18 * len + 0.06 * len
      return { cx: mx - (dy / len) * bend, cy: my + (dx / len) * bend }
    }
    const bez = (a, c, b, t) => {
      const u = 1 - t
      return [u * u * a.x + 2 * u * t * c.cx + t * t * b.x, u * u * a.y + 2 * u * t * c.cy + t * t * b.y]
    }

    const draw = (now) => {
      s.raf = requestAnimationFrame(draw)
      if (s.autoFit) {
        const t = fitTarget()
        if (t) { s.tf.k += (t.k - s.tf.k) * 0.08; s.tf.x += (t.x - s.tf.x) * 0.08; s.tf.y += (t.y - s.tf.y) * 0.08 }
      }
      ctx.setTransform(s.dpr, 0, 0, s.dpr, 0, 0)
      ctx.clearRect(0, 0, s.w, s.h)
      // faint grid
      ctx.save()
      ctx.translate(s.tf.x, s.tf.y); ctx.scale(s.tf.k, s.tf.k)
      const P = propsRef.current
      const hl = P.highlightEdges || null
      const selectedId = P.selectedId
      const speed = P.speed

      // ---- edges
      const pairSeen = new Map()
      for (const e of s.edges.values()) {
        const a = s.nodes.get(e.src), b = s.nodes.get(e.dst)
        if (!a || !b) continue
        const p = clamp((now - e.born) / 650, 0, 1)
        if (p <= 0) continue
        const rev = pairSeen.get(`${e.dst}|${e.src}`) ? 1 : 0
        pairSeen.set(e.key, true)
        const c = curve(a, b, rev)
        const on = hl && hl.has(e.key)
        const base = e.role === 'back' ? '#64748b' : on ? '#ffffff' : '#7dd3fc'
        const alpha = (hl ? (on ? 1 : 0.18) : 0.5) * p
        ctx.lineWidth = (on ? 3.2 : 1) + 1.5 * Math.log10(1 + e.eth)
        ctx.strokeStyle = hexA(on ? '#ffffff' : e.role === 'back' ? '#64748b' : '#38bdf8', alpha)
        ctx.setLineDash(e.role === 'back' ? [5, 5] : [])
        ctx.beginPath()
        const steps_ = 18
        for (let i = 0; i <= steps_ * p; i++) {
          const [x, y] = bez(a, c, b, i / steps_)
          i ? ctx.lineTo(x, y) : ctx.moveTo(x, y)
        }
        ctx.stroke()
        ctx.setLineDash([])
        if (p >= 1) {                       // arrowhead
          const [x1, y1] = bez(a, c, b, 0.9), [x2, y2] = bez(a, c, b, 1 - (b.r + 4) / (Math.hypot(b.x - a.x, b.y - a.y) || 1))
          const ang = Math.atan2(y2 - y1, x2 - x1)
          ctx.fillStyle = hexA(base, alpha + 0.15)
          ctx.beginPath(); ctx.moveTo(x2, y2)
          ctx.lineTo(x2 - 9 * Math.cos(ang - 0.4), y2 - 9 * Math.sin(ang - 0.4)); ctx.lineTo(x2 - 9 * Math.cos(ang + 0.4), y2 - 9 * Math.sin(ang + 0.4)); ctx.fill()
          // flow particles
          const n = e.role === 'back' ? 0 : Math.min(4, 1 + Math.floor(Math.log10(1 + e.eth)))
          for (let i = 0; i < n; i++) {
            const t = (((now * 0.00028 * speed + i / n + (a.x * 0.001)) % 1) + 1) % 1
            const [px, py] = bez(a, c, b, t)
            ctx.fillStyle = hexA(on ? '#ffffff' : '#a5f3fc', hl && !on ? 0.2 : 0.95)
            ctx.shadowColor = '#22d3ee'; ctx.shadowBlur = on ? 14 : 8
            ctx.beginPath(); ctx.arc(px, py, on ? 3 : 2.2, 0, 6.3); ctx.fill()
            ctx.shadowBlur = 0
          }
          // amount label for big edges
          if (e.eth >= 300 || on) {
            const [lx, ly] = bez(a, c, b, 0.5)
            const txt = `${e.count > 1 ? '×' + e.count + ' · ' : ''}${e.eth >= 100 ? Math.round(e.eth).toLocaleString() : e.eth.toFixed(1)} ETH`
            ctx.font = '600 10.5px ui-monospace, monospace'; ctx.textAlign = 'center'
            const tw = ctx.measureText(txt).width
            ctx.fillStyle = `rgba(7,11,20,${hl && !on ? 0.3 : 0.78})`
            ctx.beginPath(); ctx.roundRect(lx - tw / 2 - 6, ly - 21, tw + 12, 17, 6); ctx.fill()
            ctx.fillStyle = hexA('#e8edf7', hl && !on ? 0.35 : 0.95)
            ctx.fillText(txt, lx, ly - 9)
          }
        }
      }

      // ---- pulses
      s.pulses = s.pulses.filter((p) => now - p.t0 < 1600)
      for (const p of s.pulses) {
        const n = s.nodes.get(p.id); const t = (now - p.t0) / 1600
        if (!n || t < 0) continue
        for (let k = 0; k < 2; k++) {
          const tt = clamp(t - k * 0.18, 0, 1)
          ctx.strokeStyle = hexA(p.color, (1 - tt) * 0.8); ctx.lineWidth = 3 * (1 - tt) + 1
          ctx.beginPath(); ctx.arc(n.x, n.y, n.r + tt * 70, 0, 6.3); ctx.stroke()
        }
      }

      // ---- nodes
      const selEdges = hl
      for (const n of s.nodes.values()) {
        const p = clamp((now - n.born) / 450, 0, 1)
        if (p <= 0) continue
        const r = n.r * easeOutBack(p)
        const col = colorOf(n)
        const dim = selEdges && !highlightNodes.has(n.id)
        const g = ctx.createRadialGradient(n.x, n.y, r * 0.3, n.x, n.y, r * 2.8)
        g.addColorStop(0, hexA(col, dim ? 0.1 : 0.5)); g.addColorStop(1, hexA(col, 0))
        ctx.fillStyle = g; ctx.beginPath(); ctx.arc(n.x, n.y, r * 2.8, 0, 6.3); ctx.fill()
        ctx.fillStyle = hexA(col, dim ? 0.35 : 1)
        ctx.beginPath(); ctx.arc(n.x, n.y, r, 0, 6.3); ctx.fill()
        const isTerm = n.term || metaOf(n.id)?.terminal
        ctx.lineWidth = isTerm || n.id === s.source ? 3 : 1.5
        ctx.strokeStyle = hexA('#ffffff', dim ? 0.12 : isTerm || n.id === s.source ? 0.9 : 0.35)
        ctx.stroke()
        if (selectedId === n.id || s.hover === n.id) { ctx.strokeStyle = '#fff'; ctx.lineWidth = 2; ctx.beginPath(); ctx.arc(n.x, n.y, r + 5, 0, 6.3); ctx.stroke() }
        // label
        const m = metaOf(n.id)
        const focus = s.hover === n.id || selectedId === n.id
        const tname = m?.terminal?.name || n.termName
        const isDeposit = m?.terminal?.kind === 'exchange_deposit'   // dozens of these: label only the focused one
        const label = n.id === s.source ? 'Reported wallet'
          : isTerm ? (isDeposit ? (focus ? `${tname} deposit` : '') : tname)
          : focus ? short(n.id) : ''
        if (label && p >= 1) {
          ctx.font = '600 12px Inter, system-ui, sans-serif'; ctx.textAlign = 'left'
          const tw = ctx.measureText(label).width
          ctx.fillStyle = `rgba(7,11,20,${dim ? 0.3 : 0.78})`
          ctx.beginPath(); ctx.roundRect(n.x + r + 5, n.y - 13, tw + 14, n.id === s.source ? 38 : 25, 8); ctx.fill()
          ctx.fillStyle = hexA('#ffffff', dim ? 0.3 : 0.96)
          ctx.fillText(label, n.x + r + 12, n.y + 4)
          if (n.id === s.source) { ctx.font = '500 10.5px ui-monospace, monospace'; ctx.fillStyle = hexA('#9fb0c9', 0.9); ctx.fillText(short(n.id), n.x + r + 12, n.y + 19) }
        }
      }
      ctx.restore()
    }
    let highlightNodes = new Set()
    const updHL = () => {
      highlightNodes = new Set()
      const he = propsRef.current.highlightEdges
      if (he) for (const k of he) { const [a, b] = k.split('|'); highlightNodes.add(a); highlightNodes.add(b) }
    }
    updHL()
    s.updHL = updHL
    s.raf = requestAnimationFrame(draw)
    return () => { cancelAnimationFrame(s.raf); ro.disconnect() }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => { S.current.updHL?.() }, [highlightEdges])

  // ---------------------------------------------------------------- pointer interaction
  const toWorld = (ev) => {
    const r = canvasRef.current.getBoundingClientRect(); const s = S.current
    return { x: (ev.clientX - r.left - s.tf.x) / s.tf.k, y: (ev.clientY - r.top - s.tf.y) / s.tf.k, sx: ev.clientX - r.left, sy: ev.clientY - r.top }
  }
  const pick = (w) => {
    let best = null, bd = Infinity
    for (const n of S.current.nodes.values()) { const d = Math.hypot(n.x - w.x, n.y - w.y); if (d < n.r + 8 && d < bd) { best = n; bd = d } }
    return best
  }
  const onMove = (ev) => {
    const s = S.current, w = toWorld(ev)
    if (s.drag) { s.tf.x += ev.movementX; s.tf.y += ev.movementY; s.autoFit = false; return }
    const n = pick(w)
    s.hover = n ? n.id : null
    canvasRef.current.style.cursor = n ? 'pointer' : 'grab'
    onHover?.(n ? { id: n.id, x: w.sx, y: w.sy, term: n.term, termName: n.termName, termReason: n.termReason } : null)
  }
  const onWheel = (ev) => {
    const s = S.current, w = toWorld(ev)
    const k = clamp(s.tf.k * (ev.deltaY < 0 ? 1.12 : 0.89), 0.2, 3)
    s.tf.x = w.sx - w.x * k; s.tf.y = w.sy - w.y * k; s.tf.k = k; s.autoFit = false
  }

  return (
    <div ref={wrapRef} style={{ position: 'absolute', inset: 0 }}>
      <canvas
        ref={canvasRef}
        onMouseMove={onMove}
        onMouseLeave={() => { S.current.hover = null; onHover?.(null) }}
        onMouseDown={(ev) => { const w = toWorld(ev); if (!pick(w)) S.current.drag = true }}
        onMouseUp={() => { S.current.drag = null }}
        onClick={(ev) => { const n = pick(toWorld(ev)); onSelect?.(n ? n.id : null) }}
        onWheel={onWheel}
      />
    </div>
  )
})

export default GraphCanvas
