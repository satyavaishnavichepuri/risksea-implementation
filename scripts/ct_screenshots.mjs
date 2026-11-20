// Captures every screen of the CryptoTrace UI for the project report (Chrome DevTools Protocol, no extra packages).
// Usage: node scripts/ct_screenshots.mjs <out_dir> [base_url]
// Needs the API+UI running (uvicorn cryptotrace.api:app --app-dir src --port 8000) and Chrome installed.
import { spawn } from 'node:child_process'
import { mkdirSync, writeFileSync, mkdtempSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

const OUT = process.argv[2] || 'shots'
const BASE = process.argv[3] || 'http://127.0.0.1:8000'
const CHROME = process.env.CHROME || 'C:/Program Files/Google/Chrome/Application/chrome.exe'
const PORT = 9333
mkdirSync(OUT, { recursive: true })
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

const chrome = spawn(CHROME, ['--headless=new', `--remote-debugging-port=${PORT}`, `--user-data-dir=${mkdtempSync(join(tmpdir(), 'ctshot-'))}`,
  '--hide-scrollbars', '--no-first-run', '--disable-gpu', 'about:blank'], { stdio: 'ignore' })
let targets
for (let i = 0; i < 60; i++) { try { targets = await (await fetch(`http://127.0.0.1:${PORT}/json`)).json(); if (targets.length) break } catch {} await sleep(250) }
const page = targets.find((t) => t.type === 'page')
const ws = new WebSocket(page.webSocketDebuggerUrl)
await new Promise((r) => (ws.onopen = r))
let id = 0; const pending = new Map()
ws.onmessage = (m) => { const d = JSON.parse(m.data); if (d.id && pending.has(d.id)) { pending.get(d.id)(d); pending.delete(d.id) } }
const send = (method, params = {}) => new Promise((res, rej) => {
  const i = ++id; pending.set(i, res); ws.send(JSON.stringify({ id: i, method, params }))
  setTimeout(() => { if (pending.has(i)) { pending.delete(i); rej(new Error('timeout ' + method)) } }, 30000)
})
const ev = async (expr) => { const r = await send('Runtime.evaluate', { expression: expr, awaitPromise: true, returnByValue: true }); return r.result?.result?.value }

const viewport = (w, h, scale = 1.5) => send('Emulation.setDeviceMetricsOverride', { width: w, height: h, deviceScaleFactor: scale, mobile: false })
const shot = async (name) => {
  const r = await send('Page.captureScreenshot', { format: 'png' })
  writeFileSync(join(OUT, name + '.png'), Buffer.from(r.result.data, 'base64')); console.log('saved', name)
}
// full-height capture: grow the viewport to the tallest scrollable region, then restore
const fullShot = async (name, w = 1440) => {
  const h = await ev(`(() => { let m = document.documentElement.scrollHeight; for (const e of document.querySelectorAll('*')) { const s = getComputedStyle(e); if ((s.overflowY === 'auto' || s.overflowY === 'scroll') && e.scrollHeight > e.clientHeight) m = Math.max(m, e.scrollHeight + e.getBoundingClientRect().top) } return Math.min(Math.ceil(m), 5200) })()`)
  await viewport(w, h); await sleep(900); await shot(name); await viewport(w, 900)
}
const clickText = (text, sel = 'button, [role=button], a') => ev(`(() => { const els = [...document.querySelectorAll(${JSON.stringify(sel)})].filter(e => e.textContent.trim().includes(${JSON.stringify(text)})); els.sort((a,b)=>a.textContent.length-b.textContent.length); if(!els.length) return false; els[0].click(); return true })()`)
const clickExact = (text, sel = 'button') => ev(`(() => { const e = [...document.querySelectorAll(${JSON.stringify(sel)})].find(e => e.textContent.trim() === ${JSON.stringify(text)}); if(!e) return false; e.click(); return true })()`)
const scrub = (v) => ev(`(() => { const r = document.querySelector('.scrub'); const max = +r.max; const val = ${JSON.stringify(v)} === 'max' ? max : ${JSON.stringify(v)}; const set = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set; set.call(r, String(val)); r.dispatchEvent(new Event('input', { bubbles: true })); return max })()`)
const setInput = (sel, value, idx = 0) => ev(`(() => { const e = document.querySelectorAll(${JSON.stringify(sel)})[${idx}]; const set = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set; set.call(e, ${JSON.stringify(value)}); e.dispatchEvent(new Event('input', { bubbles: true })); e.dispatchEvent(new Event('change', { bubbles: true })); return true })()`)
const scrollTo = (sel, block = 'start') => ev(`(() => { const e = document.querySelector(${JSON.stringify(sel)}); if (!e) return false; e.scrollIntoView({ block: ${JSON.stringify(block)} }); return true })()`)
const scrollCols = (px) => ev(`(() => { document.querySelectorAll('.col').forEach(c => c.scrollTop = ${px}); return true })()`)

await send('Page.enable'); await send('Runtime.enable'); await viewport(1440, 900)
await send('Page.navigate', { url: BASE + '/' }); await sleep(3500)

// ---------- overview
await shot('01_overview_top'); await fullShot('02_overview_full')
// ---------- system
await clickText('System', '.nav button, nav button, aside button'); await sleep(1500); await shot('03_system_idle'); await fullShot('04_system_full')
await clickText('Play a trace'); await sleep(5000); await shot('05_system_playing'); await sleep(9000); await shot('06_system_playing_late')
// ---------- trace lab: phishing (TTR default)
await clickText('Trace Lab', 'aside button, nav button, .nav button'); await sleep(2500)
await clickExact('TTR-lite'); await sleep(2500)
await scrub(-1); await sleep(1200); await shot('13_lab_phishing_start')
for (const [s, n] of [[1, '14_lab_phishing_round1'], [2, '15_lab_phishing_round2'], [3, '16_lab_phishing_round3']]) { await scrub(s); await sleep(2800); await shot(n) }
await scrub('max'); await sleep(4500); await shot('17_lab_phishing_final')
await scrollTo('.term.on', 'start'); await sleep(900); await shot('18_lab_phishing_group_expanded')
await scrollTo('.pathrow', 'start'); await sleep(900); await shot('19_lab_phishing_paths')
await clickText('Inside the engine'); await sleep(1200); await shot('20_lab_phishing_engine_tab')
await clickExact('Account', 'button, [role=tab], div'); await sleep(1200); await shot('21_lab_phishing_account_tab')
await clickText('Findings'); await sleep(600)
await scrollCols(9999); await sleep(800); await shot('22_lab_parameters_panel'); await scrollCols(0)
await viewport(1280, 720); await sleep(1500); await shot('23_lab_phishing_1280x720'); await viewport(1440, 900)
// engines
await clickExact('Haircut taint'); await sleep(2500); await scrub('max'); await sleep(4500); await shot('24_lab_phishing_haircut_final')
await clickExact('Blind BFS'); await sleep(2500); await scrub('max'); await sleep(4500); await shot('25_lab_phishing_bfs_final')
await clickExact('TTR-lite'); await sleep(2000)
// what-if: change beta and re-run on the cached case
await setInput('input[type=range]:not(.scrub)', '3', 3); await sleep(500); await clickText('Run trace'); await sleep(5000); await scrub('max'); await sleep(3500); await scrollCols(9999); await sleep(600); await shot('26_lab_whatif_3rounds'); await scrollCols(0)
// ---------- kucoin
await clickText('KuCoin exchange hack', '.casecard'); await sleep(3000); await scrub(1); await sleep(2500); await shot('27_lab_kucoin_round1')
await scrub('max'); await sleep(4500); await shot('28_lab_kucoin_final'); await scrollTo('.term.on', 'start'); await sleep(900); await shot('29_lab_kucoin_mixer_expanded')
// ---------- cryptopia
await clickText('Cryptopia exchange hack', '.casecard'); await sleep(3000); await scrub(2); await sleep(2500); await shot('30_lab_cryptopia_mid')
await scrub('max'); await sleep(4500); await shot('31_lab_cryptopia_final'); await scrollTo('.term.on', 'start'); await sleep(900); await shot('32_lab_cryptopia_dex_expanded')
await clickExact('Blind BFS'); await sleep(2500); await scrub('max'); await sleep(4500); await shot('33_lab_cryptopia_bfs_final')
// ---------- any wallet
await clickExact('Any wallet'); await sleep(1200); await shot('34_lab_anywallet_empty')
await setInput('input[type=text]', '0x' + 'ab'.repeat(20)); await setInput('input[type=date]', '2020-09-25', 0); await setInput('input[type=date]', '2020-10-05', 1); await sleep(500)
await clickText('Run trace'); await sleep(3500); await shot('35_lab_anywallet_cache_miss')
// ---------- compare (three cases)
await clickText('Compare', 'aside button, nav button, .nav button'); await sleep(2000)
for (const [t, n] of [['Phishing', '36_compare_phishing'], ['KuCoin', '37_compare_kucoin'], ['Cryptopia', '38_compare_cryptopia']]) { await clickText(t, 'button'); await sleep(1800); await shot(n) }
await clickText('Phishing', 'button'); await sleep(1500); await fullShot('39_compare_full')
// ---------- gaps
await clickText('Gaps', 'aside button, nav button, .nav button'); await sleep(2000); await shot('40_gaps_top'); await fullShot('41_gaps_full')
// ---------- report (needs a trace loaded in the lab: the last lab run is the cache-miss, so reload a case first)
await clickText('Trace Lab', 'aside button, nav button, .nav button'); await sleep(2000)
await clickExact('Benchmark'); await sleep(800); await clickText('Phishing-labeled wallet', '.casecard'); await sleep(3000); await clickExact('TTR-lite'); await sleep(2500)
await clickText('Report', 'aside button, nav button, .nav button'); await sleep(2000); await shot('42_report_top'); await fullShot('43_report_full')
// ---------- tablet width
await viewport(820, 1100); await clickText('Overview', 'aside button, nav button, .nav button'); await sleep(2000); await shot('44_overview_tablet')

ws.close(); chrome.kill(); process.exit(0)
