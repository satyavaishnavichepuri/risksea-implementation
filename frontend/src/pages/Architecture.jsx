import { useEffect, useMemo, useRef, useState } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import { BookOpen, Play, Square } from 'lucide-react'
import { PageHead, StatusChip, Toggle } from '../components/ui'
import { api } from '../api'
import { groupTerminals, pct, short } from '../util'

const COLS = [['intake', 'Intake'], ['data', 'Data layer'], ['engine', 'Engines'], ['output', 'Output'], ['eval', 'Evaluation']]
const CW = 196, CH = 88, GX = 236, GY = 108, X0 = 22, Y0 = 52

export default function Architecture({ arch, cases }) {
  const [sel, setSel] = useState('tracing')
  const [showPlanned, setShowPlanned] = useState(true)
  const [lit, setLit] = useState(null)
  const [log, setLog] = useState([])
  const [playing, setPlaying] = useState(false)
  const timer = useRef(null)

  const mods = arch.modules.filter((m) => showPlanned || m.status !== 'planned')
  const pos = useMemo(() => {
    const p = {}
    COLS.forEach(([g], ci) => mods.filter((m) => m.group === g).forEach((m, ri) => { p[m.id] = { x: X0 + ci * GX, y: Y0 + ri * GY, col: ci } }))
    return p
  }, [mods])
  const flows = arch.flows.filter((f) => pos[f.from] && pos[f.to])
  const height = Math.max(...Object.values(pos).map((p) => p.y)) + CH + 40
  const width = X0 * 2 + (COLS.length - 1) * GX + CW

  const path = (f) => {
    const a = pos[f.from], b = pos[f.to]
    let x1, y1, x2, y2
    if (a.col < b.col) { x1 = a.x + CW; y1 = a.y + CH / 2; x2 = b.x; y2 = b.y + CH / 2 }
    else if (a.col > b.col) { x1 = a.x; y1 = a.y + CH / 2; x2 = b.x + CW; y2 = b.y + CH / 2 }
    else { const down = b.y > a.y; x1 = a.x + CW / 2 + 30; y1 = a.y + (down ? CH : 0); x2 = b.x + CW / 2 + 30; y2 = b.y + (down ? 0 : CH) }
    const dx = Math.max(40, Math.abs(x2 - x1) / 2)
    const horizontal = a.col !== b.col
    return horizontal
      ? `M${x1} ${y1} C ${x1 + (a.col < b.col ? dx : -dx)} ${y1}, ${x2 + (a.col < b.col ? -dx : dx)} ${y2}, ${x2} ${y2}`
      : `M${x1} ${y1} C ${x1 + 46} ${(y1 + y2) / 2}, ${x2 + 46} ${(y1 + y2) / 2}, ${x2} ${y2}`
  }

  const connected = useMemo(() => {
    const s = new Set([sel])
    flows.forEach((f) => { if (f.from === sel) s.add(f.to); if (f.to === sel) s.add(f.from) })
    return s
  }, [sel, flows])

  const stop = () => { clearInterval(timer.current); setPlaying(false); setLit(null) }
  const play = async () => {
    stop(); setLog([]); setPlaying(true)
    const cid = cases.some((x) => x.id === 'phishing_2018') ? 'phishing_2018' : 'cryptopia_2019'
    const r = await api.caseTrace(cid, 'ttr')
    const c = cases.find((x) => x.id === cid)
    const rounds = r.events.filter((e) => e.kind === 'expand')
    const g = groupTerminals(r.terminals)[0]
    const top = { ...g, path: g.members[0].path }
    const where = g.members.length > 1 ? `${g.members.length} ${g.kind === 'exchange_deposit' ? 'deposit addresses of ' : 'addresses of '}${g.name}` : g.name
    const script = [
      ['intake', `Complaint opened: wallet ${short(r.source, 6)}, window ${c.start} to ${c.end}.`],
      ['adapter', 'Asks the chain adapter for every ETH transfer touching the wallet (BigQuery, largest 200 per direction).'],
      ['cache', `First fetch scanned ${c.first_run_gib} GiB; every later run, and every parameter change, is served from the cache.`],
      ...rounds.map((e) => ['tracing', `Round ${e.round}: pushes residual from ${e.info.frontier} account${e.info.frontier === 1 ? '' : 's'} along their outflows; ${pct(e.info.residual, 0)} of the funds still unexplained.`]),
      ['attribution', `Stops at ${where} (${top.kind}) with ${pct(top.share, 1)} of the funds: ${top.reason}`],
      ['typology', `Tags laundering patterns: ${Object.entries(r.nodes.flatMap((n) => n.tags).reduce((a, t) => ({ ...a, [t]: (a[t] || 0) + 1 }), {})).map(([t, n]) => `${t.replace('_', '-')} ×${n}`).join(', ') || 'none'}.`],
      ['casefile', `Writes the case file: ${r.edges.length} transfers, ${top.path.length}-step evidence path with transaction hashes.`],
      ['report', 'Investigator report is ready to print.'],
    ]
    let i = 0
    timer.current = setInterval(() => {
      if (i >= script.length) { clearInterval(timer.current); setPlaying(false); setLit(null); return }
      const [m, text] = script[i]
      setLit(m); setSel(m); setLog((l) => [...l, { m, text }]); i += 1
    }, 1250)
  }
  useEffect(() => () => clearInterval(timer.current), [])

  const mod = arch.modules.find((m) => m.id === sel)

  return (
    <div>
      <PageHead title="How the system works">
        The prototype is a pipeline of small modules. Solid cards are built and exercised by the benchmark cases; dashed cards are the
        honest roadmap. Click a module, or play a real trace through the whole system.
      </PageHead>
      <div className="row wrap" style={{ marginBottom: 14, justifyContent: 'space-between' }}>
        <div className="row">
          <button className="btn primary" onClick={playing ? stop : play}>{playing ? <><Square size={14} /> Stop</> : <><Play size={14} /> Play a trace through the system</>}</button>
          <StatusChip s="live" /><StatusChip s="partial" /><StatusChip s="planned" />
        </div>
        <div style={{ width: 230 }}><Toggle label="Show planned modules" on={showPlanned} onChange={setShowPlanned} /></div>
      </div>

      <div style={{ display: 'grid', gap: 16 }}>
        <div className="archwrap">
          <div className="archstage" style={{ width, height, minWidth: width }}>
            {COLS.map(([g, label], i) => (
              <div key={g} className="archcol" style={{ left: X0 - 14 + i * GX, width: GX }}><span>{label}</span></div>
            ))}
            <svg width={width} height={height} style={{ position: 'absolute', inset: 0, pointerEvents: 'none' }}>
              <defs>
                <marker id="ah" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M0 0L10 5L0 10z" fill="#7dd3fc" /></marker>
                <marker id="ahd" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M0 0L10 5L0 10z" fill="#475569" /></marker>
              </defs>
              {flows.map((f, i) => {
                const on = lit ? f.from === lit || f.to === lit : connected.has(f.from) && connected.has(f.to) && (f.from === sel || f.to === sel)
                const planned = arch.modules.find((m) => m.id === f.from)?.status === 'planned' || arch.modules.find((m) => m.id === f.to)?.status === 'planned'
                return (
                  <g key={i}>
                    <path d={path(f)} fill="none" stroke={planned ? '#475569' : '#7dd3fc'} strokeOpacity={on ? 0.95 : planned ? 0.3 : 0.22} strokeWidth={on ? 2.2 : 1.4}
                      strokeDasharray={planned ? '4 6' : '7 8'} markerEnd={`url(#${planned ? 'ahd' : 'ah'})`} style={{ animation: planned ? 'none' : 'dash 1.4s linear infinite' }} />
                  </g>
                )
              })}
            </svg>
            <style>{'@keyframes dash { to { stroke-dashoffset: -30; } }'}</style>
            {mods.map((m) => (
              <motion.button key={m.id} className={`mod ${m.status} ${sel === m.id ? 'sel' : ''} ${lit === m.id ? 'lit' : ''} ${!lit && sel !== m.id && !connected.has(m.id) ? 'dim' : ''}`}
                style={{ left: pos[m.id].x, top: pos[m.id].y }} onClick={() => setSel(m.id)} initial={{ opacity: 0, scale: 0.9 }} animate={{ opacity: 1, scale: 1 }} transition={{ delay: pos[m.id].col * 0.06 }}>
                <div className="t"><span>{m.label}</span><StatusChip s={m.status} /></div>
                <div className="d">{m.desc}</div>
              </motion.button>
            ))}
          </div>
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14, alignContent: 'start' }}>
          <AnimatePresence mode="wait">
            {mod && (
              <motion.div key={mod.id} className="glass pad" initial={{ opacity: 0, x: 12 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0 }}>
                <div className="row" style={{ justifyContent: 'space-between' }}><b style={{ fontSize: 16 }}>{mod.label}</b><StatusChip s={mod.status} /></div>
                <p className="muted small" style={{ lineHeight: 1.55 }}>{mod.desc}</p>
                <ul className="small" style={{ paddingLeft: 18, lineHeight: 1.6, color: '#c3cde0' }}>{mod.details.map((d) => <li key={d}>{d}</li>)}</ul>
                {mod.ps.length > 0 && <><div className="h3" style={{ marginTop: 12 }}>Problem-statement items it serves</div>
                  <div className="row wrap">{mod.ps.map((p) => <span key={p} className="chip">{p}</span>)}</div></>}
                {mod.book && <div className="small muted" style={{ marginTop: 12 }}><BookOpen size={12} /> Book: {mod.book}</div>}
              </motion.div>
            )}
          </AnimatePresence>
          <div className="glass pad">
            <div className="h3">Live narration</div>
            {log.length === 0 && <p className="muted small" style={{ margin: 0 }}>Press play to watch a real Cryptopia trace move through each module.</p>}
            <div className="scroll" style={{ maxHeight: 280, overflow: 'auto' }}>
              {log.map((l, i) => (
                <motion.div key={i} className={`logline ${i === log.length - 1 ? 'cur' : ''}`} initial={{ opacity: 0, x: 8 }} animate={{ opacity: 1, x: 0 }}>
                  <span className="rn">{arch.modules.find((m) => m.id === l.m)?.label}</span><br />{l.text}
                </motion.div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
