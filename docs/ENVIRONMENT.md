# Python environment (standard project venv)

This repo should be run using a **project-local virtual environment** (`.venv`) so the gateway, smoke tests, Cursor/Codex, MCP scripts, and future agents all use the **same interpreter + dependencies**.

## Recommended Python version
- **Python 3.12** is preferred for now.
- Avoid **Python 3.14+** until key dependencies (notably `pydantic-core`) support it cleanly on this machine.

## Why we use a venv
- **Isolates project dependencies** from system/global Python installs.
- Prevents mismatch between `python`, `py -3`, and other launchers.
- Ensures gateway + tests + optional integration scripts all run against the same installed requirements.

## Windows setup (PowerShell)

From the repo root:

```powershell
cd C:\AI\mini-jarvis
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python main.py
```

Or use the helper script:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\setup_venv.ps1
.\.venv\Scripts\Activate.ps1
python main.py
```

## Running tests inside the venv

```powershell
.\.venv\Scripts\Activate.ps1
powershell -ExecutionPolicy Bypass -File .\scripts\run_all_tests.ps1
```

## Running without activating the venv
PowerShell scripts do not automatically “inherit” a venv unless you activate it or explicitly point to its interpreter.

You can set:

```powershell
$env:PYTHON = "C:\AI\mini-jarvis\.venv\Scripts\python.exe"
```

Then run the scripts. Agent tooling should prefer `.venv\Scripts\python.exe` when present.

## Repo convention
- Do **not** use `py -3` by default in this repo.
- Prefer `.venv\Scripts\python.exe` (or `$env:PYTHON`) to avoid launcher/version drift.

