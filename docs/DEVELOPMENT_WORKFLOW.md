# Mini-Jarvis Safe Development Workflow

This workflow lets Hermes, Codex, Cursor, Git, and GitHub work together on Mini-Jarvis while protecting branch scope, secrets, runtime data, and the user's final approval authority.

The default rule is simple: keep every branch narrow, review every diff before staging, never stage broadly, and never commit or push until the user explicitly approves.

## Roles

### Hermes coordinates

Hermes is responsible for:

- reading branch instructions
- reading `HERMES_REPO_RULES.md`
- checking repository status before editing
- identifying pre-existing dirty and untracked files
- keeping the branch scope narrow
- running preflight checks and tests
- showing diffs and changed files
- proposing exact files and a commit message
- waiting for approval before commit or push

Hermes must not bypass Mini-Jarvis policy, approval, registry, sandbox, generated-tool execution, router, or task-state boundaries.

### Codex edits code when needed

Codex may be used only for bounded coding implementation tasks. The prompt to Codex should include:

- the branch goal
- exact in-scope files or directories
- out-of-scope files and runtime behavior that must not change
- tests to run
- a reminder not to stage, commit, push, merge, or force-push

Do not use Codex for broad repository cleanup, visual diff review, mixed-change splitting, or approval decisions.

### Cursor reviews visually

Cursor is useful for:

- visual/manual diff review
- mixed file cleanup
- hunk-level review
- conflict cleanup
- checking docs formatting and examples

Cursor review does not replace the required Git preflight, diff/stat, tests, or user approval.

### User approves final side effects

The user is the only approval authority for:

- committing
- pushing
- merging
- deleting branches
- force operations
- risky file operations

The approval phrase for commit and push is:

```text
Approved: commit and push this branch.
```

## Hard safety rules

Never run these during normal branch work:

```text
git add .
git add -A
git add --all
git push --force
git push --force-with-lease
git reset --hard
git clean -fdx
git merge main
git rebase
```

Never stage these unless the user explicitly approves a branch about them:

- `.env` or secret-bearing `.env.*` files
- credentials, token files, private keys, or API keys
- `data/workspaces/`
- model files and checkpoints such as `*.gguf`, `*.safetensors`, `*.ckpt`, `*.pt`, `*.pth`, `*.onnx`, `*.bin`, `*.model`
- generated caches/build outputs such as `__pycache__/`, `.pytest_cache/`, `.mypy_cache/`, `.ruff_cache/`, `node_modules/`, `dist/`, `build/`, `.next/`, `.vite/`
- unrelated files from other branch work
- line-ending-only noise

Never push directly to `main` or `master`.

## Standard branch loop

### 1. Start from instructions

Read the task file or user request. Identify:

- branch name
- branch goal
- in-scope files
- out-of-scope files
- expected tests
- whether runtime behavior may change

### 2. Run status and preflight

From the repository root:

```powershell
git status --short --branch
powershell -ExecutionPolicy Bypass -File .\scripts\git_branch_preflight.ps1
```

If PowerShell 7 is installed as `pwsh`, this is also fine:

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File .\scripts\git_branch_preflight.ps1
```

Report:

- current branch
- dirty tracked files
- untracked files
- forbidden path warnings
- line-ending-only tracked changes
- whether unrelated pre-existing changes are present

If unrelated dirty files are present, stop and ask before editing or switching branches.

### 3. Create or switch to the approved branch

Only after branch scope is clear:

```powershell
git switch main
git pull --ff-only origin main
git switch -c git-safe-agent-workflow
```

If the branch already exists:

```powershell
git switch git-safe-agent-workflow
```

Do not switch branches with a dirty worktree unless the user explicitly chooses that option.

### 4. Edit only in-scope files

Use Hermes file tools for docs and small scripts. Use Codex only for bounded coding tasks when useful.

For this workflow branch, the intended files are:

```text
HERMES_REPO_RULES.md
docs/DEVELOPMENT_WORKFLOW.md
scripts/git_branch_preflight.ps1
scripts/git_commit_approved_files.ps1
```

This branch must not change Mini-Jarvis runtime behavior.

### 5. Review diffs before tests/staging

Use targeted review commands:

```powershell
git diff --stat -- HERMES_REPO_RULES.md docs/DEVELOPMENT_WORKFLOW.md scripts/git_branch_preflight.ps1 scripts/git_commit_approved_files.ps1
git diff --name-status -- HERMES_REPO_RULES.md docs/DEVELOPMENT_WORKFLOW.md scripts/git_branch_preflight.ps1 scripts/git_commit_approved_files.ps1
git diff -- HERMES_REPO_RULES.md docs/DEVELOPMENT_WORKFLOW.md scripts/git_branch_preflight.ps1 scripts/git_commit_approved_files.ps1
```

Use Cursor for visual review or manual cleanup if a file contains mixed changes.

### 6. Run relevant tests

For docs-only or script-helper branches, run syntax and smoke checks instead of full runtime tests when appropriate.

PowerShell parser check example:

```powershell
powershell -NoProfile -Command "[System.Management.Automation.PSParser]::Tokenize((Get-Content -Raw .\scripts\git_branch_preflight.ps1), [ref]$null) | Out-Null; 'preflight syntax ok'"
powershell -NoProfile -Command "[System.Management.Automation.PSParser]::Tokenize((Get-Content -Raw .\scripts\git_commit_approved_files.ps1), [ref]$null) | Out-Null; 'commit script syntax ok'"
```

Read-only preflight smoke test:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\git_branch_preflight.ps1
powershell -ExecutionPolicy Bypass -File .\scripts\git_branch_preflight.ps1 -Json
```

If runtime code changed, run the branch-specific unit/integration tests documented for that area. Do not claim tests passed unless they actually ran.

### 7. Prepare commit proposal without staging

Before asking for approval, show:

```powershell
git diff --stat -- HERMES_REPO_RULES.md docs/DEVELOPMENT_WORKFLOW.md scripts/git_branch_preflight.ps1 scripts/git_commit_approved_files.ps1
git status --short --branch
```

Then propose:

- exact files to stage
- exact commit message
- tests run and results

Do not stage yet unless the user has already given the approval phrase.

### 8. Commit and push only after approval

After the user says exactly:

```text
Approved: commit and push this branch.
```

run the approved helper with exact files only:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\git_commit_approved_files.ps1 `
  -Files @(
    'HERMES_REPO_RULES.md',
    'docs/DEVELOPMENT_WORKFLOW.md',
    'scripts/git_branch_preflight.ps1',
    'scripts/git_commit_approved_files.ps1'
  ) `
  -Message "docs: add safe agent git workflow" `
  -Confirm "Approved: commit and push this branch."
```

The helper refuses to run on `main` or `master`, refuses forbidden paths, refuses pre-existing staged files, stages only the listed paths, commits, and pushes the current branch.

## Final handoff template

Use this format before waiting for approval:

```text
Branch: <branch>

Changed files proposed for commit:
- <file>

Tests/checks run:
- <command>: <result>

Diff/stat:
<git diff --stat output>

Proposed commit message:
<message>

No files have been staged, committed, or pushed.
Waiting for approval phrase: Approved: commit and push this branch.
```
