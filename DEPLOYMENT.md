# Deployment

The repo is deployment-ready: CORS, ports and the API base URL are all
environment-driven, and the platform configs are committed. What remains is
signing in to a host, which needs a browser.

## Why not serverless

The agent spawns `backend/mcp_server.py` as a **stdio subprocess per request** —
that is the whole point of the MCP boundary. Vercel/Netlify *functions* and
edge runtimes cannot reliably do that, so the backend needs a real container or
VM. The **frontend** is a static bundle and can go anywhere.

---

## Option A — Render, both services from the blueprint (recommended)

One platform, one file, free tier. [`render.yaml`](render.yaml) declares both
services.

1. Go to **https://dashboard.render.com** → sign in with GitHub.
2. **New → Blueprint** → select
   `Arunav1/Aragen_Hackathon_GenAi-Full_Stack_Software` → **Apply**.
   Render reads `render.yaml` and creates `lab-triage-api` and `lab-triage-web`.
3. It will prompt for the values marked `sync: false`. Set on **lab-triage-api**:
   - `GEMINI_API_KEY` → your key
   - `CORS_ORIGINS` → leave blank for now
4. Wait for `lab-triage-api` to go live, copy its URL
   (e.g. `https://lab-triage-api.onrender.com`), then on **lab-triage-web** set:
   - `VITE_API_BASE` → that backend URL
   
   and redeploy the frontend so the URL is baked into the bundle.
5. Copy the frontend URL and set it as `CORS_ORIGINS` on the backend.
   *(Both services are on `*.onrender.com`, which the default
   `CORS_ORIGIN_REGEX` already allows — so this step is belt-and-braces.)*

**Verify:**

```bash
curl https://lab-triage-api.onrender.com/health
curl https://lab-triage-api.onrender.com/mcp_tools
```

`/mcp_tools` opening a live MCP session in production is the proof the stdio
subprocess works on the host.

### ⚠️ Free-tier cold starts

Render's free plan **spins the backend down after ~15 minutes idle**, and the
next request takes **50+ seconds** to wake it. That is a real demo hazard.
Before presenting, hit `/health` once to warm it, or keep a browser tab open.

---

## Option B — Frontend on Vercel, backend on Render/Railway

Use this if you want the faster frontend CDN.

**Frontend (Vercel):** import the repo, set **Root Directory** to `frontend`.
[`frontend/vercel.json`](frontend/vercel.json) supplies the rest. Add env var
`VITE_API_BASE` = your backend URL, then deploy.

**Backend (Railway):** New Project → Deploy from GitHub. Railway detects the
[`Dockerfile`](Dockerfile). Set `GEMINI_API_KEY` and `CORS_ORIGINS`. Railway
supplies `$PORT`, which the image honours.

Preview URLs on `*.vercel.app` and `*.netlify.app` are already permitted by the
default `CORS_ORIGIN_REGEX`, so per-commit previews work without a redeploy.

---

## Option C — Any container host

```bash
docker build -t lab-triage .
docker run -p 8000:8000 \
  -e GEMINI_API_KEY=your_key \
  -e CORS_ORIGINS=https://your-frontend-url \
  lab-triage
```

Works on Fly.io, Cloud Run, ECS, or a plain VM.

---

## Environment variables

### Backend

| Variable | Required | Purpose |
|---|---|---|
| `GEMINI_API_KEY` | **Yes** | Gemini key. Without it classification still works; explanations fall back to the deterministic basis text. |
| `GEMINI_MODEL` | No | Defaults to `gemini-3.1-flash-lite`. Avoid non-lite flash models — 20 requests/day free-tier cap. |
| `CORS_ORIGINS` | Yes in prod | Comma-separated frontend origins. |
| `CORS_ORIGIN_REGEX` | No | Defaults to `*.vercel.app`, `*.netlify.app`, `*.onrender.com`. |
| `PORT` | Supplied by host | Bound automatically. |

### Frontend

| Variable | Required | Purpose |
|---|---|---|
| `VITE_API_BASE` | **Yes** | Backend URL. Baked in **at build time** — changing it requires a rebuild, not just a restart. |

---

## Pre-deploy checklist

- [x] CORS is environment-driven — verified that configured origins and platform
      preview domains are allowed and an unknown origin is blocked
- [x] `PORT` honoured, binding `0.0.0.0` (not `127.0.0.1`, which fails health checks)
- [x] `VITE_API_BASE` from a platform env var is baked into the production bundle
      — verified by grepping the built JS
- [x] `.env` is gitignored and absent from git history; secrets are set in the
      host dashboard
- [x] `load_dotenv(..., override=False)` so a missing `.env` is normal in prod and
      real environment variables win
- [x] Health check endpoint at `/health`
- [x] Container runs as a non-root user

---

## Post-deploy smoke test

```bash
API=https://your-backend-url

curl -s $API/health
curl -s $API/mcp_tools          # proves MCP works on the host

curl -s -X POST $API/analyze_labs \
  -H 'Content-Type: application/json' \
  -d '{"labs":[{"test_name":"Potassium","value":6.8,"unit":"mmol/L"}]}' \
  | python3 -m json.tool
```

Expect `status: "critical"`, a populated `basis`, and `meta.llm_ok: true`.
Then open the frontend, click **Load example** → **Analyze**.

---

**Decision support, not a diagnosis.**
