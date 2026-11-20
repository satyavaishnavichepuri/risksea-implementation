// Thin client for the FastAPI backend (proxied under /api in dev, served from the same origin in production).
async function j(url, opts) {
  const r = await fetch(url, opts)
  if (!r.ok) {
    let msg = r.statusText
    try { msg = (await r.json()).detail || msg } catch { /* not json */ }
    throw new Error(msg)
  }
  return r.json()
}

export const api = {
  meta: () => j('/api/meta'),
  cases: () => j('/api/cases'),
  architecture: () => j('/api/architecture'),
  caseTrace: (caseId, engine) => j(`/api/cases/${caseId}/trace/${engine}`),
  compare: (caseId) => j(`/api/cases/${caseId}/compare`),
  startTrace: (body) => j('/api/trace', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }),
}

/** Opens the server-sent-event stream of a job. Calls onEvent for each engine event, onDone(result) or onError(err). */
export function streamJob(jobId, { onEvent, onDone, onError }) {
  const es = new EventSource(`/api/jobs/${jobId}/stream`)
  es.onmessage = (m) => {
    const msg = JSON.parse(m.data)
    if (msg.type === 'event') onEvent(msg)
    else if (msg.type === 'result') { es.close(); onDone(msg.result) }
    else if (msg.type === 'error') { es.close(); onError(msg) }
  }
  es.onerror = () => { es.close(); onError({ code: 'stream', message: 'The connection to the backend was lost.' }) }
  return () => es.close()
}
