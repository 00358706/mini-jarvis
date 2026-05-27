# Hermes Repo Rules for Mini-Jarvis

Hermes may coordinate Mini-Jarvis development, call Codex for bounded coding tasks, run tests, and prepare GitHub branches. Mini-Jarvis remains the authority layer: do not bypass or weaken gateway policy, approval, registry, sandbox, generated-tool execution, router, or task-state boundaries.

## Roles

- **Hermes**: coordinator, branch manager, preflight runner, test runner, and summary writer.
- **Codex**: bounded coding executor when implementation changes are needed.
- **Cursor**: visual/manual review tool for diffs, mixed files, hunk cleanup, and conflict cleanup.
- **User**: final approval authority for commit, push, merge, branch deletion, and risky operations.
- **GitHub**: remote branch and pull-request target only after approval.

## Required workflow

1. Before any work:
   - run `git status --short --branch`
   - run `powershell -ExecutionPolicy Bypass -File .\scripts\git_branch_preflight.ps1` when PowerShell is available
   - report current branch
   - report dirty tracked files
   - report untracked files
   - identify pre-existing changes before editing

2. Branch scope:
   - work only on the approved branch
   - keep changes branch-scoped
   - stop and ask if unrelated dirty files are present
   - do not switch branches with a dirty worktree unless the user explicitly chooses that path

3. Editing:
   - use Codex only for bounded implementation tasks when needed
   - use Hermes for coordination, docs, tests, summaries, and exact file operations
   - use Cursor for visual review/manual diff cleanup, especially mixed files
   - do not edit secrets or `.env`
   - do not modify model files, data/workspaces, generated caches, or unrelated files
   - do not change Mini-Jarvis runtime behavior unless the branch explicitly requires it

4. Testing:
   - run branch-specific tests
   - run syntax checks for touched scripts when available
   - report pass/fail honestly
   - do not claim tests passed unless they actually ran

5. Review before staging:
   - show `git diff --stat`
   - show changed files
   - show untracked files
   - identify forbidden/sensitive paths
   - identify line-ending-only noise
   - confirm the exact files proposed for commit

6. Staging:
   - never use `git add .`
   - never use `git add -A` or `git add --all`
   - stage only files explicitly listed for the approved branch
   - show exact staged files with `git diff --cached --name-status` before commit

7. Commit and push:
   - do not commit without explicit user approval
   - do not push without explicit user approval
   - do not merge to main
   - do not force push
   - do not delete branches

## Approval phrase

Only after the user says exactly:

```text
Approved: commit and push this branch.
```

may Hermes stage approved files, commit, and push the current branch.

## Forbidden commands unless explicitly requested

- `git add .`
- `git add -A`
- `git add --all`
- `git push --force`
- `git push --force-with-lease`
- `git reset --hard`
- `git clean -fdx`
- `git merge main`
- `git rebase`
- deleting branches
- modifying `.env`
- staging secrets, credentials, or token files
- staging `data/workspaces`
- staging model files
- staging generated caches

## Forbidden paths for normal branch commits

Do not stage these unless the user explicitly approves a branch that is about those files:

- `.env`, `.env.*` files containing secrets, credentials, API keys, tokens, or local-only config
- private keys such as `id_rsa`, `id_ed25519`, or credential stores
- `data/workspaces/`
- model/checkpoint artifacts such as `*.gguf`, `*.safetensors`, `*.ckpt`, `*.pt`, `*.pth`, `*.onnx`, `*.bin`, `*.model`
- generated caches/build outputs such as `__pycache__/`, `.pytest_cache/`, `.mypy_cache/`, `.ruff_cache/`, `node_modules/`, `dist/`, `build/`, `.next/`, `.vite/`

## Mini-Jarvis runtime safety

Branches that only add workflow documentation or Git helper scripts must not change:

- gateway authority behavior
- approval semantics
- registry semantics
- sandbox execution behavior
- generated-tool execution behavior
- router behavior
- local model routing behavior
- runtime agent behavior
