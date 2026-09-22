# Deploying NOVA to Vercel

NOVA ships with a **serverless deployment target**: the full FastAPI backend +
developer dashboard running on Vercel (`vercel.json` + `api/index.py`).

## What works in the cloud — and what can't

| Works on Vercel | Why it can't run in the cloud |
|---|---|
| Agent brain: planner → queue → executor → verify | Controlling **your** PC (mouse/keyboard/apps) — needs the desktop build |
| Filesystem tools (sandboxed to the cloud `/tmp`) | Microphone / voice capture |
| Workflows, macros, `{variables}` | Screen capture of your desktop |
| Memory, session context, dev commands | WhatsApp/VS Code on your machine |
| Dashboard, SSE timeline, health score | Windows UI automation |

Security: **21 dangerous tools are hard-denied in the cloud build**
(shell execution, shutdown/restart, process control, input injection).
Attempting them returns "Denied by permission policy" (§56).

## Deploy (GitHub import — recommended)

1. Push this repo to GitHub (already done for this project).
2. Go to [vercel.com/new](https://vercel.com/new) → **Import** the repo.
3. Vercel auto-detects `vercel.json` — no settings changes needed.
4. Click **Deploy**. Your URL is live: dashboard at `/`, API under `/api`.

## Deploy (CLI)

```bash
npm i -g vercel
vercel login
cd nova-agent
vercel --prod
```

## Optional hardening (Vercel project → Settings → Environment Variables)

| Variable | Effect |
|---|---|
| `NOVA_API_TOKEN` + setting `api.auth_enabled=true` | require bearer token on every API call |
| `OPENAI_API_KEY` | real LLM planning instead of the heuristic planner |

## Serverless realities (by design, not bugs)

- **State is ephemeral**: SQLite lives in `/tmp`; data resets on cold starts.
  The deployment is for demo/control-panel use — the persistent home of NOVA
  is the desktop build (`python -m backend.main` + `python -m apps.desktop.main`).
- **SSE streams** are cut at the function timeout; the dashboard reconnects
  automatically (heartbeat design).
- Hobby plan caps function duration at 10 s — long `npm install`-style tasks
  may time out; the desktop build has no such cap.
