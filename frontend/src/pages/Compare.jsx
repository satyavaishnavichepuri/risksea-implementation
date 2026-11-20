import { useEffect, useState } from 'react'
import { motion } from 'framer-motion'
import { Bar, BarChart, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { Chip, PageHead, Seg } from '../components/ui'
import { api } from '../api'

const COLORS = { ttr: '#22d3ee', haircut: '#a78bfa', bfs: '#fb7185' }

// Chapter 8, Table 8.2 of the book: 20 real cases across Ethereum, BNB Chain and Polygon (published numbers, not ours)
const BOOK = [
  ['TRacer (ranked local search)', '92.31', '0.87', '5.05', '0.65', true],
  ['APPR (personalised PageRank)', '71.92', '0.66', '3.60', '0.51'],
  ['BFS (depth 2)', '77.02', '52.50', '2.00', '0.05'],
  ['Poison taint (depth 2)', '70.06', '41.45', '2.00', '0.03'],
  ['Haircut taint', '58.85', '10.35', '4.15', '0.01'],
  ['Label propagation (LPA)', '67.76', '682.30', '10.35', '1.76'],
  ['Louvain communities', '51.27', '111.84', '9.75', '1.69'],
  ['Ethprivacy (features)', '0.01', '1.89', '1.10', '1.78'],
  ['Metapath2Vec / Ethprivacy (embeddings)', '—', '—', '—', '> 24'],
]

function MiniBar({ title, data, dataKey, hint }) {
  return (
    <div className="glass pad">
      <div className="h3" style={{ marginBottom: 2 }}>{title}</div>
      <div className="muted tiny" style={{ marginBottom: 8 }}>{hint}</div>
      <div style={{ height: 150 }}>
        <ResponsiveContainer>
          <BarChart data={data} margin={{ left: -18, right: 6, top: 6 }}>
            <XAxis dataKey="name" tick={{ fill: '#8b97ad', fontSize: 11 }} axisLine={false} tickLine={false} />
            <YAxis tick={{ fill: '#8b97ad', fontSize: 11 }} axisLine={false} tickLine={false} allowDecimals={false} />
            <Tooltip cursor={{ fill: 'rgba(255,255,255,.04)' }} contentStyle={{ background: '#0b1120', border: '1px solid rgba(255,255,255,.1)', borderRadius: 10, fontSize: 12 }} />
            <Bar dataKey={dataKey} radius={[8, 8, 0, 0]} animationDuration={700}>
              {data.map((d) => <Cell key={d.engine} fill={COLORS[d.engine]} />)}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}

export default function Compare({ cases }) {
  const [caseId, setCaseId] = useState(cases.some((c) => c.id === 'phishing_2018') ? 'phishing_2018' : cases[0].id)
  const [data, setData] = useState(null)
  useEffect(() => { setData(null); api.compare(caseId).then(setData) }, [caseId])

  const rows = data?.rows.map((r) => ({ ...r, name: r.engine_label.split(' ')[0] })) || []
  const same = rows.length > 1 && new Set(rows.map((r) => r.top_exchange_by_share || r.nearest_exchange || r.terminals)).size === 1
  const bfs = rows.find((r) => r.engine === 'bfs')
  const ttr = rows.find((r) => r.engine === 'ttr')
  const bfsBlind = !!bfs && !!ttr && bfs.terminals === 0 && ttr.terminals > 0

  return (
    <div>
      <PageHead title="Does the search strategy matter?">
        The same case traced three ways: our ranked, time-respecting search (TTR-lite), classic taint tracking (Haircut) and a blind
        breadth-first search. The book’s published 20-case benchmark is shown for reference; our three cases are a smoke test, not a replication.
      </PageHead>
      <div style={{ marginBottom: 16 }}>
        <Seg options={cases.map((c) => ({ id: c.id, label: c.title.split('(')[0].trim() }))} value={caseId} onChange={setCaseId} />
      </div>

      {data && (
        <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }}>
          <div className="glass" style={{ overflow: 'hidden' }}>
            <table className="tbl">
              <thead><tr>
                <th>Strategy</th><th>Expected destinations found</th><th>Destinations reached</th><th>Accounts to audit</th>
                <th>Transfers considered</th><th>Max depth</th><th>Rounds</th><th>Run time</th>
              </tr></thead>
              <tbody>
                {data.rows.map((r) => (
                  <tr key={r.engine} className={r.engine === 'ttr' ? 'hl' : ''}>
                    <td><span className="dot" style={{ background: COLORS[r.engine], marginRight: 8 }} /><b>{r.engine_label}</b></td>
                    <td>{r.expected_total === 0
                      ? <span className="muted">no published answer</span>
                      : <>{r.expected_hit} of {r.expected_total} {Object.entries(r.found).map(([k, v]) => <Chip key={k} kind={v ? 'live' : ''} style={{ marginLeft: 4 }}>{k} {v ? '✓' : '✗'}</Chip>)}</>}</td>
                    <td>{r.terminals}</td><td>{r.nodes}</td><td>{r.edges_considered}</td><td>{r.depth}</td><td>{r.rounds}</td><td>{r.seconds}s <span className="muted tiny">(cached)</span></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="muted small" style={{ lineHeight: 1.6, margin: '10px 4px 18px' }}>
            {data.case.expected.length
              ? <>Expected destinations come from the book: <b>{data.case.expected.join(' · ')}</b>. Names are matched against the labels we hold, so a destination that is
                not in our label sets (for example EtherDelta before we curated it, or a destination only reachable through a DEX) counts as missed.</>
              : <>This case has no published answer, so there is no recall to report; the table shows what each strategy reaches and how much it has to touch.</>}
            The one-off BigQuery cost of fetching this case was {data.first_run_gib} GiB, shared by all three strategies.
          </p>

          <div className="grid3">
            <MiniBar title="Accounts an investigator must audit" data={rows} dataKey="nodes" hint="Smaller is better at equal results" />
            <MiniBar title="Transfers considered" data={rows} dataKey="edges_considered" hint="Work done by the search" />
            <MiniBar title="Deepest hop reached" data={rows} dataKey="depth" hint="How far downstream it followed the money" />
          </div>

          <div className="glass pad" style={{ marginTop: 16, lineHeight: 1.65 }}>
            <b>Reading this honestly.</b>{' '}
            <span className="muted">
              {bfsBlind
                ? `Here the strategies separate, as the book’s benchmark predicts: the ranked and taint searches reach ${ttr.terminals} destinations, while blind depth-2 BFS reaches none, because the funds only arrive at exchange deposit addresses several hops downstream. This case has no published answer, so read it as an illustration of the gap, not as a measured accuracy. `
                : same
                ? 'On this case all three strategies end at the same destination, because the funds move in a few large chunks. The strategies differ in how much they have to touch to get there, not in the answer. '
                : 'The strategies reach different destinations on this case. '}
              The book’s benchmark is where they separate: blind BFS needs 52,500 accounts reviewed for 77% recall, the ranked search 870 for 92%. Our harness is built to run that
              benchmark; it needs the book’s 20 case files, which we have not obtained.
            </span>
          </div>
        </motion.div>
      )}

      <h3 className="h3" style={{ margin: '28px 0 12px' }}>The book’s benchmark (Chapter 8, 20 real cases, published numbers)</h3>
      <div className="glass" style={{ overflow: 'hidden' }}>
        <table className="tbl">
          <thead><tr><th>Method</th><th>Recall of target accounts (%)</th><th>Accounts in output (thousands)</th><th>Tracing depth</th><th>Runtime (hours)</th></tr></thead>
          <tbody>
            {BOOK.map(([m, r, n, d, t, hl]) => (
              <tr key={m} className={hl ? 'hl' : ''}><td><b>{m}</b></td><td>{r}</td><td>{n}</td><td>{d}</td><td>{t}</td></tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="muted small" style={{ margin: '10px 4px', lineHeight: 1.6 }}>
        Embedding-based methods needed more than 24 hours per case and were stopped; feature-based clustering found almost nothing. This is the evidence behind
        choosing a local, ranked, time-respecting search for tracing instead of a learned graph embedding.
      </p>
    </div>
  )
}
