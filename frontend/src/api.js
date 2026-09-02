const API_BASE = import.meta.env.VITE_API_BASE || 'http://127.0.0.1:8000'

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
    throw new Error(
      `Cannot reach the backend at ${API_BASE}. Start it with: ` +
        `.venv/bin/python -m uvicorn main:app --app-dir backend --port 8000`
    )
  }

  if (!response.ok) {
    throw new Error(`Backend returned HTTP ${response.status}.`)
  }
  return response.json()
}
