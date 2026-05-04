# AI OS hierarchy (mini-jarvis)

Human-readable view of how responsibilities stack. Lower layers do not replace gateway authority.

## Order of concern (top to bottom)

1. **Human** — Owns goals, approves risky work, and decides when proposals become real changes. Ultimate accountability.

2. **Gateway** — Single entry for ingest and (future) plan submission. Validates requests, authentication, and coarse policy. The gateway is the **authority** for what the system will attempt; nothing “below” it overrides that.

3. **Agent filesystem context** — Folders under `agents/<agent_id>/` (`agent.yaml`, `tools.yaml`, prompts, examples, local notes). These are **workflow and persona configuration**, not microservices. Agents **do not own** tools and **do not execute** them.

4. **Planner / model** — Produces **proposals**: natural language, structured plans (`plans.py`), or suggested edits. Model output is **not** authority; it is input to policy and human review.

5. **Policy** — Evaluates proposed plans (`policy.py`): risk, approvals, cloud/delete flags, consistency with installed tools when that set is provided. No tool execution, no registry writes.

6. **Registry** — Source of truth for **which tools exist and are installed**, their schemas, and lifecycle (propose → approve → install). Generated or model-suggested tools remain **proposals** until reviewed and installed; installation is not automatic execution of arbitrary code.

7. **Approval / session** — Plans may move through filesystem stages (`approvals.py`: pending, approved, rejected, executed). This is bookkeeping and human workflow support, not permission replacement for the gateway.

8. **Sandbox worker** — **Only** execution path for registered tool **side effects**. Subprocess boundary; no substitute for policy or registry gates.

9. **Tools** — Concrete implementations callable only after registry + validation + sandbox dispatch. HTTP to configured services is additionally constrained (e.g. `http_allowlist.py`).

10. **Audit** — Append-only style observation of decisions and outcomes for operators.

11. **User feedback** — Corrections and preferences that can inform future proposals and policy tuning; not a silent execution channel.

## Clarifications

- **Agents are not services.** They do not listen on ports or run schedulers. They are packaged context for planners and documentation.

- **Agents do not own tools.** Tool names in agent `tools.yaml` are allowlists or intentions; the registry decides what is actually installed and runnable.

- **Model output is proposal, not authority.** A plan must pass policy and approvals (when required) before any execution path considers it.

- **Tool creation is a lifecycle, not auto-run.** New tools are proposed, reviewed, approved, and installed into the registry before the sandbox may invoke them.

- **LoopLM and LoRA** (and similar) are **future improvements** to planners or models only. They are not additional permission layers and do not bypass the gateway, registry, policy, or sandbox.
