# Wiki log

Append short notes here when a change introduces new durable knowledge that future sessions will need.

Format:
- Date (UTC), short title
- Links to evidence (workspace id / commit hash / source file / test invocation)
- 1–3 bullet takeaways

Example:
- 2026-05-06 — Added compact workspace review
  - Evidence: commit `<sha>`, `main.py`, `scripts/test_workspace_compact_summary.ps1`
  - Takeaways: approval-card JSON exists; detailed endpoints still available.

- 2026-05-06 — Open WebUI approval workflow clarified
  - Evidence (source): `integrations/openwebui/mini_jarvis_plan_propose.py`, `integrations/openwebui/mini_jarvis_plan_review.py`, `README.md`
  - Evidence (tests): `scripts/test_openwebui_action_wrapper.ps1`, `scripts/test_openwebui_plan_review_wrapper.ps1`
  - Evidence (execution): N/A (wrapper UX + smoke tests only; no gateway authority changes)
  - Takeaways:
    - Wrappers are compact by default; raw JSON requires `DEBUG=1`.
    - Approve and execute remain separate explicit steps (no shortcuts; `--confirm` required).

