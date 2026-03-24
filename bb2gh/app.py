from __future__ import annotations

import shutil
import signal
import sys
import tempfile
from pathlib import Path

from dotenv import load_dotenv
from rich.panel import Panel
from rich.rule import Rule

from bb2gh.bb_api import list_bb_repos
from bb2gh.cli import filter_repos, parse_args
from bb2gh.console import console
from bb2gh.env import env, env_required
from bb2gh.gh_api import create_gh_repo, list_gh_repos
from bb2gh.plan import run_plan
from bb2gh.sync import mirror_repo, sync_repo_config_bb_to_gh

load_dotenv()

_shutdown_requested = False
_current_work_dir: Path | None = None


def _cleanup():
    if _current_work_dir and _current_work_dir.exists():
        shutil.rmtree(_current_work_dir, ignore_errors=True)


def _handle_shutdown(signum, frame):
    global _shutdown_requested
    sig_name = signal.Signals(signum).name
    if _shutdown_requested:
        print("\n\n  ✗ Forçando saída...")
        _cleanup()
        sys.exit(1)
    _shutdown_requested = True
    print(f"\n\n  ❌ {sig_name} recebido. Finalizando gracefully...")
    print(" (pressione Ctrl+C novamente para forçar)")


def main():
    signal.signal(signal.SIGINT, _handle_shutdown)
    signal.signal(signal.SIGTERM, _handle_shutdown)

    args = parse_args()

    if shutil.which("git") is None:
        print("ERRO: 'git' não encontrado no PATH.")
        sys.exit(1)

    bb_username = env_required("BB_USERNAME")
    bb_email = env_required("BB_EMAIL")
    bb_api_token = env_required("BB_API_TOKEN")
    gh_token = env_required("GH_TOKEN")
    gh_org = env_required("GH_ORG")
    bb_workspace = env("BB_WORKSPACE", bb_username) or bb_username

    private = not args.public
    gh_headers = {
        "Authorization": f"token {gh_token}",
        "Accept": "application/vnd.github.v3+json",
    }

    if args.gh_name and args.repos and "," in args.repos:
        print("ERRO: --gh-name só pode ser usado com um único repo em --repos.")
        sys.exit(1)

    console.print(Panel.fit("[bold]Bitbucket -> GitHub Migration[/bold]", border_style="cyan"))
    console.print(f" Bitbucket workspace : {bb_workspace}")
    console.print(f" GitHub destino      : {gh_org}")
    console.print(f" Repos privados      : {private}")
    console.print(f" Dry run             : {args.dry_run}")
    if args.repos:
        console.print(f" Repos selecionados  : {args.repos}")
    if args.exclude:
        console.print(f" Repos excluídos     : {args.exclude}")
    if args.pattern:
        console.print(f" Pattern             : {args.pattern}")
    if args.gh_prefix:
        console.print(f" Prefixo GitHub      : {args.gh_prefix}")
    if args.force:
        console.print(" Forçar re-migração  : sim")
    console.print()

    console.print(f"Buscando repositórios do Bitbucket (workspace: {bb_workspace})...")
    all_repos = list_bb_repos(bb_email, bb_api_token, bb_workspace)
    console.print(f"Encontrados {len(all_repos)} repositório(s) no Bitbucket.\n")

    if not all_repos:
        print("Nenhum repositório encontrado. Verifique credenciais e workspace.")
        return

    repos = filter_repos(all_repos, args)
    console.print(f"Após filtros: {len(repos)} repositório(s) selecionado(s).\n")
    console.print()

    if args.list:
        return

    if args.dry_run or args.plan:
        run_plan(
            repos,
            args,
            bb_email,
            bb_api_token,
            bb_workspace,
            gh_org,
            gh_headers,
            args.gh_prefix,
            is_shutdown_requested=lambda: _shutdown_requested,
        )
        if args.dry_run:
            print("DRY RUN — nenhuma ação foi executada.\n")
        return

    if not repos:
        print("Nenhum repositório corresponde aos filtros. Nada a fazer.")
        return

    console.print("  Carregando repos do GitHub...")
    gh_repos_map = list_gh_repos(gh_org, gh_headers)
    console.print(f"GitHub: {len(gh_repos_map)} repo(s) acessíveis.\n")

    work_dir = Path(tempfile.mkdtemp(prefix="bb2gh_"))
    global _current_work_dir
    _current_work_dir = work_dir

    success, skipped, failed = 0, 0, 0
    manual_tasks_all: list[str] = []

    for repo in repos:
        if _shutdown_requested:
            print("\n  ❌ Interrompido pelo usuário. Parando migração...")
            break

        slug = repo["slug"]
        gh_name = args.gh_name if args.gh_name else f"{args.gh_prefix}{slug}"

        console.print(Rule(f"Migrando: {slug} -> {gh_org}/{gh_name}", style="cyan"))

        exists = gh_name.lower() in gh_repos_map
        if exists:
            console.print("Repo já existe no GitHub.")

        if not exists:
            if not create_gh_repo(gh_name, repo["description"], private, gh_headers):
                failed += 1
                continue
            gh_repos_map[gh_name.lower()] = {"name": gh_name}

        did_mirror = False
        if not exists or args.force:
            if not repo["clone_url"]:
                console.print("❌ URL de clone não encontrada no Bitbucket. Pulando...")
                failed += 1
                continue

            if mirror_repo(repo["clone_url"], slug, gh_name, work_dir, bb_username, bb_api_token, gh_token, gh_org):
                console.print("✓ Mirror de código concluído.")
                did_mirror = True
            else:
                failed += 1
                continue
        else:
            console.print("➡️  Repo existente: não sobrescrevendo código (use --force para mirror).")

        sync_stats = sync_repo_config_bb_to_gh(bb_email, bb_api_token, bb_workspace, slug, gh_org, gh_name, gh_headers)
        manual_tasks_all.extend(sync_stats["manual_tasks"])

        changes_applied = sync_stats["repo_vars_created"] + sync_stats["envs_created"] + sync_stats["env_vars_created"]
        has_manual = len(sync_stats["manual_tasks"]) > 0

        if sync_stats["errors"] > 0:
            console.print(f"❌ Erros ao sincronizar config: {sync_stats['errors']}")
            failed += 1
            console.print()
            continue

        if exists and not args.force and not did_mirror and changes_applied == 0 and not has_manual:
            console.print("✅ Já estava sincronizado. Nada para copiar.")
            skipped += 1
            console.print()
            continue

        console.print(
            f"Config aplicada: vars={sync_stats['repo_vars_created']}, "
            f"envs={sync_stats['envs_created']}, env_vars={sync_stats['env_vars_created']}"
        )
        if has_manual:
            console.print(f"🔒 Tarefas manuais neste repo: {len(sync_stats['manual_tasks'])}")

        success += 1
        console.print()

    shutil.rmtree(work_dir, ignore_errors=True)
    _current_work_dir = None

    console.print()
    console.print(Panel.fit("[bold]Resumo da migração[/bold]", border_style="green"))
    console.print(f"Sucesso : {success}")
    console.print(f"Pulados : {skipped} (já estavam sincronizados)")
    console.print(f"Falhas  : {failed}")
    console.print(f"Total   : {len(repos)}")

    if manual_tasks_all:
        console.print()
        console.print(Panel.fit("[bold yellow]ALERTA - tarefas manuais necessárias[/bold yellow]", border_style="yellow"))
        unique_tasks = list(dict.fromkeys(manual_tasks_all))
        for t in unique_tasks:
            console.print(f"🔒 {t}")
