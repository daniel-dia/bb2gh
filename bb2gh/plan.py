from __future__ import annotations

import argparse
from typing import Callable

from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table

from bb2gh.bb_api import (
    bb_get_deploy_keys,
    bb_get_env_variables,
    bb_get_environments,
    bb_get_pipeline_variables,
)
from bb2gh.gh_api import (
    gh_get_deploy_keys,
    gh_get_environments,
    gh_get_secrets,
    gh_get_variables,
    list_gh_repos,
)
from bb2gh.console import console


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

    console.print(Panel.fit("[bold]PLAN - Comparação Bitbucket <-> GitHub[/bold]", border_style="cyan"))
    console.print()

    only_bb = []
    both = []

    console.print("  Carregando repos do GitHub...", end="")
    gh_repos_map = list_gh_repos(gh_org, gh_headers)
    console.print(f"\r  GitHub: {len(gh_repos_map)} repo(s) acessíveis.{' ' * 20}")

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

    console.print(Rule("RESUMO GERAL", style="cyan"))
    summary_table = Table(show_header=False, box=None, pad_edge=False)
    summary_table.add_column("label", style="bold")
    summary_table.add_column("value")
    summary_table.add_row("Bitbucket (total)", str(len(repos)))
    summary_table.add_row("GitHub (acessíveis)", str(len(gh_repos_map)))
    summary_table.add_row("Só no Bitbucket", f"{len(only_bb)} (serão criados)")
    summary_table.add_row("Em ambos", f"{len(both)} (já migrados)")
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
        done = 0
        for s in slugs:
            if is_shutdown_requested():
                break
            done += 1
            console.print(f"\r  Coletando detalhes BB... {done}/{len(slugs)}", end="")
            slug, data = _fetch_bb_details(s)
            bb_extra[slug] = data
        console.print(f"\r  Detalhes BB coletados.{' ' * 30}")

    if only_bb:
        console.print(Rule(f"SOMENTE NO BITBUCKET - {len(only_bb)} repo(s)", style="green"))
        for repo, gh_name in only_bb:
            slug = repo["slug"]
            extra = bb_extra.get(slug, {})
            console.print(f"\n➡️  {slug} -> {gh_org}/{gh_name}")
            console.print(f"Projeto: {repo.get('project_name') or '-'}")

            bb_vars = extra.get("vars", [])
            if bb_vars:
                console.print(f"Pipeline Variables ({len(bb_vars)})")
                for v in bb_vars:
                    icon = "🔒" if v["secured"] else "➡️"
                    console.print(f"  {icon} {v['key']}")

            bb_envs = extra.get("envs", [])
            if bb_envs:
                console.print(f"Environments ({len(bb_envs)})")
                for e in bb_envs:
                    console.print(f"  ➡️ {e['name']}")

    both_details: dict[str, dict] = {}
    if both:
        console.print(Rule(f"EM AMBOS (BB <-> GH) - {len(both)} repo(s)", style="yellow"))
        done = 0
        for repo, gh_name, _ in both:
            if is_shutdown_requested():
                break
            done += 1
            console.print(f"\r  Comparando repos... {done}/{len(both)}", end="")
            slug = repo["slug"]
            bb_vars = bb_get_pipeline_variables(bb_email, bb_api_token, bb_workspace, slug)
            bb_envs = bb_get_environments(bb_email, bb_api_token, bb_workspace, slug)
            bb_keys = bb_get_deploy_keys(bb_email, bb_api_token, bb_workspace, slug)
            bb_env_vars = {e["uuid"]: bb_get_env_variables(bb_email, bb_api_token, bb_workspace, slug, e["uuid"]) for e in bb_envs}
            both_details[slug] = {
                "bb_vars": bb_vars,
                "bb_envs": bb_envs,
                "bb_keys": bb_keys,
                "bb_env_vars": bb_env_vars,
                "gh_secrets": gh_get_secrets(gh_org, gh_name, gh_headers),
                "gh_vars": gh_get_variables(gh_org, gh_name, gh_headers),
                "gh_envs": gh_get_environments(gh_org, gh_name, gh_headers),
                "gh_keys": gh_get_deploy_keys(gh_org, gh_name, gh_headers),
            }
        console.print(f"\r  Comparação concluída.{' ' * 30}")

        for repo, gh_name, gh_info in both:
            slug = repo["slug"]
            detail = both_details.get(slug, {})
            bb_vars = detail.get("bb_vars", [])
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

            has_diffs = bool(vars_only_bb or vars_only_gh or envs_only_bb or envs_only_gh)
            status_icon = "➡️" if has_diffs else "✅"
            console.print(f"\n{status_icon} {slug} ➡️ {gh_org}/{gh_name}")
            if not has_diffs:
                console.print("  ✅ Tudo sincronizado!")
            for k in vars_only_bb:
                console.print(f"  ➡️ {k:<28} ← só no BB")
            for k in vars_only_gh:
                console.print(f"  ❌ {k:<28} ← só no GH")
            for e in envs_only_bb:
                console.print(f"  ➡️ {e:<28} ← só no BB")
            for e in envs_only_gh:
                console.print(f"  ❌ {e:<28} ← só no GH")

    console.print(Panel.fit("[bold]RESUMO DO PLANO[/bold]", border_style="green"))
    plan_table = Table(show_header=False, box=None, pad_edge=False)
    plan_table.add_column("label", style="bold")
    plan_table.add_column("value")
    plan_table.add_row("Repos a criar no GitHub", str(len(only_bb)))
    plan_table.add_row("Repos já em ambos", str(len(both)))
    console.print(plan_table)
    console.print()
    console.print("Legenda:")
    console.print("✅ sincronizado (nada a fazer)")
    console.print("➡️  só no BB (copiar)")
    console.print("❌ erro / diferença")
    console.print("🔒 segredo: criar manualmente")
