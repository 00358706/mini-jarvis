# 0001 — Gateway authority is non-negotiable

## Status
Accepted.

## Decision
The **gateway** remains the only authority that can:
- validate inputs and proposals
- evaluate policy decisions
- decide approval/execution gates
- enforce registry-installed tool execution
- define the sandbox boundary and execution path

Agents are **folders** and provide proposal constraints and context only. Tool names referenced by an agent are not execution authority.

## Rationale
This keeps:
- execution explicit and auditable
- policy deterministic and enforceable
- side effects confined to the sandbox worker path
- “model output” and “agent config” as proposal inputs, not authority

## Evidence
- Source files: `main.py`, `policy.py`, `registry.py`, `sandbox.py`, `sandbox_worker.py`, `workspace.py`, `agent_loader.py`
- (Add commit hashes / workspace ids here when this decision is referenced by a concrete change.)

