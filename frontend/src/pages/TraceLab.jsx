import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import { AlertTriangle, Database, ExternalLink, Maximize2, Pause, Play, RotateCcw, SkipBack, SkipForward, Zap } from 'lucide-react'
import { Area, AreaChart, ResponsiveContainer, Tooltip as RTip, XAxis, YAxis } from 'recharts'
import GraphCanvas from '../components/GraphCanvas'
import { Chip, Seg, Slider, Spinner, Toggle } from '../components/ui'
import { api, streamJob } from '../api'
import { KIND_COLOR, KIND_NAME, buildSteps, etherscanAddr, etherscanTx, fmtDate, fmtDay, fmtEth, groupTerminals, pct, short } from '../util'

const TAGS = {
  zero_out: ['Zero-out account', 'Forwards almost everything it received within 24 hours: a pass-through bridge account.'],
  fan_out: ['Fan-out', 'Splits funds to five or more recipients within a day: layering.'],
  fan_in: ['Fan-in', 'Collects from five or more senders: an aggregation point.'],
  peel: ['Peeling chain', 'Passes most funds on and keeps a small part, repeatedly.'],
  fast_hop: ['Fast hop', 'First outflow within an hour of the funds arriving.'],
}

function headline(r) {
  if (!r || !r.terminals.length) return { tone: 'warn', text: 'No destination reached yet. The funds are still moving, or fall below the dust and share thresholds.' }
  const t = r.terminals[0]
  const where = `${pct(t.share, 1)} of the traced funds (about ${fmtEth(t.eth_est)} ETH) reached`
  const hops = `${t.depth} hop${t.depth === 1 ? '' : 's'}`
  if (t.kind === 'exchange') return { tone: 'good', text: `${where} ${t.name}, a labeled exchange, in ${hops}. This is the account to send a freeze and KYC request to.` }
  if (t.kind === 'exchange_deposit') return { tone: 'good', text: `${where} a deposit address that sweeps into ${t.name} (inferred), in ${hops}. Ask ${t.name} to freeze and identify the account holder.` }
  if (t.kind === 'mixer') return { tone: 'bad', text: `${where} ${t.name} in ${hops}. A mixer breaks the on-chain link, so tracing stops here. Preserve the evidence and flag for specialist follow-up.` }
  if (t.kind === 'dex') return { tone: 'warn', text: `${where} ${t.name} in ${hops}. Funds enter a DEX contract; the way out is an internal transfer that this MVP cannot yet follow (see the roadmap).` }
  if (t.kind === 'sanctioned') return { tone: 'bad', text: `${where} an OFAC-sanctioned address in ${hops}.` }
  return { tone: 'warn', text: `${where} an unlabeled high-activity service in ${hops}. Manual review needed to identify it.` }
}

/** Headline sentence built from the grouped findings (one finding per receiving entity). */
function headlineG(groups) {
  if (!groups.length) return { tone: 'warn', text: 'No destination reached yet. The funds are still moving, or fall below the dust and share thresholds.' }
  const g = groups[0]
  const n = g.members.length
  const where = `${pct(g.share, 1)} of the traced funds (about ${fmtEth(g.eth_est)} ETH) reached`
  const hops = `${g.depth} hop${g.depth === 1 ? '' : 's'}`
  const rest = groups.slice(1).reduce((a, x) => a + x.share, 0)
  const tail = rest > 0.01 ? ` A further ${pct(rest, 0)} ended at other services (see below).` : ''
  if (g.kind === 'exchange') return { tone: 'good', text: `${where} ${g.name}, a labeled exchange, in ${hops}. This is the account to send a freeze and KYC request to.${tail}` }
  if (g.kind === 'exchange_deposit') return { tone: 'good', text: `${where} ${n} deposit address${n === 1 ? '' : 'es'} that sweep into ${g.name} (inferred), within ${hops}. Ask ${g.name} to freeze these addresses and identify the account holders.${tail}` }
  if (g.kind === 'mixer') return { tone: 'bad', text: `${where} ${g.name} in ${hops}. A mixer breaks the on-chain link, so tracing stops here. Preserve the evidence and flag for specialist follow-up.${tail}` }
  if (g.kind === 'dex') return { tone: 'warn', text: `${where} ${g.name} in ${hops}. Funds enter a DEX contract; the way out is an internal transfer that this MVP cannot yet follow (see the roadmap).${tail}` }
  if (g.kind === 'sanctioned') return { tone: 'bad', text: `${where} an OFAC-sanctioned address in ${hops}.${tail}` }
  return { tone: 'warn', text: `${where} an unlabeled high-activity service in ${hops}. Manual review needed to identify it.${tail}` }
}

export default function TraceLab({ meta, cases, initialCase, onResult }) {
  const [mode, setMode] = useState('case')
  const [caseId, setCaseId] = useState(initialCase || (cases.some((c) => c.id === 'phishing_2018') ? 'phishing_2018' : cases[0].id))
  const [engine, setEngine] = useState('ttr')
  const [params, setParams] = useState(meta.defaults)
  const [custom, setCustom] = useState({ source: '', start: '', end: '', live: false })
  const [result, setResult] = useState(null)
  const [events, setEvents] = useState([])
  const [running, setRunning] = useState(false)
  const [error, setError] = useState(null)
  const [stepIndex, setStepIndex] = useState(-1)
  const [playing, setPlaying] = useState(true)
  const [speed, setSpeed] = useState(1)
  const [resetKey, setResetKey] = useState(0)
  const [tab, setTab] = useState('findings')
  const [selTerm, setSelTerm] = useState(null)
  const [selNode, setSelNode] = useState(null)
  const [tip, setTip] = useState(null)
  const canvasRef = useRef(null)
  const stopRef = useRef(null)

  const steps = useMemo(() => buildSteps(events), [events])
  const nodeMeta = useMemo(() => (result ? new Map(result.nodes.map((n) => [n.id, n])) : null), [result])
  const caseObj = cases.find((c) => c.id === caseId)
  const cur = steps[Math.max(0, Math.min(stepIndex, steps.length - 1))]

  const fresh = () => { setResetKey((k) => k + 1); setStepIndex(-1); setPlaying(true); setSelTerm(null); setSelNode(null); setTab('findings') }

  const loadStored = useCallback(async (cid, eng) => {
    stopRef.current?.(); setError(null); setRunning(false)
    try {
      const r = await api.caseTrace(cid, eng)
      setResult(r); setEvents(r.events); setParams({ ...meta.defaults, ...r.params }); fresh(); onResult?.(r)
    } catch (e) { setError(e.message) }
  }, [meta.defaults, onResult])

  useEffect(() => { if (mode === 'case') loadStored(caseId, engine) }, [caseId, engine, mode, loadStored])

  const run = async () => {
    stopRef.current?.(); setError(null); setRunning(true); setResult(null); setEvents([]); fresh()
    const body = mode === 'case'
      ? { engine, case_id: caseId, params, live: false }
      : { engine, source: custom.source.trim(), start: custom.start, end: custom.end, params, live: custom.live }
    try {
      const { job_id } = await api.startTrace(body)
      stopRef.current = streamJob(job_id, {
        onEvent: (ev) => setEvents((es) => [...es, ev]),
        onDone: (r) => { setResult(r); setRunning(false); onResult?.(r) },
        onError: (e) => { setError(e.message); setRunning(false) },
      })
    } catch (e) { setError(e.message); setRunning(false) }
  }

  // playback clock: advance one search round at a time while there is something to show
  useEffect(() => {
    if (!playing) return undefined
    const id = setInterval(() => {
      setStepIndex((i) => {
        if (i < steps.length - 1) return i + 1
        if (!running && steps.length) setPlaying(false)
        return i
      })
    }, 1700 / speed)
    return () => clearInterval(id)
  }, [playing, steps.length, speed, running])

  const visible = useMemo(() => {
    const nodes = new Set(); let edges = 0
    steps.slice(0, stepIndex + 1).forEach((s) => { s.nodes?.forEach?.((n) => s.kind === 'start' && nodes.add(n)); s.edges.forEach((e) => { nodes.add(e.src); nodes.add(e.dst); edges += 1 }) })
    return { nodes: nodes.size, edges }
  }, [steps, stepIndex])

  const groups = useMemo(() => (result ? groupTerminals(result.terminals) : []), [result])
  const selGroup = groups.find((g) => g.key === selTerm)
  const highlightEdges = useMemo(
    () => (selGroup ? new Set(selGroup.members.slice(0, 14).flatMap((m) => m.path.map((e) => `${e.src}|${e.dst}`))) : null), [selGroup])
  const hl = headlineG(groups)
  const doneAll = !running && steps.length > 0 && stepIndex >= steps.length - 1
  const selMeta = selNode ? nodeMeta?.get(selNode) : null

  // when the animation reaches the end, highlight the top finding so the audience sees the answer without clicking
  useEffect(() => {
    if (doneAll && groups.length && !selTerm) { setSelTerm(groups[0].key); setSelNode(groups[0].members[0].node) }
  }, [doneAll, groups]) // eslint-disable-line react-hooks/exhaustive-deps

  // keyboard shortcuts for presenting: Space play/pause, arrows step, F fit, R replay
  useEffect(() => {
    const onKey = (e) => {
      const t = e.target?.tagName
      if (t === 'INPUT' || t === 'TEXTAREA' || t === 'SELECT' || e.metaKey || e.ctrlKey || e.altKey) return
      if (e.key === ' ') { e.preventDefault(); setPlaying((p) => !p) }
      else if (e.key === 'ArrowRight') setStepIndex((i) => Math.min(steps.length - 1, i + 1))
      else if (e.key === 'ArrowLeft') setStepIndex((i) => Math.max(-1, i - 1))
      else if (e.key === 'f' || e.key === 'F') canvasRef.current?.fit()
      else if (e.key === 'r' || e.key === 'R') { fresh() }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [steps.length]) // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className="lab">
      {/* ------------------------------------------------------------ left: controls */}
      <div className="col">
        <div className="glass pad guide">
          <h4 className="h3" style={{ margin: 0 }}>Demo guide</h4>
          <ol>
            <li>Pick a case. The animation shows the search spreading one round at a time.</li>
            <li>Watch “Unexplained” fall: that is the share of funds not yet pinned to a destination.</li>
            <li>At the end the top finding is highlighted. Open it for addresses and the evidence path.</li>
            <li>Switch algorithm to Blind BFS and compare what it misses.</li>
            <li>Open Report for the printable case file.</li>
          </ol>
          <div className="muted tiny" style={{ marginTop: 8 }}><kbd>Space</kbd> play/pause · <kbd>←</kbd><kbd>→</kbd> step · <kbd>F</kbd> fit · <kbd>R</kbd> replay</div>
        </div>
        <div className="glass pad">
          <div className="row" style={{ justifyContent: 'space-between', marginBottom: 10 }}>
            <h4 className="h3" style={{ margin: 0 }}>Case</h4>
            <Seg options={[{ id: 'case', label: 'Benchmark' }, { id: 'custom', label: 'Any wallet' }]} value={mode} onChange={setMode} />
          </div>
          {mode === 'case' ? (
            <div style={{ display: 'grid', gap: 8 }}>
              {cases.map((c) => (
                <button key={c.id} className={`casecard ${c.id === caseId ? 'on' : ''}`} onClick={() => setCaseId(c.id)}>
                  <b>{c.title}</b>
                  <span className="muted tiny">{c.start} → {c.end} · {short(c.source, 6)}</span>
                </button>
              ))}
              {caseObj && <p className="muted small" style={{ margin: '4px 2px 0', lineHeight: 1.5 }}>{caseObj.story}</p>}
            </div>
          ) : (
            <div style={{ display: 'grid', gap: 8 }}>
              <input type="text" placeholder="0x… reported wallet" value={custom.source} onChange={(e) => setCustom({ ...custom, source: e.target.value })} />
              <div className="row"><input type="date" value={custom.start} onChange={(e) => setCustom({ ...custom, start: e.target.value })} /><input type="date" value={custom.end} onChange={(e) => setCustom({ ...custom, end: e.target.value })} /></div>
              <Toggle label="Allow live BigQuery (billed, capped)" on={custom.live} onChange={(v) => setCustom({ ...custom, live: v })} disabled={!meta.live_available}
                hint={meta.live_available ? '' : 'Start the backend with CRYPTOTRACE_BQ_PROJECT set to enable live queries'} />
              <p className="muted tiny" style={{ margin: 0 }}>Window: at most 120 days from the incident. Uncached wallets need live mode.{!meta.live_available && ' Live mode is off on this server.'}</p>
            </div>
          )}
        </div>

        <div className="glass pad">
          <h4 className="h3">Algorithm</h4>
          <Seg options={meta.engines.map((e) => ({ id: e.id, label: e.label }))} value={engine} onChange={setEngine} />
          <p className="muted small" style={{ lineHeight: 1.5, margin: '10px 0 0' }}>{meta.engines.find((e) => e.id === engine)?.desc}</p>
        </div>

        <div className="glass pad">
          <h4 className="h3">Parameters <span className="tiny" style={{ textTransform: 'none', letterSpacing: 0 }}>(re-runs on cached cases are free)</span></h4>
          <Slider label="α  stay probability" value={params.alpha} min={0.01} max={0.5} step={0.01} onChange={(v) => setParams({ ...params, alpha: v })} />
          <Slider label="β  forward attention" value={params.beta} min={0.5} max={1} step={0.05} onChange={(v) => setParams({ ...params, beta: v })} />
          <Slider label="ε  residual threshold" value={params.epsilon} min={0.0001} max={0.1} step={0.0001} fmt={(v) => v.toExponential(1)} onChange={(v) => setParams({ ...params, epsilon: v })} />
          <Slider label="Max rounds (hops)" value={params.max_rounds} min={1} max={10} step={1} onChange={(v) => setParams({ ...params, max_rounds: v })} />
          <Slider label="Hub threshold (transfers)" value={params.hub_degree} min={100} max={20000} step={100} onChange={(v) => setParams({ ...params, hub_degree: v })} />
          <Toggle label="Time-respecting" on={params.time_respecting} onChange={(v) => setParams({ ...params, time_respecting: v })} />
          <button className="btn primary" style={{ width: '100%', justifyContent: 'center' }} onClick={run} disabled={running || (mode === 'custom' && !custom.source)}>
            {running ? <><Spinner /> Tracing…</> : <><Zap size={16} /> Run trace</>}
          </button>
        </div>
      </div>

      {/* ------------------------------------------------------------ centre: graph */}
      <div className="canvaswrap">
        <div className="canvasbox">
          {!steps.length && !error && <div className="empty">{running ? <div><Spinner /> <p>Waiting for the first search round…</p></div> : 'Loading…'}</div>}
          {error && <div className="empty"><div><AlertTriangle color="#fbbf24" /><p style={{ maxWidth: 420 }}>{error}</p></div></div>}
          <GraphCanvas ref={canvasRef} steps={steps} stepIndex={stepIndex} nodeMeta={nodeMeta} highlightEdges={highlightEdges}
            selectedId={selNode} resetKey={resetKey} speed={speed}
            onHover={setTip} onSelect={(id) => { setSelNode(id); if (id) setTab('node') }} />

          <div className="overlay hud">
            <div className="hudpill"><div className="k">Round</div><div className="v">{Math.max(0, cur?.round ?? 0)}<span className="muted" style={{ fontSize: 12 }}> / {result?.stats.rounds ?? '…'}</span></div></div>
            <div className="hudpill"><div className="k">Accounts</div><div className="v">{visible.nodes}</div></div>
            <div className="hudpill"><div className="k">Transfers</div><div className="v">{visible.edges}</div></div>
            <div className="hudpill"><div className="k">Unexplained</div><div className="v">{cur?.info?.residual !== undefined ? pct(cur.info.residual, 0) : '—'}</div></div>
            <div className="hudpill"><div className="k">Data layer</div><div className="v" style={{ fontSize: 13, lineHeight: '22px' }}><Database size={12} style={{ marginRight: 6 }} />{cur?.info?.queries ?? 0} queries · {cur?.info?.cache_hits ?? 0} cached</div></div>
          </div>

          <div className="overlay legend">
            {[['source', 'Reported wallet'], ['intermediate', 'Intermediate account'], ['exchange_deposit', 'Exchange deposit / exchange'], ['mixer', 'Mixer'], ['dex', 'DEX contract'], ['service_hub', 'Unlabeled service']].map(([k, l]) => (
              <div key={k}><i style={{ background: KIND_COLOR[k] }} />{l}</div>
            ))}
          </div>

          <div className="playbar">
            <button className="btn iconbtn" onClick={() => setStepIndex((i) => Math.max(-1, i - 1))} title="Back one round"><SkipBack size={15} /></button>
            <button className="btn iconbtn primary" onClick={() => (doneAll ? (fresh(), setStepIndex(-1)) : setPlaying((p) => !p))} title={doneAll ? 'Replay' : playing ? 'Pause' : 'Play'}>
              {doneAll ? <RotateCcw size={15} /> : playing ? <Pause size={15} /> : <Play size={15} />}
            </button>
            <button className="btn iconbtn" onClick={() => setStepIndex((i) => Math.min(steps.length - 1, i + 1))} title="Forward one round"><SkipForward size={15} /></button>
            <input className="scrub" type="range" min={-1} max={Math.max(0, steps.length - 1)} value={stepIndex} onChange={(e) => { setStepIndex(+e.target.value); setPlaying(false) }} />
            <Seg options={[{ id: 0.5, label: '0.5×' }, { id: 1, label: '1×' }, { id: 2, label: '2×' }]} value={speed} onChange={setSpeed} />
            <button className="btn iconbtn" onClick={() => canvasRef.current?.fit()} title="Fit to view"><Maximize2 size={15} /></button>
          </div>

          {tip && (
            <div className="tip" style={{ left: Math.min(tip.x + 14, 9999), top: tip.y + 14 }}>
              <b className="mono">{short(tip.id, 8)}</b>
              {(() => { const m = nodeMeta?.get(tip.id); return m ? (
                <div className="muted">
                  {m.label ? <div>{m.label.name} <span className="tiny">({m.label.kind})</span></div> : null}
                  {m.terminal ? <div style={{ color: KIND_COLOR[m.terminal.kind] }}>{KIND_NAME[m.terminal.kind]}</div> : null}
                  <div>Share of funds: {pct(m.share, 1)} · first seen {fmtDay(m.first_ts)}</div>
                  {m.tags.length ? <div>{m.tags.map((t) => TAGS[t]?.[0] || t).join(' · ')}</div> : null}
                </div>) : tip.termName ? <div className="muted">{tip.termName}<div className="tiny">{tip.termReason}</div></div> : null })()}
            </div>
          )}
        </div>
      </div>

      {/* ------------------------------------------------------------ right: findings */}
      <div className="col">
        <div className="glass pad" style={{ paddingBottom: 6 }}>
          <div className="tabs">
            {[['findings', 'Findings'], ['inside', 'Inside the engine'], ['node', 'Account']].map(([id, l]) => <button key={id} className={tab === id ? 'on' : ''} onClick={() => setTab(id)}>{l}</button>)}
          </div>

          {tab === 'findings' && result && (
            <div>
              <motion.div key={result.engine + result.source + result.stats.rounds} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }}
                style={{ padding: '12px 14px', borderRadius: 14, marginBottom: 14, lineHeight: 1.55, fontSize: 13.5, border: '1px solid var(--line)',
                  background: hl.tone === 'good' ? 'rgba(52,211,153,.09)' : hl.tone === 'bad' ? 'rgba(251,113,133,.09)' : 'rgba(251,191,36,.08)' }}>
                {hl.text}
              </motion.div>
              <h4 className="h3">Where the funds ended up</h4>
              <div style={{ display: 'grid', gap: 8 }}>
                {groups.map((g) => {
                  const best = g.members[0]
                  const multi = g.members.length > 1
                  const into = g.members.flatMap((m) => result.edges.filter((e) => e.dst === m.node && e.role === 'fwd'))
                  return (
                    <div key={g.key} role="button" tabIndex={0} className={`term ${selTerm === g.key ? 'on' : ''}`}
                      onClick={() => { setSelTerm(selTerm === g.key ? null : g.key); setSelNode(best.node) }}>
                      <div className="row" style={{ justifyContent: 'space-between', marginBottom: 6 }}>
                        <b style={{ fontSize: 13.5 }}><span className="dot" style={{ background: KIND_COLOR[g.kind], marginRight: 8 }} />{g.name}
                          {multi && <span className="muted" style={{ fontWeight: 500 }}> · {g.members.length} addresses</span>}</b>
                        <Chip kind={g.confidence}>{g.confidence} confidence</Chip>
                      </div>
                      <div className="bar"><i style={{ width: `${Math.max(2, g.share * 100)}%` }} /></div>
                      <div className="row small muted" style={{ justifyContent: 'space-between', marginTop: 6 }}>
                        <span>{pct(g.share, 1)} · ≈{fmtEth(g.eth_est)} ETH</span><span>{g.depth} hops · {KIND_NAME[g.kind]}</span>
                      </div>
                      <AnimatePresence>
                        {selTerm === g.key && (
                          <motion.div initial={{ height: 0, opacity: 0 }} animate={{ height: 'auto', opacity: 1 }} exit={{ height: 0, opacity: 0 }} style={{ overflow: 'hidden', textAlign: 'left' }}>
                            <p className="small muted" style={{ margin: '10px 0 6px', lineHeight: 1.5 }}>{g.reason}</p>
                            {multi && (<>
                              <div className="h3" style={{ marginTop: 10 }}>Addresses to ask {g.name} to freeze ({g.members.length})</div>
                              {g.members.slice(0, 8).map((m) => (
                                <div key={m.node} className="row small" style={{ justifyContent: 'space-between', padding: '3px 0' }}>
                                  <a className="mono" href={etherscanAddr(m.node)} target="_blank" rel="noreferrer" onClick={(ev) => ev.stopPropagation()}>{short(m.node, 6)}</a>
                                  <span className="muted">{pct(m.share, 1)} · ≈{fmtEth(m.eth_est)} ETH</span>
                                </div>
                              ))}
                              {g.members.length > 8 && <div className="muted tiny">+ {g.members.length - 8} more, all listed in the Report</div>}
                            </>)}
                            <div className="h3" style={{ marginTop: 10 }}>Evidence path to {multi ? 'the largest of these' : 'this'} address ({best.path.length} transfers)</div>
                            <div className="muted tiny" style={{ marginBottom: 4 }}>
                              Highest-value route shown. In total {into.length} transfer{into.length === 1 ? '' : 's'} from the traced accounts entered {multi ? 'these addresses' : 'this destination'} (≈{fmtEth(into.reduce((a, e) => a + e.eth, 0))} ETH).
                            </div>
                            {best.path.map((e, i) => (
                              <div key={i} className="pathrow">
                                <div className="stepdot">{i + 1}</div>
                                <div>
                                  <div className="mono">{short(e.src, 5)} → {short(e.dst, 5)}</div>
                                  <div className="muted tiny">{fmtEth(e.eth)} ETH · {fmtDate(e.ts)}</div>
                                  {e.tx && <a className="tiny mono" href={etherscanTx(e.tx)} target="_blank" rel="noreferrer" onClick={(ev) => ev.stopPropagation()}>{e.tx.slice(0, 18)}… <ExternalLink size={10} /></a>}
                                </div>
                              </div>
                            ))}
                          </motion.div>
                        )}
                      </AnimatePresence>
                    </div>
                  )
                })}
              </div>
              {result.warnings.length > 0 && <div className="small" style={{ marginTop: 12, color: 'var(--warn)' }}><AlertTriangle size={13} /> {result.warnings.join(' ')}</div>}
              <h4 className="h3" style={{ marginTop: 16 }}>Laundering patterns seen</h4>
              <div className="row wrap">
                {Object.entries(result.nodes.flatMap((n) => n.tags).reduce((a, t) => ({ ...a, [t]: (a[t] || 0) + 1 }), {})).map(([t, c]) => (
                  <span key={t} title={TAGS[t]?.[1]}><Chip>{TAGS[t]?.[0] || t} · {c}</Chip></span>
                ))}
                {!result.nodes.some((n) => n.tags.length) && <span className="muted small">None triggered.</span>}
              </div>
            </div>
          )}

          {tab === 'inside' && (
            <div>
              <h4 className="h3">What the engine is doing now</h4>
              <p className="small" style={{ lineHeight: 1.6, margin: '0 0 12px', color: '#c3cde0' }}>
                {!cur ? 'Waiting…' : cur.kind === 'start'
                  ? 'A case is opened for the reported wallet. All of the funds (100%) are "unexplained residual" sitting on this one account.'
                  : `Round ${cur.round}: ${cur.info.frontier} account${cur.info.frontier === 1 ? ' carries' : 's carry'} enough unexplained residual to be worth following. The engine fetches their transfers (${cur.info.queries} BigQuery quer${cur.info.queries === 1 ? 'y' : 'ies'} so far, ${cur.info.cache_hits} lookups served from cache, ${(cur.info.bytes_billed / 1024 ** 3).toFixed(2)} GiB billed), keeps only outflows that happened after the funds arrived, splits the residual between recipients by amount, and stops at any exchange, mixer, DEX or busy hub. ${pct(cur.info.residual, 0)} of the funds are still unexplained.`}
              </p>
              {cur?.absorbs?.length > 0 && cur.absorbs.map((a, i) => (
                <div key={i} className="small" style={{ padding: '8px 10px', borderRadius: 10, background: 'rgba(255,255,255,.05)', marginBottom: 6 }}>
                  <b style={{ color: KIND_COLOR[a.info.kind_of] }}>Stop · {a.info.name}</b>
                  <div className="muted tiny">{a.info.reason}</div>
                </div>
              ))}
              {cur?.info?.weights && Object.keys(cur.info.weights).length > 0 && (<>
                <h4 className="h3" style={{ marginTop: 14 }}>Accounts being pushed from (relative weight)</h4>
                {Object.entries(cur.info.weights).map(([a, w]) => (
                  <div key={a} style={{ marginBottom: 7 }}>
                    <div className="row small" style={{ justifyContent: 'space-between' }}><span className="mono">{short(a, 5)}</span><span className="mono muted">{w.toFixed(3)}</span></div>
                    <div className="bar"><i style={{ width: `${Math.min(100, w * 100)}%` }} /></div>
                  </div>
                ))}
              </>)}
              <h4 className="h3" style={{ marginTop: 14 }}>Unexplained funds per round</h4>
              <div style={{ height: 120 }}>
                <ResponsiveContainer>
                  <AreaChart data={steps.filter((s) => s.info?.residual !== undefined).map((s) => ({ round: s.round, residual: s.info.residual }))} margin={{ left: -20, right: 6, top: 6 }}>
                    <defs><linearGradient id="rg" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#22d3ee" stopOpacity={0.5} /><stop offset="100%" stopColor="#22d3ee" stopOpacity={0} /></linearGradient></defs>
                    <XAxis dataKey="round" tick={{ fill: '#8b97ad', fontSize: 10 }} axisLine={false} tickLine={false} />
                    <YAxis tick={{ fill: '#8b97ad', fontSize: 10 }} axisLine={false} tickLine={false} />
                    <RTip contentStyle={{ background: '#0b1120', border: '1px solid rgba(255,255,255,.1)', borderRadius: 10, fontSize: 12 }} />
                    <Area type="monotone" dataKey="residual" stroke="#22d3ee" fill="url(#rg)" strokeWidth={2} />
                  </AreaChart>
                </ResponsiveContainer>
              </div>
              <h4 className="h3" style={{ marginTop: 10 }}>Round log</h4>
              {steps.slice(0, stepIndex + 1).map((s, i) => (
                <div key={i} className={`logline ${i === stepIndex ? 'cur' : ''}`}>
                  <span className="rn">R{s.round}</span>
                  {s.kind === 'start' ? 'Open case' : `Expand ${s.info.frontier} account${s.info.frontier === 1 ? '' : 's'}, ${s.edges.length} transfers kept${s.absorbs.length ? `, stopped at ${s.absorbs.map((a) => a.info.name).join(', ')}` : ''}`}
                </div>
              ))}
            </div>
          )}

          {tab === 'node' && (
            <div>
              {!selNode ? <p className="muted small">Click any account in the graph, or a destination in Findings.</p> : (<>
                <div className="mono" style={{ wordBreak: 'break-all', marginBottom: 6 }}>{selNode}</div>
                <a className="small" href={etherscanAddr(selNode)} target="_blank" rel="noreferrer">Open on Etherscan <ExternalLink size={11} /></a>
                <div style={{ marginTop: 12, display: 'grid', gridTemplateColumns: '120px 1fr', gap: '7px 10px', fontSize: 12.5 }}>
                  <span className="muted">Role</span><span>{selMeta?.terminal ? KIND_NAME[selMeta.terminal.kind] : selMeta?.role || '—'}</span>
                  <span className="muted">Label</span><span>{selMeta?.label ? `${selMeta.label.name} (${selMeta.label.source})` : 'none'}</span>
                  <span className="muted">Share of funds</span><span>{selMeta ? pct(selMeta.share, 2) : '—'}</span>
                  <span className="muted">Hops from source</span><span>{selMeta?.depth ?? '—'}</span>
                  <span className="muted">First funds in</span><span>{fmtDate(selMeta?.first_ts)}</span>
                  <span className="muted">Transfers in / out</span><span>{selMeta?.deg_in ?? '—'} / {selMeta?.deg_out ?? '—'} (in window)</span>
                  <span className="muted">Rank</span><span>{selMeta ? selMeta.rank.toFixed(4) : '—'}</span>
                </div>
                {selMeta?.terminal && <p className="small muted" style={{ lineHeight: 1.5 }}>{selMeta.terminal.reason}</p>}
                {selMeta?.tags?.length > 0 && <div style={{ marginTop: 8 }}>{selMeta.tags.map((t) => <div key={t} className="small" style={{ marginBottom: 6 }}><Chip>{TAGS[t]?.[0] || t}</Chip> <span className="muted">{TAGS[t]?.[1]}</span></div>)}</div>}
              </>)}
            </div>
          )}
        </div>

        {result && (
          <div className="glass pad small muted" style={{ lineHeight: 1.6 }}>
            <b style={{ color: 'var(--text)' }}>Limits of this MVP</b>
            <ul style={{ margin: '6px 0 0', paddingLeft: 18 }}>{meta.limits.map((l) => <li key={l}>{l}</li>)}</ul>
          </div>
        )}
      </div>
    </div>
  )
}
