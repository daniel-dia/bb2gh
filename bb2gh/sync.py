from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from bb2gh.bb_api import (
    bb_get_deploy_keys,
    bb_get_env_variables,
    bb_get_environments,
    bb_get_pipeline_variables,
)
from bb2gh.gh_api import (
    gh_ensure_environment,
    gh_get_environment_secrets,
    gh_get_environment_variables,
    gh_get_environments,
    gh_get_secrets,
    gh_get_variables,
    gh_set_environment_variable,
    gh_set_repo_variable,
)
from bb2gh.progress import log_copy_done, log_copy_fail, log_copy_start


def mirror_repo(
    bb_clone_url: str,
    repo_slug: str,
    gh_name: str,
    work_dir: Path,
    bb_username: str,
    bb_api_token: str,
    gh_token: str,
    gh_org: str,
) -> bool:
    local_path = work_dir / f"{repo_slug}.git"
    bb_authed = bb_clone_url.replace("https://", f"https://x-token-auth:{bb_api_token}@")
    gh_url = f"https://{gh_token}@github.com/{gh_org}/{gh_name}.git"

    clone_label = f"Clone bare {repo_slug}"
    log_copy_start(clone_label)
    result = subprocess.run(["git", "clone", "--bare", bb_authed, str(local_path)], capture_output=True, text=True)
    if result.returncode != 0:
        log_copy_fail(clone_label)
        print(f"✗ Falha ao clonar: {result.stderr[:200]}")
        return False
    log_copy_done(clone_label)

    push_label = f"Mirror push {repo_slug}"
    log_copy_start(push_label)
    result = subprocess.run(["git", "push", "--mirror", gh_url], capture_output=True, text=True, cwd=str(local_path))
    if result.returncode != 0:
        log_copy_fail(push_label)
        print(f"✗ Falha no push: {result.stderr[:200]}")
        return False
    log_copy_done(push_label)

    shutil.rmtree(local_path, ignore_errors=True)
    return True


def sync_repo_config_bb_to_gh(
    bb_email: str,
    bb_api_token: str,
    bb_workspace: str,
    bb_slug: str,
    gh_org: str,
    gh_repo: str,
    gh_headers: dict,
) -> dict:
    stats = {
        "repo_vars_created": 0,
        "envs_created": 0,
        "env_vars_created": 0,
        "manual_tasks": [],
        "errors": 0,
    }

    bb_vars = bb_get_pipeline_variables(bb_email, bb_api_token, bb_workspace, bb_slug)
    bb_envs = bb_get_environments(bb_email, bb_api_token, bb_workspace, bb_slug)
    bb_keys = bb_get_deploy_keys(bb_email, bb_api_token, bb_workspace, bb_slug)
    bb_env_vars = {
        e["uuid"]: bb_get_env_variables(bb_email, bb_api_token, bb_workspace, bb_slug, e["uuid"])
        for e in bb_envs
    }

    gh_secrets = gh_get_secrets(gh_org, gh_repo, gh_headers)
    gh_vars = gh_get_variables(gh_org, gh_repo, gh_headers)
    gh_envs = set(gh_get_environments(gh_org, gh_repo, gh_headers))
    gh_all_keys = set(gh_secrets) | {v["name"] for v in gh_vars}

    for v in bb_vars:
        key = v["key"]
        if key in gh_all_keys:
            continue
        if v.get("secured"):
            stats["manual_tasks"].append(f"{gh_org}/{gh_repo}: criar secret de repo '{key}' manualmente")
            continue
        label = f"Repo var {gh_repo}:{key}"
        log_copy_start(label)
        if gh_set_repo_variable(gh_org, gh_repo, key, v.get("value", ""), gh_headers):
            stats["repo_vars_created"] += 1
            log_copy_done(label)
        else:
            stats["errors"] += 1
            log_copy_fail(label)

    for e in bb_envs:
        env_name = e["name"]
        if env_name not in gh_envs:
            env_label = f"Environment {gh_repo}:{env_name}"
            log_copy_start(env_label)
            if gh_ensure_environment(gh_org, gh_repo, env_name, gh_headers):
                stats["envs_created"] += 1
                gh_envs.add(env_name)
                log_copy_done(env_label)
            else:
                stats["errors"] += 1
                log_copy_fail(env_label)
                continue

        gh_env_vars = gh_get_environment_variables(gh_org, gh_repo, env_name, gh_headers)
        gh_env_secrets = gh_get_environment_secrets(gh_org, gh_repo, env_name, gh_headers)

        for ev in bb_env_vars.get(e["uuid"], []):
            key = ev["key"]
            if ev.get("secured"):
                if key in gh_env_secrets:
                    continue
                stats["manual_tasks"].append(
                    f"{gh_org}/{gh_repo}: criar secret do environment '{env_name}' -> '{key}' manualmente"
                )
                continue

            if key in gh_env_vars and gh_env_vars.get(key) == ev.get("value", ""):
                continue

            ev_label = f"Env var {gh_repo}:{env_name}:{key}"
            log_copy_start(ev_label)
            if gh_set_environment_variable(gh_org, gh_repo, env_name, key, ev.get("value", ""), gh_headers):
                stats["env_vars_created"] += 1
                log_copy_done(ev_label)
            else:
                stats["errors"] += 1
                log_copy_fail(ev_label)

    for k in bb_keys:
        stats["manual_tasks"].append(
            f"{gh_org}/{gh_repo}: revisar deploy key '{k.get('label', '')}' e recriar manualmente se necessário"
        )

    return stats
