# AGENT_HANDOFF

Mini-Jarvis is a local-first Agentic Gateway OS.

This file is a strict handoff for future coding agents. Read it before editing.

## Core Principle

- Filesystem = readable workflow state.
- Python modules = validation, policy, and execution authority.

Workspace files, wiki pages, markdown docs, route mirrors, and generated artifacts help humans review what happened. They do not authorize execution.

## Authority Invariants

- Gateway remains the authority.
- Agents are folders, not services.
- Agents may propose plans and reference registered tools.
- Agents may not execute tools directly.
- Registry is the source of truth for installed tools.
- Policy decides whether a proposed plan is allowed.
- Human approval is required before execution.
- Approval and execution are separate.
- Sandbox worker is the only side-effect execution path.
- Model output is proposal, not authority.

## Forbidden Near-Term Changes

Do not add or wire any of these unless explicitly approved:

- LoopLM
- generated tool execution
- apply-patch
- MCP tools
- auto-approve
- auto-execute
- approve+execute shortcuts
- `/ingest` changes

## Files To Read Before Editing

- `README.md`
- `docs/CURRENT_STATE.md`
- `docs/ARCHITECTURE_INVARIANTS.md`
- `docs/ENVIRONMENT.md`
- `docs/wiki/README.md`

## Standard Test Commands

```powershell
git diff --check
powershell -ExecutionPolicy Bypass -File .\scripts\run_all_tests.ps1
```

Run broader tests when behavior changes. For docs-only changes, `git diff --check` is the minimum acceptance check.

## Required Final Branch Summary Format

Use this format in final handoff:

- files changed
- behavior changed
- tests run
- authority-boundary confirmation
