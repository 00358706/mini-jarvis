# LOCAL_MODEL_ADAPTER_CONTRACT (docs-only)

This document is a **docs-only local model adapter contract** for Mini-Jarvis. It defines how future local model runtimes may be described and used as **adapters** for classification, drafting, summarization, and structured proposal output without changing the gateway authority model.

**This document does not change runtime behavior.** It does not change `/ingest`, add model calls, add endpoints, add MCP tools, add tool calling by a model, add generated tool execution, add automatic tool registration, add automatic registry installation, add model-driven tool installation, or add apply-patch.

**Align with:** `docs/ARCHITECTURE_INVARIANTS.md`, `docs/IO_ADAPTER_CONTRACT.md`, `docs/ROUTINE_CONTRACT.md`, `docs/CAPABILITY_REGISTRY_SCHEMA.md`, `docs/TOOL_PROPOSAL_SCHEMA.md`, `docs/EXECUTION_AUTHORIZATION.md`, and `docs/ACTION_EVIDENCE_SCHEMA.md`.

---

## Purpose

- Define a safe contract for local model runtimes such as llama.cpp, Ollama, and OpenAI-compatible local servers.
- Keep model runtimes as **adapters only**: they may transform input into text or structured proposal artifacts, but they do not own execution, approval, policy, registry state, or sandbox behavior.
- Make future local model use reviewable by specifying configuration, allowed task types, structured output expectations, evidence, and security rules before adding any implementation.

Local models can improve user experience and proposal quality. They do not change who may execute what.

---

## Core invariant

**Gateway remains the authority.** Local model runtimes, prompts, model output, sidecars, and adapter configuration are **not authority**.

- **Model output remains proposal, not authority.**
- **Registry remains the source of truth for installed tools.**
- **Policy, authorization, schema validation, and sandbox execution remain the enforcement path.**
- **Local model runtimes are adapters only**, even when they run on the same machine or trusted network.
- **Tool calling by the model is not allowed** by this contract.

Any future flow that uses local model output must still pass through gateway-owned validation, policy, approval/authorization, registry/schema checks, and sandbox execution before any side effect.

---

## Supported runtime types

The following runtime categories are in scope as future adapter targets:

| Runtime type | Description | Authority rule |
|--------------|-------------|----------------|
| `llama_cpp` | Local llama.cpp server or process-backed model runtime. | Adapter only; no tool calling, no execution authority. |
| `ollama` | Local or trusted-network Ollama model runtime. | Adapter only; no tool calling, no execution authority. |
| `openai_compatible_local` | Local server exposing an OpenAI-compatible API surface. | Adapter only; compatibility does not grant authority. |

Runtime type names are target schema values. They do not imply that Mini-Jarvis currently supports or calls these runtimes.

---

## Adapter responsibilities

A local model adapter may be responsible for:

- Sending bounded prompts and context to a configured local runtime.
- Requesting deterministic or low-temperature output for structured tasks.
- Returning text or structured JSON-like output to gateway-owned code for validation.
- Recording which runtime, model, prompt template, input references, and output shape were used.
- Reporting parse failures, schema failures, refusals, and runtime errors as reviewable failures.
- Applying prompt-size, timeout, retry, and output-size limits.
- Marking untrusted input so downstream review can see prompt-injection risk.

The adapter must be a client of gateway policy and schema rules. It must not create its own execution channel.

---

## Non-authority rules

A local model adapter must never:

- Execute tools directly.
- Emit direct tool calls that are treated as executable.
- Approve, reject, authorize, or execute plans.
- Install, register, or mutate registry entries.
- Treat generated tool code or generated tool schemas as installed.
- Modify `/ingest` behavior by contract alone.
- Create endpoints or MCP tools by contract alone.
- Apply patches or write arbitrary runtime files.
- Treat local execution, trusted LAN, Tailscale, or sidecar access as authority.
- Bypass gateway policy, authorization, registry/schema validation, or sandbox execution.

If a model suggests a plan, tool, routine, capability mapping, or patch, that output remains a proposal or review artifact only.

---

## Target adapter configuration

Future adapter configuration should be explicit and reviewable. Storage format is TBD.

| Field | Type | Required | Purpose |
|-------|------|----------|---------|
| `adapter_id` | string | yes | Stable adapter id, e.g. `local_ollama_planner`. |
| `runtime_type` | enum | yes | `llama_cpp` \| `ollama` \| `openai_compatible_local`. |
| `runtime_endpoint` | string or null | yes | Local/trusted endpoint or process reference; never a secret. |
| `model_id` | string | yes | Runtime model name or id. |
| `model_version` | string or null | optional | Optional digest, tag, or local version reference. |
| `allowed_task_types` | array of enum | yes | See **Allowed task types**. |
| `structured_output` | object | yes | See **Structured output requirements**. |
| `temperature` | number | yes | Prefer `0` or low deterministic values for structured tasks. |
| `max_input_tokens` | integer | optional | Upper bound for prompt/context size. |
| `max_output_tokens` | integer | yes | Upper bound for generated output. |
| `timeout_ms` | integer | yes | Runtime call timeout. |
| `retry_policy` | object | optional | Bounded retries for transport/runtime failures only. |
| `network_access` | enum | yes | `none` \| `local` \| `tailnet`; local model adapters should not require `internet`. |
| `privacy_profile` | enum | yes | `local_only` \| `trusted_network`; cloud profiles are out of scope for this contract. |
| `prompt_template_ref` | string | optional | Reviewable prompt/template reference or version. |
| `tool_calling_enabled` | boolean | yes | Must be `false`. |
| `generated_tool_execution_allowed` | boolean | yes | Must be `false`. |
| `evidence_required` | boolean | yes | Should be `true` for proposal-producing tasks. |

Example shape:

```json
{
  "adapter_id": "local_ollama_planner",
  "runtime_type": "ollama",
  "runtime_endpoint": "http://127.0.0.1:11434",
  "model_id": "example-local-model",
  "model_version": null,
  "allowed_task_types": ["classification_assist", "proposal_draft", "summarization"],
  "structured_output": {
    "mode": "json_object",
    "schema_ref": "plan-draft.v1",
    "gateway_validation_required": true,
    "reject_on_parse_error": true
  },
  "temperature": 0,
  "max_input_tokens": 8192,
  "max_output_tokens": 2048,
  "timeout_ms": 30000,
  "retry_policy": {
    "retry_allowed": false,
    "max_retries": 0
  },
  "network_access": "local",
  "privacy_profile": "local_only",
  "prompt_template_ref": "prompts/local_planner.v1",
  "tool_calling_enabled": false,
  "generated_tool_execution_allowed": false,
  "evidence_required": true
}
```

---

## Allowed task types

Allowed task types describe what the model adapter may be asked to produce. They do not grant execution rights.

| Task type | Allowed output | Must not do |
|-----------|----------------|-------------|
| `classification_assist` | Routing hints, labels, confidence notes, or structured classification candidates. | Override gateway routing policy or execute tools. |
| `summarization` | Bounded summaries of user input, workspace evidence, logs, or results. | Treat summary as authority or hide source limitations. |
| `extraction` | Structured fields extracted from provided context. | Invent required authority fields or bypass validation. |
| `proposal_draft` | Draft plan, routine, capability, or tool proposal artifacts for review. | Approve, execute, install, or call tools. |
| `review_assist` | Human-readable risk, duplicate, or policy-fit notes. | Replace deterministic policy decisions. |
| `response_draft` | Draft user-facing response text from already validated state. | Claim execution happened without gateway evidence. |

Any future task that can produce side effects must be modeled as a tool or execution adapter and remain outside this local model adapter contract.

---

## Structured output requirements

For structured tasks, adapter output should follow these rules:

- Use an explicit `schema_ref` or named target shape.
- Prefer JSON object output for machine-checked proposal artifacts.
- Treat parsing failure as a failed adapter result, not as permission to continue with free-form text.
- Validate output in gateway-owned code before using it to create plans, routines, tool proposals, or evidence records.
- Preserve raw model output as capped evidence when safe; otherwise preserve hashes and summaries.
- Mark every model-generated field as model-generated in downstream evidence when practical.
- Never treat model-generated `tool_name`, `args`, `authorization`, `registry_status`, or `approval_state` as authoritative.

If a local model emits a plan-like object, it is still only a draft until the gateway validates and stores a proposal through the normal path.

---

## Evidence requirements

Any future use of a local model adapter should leave enough evidence for review and audit.

Recommended evidence fields:

| Field | Purpose |
|-------|---------|
| `adapter_id` | Which adapter configuration was used. |
| `runtime_type` | `llama_cpp`, `ollama`, or `openai_compatible_local`. |
| `model_id` / `model_version` | Which local model produced output. |
| `task_type` | Requested task type. |
| `prompt_template_ref` | Prompt/template identity or version. |
| `input_refs` | Review-safe references to source inputs or workspace files. |
| `untrusted_input_present` | Whether user or external content influenced output. |
| `output_schema_ref` | Structured output target, if any. |
| `schema_validation_state` | `not_applicable` \| `passed` \| `failed`. |
| `output_ref` | Capped output, workspace reference, hash, or summary. |
| `error_state` | Parse/runtime/refusal/error summary when failed. |
| `created_at` | ISO 8601 timestamp. |

Evidence is review state only. It must not approve, authorize, install, or execute anything.

---

## Security and privacy rules

- Local does not automatically mean safe. Treat local model output as untrusted proposal text.
- Do not send secrets, API keys, credentials, or unnecessary raw files to model runtimes.
- Cap prompt, attachment, and output sizes.
- Preserve source labels and `untrusted_input_present` when user-provided or external content influences prompts.
- Defend against prompt injection by keeping authority outside the model and validating all structured output.
- Use configured local or trusted-network endpoints only; avoid internet access for local model adapters.
- Do not rely on model refusals or model self-reporting as policy decisions.
- Keep side effects out of the model runtime; tools still execute only through the gateway sandbox path.
- Do not allow model runtimes or sidecars to write arbitrary workspace, registry, or code files.

---

## Relationship to clients and sidecars

Clients and sidecars such as Open WebUI, Hermes-style local assistants, chat panels, and desktop helpers may wrap or present model interactions, but they remain **clients/adapters**.

They may:

- Submit user messages or context to gateway-approved flows.
- Display model-drafted summaries, plans, or proposal artifacts.
- Help a human review evidence and make explicit decisions.

They must not:

- Execute tools directly.
- Treat model output as approval, authorization, or registry truth.
- Hide whether output was generated by a model.
- Bypass `/plans/*` proposal, review, approval, and execution boundaries.
- Create a parallel approval or execution system outside the gateway.

Open WebUI/Hermes-style integrations should follow `docs/IO_ADAPTER_CONTRACT.md` as client/input adapters and this document when they delegate generation to a local model runtime.

---

## Relationship to other contracts

| Document | Relationship |
|----------|--------------|
| `docs/ARCHITECTURE_INVARIANTS.md` | Gateway, registry, policy, approval, sandbox, and model-output boundaries. |
| `docs/IO_ADAPTER_CONTRACT.md` | Clients and sidecars submit context; they are not execution authorities. |
| `docs/ROUTINE_CONTRACT.md` | Routines may request proposal drafts, but local model output does not authorize routine execution. |
| `docs/CAPABILITY_REGISTRY_SCHEMA.md` | Model-assisted capability lookup is advisory only. |
| `docs/TOOL_PROPOSAL_SCHEMA.md` | Model-drafted tool proposals remain review artifacts only. |
| `docs/EXECUTION_AUTHORIZATION.md` | Human authorization still binds to exact reviewed plan content. |
| `docs/ACTION_EVIDENCE_SCHEMA.md` | Future action evidence may reference model adapter inputs and outputs. |

---

## Non-goals

- No runtime model adapter implementation in this branch.
- No new model calls.
- No changes to `/ingest`.
- No endpoints, MCP tools, or sidecar runtime behavior.
- No model tool-calling support.
- No generated tool execution.
- No automatic registry mutation, registration, or installation.
- No model-driven tool installation.
- No apply-patch.
- No replacement for policy, authorization, schema validation, registry truth, or sandbox execution.

---

## Future implementation rules

- Implement local model adapter runtime only in a future branch with explicit approval.
- Start with read-only or proposal-only task types and require structured output validation before persistence.
- Keep `tool_calling_enabled: false` and `generated_tool_execution_allowed: false` unless a future contract explicitly changes the boundary.
- Re-check policy, authorization, registry/schema, and sandbox rules for any plan that came from model output.
- Record adapter evidence before relying on generated summaries, plans, or proposals for human review.
- Keep client and sidecar integrations visibly subordinate to the gateway authority model.
