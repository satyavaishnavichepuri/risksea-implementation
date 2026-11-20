import { Printer, Radar } from 'lucide-react'
import { KIND_NAME, etherscanTx, fmtDate, fmtDay, fmtEth, groupTerminals, pct } from '../util'

const TAGS = { zero_out: 'Zero-out account', fan_out: 'Fan-out', fan_in: 'Fan-in', peel: 'Peeling chain', fast_hop: 'Fast hop' }

function summary(r) {
  const t = groupTerminals(r.terminals)[0]
  if (!t) return 'No destination was reached within the window and thresholds.'
  const n = t.members.length
  const target = n > 1 ? `${n} addresses of ${t.name}` : t.name
  const where = `${pct(t.share, 1)} of the traced funds (about ${fmtEth(t.eth_est)} ETH) reached ${target} after ${t.depth} hops`
  if (t.kind === 'exchange')return `${where}. This is a labeled exchange: send a freeze and KYC request referencing the evidence path below.`
  if (t.kind === 'exchange_deposit') return `${where}. This is an exchange deposit address inferred by the sweep rule (medium confidence): ask the exchange to confirm and freeze.`
  if (t.kind === 'mixer') return `${where}. A mixer breaks the on-chain trail; further tracing is not possible by this method.`
  if (t.kind === 'dex') return `${where}. This is a DEX contract; funds are pooled and the exit is an internal transfer this system cannot yet follow.`
  return `${where}. The destination is an unlabeled high-activity service and needs manual review.`
}

export default function Report({ trace, meta, openLab }) {
  if (!trace) {
    return (
      <div className="glass pad" style={{ maxWidth: 640, margin: '80px auto', textAlign: 'center' }}>
        <h2>No trace to report yet</h2>
        <p className="muted">Run a trace in the Trace Lab and its findings appear here as a printable investigator report.</p>
        <button className="btn primary" onClick={() => openLab('phishing_2018')}><Radar size={15} /> Open the Trace Lab</button>
      </div>
    )
  }
  const r = trace
  const tagged = r.nodes.filter((n) => n.tags.length)
  const groups = groupTerminals(r.terminals)
  return (
    <div>
      <div className="row noprint" style={{ justifyContent: 'flex-end', marginBottom: 14 }}>
        <button className="btn primary" onClick={() => window.print()}><Printer size={15} /> Print / save as PDF</button>
      </div>
      <div className="report">
        <h1>Fund-flow trace report</h1>
        <div style={{ color: '#6b7280', fontSize: 12 }}>Automated analysis · engine: {r.engine_label} · generated from public on-chain data</div>

        <h2>1. Case</h2>
        <table><tbody>
          <tr><th style={{ width: 150 }}>Reported wallet</th><td className="mono">{r.source}</td></tr>
          <tr><th>Window analysed</th><td>{fmtDay(r.t0)} to {fmtDay(r.t1)}</td></tr>
          <tr><th>Funds leaving the wallet</th><td>{fmtEth(r.summary.source_out_eth)} ETH in the window (external transfers of at least {r.params.min_eth} ETH)</td></tr>
        </tbody></table>

        <h2>2. Summary</h2>
        <div className="box">{summary(r)}</div>

        <h2>3. Destinations reached</h2>
        <table>
          <thead><tr><th>Destination</th><th>Type</th><th>Confidence</th><th>Share</th><th>≈ ETH</th><th>Addresses</th><th>Hops</th></tr></thead>
          <tbody>{groups.map((g) => (
            <tr key={g.key}><td><b>{g.name}</b><div style={{ color: '#6b7280' }}>{g.reason}</div></td>
              <td>{KIND_NAME[g.kind]}</td><td>{g.confidence}</td><td>{pct(g.share, 1)}</td><td>{fmtEth(g.eth_est)}</td><td>{g.members.length}</td><td>{g.depth}</td></tr>
          ))}</tbody>
        </table>

        <h2>3a. Addresses to ask the exchange to freeze</h2>
        {groups.filter((g) => g.kind === 'exchange_deposit' || g.kind === 'exchange').map((g) => (
          <div key={g.key} style={{ marginBottom: 12 }}>
            <b style={{ fontSize: 13 }}>{g.name} ({g.members.length} address{g.members.length === 1 ? '' : 'es'})</b>
            <table>
              <thead><tr><th>Address</th><th>Share</th><th>≈ ETH</th><th>First funds in</th></tr></thead>
              <tbody>{g.members.map((t) => (
                <tr key={t.node}><td className="mono">{t.node}</td><td>{pct(t.share, 1)}</td><td>{fmtEth(t.eth_est)}</td><td>{fmtDate(t.first_ts)}</td></tr>
              ))}</tbody>
            </table>
          </div>
        ))}

        <h2>4. Evidence: transaction paths (largest address of each destination)</h2>
        {groups.map((g) => g.members[0]).map((t) => (
          <div key={t.node} style={{ marginBottom: 14 }}>
            <b style={{ fontSize: 13 }}>Path to {t.name}</b>
            <table>
              <thead><tr><th>#</th><th>From</th><th>To</th><th>ETH</th><th>Time (UTC)</th><th>Transaction hash</th></tr></thead>
              <tbody>{t.path.map((e, i) => (
                <tr key={i}><td>{i + 1}</td><td className="mono">{e.src}</td><td className="mono">{e.dst}</td><td>{fmtEth(e.eth)}</td><td>{fmtDate(e.ts)}</td>
                  <td className="mono">{e.tx ? <a href={etherscanTx(e.tx)} target="_blank" rel="noreferrer">{e.tx}</a> : '—'}</td></tr>
              ))}</tbody>
            </table>
            <div style={{ fontSize: 11.5, color: '#6b7280', marginTop: 4 }}>
              {(() => {
                const into = r.edges.filter((e) => e.dst === t.node && e.role === 'fwd')
                return `The highest-value route is shown. In total ${into.length} transfer${into.length === 1 ? '' : 's'} from the traced accounts entered this destination (about ${fmtEth(into.reduce((a, e) => a + e.eth, 0))} ETH in the window).`
              })()}
            </div>
          </div>
        ))}

        <h2>5. Laundering patterns observed</h2>
        {tagged.length === 0 ? <p>No pattern rules were triggered.</p> : (
          <table>
            <thead><tr><th>Account</th><th>Patterns</th><th>Funds share</th></tr></thead>
            <tbody>{tagged.map((n) => <tr key={n.id}><td className="mono">{n.id}</td><td>{n.tags.map((t) => TAGS[t] || t).join(', ')}</td><td>{pct(n.share, 1)}</td></tr>)}</tbody>
          </table>
        )}

        <h2>6. Method, limits and confidence</h2>
        <ul style={{ fontSize: 12.5, lineHeight: 1.6 }}>
          <li>Method: {r.engine_label}. Parameters α={r.params.alpha}, β={r.params.beta}, ε={r.params.epsilon}, up to {r.params.max_rounds} rounds, time-respecting={String(r.params.time_respecting)}.</li>
          {meta.limits.map((l) => <li key={l}>{l}</li>)}
          {r.warnings.map((w) => <li key={w}>{w}</li>)}
          <li>Labels come from public lists (Etherscan-derived, OFAC, a few curated entries) and may be incomplete or out of date. Exchange deposit addresses are inferred, not confirmed.</li>
          <li>This is an investigative lead, not proof of ownership. Confirm with the receiving service and preserve the cited transactions before any action.</li>
        </ul>
      </div>
    </div>
  )
}
