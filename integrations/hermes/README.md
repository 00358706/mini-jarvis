# Hermes Mini-Jarvis Media Flow

This integration is a thin Hermes-facing command wrapper for Mini-Jarvis media plans.
It preserves Mini-Jarvis as the authority layer and never talks to media services directly.

## Authority boundaries

- Hermes calls Mini-Jarvis endpoints only.
- Hermes does not call Radarr, Sonarr, SABnzbd, Prowlarr, or other ARR APIs directly.
- Natural-language chat is not authorization.
- Approval and execution are separate operator actions.
- `approve` requires `--confirm` and does **not** execute.
- `execute` requires `--confirm` and does **not** approve.
- No combined approve+execute command is implemented.

## Configuration

Set these environment variables where Hermes will run the wrapper:

```bash
export MINI_JARVIS_BASE_URL="http://127.0.0.1:8000"   # optional default
export MINI_JARVIS_API_KEY="..."                       # required
export MINI_JARVIS_AGENT="media_agent"                 # optional default
```

Use `DEBUG=1` to print raw JSON responses for troubleshooting.

## Commands

Propose a media plan from a natural-language request. This creates a pending
Mini-Jarvis plan only; it does not approve or execute anything.

```bash
python integrations/hermes/mini_jarvis_media_flow.py propose "add Arrival to the movie library"
```

List pending plans:

```bash
python integrations/hermes/mini_jarvis_media_flow.py pending
```

Review a plan/workspace summary:

```bash
python integrations/hermes/mini_jarvis_media_flow.py show <plan_id>
```

Approve a reviewed pending plan. The explicit flag is required, and this command
still does not execute tools:

```bash
python integrations/hermes/mini_jarvis_media_flow.py approve <plan_id> --confirm
```

Execute an already approved plan. The explicit flag is required, and this command
will not approve a pending plan for you:

```bash
python integrations/hermes/mini_jarvis_media_flow.py execute <plan_id> --confirm
```

## Mini-Jarvis endpoints used

The wrapper uses only Mini-Jarvis gateway endpoints:

- `POST /plans/from-message`
- `GET /plans/pending`
- `POST /plans/{plan_id}/approve`
- `POST /plans/{plan_id}/execute`
- `GET /workspaces/{state}/{plan_id}/compact`
- `GET /workspaces/{state}/{plan_id}`

All registry, policy, approval, and sandbox enforcement remains inside Mini-Jarvis.
