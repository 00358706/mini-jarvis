## local_dashboard (client-only)

Tiny local review dashboard to demonstrate that a non–Open WebUI UI can operate Mini‑Jarvis through **documented gateway HTTP endpoints only**.

### What this is
- A static HTML/JS UI served locally.
- A tiny optional local dev server that **proxies HTTP requests** to the gateway so the browser does not require gateway CORS changes.

### What this is not
- Not a planner.
- Not an execution authority.
- Not a tool runner.
- Not a gateway extension (no new endpoints in the gateway).

### Run it
Prereqs:
- Gateway running (default `http://127.0.0.1:8000`)
- Do not commit or hardcode API keys

PowerShell:

```powershell
# From repo root
.\.venv\Scripts\python.exe integrations\local_dashboard\serve_dashboard.py --listen 127.0.0.1 --port 5173
```

Then open:
- `http://127.0.0.1:5173/`

In the UI:
1. Set **Gateway base URL** and **API key** (kept in memory / session only).
2. Propose a plan via `POST /plans/from-message`.
3. List pending plans via `GET /plans/pending`.
4. Show compact review via `GET /workspaces/active/<plan_id>/compact`.
5. Approve via `POST /plans/<plan_id>/approve` (explicit click).
6. Execute via `POST /plans/<plan_id>/execute` (separate explicit click).
7. Show completed compact + capped RESULT.md preview.

### Endpoint mapping (client contract)
The dashboard uses only these gateway endpoints:
- `POST /plans/from-message`
- `GET /plans/pending`
- `GET /workspaces/active/<plan_id>/compact`
- `POST /plans/<plan_id>/approve`
- `POST /plans/<plan_id>/reject`
- `POST /plans/<plan_id>/execute`
- `GET /workspaces/completed/<plan_id>/compact`
- `GET /workspaces/completed/<plan_id>/files/RESULT.md`

