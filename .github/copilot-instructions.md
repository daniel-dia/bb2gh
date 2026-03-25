# Copilot Instructions for bb2gh

## Project Goal
This repository provides a Python CLI that migrates repositories and selected configuration from Bitbucket to GitHub.

## Key Architecture
- `migrate.py`: thin entrypoint.
- `bb2gh/app.py`: CLI orchestration and run flow.
- `bb2gh/plan.py`: dry-run and comparison output.
- `bb2gh/sync.py`: mirror and config sync execution.
- `bb2gh/bb_api.py` and `bb2gh/gh_api.py`: provider API layers.
- `bb2gh/progress.py`: spinner/status output helpers.

## Behavior Expectations
- Keep logic and CLI display concerns separated.
- Preserve English user-facing CLI strings unless explicitly requested.
- Prefer incremental, minimal patches over broad refactors.
- Do not overwrite or reset unrelated user changes.

## Migration Rules
- Existing GitHub repositories should still be synchronized for config.
- Git mirror overwrite should only happen with force semantics.
- Secrets are treated as sensitive/manual actions where API copy is not available.
- Plan output should highlight sensitive values and required manual actions.

## Logging
- The CLI records output and writes a run log file.
- Default log location: `logs/bb2gh_YYYYMMDD_HHMMSS.log`.
- Custom log path is supported via `--log-file`.
- Keep logs actionable; include per-item error details when sync fails.

## Safe Change Workflow
1. Read affected modules first.
2. Apply the smallest viable change.
3. Run compile validation:
   - `python3 -m py_compile migrate.py bb2gh/*.py`
4. When changing behavior, validate with representative dry-runs.

## Code Style
- Use clear names and small functions.
- Add brief comments only for non-obvious logic.
- Keep ASCII by default.
