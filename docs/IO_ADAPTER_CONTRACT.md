# IO_ADAPTER_CONTRACT

Mini-Jarvis will eventually accept many input types from many trusted devices while preserving the gateway authority model.

This document is a docs-only contract. It does not change current `/ingest` behavior, create runtime requirements, add endpoints, add adapters, or authorize execution.

## Purpose

The purpose of this contract is to separate input, context, and execution responsibilities before Mini-Jarvis grows more entry points.

Future trusted-network sources may include a control panel chat bar, iPhone Shortcut, Windows hotkey, Open WebUI wrapper, Discord bot, file/image ingress, or voice ingress. Those sources may help submit requests and context. They must not become execution authorities.

## Adapter Categories

### Client/Input Adapter

What it is:
- A user-facing input surface that submits a request to Mini-Jarvis.
- It may run on a trusted LAN or Tailscale-connected device.

What it may do:
- Collect text, voice transcripts, selected text, clipboard content, images, files, or URLs.
- Submit a user intent or message to a documented gateway/client flow.
- Request a specific agent as a preference.
- Display proposal, policy, approval, execution, and result state.

What it must never do:
- Execute tools directly.
- Treat input, model output, or workspace files as authority.
- Bypass registry, policy, approval, or sandbox checks.
- Auto-approve, auto-execute, or combine approve+execute.
- Hide approval or execution state from the user.

Example adapters:
- Control panel chat bar.
- Open WebUI wrapper.
- iPhone Shortcut.
- Windows hotkey.
- Discord bot.

### Resource/Context Adapter

What it is:
- A read-oriented provider that exposes context or references for review and planning.
- It helps Mini-Jarvis or a human understand available information without granting execution authority.

What it may do:
- Search or summarize available context.
- Expose read-only workspace resources.
- Return references to files, search results, images, or text snippets.
- Mark whether input is untrusted.

What it must never do:
- Approve, reject, execute, or mutate plans.
- Install or run tools.
- Write arbitrary workspace or filesystem state.
- Treat a found resource or file as permission to execute.

Example adapters:
- Windows Search.
- Read-only workspace resources.
- Future file search/context providers.

### Tool/Execution Adapter

What it is:
- A side-effectful capability that performs an action after the gateway approves execution.
- It is not an input surface and not a context provider.

What it may do:
- Execute a registered, installed tool through the approved gateway execution path.
- Perform the specific side effect allowed by policy, approval state, registry status, schema validation, and sandbox execution.

What it must never do:
- Run outside the gateway-controlled registry/policy/approval/sandbox path.
- Self-install from model output.
- Treat a client request as approval.
- Execute before explicit human approval.

Example adapters:
- Edit file.
- Download media.
- Send message.
- Apply patch.
- Any side-effectful operation.

## Authority Boundary

- Gateway remains authority.
- Agents are folders, not services.
- Model output is proposal, not authority.
- Workspace files are evidence and review state, not authority.
- Registry remains the source of truth for installed tools.
- Policy decides whether a proposed plan is allowed.
- Human approval is required before approved-plan execution.
- Approval and execution remain separate.
- Sandbox worker remains the only side-effect execution path.
- Trusted LAN or Tailscale access does not make input, clients, attachments, context adapters, or model output authoritative.

Terminology alignment:
- “Approve” means “approve for later” (no tool execution).
- “Execute” means “execute an already approved plan” (explicit action).
- “Authorize & Run” is a future docs-only mode for an explicit human action after review that binds to the exact reviewed plan content (see `docs/EXECUTION_AUTHORIZATION.md`).

## Normalized Input Envelope

This is a future target shape only. It does not change current `/ingest` behavior and does not create new runtime requirements.

| Field | Type | Purpose |
|-------|------|---------|
| `schema_version` | string | Envelope schema version, for example `io-adapter-input.v1`. |
| `source_client` | string | Client/input adapter identity, for example `control_panel`, `iphone_shortcut`, or `openwebui`. |
| `source_client_version` | string or null | Optional client version/build reference. |
| `device_id` | string or null | Stable local device identifier when available. |
| `message` | string or null | Human-readable request text. |
| `user_intent` | string or null | Normalized request intent if the adapter has one. |
| `input_type` | string | Primary input type, for example `text`, `voice`, `image`, `file`, `url`, `hotkey`, or `chat`. |
| `modalities` | array | Modalities included in the request, for example `text`, `image`, `audio`, or `file`. |
| `attachments` | array | Attachment/reference objects as defined below. |
| `trusted_network` | boolean | Whether the request arrived over a trusted LAN/Tailscale route. This is context, not authority. |
| `requested_agent_id` | string or null | Requested agent preference, not an execution grant. |
| `requested_output_mode` | string or null | Requested response style, for example `chat`, `compact_review`, or `result_preview`. |
| `created_at` | string | ISO 8601 timestamp created by the adapter or gateway. |

Example shape:

```json
{
  "schema_version": "io-adapter-input.v1",
  "source_client": "control_panel",
  "source_client_version": "0.1",
  "device_id": "desktop-01",
  "message": "list project files",
  "user_intent": null,
  "input_type": "chat",
  "modalities": ["text"],
  "attachments": [],
  "trusted_network": true,
  "requested_agent_id": "project_maintainer_agent",
  "requested_output_mode": "compact_review",
  "created_at": "2026-05-07T00:00:00Z"
}
```

## Attachment/Reference Model

Attachments and references are input evidence/context, not execution authority.

| Field | Type | Purpose |
|-------|------|---------|
| `kind` | string | Attachment kind, for example `image`, `audio`, `file`, `url`, `text`, `clipboard`, or `screenshot`. |
| `ref` | string or null | Stable reference, URI, id, or opaque handle when available. |
| `path` | string or null | Local path only when intentionally provided and later validated by gateway/runtime code. |
| `mime_type` | string or null | MIME type if known. |
| `size_bytes` | number or null | Size if known. |
| `source_label` | string or null | Human-readable source label, for example `clipboard`, `camera`, or `selected file`. |
| `untrusted_input` | boolean | Whether the attachment/reference should be treated as untrusted input. |

Example shape:

```json
{
  "kind": "screenshot",
  "ref": "adapter-local-ref-123",
  "path": null,
  "mime_type": "image/png",
  "size_bytes": 245000,
  "source_label": "control panel screenshot",
  "untrusted_input": true
}
```

## Event/Output States

These states are descriptive for future event/feed design. They do not authorize execution.

- `received`
- `normalized`
- `routed`
- `proposal_created`
- `policy_checked`
- `awaiting_approval`
- `approved`
- `execution_started`
- `execution_completed`
- `failed`

Only gateway-controlled approval and execution state can determine whether execution may happen.

## Relationship To Current APIs

Current safe client flow:

1. Propose with `/plans/from-message` or `/plans/propose`.
2. Read `/plans/pending`.
3. Review compact workspace state.
4. Approve or reject explicitly.
5. Execute only after approval.
6. Read completed workspace result state.

Future normalized ingress must not bypass the plan/policy/approval path. New input adapters should feed requests into the gateway-authorized proposal and review lifecycle, not into tools or sandbox execution.

## Future Examples

- Control panel chat feed submits text/file/photo input as a client adapter.
- iPhone Shortcut submits voice/text/photo as a client adapter.
- Windows hotkey submits selected text or clipboard as a client adapter.
- Open WebUI wrapper remains a client adapter.
- Windows Search is a resource/context adapter.
- Discord bot is an optional client/input adapter.

## Generated Tools Rule

If a request requires a capability that does not exist, Mini-Jarvis may propose a tool design or implementation plan, but must not install or execute generated tools automatically.

Generated tool work must remain proposal-only until reviewed, approved through the tool lifecycle, installed in the registry, and executed only through the approved gateway/sandbox path.

## Required Final Branch Summary Format

Use this format in final handoff:

- files changed
- behavior changed
- tests run
- contract summary
- authority-boundary confirmation

