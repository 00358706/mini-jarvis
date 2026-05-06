# mini-jarvis project memory wiki

This folder is a **durable project-memory wiki**, inspired by the “LLM Wiki” idea.

## What this is
- **Durable synthesized memory**: short, human-readable summaries of what we learned, what we decided, and why.
- **Not authoritative**: wiki summaries are convenience for humans and future chat sessions, not a source of truth.

## What this is not
- Not an execution surface.
- Not an automatic update system (no background updating, no “self-modifying wiki”).

## Relationship to `data/workspaces/*`
There are two different kinds of artifacts in this repo:

### `data/workspaces/*` = transactional task state
- Per-plan/task, lifecycle-scoped artifacts (active/completed/rejected).
- Mirrors plan and execution lifecycle and preserves evidence for a specific run.

### `docs/wiki/*` = durable synthesized memory
- Cross-task, cross-branch summaries intended to survive beyond any one workspace.
- Should cite evidence instead of copying large raw content.

## Evidence linking rules (required)
Every wiki page must link back to **evidence** (one or more of):
- **workspace id**: e.g. `data/workspaces/completed/<plan_id>/`
- **commit hash**: e.g. `git show <sha>`
- **source file**: path in the repo (and optionally line ranges)
- **test output**: paste only short excerpts; prefer pointing to the script name + invocation

If evidence is missing, the page must say so explicitly.

## Authority reminder (non-negotiable)
Even when the wiki says “X is true”, authority remains with:
- gateway code (`main.py` + supporting modules)
- policy (`policy.py`)
- registry (`registry.py`)
- sandbox boundary (`sandbox.py` → `sandbox_worker.py`)

Start here:
- `docs/wiki/index.md`
- `docs/wiki/log.md`
- `docs/wiki/decisions/0001-gateway-authority.md`

