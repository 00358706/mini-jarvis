# AUTOMATION_LAB_SPIKE

This document describes the proposal-only automation lab spike.

The lab creates review artifacts under `data/automation_lab/<request_id>/` from a user message. It is intentionally deterministic and template-based for now.

Optional local-model drafting can be enabled explicitly for review assistance. It is off by default and model output remains advisory evidence only.

Static capability fixture lookup can also be enabled explicitly to enrich capability-match evidence. Fixtures are advisory hints only; they do not read, install, update, or replace the real registry.

## CLI

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\automation_lab_propose.ps1 -Message "Create a tool to list new Navidrome releases"
```

The command prints JSON containing the `request_id`, output folder, artifact list, classification, and authority-boundary flags.

Optional local model drafting against an OpenAI-compatible local runtime:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\automation_lab_propose.ps1 `
  -Message "Create a tool to list new Navidrome releases" `
  -UseLocalModel `
  -ModelBaseUrl "http://127.0.0.1:10000/v1" `
  -ModelName "local-model"
```

Use `-StrictModel` only when model validation failure should make the CLI fail after writing evidence. Without strict mode, unreachable model endpoints or invalid JSON are recorded and deterministic artifacts remain available.

Optional static capability fixture lookup:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\automation_lab_propose.ps1 `
  -Message "Review repo and summarize project files" `
  -FixturePath ".\fixtures\automation_lab\capabilities.json"
```

Fixture lookup only improves `CAPABILITY_MATCHES.json` fields such as `candidate_tools`, `primary_outcome`, `lookup_notes`, and `outcomes_considered`.

## Artifacts

Each run writes:

- `REQUEST.json`
- `CLASSIFICATION.json`
- `CAPABILITY_MATCHES.json`
- `REVIEW_SUMMARY.md`

Depending on deterministic classification, it may also write one of:

- `ROUTINE_PROPOSAL.md`
- `TOOL_PROPOSAL.md`
- `AGENT_PROPOSAL.md`

When `-UseLocalModel` is set, it also writes:

- `MODEL_REQUEST.json`
- `MODEL_RESPONSE.json`
- `MODEL_VALIDATION.json`
- `MODEL_DRAFT.md`

## Authority Boundary

Automation lab folders are review evidence only. They do not approve, authorize, install, register, or execute anything.

The spike does not change `/ingest`, add endpoints, add MCP tools, execute tools, call the sandbox worker, or mutate the registry. Optional local model calls are disabled by default, use no model tool-calling, and produce advisory draft artifacts only. Capability outcomes are advisory and use the vocabulary from `docs/CAPABILITY_REGISTRY_SCHEMA.md`.

Static fixture lookup is disabled unless `-FixturePath` is passed. Fixture matches remain review evidence only and cannot assert `status=installed`; registry status is still the execution truth after normal manual install and review.

Any future implementation work must remain behind gateway policy, authorization, registry/schema validation, and sandbox execution.
