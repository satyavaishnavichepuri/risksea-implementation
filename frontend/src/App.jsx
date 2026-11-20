import { useEffect, useState } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import { BarChart3, FileText, LayoutDashboard, Map as MapIcon, Network, Radar, Waypoints } from 'lucide-react'
import { api } from './api'
import Overview from './pages/Overview'
import Architecture from './pages/Architecture'
import TraceLab from './pages/TraceLab'
import Compare from './pages/Compare'
import Roadmap from './pages/Roadmap'
import Report from './pages/Report'

const PAGES = [
  { id: 'overview', label: 'Overview', icon: LayoutDashboard },
  { id: 'architecture', label: 'System', icon: Network },
  { id: 'lab', label: 'Trace Lab', icon: Radar },
  { id: 'compare', label: 'Compare', icon: BarChart3 },
  { id: 'roadmap', label: 'Gaps', icon: MapIcon },
  { id: 'report', label: 'Report', icon: FileText },
]

export default function App() {
  const [page, setPage] = useState(() => (location.hash.slice(1) || 'overview'))
  const [boot, setBoot] = useState({ loading: true })
  const [labCase, setLabCase] = useState(null)       // case chosen from another page
  const [trace, setTrace] = useState(null)           // latest trace result, shared with the report page

  useEffect(() => { if (location.hash.slice(1) !== page) location.hash = page }, [page])
  useEffect(() => {                                // keep the page in sync with the URL (deep links, back button)
    const onHash = () => setPage(location.hash.slice(1) || 'overview')
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [])
  useEffect(() => {
    Promise.all([api.meta(), api.cases(), api.architecture()])
      .then(([meta, cases, arch]) => setBoot({ meta, cases, arch }))
      .catch((e) => setBoot({ error: e.message }))
  }, [])

  const openLab = (caseId) => { setLabCase(caseId); setPage('lab') }

  let body
  if (boot.loading) body = <div className="empty">Connecting to the backend…</div>
  else if (boot.error) body = (
    <div className="empty"><div>
      <h2>Backend not reachable</h2>
      <p className="muted">{boot.error}</p>
      <p className="muted small">Start it with: <code>uvicorn cryptotrace.api:app --app-dir src --port 8000</code></p>
    </div></div>
  )
  else {
    const props = { ...boot, openLab, setPage }
    body = (
      <AnimatePresence mode="wait">
        <motion.div key={page} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }} transition={{ duration: 0.22 }}>
          {page === 'overview' && <div className="page"><Overview {...props} /></div>}
          {page === 'architecture' && <div className="page"><Architecture {...props} /></div>}
          {page === 'lab' && <TraceLab {...props} initialCase={labCase} onResult={setTrace} />}
          {page === 'compare' && <div className="page"><Compare {...props} /></div>}
          {page === 'roadmap' && <div className="page"><Roadmap {...props} /></div>}
          {page === 'report' && <div className="page"><Report {...props} trace={trace} openLab={openLab} /></div>}
        </motion.div>
      </AnimatePresence>
    )
  }

  return (
    <div className="shell">
      <nav className="side noprint">
        <div className="logo"><Waypoints size={22} color="#04101a" strokeWidth={2.6} /></div>
        {PAGES.map((p) => (
          <button key={p.id} className={`navbtn ${page === p.id ? 'on' : ''}`} onClick={() => setPage(p.id)} title={p.label}>
            <p.icon size={20} /> {p.label}
          </button>
        ))}
      </nav>
      <main className="main">{body}</main>
    </div>
  )
}
