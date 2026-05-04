# Example outputs (documentation only)

Illustrative shapes for plans and proposals. Conceptual tool names are **not** in the registry yet.

---

## Example A — Architecture review (no tools executed)

**Maintainer ask:** "Does our README still match the ingest pipeline?"

**Proposed response shape:**

1. **Manual / conceptual steps** (today): Compare `README.md` sections to `dispatch.py` and `tools.execute` flow; list any drift (e.g. missing audit mention).
2. **Future step** (when registered): `check_invariants` — compare documented pipeline strings to module docstrings.

**Claim discipline:** "If you adopt these edits, apply them in the editor; this agent did not modify files."

---

## Example B — Proposed documentation patch (text only)

**Maintainer ask:** "Add a note that agents/ is config-only."

**Proposed patch suggestion** (for human to apply):

```text
--- a/README.md
+++ b/README.md
@@ ... @@
 ## agents/ — configuration only
+New agent folders under `agents/` describe workflow intent only until wired by maintainers.
```

---

## Example C — Refactor plan (reviewable)

**Goal:** Split a long function without changing behavior.

**Proposed plan:**

1. Identify pure helpers vs I/O in `example_module.py` (read-only reasoning).
2. Propose extraction with identical signatures; no dispatch/sandbox edits.
3. Run tests / smoke checks **after maintainer applies** the patch (agent does not run them unless future tools exist and gateway permits).

---

## Example D — Conceptual tool sequence (future registry)

When `inspect_file` and `propose_patch` exist and are **installed** in the registry:

1. `inspect_file` — path `sandbox.py`, scope `docstring+exports`
2. `propose_patch` — unified diff for review only

Until then, describe the same steps in natural language without implying execution.
