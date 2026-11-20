import { motion } from 'framer-motion'
import { PageHead, StatusChip } from '../components/ui'

// Research gaps between a risk-scoring baseline (our RiskSEA reproduction) and what the problem statement needs.
const GAPS = [
  { t: 'Scoring is not tracing', gap: 'A risk model says “this wallet looks risky”. An investigator needs “where did the money go, and which exchange received it?”. These are different jobs.',
    ev: 'The book separates proactive alerting from remedial tracing and treats tracing as a graph-search problem (Ch. 8).',
    we: 'A tracing engine that follows the funds and attributes the receiving service. Scoring stays a plug-in.' },
  { t: 'Summarised graphs lose what tracing needs', gap: 'Our baseline collapsed transactions into undirected counts. Following money needs direction, amount, timing and token swaps.',
    ev: 'These are exactly the four strategies behind the book’s tracing method.',
    we: 'Every transfer is kept. The search only follows outflows after the funds arrived and splits funds by amount.' },
  { t: 'Embeddings are slow and weak at tracing', gap: 'Graph-embedding methods need the whole graph and rank similar-looking accounts, not accounts that actually received the money.',
    ev: 'In the book’s 20-case test, embedding methods ran over 24 hours or found almost nothing, while the ranked local search found 92% of targets reviewing about 870 accounts.',
    we: 'A local search that starts at the reported wallet; its cost does not depend on the size of the chain.' },
  { t: 'Neighbours are often different kinds of account', gap: 'Scam wallets sit next to exchanges and ordinary users, but node2vec assumes neighbours are alike.',
    ev: 'The book measures an edge homophily of only 0.28 on Ethereum. Our reproduction found node2vec lost to plain behaviour features. This link is plausible, not proven.',
    we: 'Avoids averaging over neighbours; uses explicit, explainable rules for what each account is.' },
  { t: 'One chain, old data, no live feed', gap: 'Our baseline was Ethereum 2018 in batch. Real complaints are recent, can span chains, and need fresh data.',
    ev: 'The book chapters we read cover single-chain, account-based methods; cross-chain and bridge tracing is not covered.',
    we: 'Ethereum ETH transfers from public data with a lag, behind an adapter interface for other chains. Cross-chain is open research.' },
  { t: 'Finding the exchange needs labels that mostly do not exist', gap: 'Public lists name a few hundred exchange wallets. The deposit addresses victims’ money actually lands in are almost never labeled.',
    ev: 'Deposit addresses sweep into an exchange hot wallet; this pattern is the standard way to attribute them (Ch. 1).',
    we: 'A label store with provenance, plus a sweep rule that infers deposit addresses and a guard that flags unlabeled busy hubs.' },
  { t: 'Smart contracts break the trail', gap: 'Funds that enter a DEX or mixer contract mix with others; the way out is an internal transfer, not a normal one.',
    ev: 'Our Cryptopia trace ends at the EtherDelta contract. The book’s tool models swaps explicitly to continue past them.',
    we: 'Stops there and says so. Following DEX deposits to withdrawals through internal transfers is the first roadmap item.' },
  { t: 'A score is not evidence', gap: 'Law enforcement and exchanges act on transaction hashes, timelines and amounts, not on probabilities.',
    ev: 'The book evaluates tracing by recall of real target accounts and by how few accounts an auditor must review.',
    we: 'Each finding carries a path of real transactions, a confidence level, and the limits of what is known.' },
]

const NEXT = [
  ['DEX pass-through', 'Match deposits and withdrawals through contracts using internal transfers, so the Cryptopia trace continues to Yobit and OKEx as the book reports.'],
  ['ERC-20 and stablecoins', 'Follow USDT and other tokens, not only ETH.'],
  ['More chains', 'Adapters for Tron, BNB Chain and Bitcoin behind the same transfer interface.'],
  ['Risk model plug-in', 'Wire in the RiskSEA baseline, then heterophily-aware or unsupervised risk rating.'],
  ['Watchlist and alerts', 'Needs a live feed (node, RPC or an API key); a replay demo works with the cached cases.'],
  ['Integrations', 'SAHYOG and NCRP: specification unknown, so a plain JSON or CSV in and out until it is clarified.'],
  ['Full benchmark', 'Run the book’s 20 cases to compare strategies where they actually separate.'],
]

export default function Roadmap({ arch }) {
  const req = {}
  arch.modules.forEach((m) => m.ps.forEach((p) => { (req[p] ||= []).push(m) }))
  const rank = { live: 3, partial: 2, planned: 1 }
  const rows = Object.entries(req).map(([p, ms]) => ({ p, ms, best: ms.reduce((a, m) => (rank[m.status] > rank[a] ? m.status : a), 'planned') }))
    .sort((a, b) => rank[b.best] - rank[a.best] || a.p.localeCompare(b.p))

  return (
    <div>
      <PageHead title="Research gaps and roadmap">
        Why a risk-scoring baseline is not enough for this problem, in plain words, what each gap means for the prototype, and what is still
        missing against the problem statement.
      </PageHead>

      <h3 className="h3">Research gaps</h3>
      <div className="grid2">
        {GAPS.map((g, i) => (
          <motion.div key={g.t} className="glass gapcard" initial={{ opacity: 0, y: 14 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * 0.05 }} whileHover={{ y: -3 }}>
            <div className="row" style={{ marginBottom: 8 }}><div className="gapno">{i + 1}</div><h3 style={{ margin: 0 }}>{g.t}</h3></div>
            <div className="kv">
              <b>The gap</b><span>{g.gap}</span>
              <b>Evidence</b><span className="muted">{g.ev}</span>
              <b>This prototype</b><span>{g.we}</span>
            </div>
          </motion.div>
        ))}
      </div>

      <h3 className="h3" style={{ margin: '30px 0 12px' }}>Coverage of the problem statement</h3>
      <div className="glass" style={{ overflow: 'hidden' }}>
        <table className="tbl">
          <thead><tr><th>Requirement</th><th>Status</th><th>Served by</th></tr></thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.p}><td>{r.p}</td><td><StatusChip s={r.best} /></td><td className="muted small">{r.ms.map((m) => m.label).join(' · ')}</td></tr>
            ))}
          </tbody>
        </table>
      </div>

      <h3 className="h3" style={{ margin: '30px 0 12px' }}>What comes next</h3>
      <div className="glass pad">
        <div className="timeline">
          {NEXT.map(([t, d]) => (
            <div key={t} className="tlitem"><b>{t}</b><div className="muted small" style={{ lineHeight: 1.55, maxWidth: 780 }}>{d}</div></div>
          ))}
        </div>
      </div>
    </div>
  )
}
