/**
 * Resolve the backend base URL.
 *
 * Order matters:
 *   1. VITE_API_BASE if the build supplied one (split-service deployments).
 *   2. Otherwise, if the page is NOT on localhost, use the SAME ORIGIN. The
 *      backend serves the built frontend in the single-service deployment, so
 *      the API lives alongside the page.
 *   3. Only when running on localhost does it fall back to the dev server.
 *
 * Step 2 is the important one: defaulting a deployed page to 127.0.0.1 points
 * the browser at the viewer's own machine, which can never work, and produces
 * a "start uvicorn locally" message that makes no sense on a hosted site.
 */
function resolveApiBase() {
  const configured = import.meta.env.VITE_API_BASE
  if (configured && configured.trim()) return configured.trim().replace(/\/+$/, '')

  if (typeof window !== 'undefined') {
    const { hostname, origin } = window.location
    const isLocal =
      hostname === 'localhost' || hostname === '127.0.0.1' || hostname === '[::1]'
    if (!isLocal) return origin
  }

  return 'http://127.0.0.1:8000'
}

const API_BASE = resolveApiBase()
const IS_LOCAL_TARGET = /^https?:\/\/(localhost|127\.0\.0\.1|\[::1\])/.test(API_BASE)

export { API_BASE }

/**
 * POST /analyze_labs. The backend answers 200 with a structured body even for
 * bad input, so a thrown error here means the server is genuinely unreachable.
 */
export async function analyzeLabs(labs) {
  let response
  try {
    response = await fetch(`${API_BASE}/analyze_labs`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ labs }),
    })
  } catch (err) {
    // Tailor the guidance: telling someone on a deployed site to run uvicorn
    // locally is useless, and telling a developer the server is "down" when
    // they simply have not started it is equally unhelpful.
    throw new Error(
      IS_LOCAL_TARGET
        ? `Cannot reach the backend at ${API_BASE}. Start it with: ` +
          `.venv/bin/python -m uvicorn main:app --app-dir backend --port 8000`
        : `Cannot reach the API at ${API_BASE}. The server may still be waking ` +
          `up — free hosting tiers sleep when idle and can take up to a minute ` +
          `on the first request. Try again shortly.`
    )
  }

  if (!response.ok) {
    throw new Error(`Backend returned HTTP ${response.status}.`)
  }
  return response.json()
}
