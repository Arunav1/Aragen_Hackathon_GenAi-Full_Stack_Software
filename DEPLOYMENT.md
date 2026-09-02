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

## Option A — Render, ONE service (recommended)

The API process also serves the built frontend, so the page and the API share an
origin. **There is no `VITE_API_BASE` to set and no CORS to configure** — the two
settings most likely to be missed in a split deploy, and the cause of a deployed
page trying to call `127.0.0.1`.

1. Go to **https://dashboard.render.com** → sign in with GitHub.
2. **New → Blueprint** → select
   `Arunav1/Aragen_Hackathon_GenAi-Full_Stack_Software` → **Apply**.
3. When prompted, set the one value marked `sync: false`:
   - `GEMINI_API_KEY` → your key
4. That's it. Render builds the Docker image (Node builds the frontend, Python
   serves it alongside the API) and gives you a single URL.

> If you already created the two-service blueprint, **delete both services first**,
> then re-apply. Render will not convert them in place.

**Verify** (replace with your service URL):

```bash
curl https://<your-service>.onrender.com/health
curl https://<your-service>.onrender.com/mcp_tools
```

`/mcp_tools` opening a live MCP session in production is the proof the stdio
subprocess design works on the host. Then open the URL in a browser — the app is
served from the same address.

### ⚠️ Free-tier cold starts

Render's free plan **spins the backend down after ~15 minutes idle**, and the
next request takes **50+ seconds** to wake it. That is a real demo hazard.
Before presenting, hit `/health` once to warm it, or keep a browser tab open.

---

## Option B — Split: frontend on Vercel, backend on Render/Railway

Use this only if you want the frontend on a CDN. **It reintroduces the two
settings Option A removes**, so get both right:

- `VITE_API_BASE` must be set **before** the frontend build. It is substituted at
  build time, so setting it afterwards does nothing until you rebuild. If it is
  missing, the deployed page falls back to its own origin — where no API lives —
  and every request fails.
- `CORS_ORIGINS` on the backend must list the frontend's origin.

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
| `VITE_API_BASE` | **Only for split deploys** | Backend URL. Baked in **at build time** — changing it requires a rebuild, not just a restart. Leave unset in the single-service deploy, where the app uses its own origin. |

### How the frontend resolves the API URL

1. `VITE_API_BASE` if the build supplied one.
2. Otherwise, if the page is **not** on localhost → **the page's own origin**.
3. Only on localhost → `http://127.0.0.1:8000`.

Step 2 is what stops a deployed page from calling `127.0.0.1`, which points the
browser at the *viewer's* machine and can never work.

---

## Pre-deploy checklist

- [x] Single-service verified end to end from a **non-localhost** origin: the app
      loaded, called its own origin, and returned 3 critical / 3 warning / 1 normal
      with 4 panel insights and no fallback explanations
- [x] The static mount does not shadow `/health`, `/mcp_tools` or `/analyze_labs`
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
