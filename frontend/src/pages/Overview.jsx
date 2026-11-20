import { motion } from 'framer-motion'
import { ArrowRight, Fingerprint, GitBranch, SearchCheck, ShieldCheck } from 'lucide-react'
import { Stat } from '../components/ui'
import { KIND_COLOR, pct } from '../util'

const STEPS = [
  { icon: Fingerprint, t: 'Report a wallet', d: 'A victim-reported address and the time of the incident open a case.' },
  { icon: GitBranch, t: 'Follow the money', d: 'A ranked, time-respecting search follows outflows hop by hop, splitting the funds by amount.' },
  { icon: SearchCheck, t: 'Stop at a service', d: 'It stops at a labeled exchange, an inferred exchange deposit, a mixer, a DEX or a busy hub, and says which.' },
  { icon: ShieldCheck, t: 'Hand over evidence', d: 'A path of real transactions with hashes, amounts and times, plus the limits of what is known.' },
]

export default function Overview({ cases, meta, openLab, setPage }) {
  const cp = cases.find((c) => c.id === 'cryptopia_2019')
  const ku = cases.find((c) => c.id === 'kucoin_2020')
  const ph = cases.find((c) => c.id === 'phishing_2018')
  const phTop = ph?.headline?.terminals?.[0]
  return (
    <div>
      <motion.div className="glass hero" initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.55 }}>
        <div className="eyebrow">Crypto fraud attribution · working prototype</div>
        <h1>From a victim’s wallet to the <span className="grad">exchange that can freeze it</span></h1>
        <p>
          Victims report suspect wallet addresses; investigators lose days tracing where the money went. CryptoTrace follows the
          funds automatically, finds the first service that received them, and shows every step as evidence, including when it
          has to stop and why.
        </p>
        <div className="row wrap">
          <button className="btn primary" onClick={() => openLab('phishing_2018')}>Open the Trace Lab <ArrowRight size={16} /></button>
          <button className="btn" onClick={() => setPage('architecture')}>See how the system works</button>
          <button className="btn ghost" onClick={() => setPage('roadmap')}>Research gaps & roadmap</button>
        </div>
        <svg width="100%" height="120" viewBox="0 0 900 120" preserveAspectRatio="none" style={{ position: 'absolute', right: 0, bottom: 0, opacity: 0.5, pointerEvents: 'none' }}>
          {[0, 1, 2].map((i) => (
            <motion.path key={i} d={`M0 ${90 - i * 8} C 200 ${20 + i * 18}, 380 ${110 - i * 10}, 560 ${50 + i * 6} S 820 ${30 + i * 12}, 900 ${60 - i * 5}`}
              fill="none" stroke={i === 1 ? '#a78bfa' : '#22d3ee'} strokeWidth="1.5" strokeDasharray="6 10"
              animate={{ strokeDashoffset: [0, -64] }} transition={{ repeat: Infinity, duration: 3 + i, ease: 'linear' }} />
          ))}
        </svg>
      </motion.div>

      <div className="grid4" style={{ marginTop: 18 }}>
        <Stat value={cp?.headline ? pct(cp.headline.terminals[0].share, 1) : '—'} label="of the stolen ETH in the Cryptopia case followed to its destination (EtherDelta DEX), in 6 search rounds" delay={0.1} color={KIND_COLOR.dex} />
        <Stat value={ku?.headline ? pct(ku.headline.terminals[0].share, 1) : '—'} label="of the KuCoin hack followed into the Tornado Cash pool in 3 rounds, where tracing correctly stops" delay={0.18} color={KIND_COLOR.mixer} />
        <Stat value="≈ $0.06" label="BigQuery list-price cost of the first full Cryptopia trace. Re-runs and parameter changes hit the cache and are free." delay={0.26} />
        <Stat value={phTop ? `${phTop.count} → 1` : '—'} label={phTop ? `deposit addresses traced from one phishing-labeled wallet into a single exchange (${phTop.name}, ${pct(phTop.share, 0)} of funds, inferred). Blind depth-2 BFS finds none.` : ''} delay={0.34} color={KIND_COLOR.exchange_deposit} />
      </div>

      <h3 className="h3" style={{ margin: '30px 0 12px' }}>How a trace works</h3>
      <div className="grid4">
        {STEPS.map((s, i) => (
          <motion.div key={s.t} className="glass stepcard" initial={{ opacity: 0, y: 14 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.15 + i * 0.09 }} whileHover={{ y: -4 }}>
            <div className="row" style={{ justifyContent: 'space-between', marginBottom: 12 }}>
              <s.icon size={22} color="#22d3ee" /><span className="stepno">0{i + 1}</span>
            </div>
            <b>{s.t}</b>
            <p className="muted small" style={{ margin: '6px 0 0', lineHeight: 1.55 }}>{s.d}</p>
          </motion.div>
        ))}
      </div>

      <h3 className="h3" style={{ margin: '30px 0 12px' }}>Cases: two documented in the book’s Chapter 8, one real attribution example</h3>
      <div className="grid2">
        {cases.map((c) => (
          <motion.button key={c.id} className="glass pad casecard" style={{ padding: 18 }} whileHover={{ y: -3 }} onClick={() => openLab(c.id)}>
            <div className="row" style={{ justifyContent: 'space-between' }}>
              <b style={{ fontSize: 16 }}>{c.title}</b><ArrowRight size={16} color="#22d3ee" />
            </div>
            <p className="muted small" style={{ lineHeight: 1.55, margin: '8px 0 12px' }}>{c.story}</p>
            <div className="row wrap">
              {c.headline?.terminals.slice(0, 1).map((t) => (
                <span key={t.name} className="chip" style={{ color: KIND_COLOR[t.kind], borderColor: 'currentColor' }}>Found: {t.name}{t.count > 1 ? ` (${t.count} addresses)` : ''} · {pct(t.share, 1)}</span>
              ))}
              <span className="chip">{c.headline?.rounds} rounds · {c.headline?.nodes} accounts in the graph</span>
              <span className="chip">first fetch {c.first_run_gib} GiB</span>
            </div>
          </motion.button>
        ))}
      </div>

      <div className="glass pad" style={{ marginTop: 22, lineHeight: 1.65 }}>
        <b>What this prototype is, and is not.</b>{' '}
        <span className="muted">
          It traces Ethereum ETH transfers from public BigQuery data, validated on two documented cases, plus one real example without a published answer (shown as a lead, not a verdict). It does not yet follow funds
          through DEX contracts, ERC-20 tokens, other chains or bridges, and it is not real-time (public data has a lag). Those gaps and
          the plan to close them are on the Gaps page.
        </span>
      </div>
    </div>
  )
}
