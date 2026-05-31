# Agent Worker Loop (docs-only contract)

This document describes a future agent worker loop shape for mini-jarvis. It is a design note only and does not change runtime behavior.

## Status

- Docs-only proposal.
- Not implemented in gateway code.
- Does not grant execution authority.
- Does not bypass plan, policy, approval, registry, sandbox, or workspace boundaries.

## Purpose

The agent worker loop is the proposed background coordination layer that would repeatedly observe eligible work, prepare bounded proposals or execution requests, and hand those requests back to the gateway authority layer.

The worker is not an authority boundary. The gateway remains responsible for:

- Plan validation and persistence.
- Policy evaluation.
- Human approval and reviewed-plan hash checks.
- Registry lookups and tool status checks.
- Sandboxed execution of installed tools.
- Audit and workspace lifecycle records.

## Non-authority rules

A worker loop must not:

- Approve plans.
- Execute tools directly.
- Mutate the registry directly.
- Treat natural language as authorization.
- Read secrets beyond explicitly configured runtime needs.
- Write runtime state outside documented gateway-owned paths.
- Use filesystem artifacts as authority when gateway state says otherwise.

## Proposed loop shape

A future worker may follow this high-level cycle:

1. Poll or receive a bounded work item from an approved queue/source.
2. Load only the minimum required context for that item.
3. Decide whether the next safe action is proposal, review evidence generation, status reporting, or no-op.
4. If action is needed, call existing gateway APIs instead of touching authority files directly.
5. Record compact evidence for what was observed and requested.
6. Stop, back off, or wait for explicit approval when the gateway requires it.

## Required boundaries

Any implementation should preserve these invariants:

- Proposal is separate from approval.
- Approval is separate from execution.
- Execution is only through installed registry tools and the sandbox path.
- Idempotency and retry behavior must be explicit per work item.
- Concurrency must not duplicate execution or corrupt plan state.
- Worker errors must fail closed and leave reviewable evidence.

## Open design questions

- Queue/source format and retention rules.
- Worker identity and role-key scoping.
- Backoff, scheduling, and crash recovery behavior.
- Evidence schema reuse with `docs/ACTION_EVIDENCE_SCHEMA.md`.
- Relationship to `docs/ROUTINE_CONTRACT.md` for repeatable workflows.

## Implementation note

This file is documentation only. Adding it does not create a worker, scheduler, queue, daemon, API route, registry entry, sandbox change, or execution path.
