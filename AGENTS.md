# AGENTS

This repository defines practical agent roles for day-to-day work on `bb2gh`.
Use these roles as operating modes in Copilot/AI sessions.

## 1) Planner Agent

**Goal**: Build a safe migration plan before any write action.

**Primary scope**:
- `bb2gh/plan.py`
- `bb2gh/bb_api.py`
- `bb2gh/gh_api.py`

**Default behavior**:
- Prefer dry-run analysis (`--dry-run` / `--plan`).
- Compare BB vs GH repo vars, environments, and environment vars.
- For missing GH environments, list all BB env vars as pending.
- Mark sensitive data and manual tasks clearly.

**Validation commands**:
```bash
python migrate.py --dry-run --repos <slug>
python3 -m py_compile migrate.py bb2gh/*.py
```

## 2) Sync Agent

**Goal**: Execute migration and config sync safely.

**Primary scope**:
- `bb2gh/sync.py`
- `bb2gh/app.py`

**Default behavior**:
- Mirror code only when needed (`--force` required to overwrite mirror).
- Sync config even when repo already exists on GitHub.
- Keep secrets as manual actions when APIs do not allow copy.
- Preserve bounded concurrency for reads/writes.

**Validation commands**:
```bash
python migrate.py --repos <slug>
python3 -m py_compile migrate.py bb2gh/*.py
```

## 3) Diagnostics Agent

**Goal**: Turn failures into actionable output.

**Primary scope**:
- `bb2gh/sync.py`
- `bb2gh/app.py`
- `bb2gh/progress.py`
- `bb2gh/console.py`

**Default behavior**:
- Capture per-item error details (scope, env, key, reason).
- Keep logs actionable and readable.
- Avoid count-only failures when details are available.
- Prevent noisy spinner artifacts from polluting exported logs.

**Validation commands**:
```bash
python migrate.py --dry-run --repos <slug> --log-file logs/test.log
python3 -m py_compile migrate.py bb2gh/*.py
```

## Global Rules For All Agents

- Keep user-facing CLI messages in English unless explicitly requested otherwise.
- Prefer minimal patches; avoid broad refactors.
- Do not revert unrelated user changes.
- Preserve architecture boundaries between orchestration, API access, plan, and sync layers.
- After behavior changes, validate with representative dry-runs.
