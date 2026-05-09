# ARCHITECTURE_INVARIANTS — non‑negotiable

These invariants are the “guard rails” for mini-jarvis. Changes should preserve them unless explicitly approved.

## Gateway is the authority
- Validation, policy evaluation, approval state, registry checks, and execution orchestration live in the gateway.
- Any “helper” integration or wrapper is convenience only and must not become an alternate authority.

## Agents are folders, not services
- Agents exist as filesystem folders under `agents/<agent_id>/`.
- Agents provide context, prompts, examples, and tool allowlists.
- Agents **do not** run tools, host servers, or perform side effects directly.

## Registry is the source of truth for installed tools
- A tool may execute only if the registry contains an entry with `status=installed`.
- Agent `tools.yaml` allows *references* in proposals, but does not grant execution authority by itself.

## Agents may propose tools but not execute them
- Agents may propose plans that reference tool names (subject to strict allowlists).
- Agents do not execute tools; the gateway executes only after approval and registry/schema checks.

## Policy before approval
- Proposed plans are evaluated by policy before they can be saved as pending approval.
- Policy decisions are deterministic and recorded as readable state.

## Approval before execution
- Execution is an explicit, separate step and requires human approval.
- No auto-approve, no “single-click approve+execute” without explicit human intent.
- Any future “Authorize & Run” UX must remain an explicit human action after review, and must not bypass policy/registry/approval/sandbox checks (see `docs/EXECUTION_AUTHORIZATION.md`).

## Sandbox worker is the only side-effect execution path
- Tool execution goes through `sandbox.run()` → `sandbox_worker.py`.
- The gateway process must not directly perform tool side effects on the hot path.

## Model output is proposal, not authority
- LLM outputs must not be treated as executable code or direct tool calls.
- Generated tools (if added later) must be proposal-only until reviewed and installed via lifecycle.

## Authorization binds to reviewed content (future contract)
- Any execution authorization must be tied to the **exact reviewed plan content** (e.g. a `plan_hash` or reviewed-content reference) and must be invalidated if the reviewed plan changes.
- Approval state and workspace files remain evidence; they do not create alternate authority channels.

## Explicitly deferred (for now)
- Do not add LoopLM yet.
- Do not add generated tool execution yet.
- Do not change `/ingest` unless explicitly asked.

## No hidden execution channels
- Do not add alternate endpoints that execute tools outside `/plans/{plan_id}/execute` or the existing ingest routing path.
- Do not add endpoints that mutate workspaces or arbitrary filesystem state.

