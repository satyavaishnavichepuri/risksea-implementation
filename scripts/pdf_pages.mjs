// Renders chosen pages of a PDF to PNG through Chrome's built-in PDF viewer (for visually checking the report).
// Usage: node scripts/pdf_pages.mjs <file.pdf> <out_dir> <page> [<page> ...]
import { spawn } from 'node:child_process'
import { mkdirSync, writeFileSync, mkdtempSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { pathToFileURL } from 'node:url'

const [pdf, out, ...pages] = process.argv.slice(2)
mkdirSync(out, { recursive: true })
const CHROME = process.env.CHROME || 'C:/Program Files/Google/Chrome/Application/chrome.exe'
const PORT = 9444
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
const chrome = spawn(CHROME, ['--headless=new', `--remote-debugging-port=${PORT}`, `--user-data-dir=${mkdtempSync(join(tmpdir(), 'pdfshot-'))}`,
  '--hide-scrollbars', '--no-first-run', '--disable-gpu', '--window-size=900,1200', 'about:blank'], { stdio: 'ignore' })
let targets
for (let i = 0; i < 60; i++) { try { targets = await (await fetch(`http://127.0.0.1:${PORT}/json`)).json(); if (targets.length) break } catch {} await sleep(250) }
const ws = new WebSocket(targets.find((t) => t.type === 'page').webSocketDebuggerUrl)
await new Promise((r) => (ws.onopen = r))
let id = 0; const pending = new Map()
ws.onmessage = (m) => { const d = JSON.parse(m.data); if (d.id && pending.has(d.id)) { pending.get(d.id)(d); pending.delete(d.id) } }
const send = (method, params = {}) => new Promise((res) => { const i = ++id; pending.set(i, res); ws.send(JSON.stringify({ id: i, method, params })) })
await send('Page.enable')
await send('Emulation.setDeviceMetricsOverride', { width: 900, height: 1250, deviceScaleFactor: 1, mobile: false })
const url = pathToFileURL(resolve(pdf)).href
for (const p of pages) {
  await send('Page.navigate', { url: 'about:blank' }); await sleep(300)
  await send('Page.navigate', { url: `${url}?r=${p}#page=${p}&view=FitH&toolbar=0&navpanes=0` })
  await sleep(3500)
  const r = await send('Page.captureScreenshot', { format: 'png' })
  writeFileSync(join(out, `p${String(p).padStart(3, '0')}.png`), Buffer.from(r.result.data, 'base64')); console.log('saved page', p)
}
ws.close(); chrome.kill(); process.exit(0)
