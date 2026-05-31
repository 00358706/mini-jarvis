# Agent Worker Loop

This document defines the supervised worker-loop pattern for Mini-Jarvis, Hermes, Codex, Cursor, and ChatGPT. It is documentation only and does not change runtime behavior.

## Status

- Docs-only contract.
- Not implemented in gateway code.
- Does not grant execution authority.
- Does not bypass plan, policy, approval, registry, sandbox, or workspace boundaries.

## Core principle

Mini-Jarvis is the supervised local automation gateway/control plane.

Workers and models may help classify, draft, edit, test, review, or summarize, but they are not authority. Model output is advisory. The gateway, policy, registry, approval lifecycle, sandbox, and evidence trail remain authoritative.

## Human and worker roles

- **User**: Defines the goal, reviews evidence, and gives final approval for commits, pushes, merges, and side effects.
- **Mini-Jarvis gateway**: Owns the request envelope, routing contract, policy checks, approval lifecycle, registry checks, evidence/workspaces, and sandbox execution boundary.
- **Hermes**: Coordinates bounded tasks, repeats command loops, writes reports, and stops on ambiguity. Hermes is useful for “keep trying this safe loop until done,” but should not be treated as authority.
- **Codex**: Produces bounded code or documentation patches from explicit task packets. Codex should not commit, push, delete branches, or broaden scope unless explicitly instructed.
- **Cursor**: Provides interactive repo navigation, manual review, and human-guided edits. Cursor is useful for inspecting larger context and making precise edits, but is not the source of authority.
- **ChatGPT**: Helps with planning, architecture review, prompt drafting, and sanity checks. ChatGPT output is advisory.

## Standard supervised loop

1. The user defines a goal.
2. A task packet is written with scope, files, constraints, and stop conditions.
3. A worker proposes or edits a bounded patch.
4. A verifier runs checks and summarizes results.
5. A reviewer inspects the diff and evidence.
6. The user explicitly approves commit, push, merge, or side effects.
7. Git and/or Mini-Jarvis records the outcome.

## Required boundaries

Any implementation should preserve these invariants:

- Proposal is separate from approval.
- Approval is separate from execution.
- Execution is only through installed registry tools and the sandbox path.
- Idempotency and retry behavior must be explicit per work item.
- Concurrency must not duplicate execution or corrupt plan state.
- Worker errors must fail closed and leave reviewable evidence.
- No worker may treat natural language as authorization.
- No worker may mutate the registry directly.
- No worker may use filesystem artifacts as authority when gateway state says otherwise.

## Git and repo workflow rules

- `main` remains the clean source of truth in `C:\AI\mini-jarvis-prod`.
- `runtime-main` remains the local runtime mirror in `C:\AI\mini-jarvis`.
- Use at most one active feature branch at a time unless a branch is intentionally waiting for review.
- Do not use broad `git add .`.
- Do not commit, push, merge, reset, or delete branches without explicit approval.
- Do not trust WSL Git status for Windows worktrees when it disagrees with Windows PowerShell Git.
- Local runtime data stays local: `.env`, `.venv`, `data`, `logs`, and workspaces are not project source.

## Failure handling

A worker should stop and summarize when it sees:

- Dirty worktree state unless explicitly expected.
- Git ambiguity.
- Test or check failure.
- Prompt/tool quoting errors.
- Missing files or unexpected paths.
- Any request that would broaden the approved scope.

Workers should not “fix forward” blindly.

## Open design questions

- Queue/source format and retention rules.
- Worker identity and role-key scoping.
- Backoff, scheduling, and crash recovery behavior.
- Evidence schema reuse with `docs/ACTION_EVIDENCE_SCHEMA.md`.
- Relationship to `docs/ROUTINE_CONTRACT.md` for repeatable workflows.
- Whether Codex/Cursor/Hermes orchestration should become a Mini-Jarvis routine, external script, or local-only operator practice.

## Implementation note

This file is documentation only. Adding it does not create a worker, scheduler, queue, daemon, API route, registry entry, sandbox change, or execution path.