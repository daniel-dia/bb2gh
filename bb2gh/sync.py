from __future__ import annotations

import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import quote, urlsplit, urlunsplit

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


def _with_basic_auth(url: str, username: str, password: str) -> str:
    parsed = urlsplit(url)
    host = parsed.hostname or parsed.netloc.split("@")[-1]
    if parsed.port:
        host = f"{host}:{parsed.port}"
    user = quote(username, safe="")
    pwd = quote(password, safe="")
    netloc = f"{user}:{pwd}@{host}"
    return urlunsplit((parsed.scheme, netloc, parsed.path, parsed.query, parsed.fragment))


def mirror_repo(
    bb_clone_url: str,
    repo_slug: str,
    gh_name: str,
    work_dir: Path,
    bb_username: str,
    bb_api_token: str,
    gh_token: str,
    gh_org: str,
) -> tuple[bool, str]:
    local_path = work_dir / f"{repo_slug}.git"
    bb_authed = _with_basic_auth(bb_clone_url, bb_username, bb_api_token)
    gh_remote = f"https://github.com/{gh_org}/{gh_name}.git"
    gh_url = _with_basic_auth(gh_remote, "x-access-token", gh_token)

    clone_label = f"Clone bare {repo_slug}"
    log_copy_start(clone_label)
    result = subprocess.run(["git", "clone", "--bare", bb_authed, str(local_path)], capture_output=True, text=True)
    if result.returncode != 0:
        log_copy_fail(clone_label)
        return False, f"Failed to clone: {result.stderr[:200]}"
    log_copy_done(clone_label)

    push_label = f"Mirror push {repo_slug}"
    log_copy_start(push_label)
    # Increase buffer to avoid HTTP 408 timeouts on large repos.
    subprocess.run(
        ["git", "config", "http.postBuffer", "524288000"],
        capture_output=True, text=True, cwd=str(local_path),
    )
    result = subprocess.run(["git", "push", "--mirror", gh_url], capture_output=True, text=True, cwd=str(local_path))
    if result.returncode != 0:
        log_copy_fail(push_label)
        return False, f"Push failed: {result.stderr[:200]}"
    log_copy_done(push_label)

    shutil.rmtree(local_path, ignore_errors=True)
    return True, ""


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
        "error_details": [],
    }
    max_write_workers = 6

    # Light parallelism for remote reads only.
    with ThreadPoolExecutor(max_workers=6) as executor:
        f_bb_vars = executor.submit(bb_get_pipeline_variables, bb_email, bb_api_token, bb_workspace, bb_slug)
        f_bb_envs = executor.submit(bb_get_environments, bb_email, bb_api_token, bb_workspace, bb_slug)
        f_bb_keys = executor.submit(bb_get_deploy_keys, bb_email, bb_api_token, bb_workspace, bb_slug)
        f_gh_secrets = executor.submit(gh_get_secrets, gh_org, gh_repo, gh_headers)
        f_gh_vars = executor.submit(gh_get_variables, gh_org, gh_repo, gh_headers)
        f_gh_envs = executor.submit(gh_get_environments, gh_org, gh_repo, gh_headers)

        bb_vars = f_bb_vars.result()
        bb_envs = f_bb_envs.result()
        bb_keys = f_bb_keys.result()
        gh_secrets = f_gh_secrets.result()
        gh_vars = f_gh_vars.result()
        gh_envs = set(f_gh_envs.result())

    bb_env_vars: dict[str, list[dict]] = {}
    with ThreadPoolExecutor(max_workers=4) as executor:
        env_futures = {
            executor.submit(bb_get_env_variables, bb_email, bb_api_token, bb_workspace, bb_slug, e["uuid"]): e["uuid"]
            for e in bb_envs
        }
        for future in as_completed(env_futures):
            env_uuid = env_futures[future]
            bb_env_vars[env_uuid] = future.result()

    gh_all_keys = set(gh_secrets) | {v["name"] for v in gh_vars}

    repo_var_writes: list[tuple[str, str]] = []
    for v in bb_vars:
        key = v["key"]
        if key in gh_all_keys:
            continue
        if v.get("secured"):
            stats["manual_tasks"].append(f"{gh_org}/{gh_repo}: create repository secret '{key}' manually")
            continue
        repo_var_writes.append((key, v.get("value", "")))

    if repo_var_writes:
        with ThreadPoolExecutor(max_workers=max_write_workers) as executor:
            futures = {
                executor.submit(gh_set_repo_variable, gh_org, gh_repo, key, value, gh_headers): key
                for key, value in repo_var_writes
            }
            for future in as_completed(futures):
                key = futures[future]
                try:
                    ok = future.result()
                except Exception as exc:
                    ok = False
                    stats["error_details"].append(f"repo var '{key}': exception: {exc}")

                if ok:
                    stats["repo_vars_created"] += 1
                else:
                    stats["errors"] += 1
                    if not any(detail.startswith(f"repo var '{key}':") for detail in stats["error_details"]):
                        stats["error_details"].append(f"repo var '{key}': API request failed")

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
                stats["error_details"].append(f"environment '{env_name}': failed to create/ensure")
                log_copy_fail(env_label)
                continue

        with ThreadPoolExecutor(max_workers=2) as executor:
            f_gh_env_vars = executor.submit(gh_get_environment_variables, gh_org, gh_repo, env_name, gh_headers)
            f_gh_env_secrets = executor.submit(gh_get_environment_secrets, gh_org, gh_repo, env_name, gh_headers)
            gh_env_vars = f_gh_env_vars.result()
            gh_env_secrets = f_gh_env_secrets.result()

        env_var_writes: list[tuple[str, str]] = []
        for ev in bb_env_vars.get(e["uuid"], []):
            key = ev["key"]
            if ev.get("secured"):
                if key in gh_env_secrets:
                    continue
                stats["manual_tasks"].append(
                    f"{gh_org}/{gh_repo}: create environment secret '{env_name}' -> '{key}' manually"
                )
                continue

            if key in gh_env_vars and gh_env_vars.get(key) == ev.get("value", ""):
                continue
            env_var_writes.append((key, ev.get("value", "")))

        if env_var_writes:
            with ThreadPoolExecutor(max_workers=max_write_workers) as executor:
                futures = {
                    executor.submit(
                        gh_set_environment_variable, gh_org, gh_repo, env_name, key, value, gh_headers
                    ): key
                    for key, value in env_var_writes
                }
                for future in as_completed(futures):
                    key = futures[future]
                    try:
                        ok = future.result()
                    except Exception as exc:
                        ok = False
                        stats["error_details"].append(
                            f"environment var '{env_name}:{key}': exception: {exc}"
                        )

                    if ok:
                        stats["env_vars_created"] += 1
                    else:
                        stats["errors"] += 1
                        if not any(
                            detail.startswith(f"environment var '{env_name}:{key}':")
                            for detail in stats["error_details"]
                        ):
                            stats["error_details"].append(
                                f"environment var '{env_name}:{key}': API request failed"
                            )

    for k in bb_keys:
        stats["manual_tasks"].append(
            f"{gh_org}/{gh_repo}: review deploy key '{k.get('label', '')}' and recreate it manually if needed"
        )

    return stats
