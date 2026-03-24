from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable

from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table
from rich.text import Text

from bb2gh.bb_api import (
    bb_get_deploy_keys,
    bb_get_env_variables,
    bb_get_environments,
    bb_get_pipeline_variables,
)
from bb2gh.gh_api import (
    gh_get_deploy_keys,
    gh_get_environment_secrets,
    gh_get_environment_variables,
    gh_get_environments,
    gh_get_secrets,
    gh_get_variables,
    list_gh_repos,
)
from bb2gh.console import console
from bb2gh.progress import log_copy_done, log_copy_start


def _render_key_with_badge(key: str) -> Text:
    badge_suffix = " [sensitive]"
    if key.endswith(badge_suffix):
        base_key = key[: -len(badge_suffix)]
        text = Text(base_key)
        text.append(" ")
        text.append("SENSITIVE", style="bold black on yellow")
        return text
    return Text(key)


def run_plan(
    repos: list[dict],
    args: argparse.Namespace,
    bb_email: str,
    bb_api_token: str,
    bb_workspace: str,
    gh_org: str,
    gh_headers: dict,
    gh_prefix: str,
    is_shutdown_requested: Callable[[], bool] | None = None,
):
    if is_shutdown_requested is None:
        is_shutdown_requested = lambda: False

    max_workers = 4

    console.print(Panel.fit("[bold]PLAN - Bitbucket <-> GitHub Comparison[/bold]", border_style="cyan"))
    console.print()

    only_bb = []
    both = []

    load_gh_label = "Loading GitHub repos"
    log_copy_start(load_gh_label)
    gh_repos_map = list_gh_repos(gh_org, gh_headers)
    log_copy_done(load_gh_label)
    console.print(f"GitHub: {len(gh_repos_map)} accessible repo(s).")

    for repo in repos:
        if is_shutdown_requested():
            break
        slug = repo["slug"]
        gh_name = f"{gh_prefix}{slug}" if not args.gh_name else args.gh_name
        gh_info = gh_repos_map.get(gh_name.lower())
        if gh_info:
            both.append((repo, gh_name, gh_info))
        else:
            only_bb.append((repo, gh_name))

    console.print(Rule("GENERAL SUMMARY", style="cyan"))
    summary_table = Table(show_header=False, box=None, pad_edge=False)
    summary_table.add_column("label", style="bold")
    summary_table.add_column("value")
    summary_table.add_row("Bitbucket (total)", str(len(repos)))
    summary_table.add_row("GitHub (accessible)", str(len(gh_repos_map)))
    summary_table.add_row("Only in Bitbucket", f"{len(only_bb)} (will be created)")
    summary_table.add_row("In both", f"{len(both)} (already migrated)")
    console.print(summary_table)
    console.print()

    bb_extra: dict[str, dict] = {}

    def _fetch_bb_details(slug: str) -> tuple[str, dict]:
        data: dict = {
            "vars": bb_get_pipeline_variables(bb_email, bb_api_token, bb_workspace, slug),
            "envs": bb_get_environments(bb_email, bb_api_token, bb_workspace, slug),
            "keys": bb_get_deploy_keys(bb_email, bb_api_token, bb_workspace, slug),
            "env_vars": {},
        }
        for e in data["envs"]:
            data["env_vars"][e["uuid"]] = bb_get_env_variables(bb_email, bb_api_token, bb_workspace, slug, e["uuid"])
        return slug, data

    if only_bb and not is_shutdown_requested():
        slugs = [r["slug"] for r, _ in only_bb]
        collect_bb_label = f"Collecting BB details ({len(slugs)} repos)"
        log_copy_start(collect_bb_label)
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(_fetch_bb_details, s): s for s in slugs if not is_shutdown_requested()}
            for fut in as_completed(futures):
                if is_shutdown_requested():
                    break
                slug, data = fut.result()
                bb_extra[slug] = data
        log_copy_done(collect_bb_label)

    if only_bb:
        console.print(Rule(f"ONLY IN BITBUCKET - {len(only_bb)} repo(s)", style="green"))
        for repo, gh_name in only_bb:
            slug = repo["slug"]
            extra = bb_extra.get(slug, {})
            console.print(f"\n➡️  {slug} -> {gh_org}/{gh_name}")
            console.print(f"Project: {repo.get('project_name') or '-'}")

            bb_vars = extra.get("vars", [])
            if bb_vars:
                console.print(f"Pipeline Variables ({len(bb_vars)})")
                for v in bb_vars:
                    icon = "🔒" if v["secured"] else "➡️ "
                    console.print(f"  {icon} {v['key']}")

            bb_envs = extra.get("envs", [])
            if bb_envs:
                console.print(f"Environments ({len(bb_envs)})")
                for e in bb_envs:
                    console.print(f"  ➡️  {e['name']}")

    both_details: dict[str, dict] = {}
    if both:
        console.print(Rule(f"IN BOTH (BB <-> GH) - {len(both)} repo(s)", style="yellow"))
        compare_label = f"Comparing repos ({len(both)})"
        log_copy_start(compare_label)
        def _fetch_both_repo_detail(repo_item: dict, gh_repo_name: str) -> tuple[str, dict]:
            slug = repo_item["slug"]
            bb_vars = bb_get_pipeline_variables(bb_email, bb_api_token, bb_workspace, slug)
            bb_envs = bb_get_environments(bb_email, bb_api_token, bb_workspace, slug)
            bb_keys = bb_get_deploy_keys(bb_email, bb_api_token, bb_workspace, slug)
            bb_env_vars = {
                e["uuid"]: bb_get_env_variables(bb_email, bb_api_token, bb_workspace, slug, e["uuid"]) for e in bb_envs
            }
            detail = {
                "bb_vars": bb_vars,
                "bb_envs": bb_envs,
                "bb_keys": bb_keys,
                "bb_env_vars": bb_env_vars,
                "gh_secrets": gh_get_secrets(gh_org, gh_repo_name, gh_headers),
                "gh_vars": gh_get_variables(gh_org, gh_repo_name, gh_headers),
                "gh_envs": gh_get_environments(gh_org, gh_repo_name, gh_headers),
                "gh_keys": gh_get_deploy_keys(gh_org, gh_repo_name, gh_headers),
            }
            return slug, detail

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(_fetch_both_repo_detail, repo, gh_name): repo["slug"]
                for repo, gh_name, _ in both
                if not is_shutdown_requested()
            }
            for fut in as_completed(futures):
                if is_shutdown_requested():
                    break
                slug, detail = fut.result()
                both_details[slug] = detail
        log_copy_done(compare_label)

        for repo, gh_name, gh_info in both:
            slug = repo["slug"]
            detail = both_details.get(slug, {})
            bb_vars = detail.get("bb_vars", [])
            bb_var_secured = {v.get("key", ""): bool(v.get("secured")) for v in bb_vars}
            gh_secrets = detail.get("gh_secrets", [])
            gh_vars_list = detail.get("gh_vars", [])
            bb_var_keys = {v["key"] for v in bb_vars}
            gh_all_keys = set(gh_secrets) | {v["name"] for v in gh_vars_list}
            vars_only_bb = sorted(bb_var_keys - gh_all_keys)
            vars_only_gh = sorted(gh_all_keys - bb_var_keys)

            bb_envs = detail.get("bb_envs", [])
            gh_envs = detail.get("gh_envs", [])
            bb_env_names = {e["name"] for e in bb_envs}
            gh_env_names = set(gh_envs)
            envs_only_bb = sorted(bb_env_names - gh_env_names)
            envs_only_gh = sorted(gh_env_names - bb_env_names)

            bb_env_by_name = {e["name"]: e for e in bb_envs}
            shared_envs = sorted(bb_env_names & gh_env_names)
            env_var_diff_rows: list[tuple[str, str, str, str]] = []

            # If the environment does not exist on GH yet, list all BB env vars as pending copy.
            for env_name in envs_only_bb:
                bb_env = bb_env_by_name.get(env_name)
                if not bb_env:
                    continue
                bb_env_items = detail.get("bb_env_vars", {}).get(bb_env["uuid"], [])
                for ev in bb_env_items:
                    key = ev["key"]
                    if ev.get("secured"):
                        env_var_diff_rows.append(
                            (env_name, f"{key} [sensitive]", "only in BB", "[yellow]action required[/yellow]")
                        )
                    else:
                        env_var_diff_rows.append((env_name, key, "only in BB", "copy to GH"))

            for env_name in shared_envs:
                bb_env = bb_env_by_name.get(env_name)
                if not bb_env:
                    continue

                bb_env_items = detail.get("bb_env_vars", {}).get(bb_env["uuid"], [])
                bb_plain_vars = {v["key"]: v.get("value", "") for v in bb_env_items if not v.get("secured")}
                bb_secret_keys = {v["key"] for v in bb_env_items if v.get("secured")}

                gh_env_vars = gh_get_environment_variables(gh_org, gh_name, env_name, gh_headers)
                gh_env_secrets = gh_get_environment_secrets(gh_org, gh_name, env_name, gh_headers)

                diff_lines: list[str] = []

                bb_all_keys = set(bb_plain_vars) | bb_secret_keys
                gh_all_env_keys = set(gh_env_vars) | set(gh_env_secrets)

                for key in sorted(bb_all_keys - gh_all_env_keys):
                    key_label = f"{key} [sensitive]" if key in bb_secret_keys else key
                    action = "[yellow]action required[/yellow]" if key in bb_secret_keys else "copy to GH"
                    diff_lines.append((env_name, key_label, "only in BB", action))
                for key in sorted(gh_all_env_keys - bb_all_keys):
                    key_label = f"{key} [sensitive]" if key in gh_env_secrets else key
                    diff_lines.append((env_name, key_label, "only in GH", "[yellow]action required[/yellow]"))

                for key in sorted(set(bb_plain_vars) & set(gh_env_vars)):
                    if bb_plain_vars.get(key, "") != gh_env_vars.get(key, ""):
                        diff_lines.append((env_name, key, "value differs", "copy to GH"))

                if diff_lines:
                    env_var_diff_rows.extend(diff_lines)

            repo_var_diff_rows: list[tuple[str, str, str]] = []
            for k in vars_only_bb:
                key_label = f"{k} [sensitive]" if bb_var_secured.get(k, False) else k
                action = "[yellow]action required[/yellow]" if bb_var_secured.get(k, False) else "copy to GH"
                repo_var_diff_rows.append((key_label, "only in BB", action))
            for k in vars_only_gh:
                key_label = f"{k} [sensitive]" if k in gh_secrets else k
                repo_var_diff_rows.append((key_label, "only in GH", "[yellow]action required[/yellow]"))

            env_presence_diff_rows: list[tuple[str, str, str]] = []
            for e in envs_only_bb:
                env_presence_diff_rows.append((e, "only in BB", "copy to GH"))
            for e in envs_only_gh:
                env_presence_diff_rows.append((e, "only in GH", "[yellow]action required[/yellow]"))

            has_diffs = bool(repo_var_diff_rows or env_presence_diff_rows or env_var_diff_rows)
            status_icon = "➡️ " if has_diffs else "✅"
            console.print(f"\n{status_icon} {slug} -> {gh_org}/{gh_name}")
            if not has_diffs:
                console.print("  ✅ Fully synchronized!")
                continue

            counts = Table(show_header=False, box=None, pad_edge=False)
            counts.add_column("label", style="bold")
            counts.add_column("value")
            counts.add_row("Repo vars differences", str(len(repo_var_diff_rows)))
            counts.add_row("Environment differences", str(len(env_presence_diff_rows)))
            counts.add_row("Environment var differences", str(len(env_var_diff_rows)))
            console.print(counts)

            if repo_var_diff_rows:
                repo_var_table = Table(title="Repo variables", box=None, pad_edge=False)
                repo_var_table.add_column("Key", style="cyan", no_wrap=True)
                repo_var_table.add_column("Difference", style="yellow")
                repo_var_table.add_column("Action", style="bold")
                for key, diff, action in repo_var_diff_rows:
                    repo_var_table.add_row(_render_key_with_badge(key), diff, action)
                console.print(repo_var_table)

            if env_presence_diff_rows:
                env_presence_table = Table(title="Environments", box=None, pad_edge=False)
                env_presence_table.add_column("Environment", style="cyan", no_wrap=True)
                env_presence_table.add_column("Difference", style="yellow")
                env_presence_table.add_column("Action", style="bold")
                for env_name, diff, action in env_presence_diff_rows:
                    env_presence_table.add_row(env_name, diff, action)
                console.print(env_presence_table)

            if env_var_diff_rows:
                env_vars_table = Table(title="Environment variables", box=None, pad_edge=False)
                env_vars_table.add_column("Environment", style="cyan", no_wrap=True)
                env_vars_table.add_column("Key", style="magenta", no_wrap=True)
                env_vars_table.add_column("Difference", style="yellow")
                env_vars_table.add_column("Action", style="bold")
                for env_name, key, diff, action in env_var_diff_rows:
                    env_vars_table.add_row(env_name, _render_key_with_badge(key), diff, action)
                console.print(env_vars_table)

    console.print(Panel.fit("[bold]PLAN SUMMARY[/bold]", border_style="green"))
    plan_table = Table(show_header=False, box=None, pad_edge=False)
    plan_table.add_column("label", style="bold")
    plan_table.add_column("value")
    plan_table.add_row("Repos to create on GitHub", str(len(only_bb)))
    plan_table.add_row("Repos already in both", str(len(both)))
    console.print(plan_table)
