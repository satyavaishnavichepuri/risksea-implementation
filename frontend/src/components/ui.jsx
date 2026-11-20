import { motion } from 'framer-motion'

export const Chip = ({ kind, children, style }) => <span className={`chip ${kind || ''}`} style={style}>{children}</span>

export const StatusChip = ({ s }) => <Chip kind={s}>{s === 'live' ? '● live' : s === 'partial' ? '◐ partial' : '○ planned'}</Chip>

export const Stat = ({ value, label, delay = 0, color }) => (
  <motion.div className="glass stat" initial={{ opacity: 0, y: 14 }} animate={{ opacity: 1, y: 0 }} transition={{ delay, duration: 0.5 }}>
    <div className="v" style={color ? { color } : undefined}>{value}</div>
    <div className="l">{label}</div>
  </motion.div>
)

export const Slider = ({ label, value, onChange, min, max, step, fmt }) => (
  <div className="sl">
    <label><span>{label}</span><b>{fmt ? fmt(value) : value}</b></label>
    <input type="range" min={min} max={max} step={step} value={value} onChange={(e) => onChange(parseFloat(e.target.value))} />
  </div>
)

export const Toggle = ({ label, on, onChange, disabled, hint }) => (
  <div className="switch" title={hint}>
    <span>{label}</span>
    <button className={`tgl ${on ? 'on' : ''}`} disabled={disabled} onClick={() => onChange(!on)} aria-pressed={on} />
  </div>
)

export const Seg = ({ options, value, onChange }) => (
  <div className="seg">
    {options.map((o) => (
      <button key={o.id} className={value === o.id ? 'on' : ''} onClick={() => onChange(o.id)}>{o.label}</button>
    ))}
  </div>
)

export const PageHead = ({ title, children }) => (
  <motion.div className="pagehead" initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} style={{ marginBottom: 22 }}>
    <h1>{title}</h1>
    <p>{children}</p>
  </motion.div>
)

export const Spinner = () => (
  <svg className="spin" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3"><circle cx="12" cy="12" r="9" opacity=".25" /><path d="M21 12a9 9 0 0 0-9-9" /></svg>
)
