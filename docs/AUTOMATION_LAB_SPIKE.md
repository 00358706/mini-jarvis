# AUTOMATION_LAB_SPIKE

This document describes the proposal-only automation lab spike.

The lab creates review artifacts under `data/automation_lab/<request_id>/` from a user message. It is intentionally deterministic and template-based for now.

## CLI

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\automation_lab_propose.ps1 -Message "Create a tool to list new Navidrome releases"
```

The command prints JSON containing the `request_id`, output folder, artifact list, classification, and authority-boundary flags.

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

## Authority Boundary

Automation lab folders are review evidence only. They do not approve, authorize, install, register, or execute anything.

The spike does not change `/ingest`, add endpoints, add MCP tools, call models, execute tools, call the sandbox worker, or mutate the registry. Capability outcomes are advisory and use the vocabulary from `docs/CAPABILITY_REGISTRY_SCHEMA.md`.

Any future implementation work must remain behind gateway policy, authorization, registry/schema validation, and sandbox execution.
