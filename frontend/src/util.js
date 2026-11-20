/** One finding per receiving entity: 29 deposit addresses that sweep into one exchange are ONE group with 29 members. */
export function groupTerminals(terminals) {
  const order = { low: 0, medium: 1, high: 2 }
  const g = new Map()
  for (const t of terminals) {
    const key = `${t.kind}|${t.name}`
    const a = g.get(key) || { key, kind: t.kind, name: t.name, reason: t.reason, confidence: t.confidence, share: 0, eth_est: 0, depth: t.depth, members: [] }
    a.share += t.share; a.eth_est += t.eth_est; a.depth = Math.min(a.depth, t.depth); a.members.push(t)
    if (order[t.confidence] < order[a.confidence]) a.confidence = t.confidence
    g.set(key, a)
  }
  for (const a of g.values()) a.members.sort((x, y) => y.share - x.share)
  return [...g.values()].sort((x, y) => y.share - x.share)
}

export const short = (a, n = 6) => (a ? `${a.slice(0, n + 2)}…${a.slice(-4)}` : '')
export const fmtEth = (x) => (x >= 100 ? Math.round(x).toLocaleString() : x >= 1 ? x.toFixed(1) : x.toFixed(3))
export const pct = (x, d = 1) => `${(100 * x).toFixed(d)}%`
export const fmtDate = (t) => (t ? new Date(t * 1000).toISOString().replace('T', ' ').slice(0, 16) + ' UTC' : '—')
export const fmtDay = (t) => (t ? new Date(t * 1000).toISOString().slice(0, 10) : '—')
export const etherscanTx = (h) => `https://etherscan.io/tx/${h}`
export const etherscanAddr = (a) => `https://etherscan.io/address/${a}`

// role / terminal kind -> colour
export const KIND_COLOR = {
  source: '#38bdf8', exchange: '#34d399', exchange_deposit: '#2dd4bf', mixer: '#f472b6', dex: '#fbbf24',
  sanctioned: '#f87171', service_hub: '#94a3b8', intermediate: '#6ea8fe', upstream: '#64748b', other: '#7c8aa5',
}
export const KIND_NAME = {
  exchange: 'Exchange (labeled)', exchange_deposit: 'Exchange deposit (inferred)', mixer: 'Mixer', dex: 'DEX contract',
  sanctioned: 'Sanctioned address', service_hub: 'Unlabeled service hub',
}
export const nodeColor = (n) => (n?.terminal ? KIND_COLOR[n.terminal.kind] : KIND_COLOR[n?.role] || KIND_COLOR.other)

/** Group the raw event log into playback steps: one per search round, with the round's absorb pulses attached. */
export function buildSteps(events) {
  const steps = []
  const byRound = {}
  for (const e of events) {
    if (e.kind === 'start') steps.push({ round: 0, kind: 'start', edges: [], absorbs: [], info: e.info, nodes: e.nodes })
    else if (e.kind === 'expand') {
      const s = { round: e.round, kind: 'expand', edges: e.edges, absorbs: [], info: e.info, nodes: e.nodes }
      byRound[e.round] = s
      steps.push(s)
    } else if (e.kind === 'absorb') (byRound[e.round] ||= { absorbs: [] }).absorbs?.push(e)
  }
  // absorb events are emitted before their round's expand event, so attach any that arrived first
  const pending = {}
  for (const e of events) if (e.kind === 'absorb') (pending[e.round] ||= []).push(e)
  for (const s of steps) if (s.kind === 'expand') s.absorbs = pending[s.round] || []
  return steps
}

/** Aggregate parallel transfers between the same two addresses into one visual edge. */
export function aggregateEdges(edges) {
  const m = new Map()
  for (const e of edges) {
    const k = `${e.src}|${e.dst}`
    const a = m.get(k) || { key: k, src: e.src, dst: e.dst, eth: 0, count: 0, share: 0, role: e.role, first: e.ts, last: e.ts, txs: [] }
    a.eth += e.eth; a.count += 1; a.share = Math.min(1, a.share + (e.share || 0)); a.first = Math.min(a.first, e.ts); a.last = Math.max(a.last, e.ts)
    if (e.tx && a.txs.length < 5) a.txs.push(e.tx)
    if (e.role === 'fwd') a.role = 'fwd'
    m.set(k, a)
  }
  return [...m.values()]
}
