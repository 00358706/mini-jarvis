# Mini-Jarvis Autonomous Agent Goal

> For Hermes: Use `subagent-driven-development` skill to implement this plan task-by-task. Preserve Mini-Jarvis as the authority layer: models and agents may propose work, but policy, approval, registry, sandbox, task state, and audit remain gateway-owned.

**Goal:** Turn Mini-Jarvis from a safe plan/approval gateway into a supervised autonomous local agent that can receive a goal, select an agent, build and manage a multi-step plan, execute allowed read-only work automatically, request approval for mutations, resume blocked/running work, and report audited results.

**Architecture:** Mini-Jarvis remains the authority boundary. A new task/runtime layer coordinates planners, agents, and workspaces, but all side effects still flow through registered tools, policy, approval, sandbox execution, and audit logging. The first autonomous milestone is supervised autonomy, not unrestricted self-direction.

**Tech Stack:** FastAPI, Pydantic, local filesystem task/workspace state, existing registry/policy/approval/sandbox modules, local small-router model for advisory routing, optional stronger planner model for proposal drafting.

**Example scope note:** Media/Radarr/Sonarr/SABnzbd flows in this plan are illustrative optional/local capability-pack examples. They are not the definition of Mini-Jarvis core, which remains the supervised local automation gateway/control plane and authority boundary.

---

## North Star

A user can say something like:

```text
Add The Matrix to my library and tell me when it is queued.
```

Mini-Jarvis should:

1. Create a durable task.
2. Route it to the media agent.
3. Build a multi-step plan.
4. Run safe read-only discovery automatically when policy allows it.
5. Produce a human-readable review workspace.
6. Ask for approval before Radarr/Sonarr mutations.
7. Execute the approved mutation through registry/schema/sandbox only.
8. Continue or resume the task after approval.
9. Write final result and audit evidence.
10. Never let the model, dashboard, Hermes, or generated code bypass gateway authority.

---

## Non-Negotiable Authority Rules

- Mini-Jarvis remains the authority layer.
- Agents are configuration/context, not independent services with direct tool access.
- Model output is proposal, not permission.
- The planner may propose `PLAN.json`; it may not approve or execute.
- All tool execution must pass through registry lookup, schema validation, policy, approval rules, sandbox worker, and audit logging.
- Generated tools from Automation Lab are not callable until reviewed, tested, approved, installed, and explicitly wired into dispatch.
- Mutating actions require approval unless a future policy rule explicitly classifies them as safe auto-actions.
- High-risk actions remain blocked initially: deletion, broad filesystem writes, host/service restarts, Proxmox admin actions, and arbitrary network/file access.

---

## Success Definition

Mini-Jarvis reaches supervised autonomous agent MVP when all of these are true:

- A task can be created from natural language and persisted with a stable `task_id`.
- A task can move through explicit states: `created`, `planning`, `proposed`, `waiting_for_approval`, `approved`, `running`, `blocked`, `completed`, `failed`, `rejected`.
- The gateway can resume a task after restart from filesystem state.
- The planner can produce valid multi-step plans using only installed registry tools.
- Policy can classify read-only, proposal-only, approval-required, and blocked steps.
- Read-only steps can be auto-executed only when policy explicitly allows them.
- Mutating steps create a pending approval and stop before side effects.
- Approval and execution are separate actions.
- Execution refuses changed/tampered plans via hash checks.
- Each task has a readable workspace with request, route, agent context, plan, policy decision, approval state, execution log, and result.
- Dashboard can show task state and let the user approve/reject/execute/resume safely.
- Tests prove `/ingest` and planner routes do not execute tools directly.

---

## Milestone 1: Durable Task State

**Objective:** Add a first-class task layer above plans so Mini-Jarvis can remember, resume, and report autonomous work.

### Deliverables

- Create `tasks.py` for task models and filesystem persistence.
- Create `routers/tasks.py` for task lifecycle endpoints.
- Add task workspace files under `data/tasks/` or integrate task metadata into `data/workspaces/` cleanly.
- Add tests for task creation, state transitions, invalid transitions, and resume/reload.

### Initial Task Model

Fields:

- `task_id`
- `created_at`
- `updated_at`
- `status`
- `message`
- `selected_agent`
- `route`
- `plan_id`
- `approval_required`
- `blocked_reason`
- `result_summary`
- `audit_refs`

### Acceptance Criteria

- `POST /tasks` creates a durable task and returns a `task_id`.
- `GET /tasks/{task_id}` returns current state.
- State survives process restart because it is stored on disk.
- Invalid state transitions are rejected.
- No task endpoint executes tools yet.

---

## Milestone 2: Planner Interface and Multi-Step Plan Drafting

**Objective:** Introduce a planner boundary that can create multi-step plan proposals without gaining authority.

### Deliverables

- Create `services/planner.py` with a strict interface: input context in, structured plan proposal out.
- Keep deterministic planner path first; optional model planner only behind explicit config.
- Add plan validation that rejects unknown tools before proposal persistence.
- Support multi-step plans, not only one-step `/plans/from-message` mappings.

### Planner Inputs

- user message
- selected agent config from `agents/<agent_id>/`
- installed registry tools and schemas
- task/workspace context
- policy hints

### Planner Output

- valid `Plan`
- or structured `missing_capability`
- or structured `manual_review_required`

### Acceptance Criteria

- Planner never calls tools.
- Planner never approves plans.
- Planner output references only installed registry tool names.
- Planner can produce a media flow like:
  - `radarr_search`
  - approval-gated `radarr_add`
  - optional `sabnzbd_queue`
- Tests prove unknown/generated tools are rejected.

---

## Milestone 3: Policy Tiers for Autonomy

**Objective:** Make policy expressive enough to decide which steps can run automatically and which must stop for approval.

### Deliverables

- Extend policy decisions with action classification:
  - `read_only_auto_allowed`
  - `proposal_only`
  - `approval_required`
  - `blocked`
- Add per-tool permission metadata mapping to these classes.
- Add policy tests for Radarr/Sonarr/SABnzbd and repo-maintenance tools.

### Initial Suggested Classifications

- Auto-allowed read-only candidates:
  - `radarr_search`
  - `sonarr_search`
  - `sabnzbd_queue`
  - `list_project_files`
  - `search_repo`
  - `inspect_file` with repo confinement
- Approval-required:
  - `radarr_add`
  - `sonarr_add`
  - `sabnzbd_pause`
  - `sabnzbd_resume`
- Proposal-only:
  - `propose_patch`
  - Automation Lab artifacts
- Blocked initially:
  - delete/remove/purge tools
  - arbitrary shell
  - arbitrary HTTP
  - broad filesystem writes
  - service/host restarts

### Acceptance Criteria

- Read-only auto-execution requires explicit policy allow.
- Mutating tools still stop at approval.
- Risky/deletion tools are blocked even if a planner proposes them.
- Policy returns machine-readable reasons for dashboard display.

---

## Milestone 4: Autonomous Run Loop v1

**Objective:** Add a supervised run loop that advances a task until it completes, blocks, or waits for approval.

### Deliverables

- Create `services/task_runner.py`.
- Add `POST /tasks/{task_id}/run` or `POST /tasks/from-message` convenience flow.
- Runner stages:
  1. load task
  2. select route/agent
  3. build plan
  4. evaluate policy
  5. execute auto-allowed read-only steps
  6. stop at approval-required step
  7. write result/blocker
- Add tests for each stop condition.

### Acceptance Criteria

- A task can progress without Hermes manually calling every endpoint.
- The runner stops before mutations and records `waiting_for_approval`.
- After approval, the runner can continue execution.
- The runner is idempotent: rerunning does not duplicate completed steps.
- Logs show every state transition.

---

## Milestone 5: Step-Level Execution State and Idempotency

**Objective:** Track individual plan steps so Mini-Jarvis can resume safely and avoid duplicate side effects.

### Deliverables

- Add step execution records to task/workspace state.
- Store `step_id`, tool, args hash, status, started/completed timestamps, result, error.
- Refuse to rerun completed mutating steps unless a future explicit replay mechanism exists.
- Use existing `idempotency_key` metadata where available.

### Acceptance Criteria

- Completed steps are skipped on resume.
- Failed read-only steps can be retried according to policy.
- Mutating step retry is conservative and requires explicit approval or idempotency proof.
- Result files clearly show which steps ran, skipped, failed, or blocked.

---

## Milestone 6: Dashboard Task UX

**Objective:** Make the local dashboard feel like an autonomous task console instead of only a plan review page.

### Deliverables

- Add task list panel.
- Add task detail view.
- Show route, selected agent, current status, plan, policy, approval requirement, step results, and result summary.
- Add buttons for run/resume, approve, reject, execute/continue where appropriate.
- Preserve existing separation: propose does not approve, approve does not execute, execute does not approve.

### Acceptance Criteria

- User can submit a goal and watch task status change.
- Approval-required tasks are obvious and safe to review.
- Dashboard never calls downstream services directly.
- Dashboard only uses documented gateway endpoints/proxy allowlist.

---

## Milestone 7: Capability Lifecycle Completion

**Objective:** Make Automation Lab proposals actionable without making generated code automatically executable.

### Deliverables

- Define reviewed install checklist for generated tools.
- Add tests/static checks for generated tool candidates.
- Add a safe path to convert approved candidate metadata into installed registry metadata.
- Keep callable dispatch explicit: generated metadata alone does not create execution access.

### Acceptance Criteria

- Automation Lab can propose missing capability artifacts.
- Human/admin can review and install metadata.
- Execution still requires a real dispatch implementation or approved safe executor path.
- Tests prove generated artifacts do not execute automatically.

---

## Milestone 8: Runtime and Deployment Hardening

**Objective:** Make the gateway reliable enough to act as a local control plane.

### Deliverables

- Document one canonical launch path for Windows/WSL.
- Verify `.env` loading and reject placeholder auth in production-like runs.
- Add health checks for gateway, router model, and configured media services.
- Prefer Tailscale/LAN-only binding.
- Add smoke test script for `/health`, `/tools`, `/plans/from-message`, task creation, and safe read-only execution.

### Acceptance Criteria

- A fresh local run can be started from documented commands.
- Health output distinguishes gateway alive vs capability installed vs downstream service reachable.
- Secrets are not printed or committed.
- Smoke tests can be run before trusting the autonomous loop.

---

## Milestone 9: Planner Quality Upgrade

**Objective:** Improve planning intelligence while preserving authority boundaries.

### Deliverables

- Add optional stronger planner backend for drafting only.
- Constrain planner with registry schemas and examples.
- Add validation/repair loop for invalid plans.
- Add fixtures for common media and project-maintenance goals.

### Acceptance Criteria

- Planner can produce useful multi-step plans from natural language.
- Invalid model output never reaches execution.
- Router/planner failures become manual review or missing capability, not unsafe action.
- Tests cover malformed JSON, unknown tools, excessive steps, cloud requests, and blocked delete intents.

---

## Milestone 10: First End-to-End Demo Scenarios

**Objective:** Prove supervised autonomy with concrete workflows.

### Demo A: Read-Only Media Status

Prompt:

```text
Check my SABnzbd queue.
```

Expected:

- task created
- media agent selected
- `sabnzbd_queue` plan built
- policy marks read-only auto-allowed
- sandbox executes queue read
- task completes with result

### Demo B: Approval-Gated Movie Add

Prompt:

```text
Add movie The Matrix to my library.
```

Expected:

- task created
- media agent selected
- plan includes lookup/review and `radarr_add`
- lookup may run automatically if policy allows
- task stops for approval before `radarr_add`
- after approval, sandbox executes `radarr_add`
- task completes with audited result

### Demo C: Project Maintenance Proposal

Prompt:

```text
Search the repo for TODO comments and propose a cleanup plan.
```

Expected:

- task created
- project maintainer selected
- read-only search runs if policy allows
- patch/code changes are proposal-only unless explicit future write tool is approved
- task completes with review artifact, not direct edits

---

## Implementation Order

1. Durable task state.
2. Planner interface.
3. Policy autonomy tiers.
4. Task runner v1.
5. Step-level execution state.
6. Dashboard task UX.
7. Capability lifecycle completion.
8. Runtime hardening.
9. Planner quality upgrade.
10. End-to-end demo scenarios.

---

## Immediate Next Implementation Slice

Start with the smallest useful slice:

1. Add `tasks.py` with task model and filesystem persistence.
2. Add `routers/tasks.py` with `POST /tasks` and `GET /tasks/{task_id}`.
3. Add tests for durable task creation and reload.
4. Wire router into `main.py`.
5. Update README with the new task layer.

Do not implement autonomous execution in the first slice. Establish durable task state first, then build the runner on top.

---

## Definition of Done for the Whole Goal

Mini-Jarvis is considered a supervised autonomous agent MVP when the end-to-end demo scenarios pass through Mini-Jarvis alone, with Hermes acting only as a user/coordinator and not bypassing gateway authority.

The final system should feel autonomous because it can carry a goal forward, but remain safe because every side effect still flows through Mini-Jarvis policy, approval, registry, sandbox, task state, and audit.
