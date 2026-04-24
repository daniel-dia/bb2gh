from __future__ import annotations

import shutil
import signal
import sys
import tempfile
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table

from bb2gh.bb_api import (
    consume_bb_pipeline_scope_warning,
    bb_get_repo,
    bb_get_pull_requests,
    bb_comment_pull_request,
    bb_decline_pull_request,
    list_bb_repos,
)
from bb2gh.cli import filter_repos, parse_args
from bb2gh.console import console, save_console_log
from bb2gh.env import env, env_required
from bb2gh.gh_api import create_gh_repo, gh_create_pull_request, list_gh_repos
from bb2gh.plan import run_plan
from bb2gh.progress import log_copy_done, log_copy_start
from bb2gh.sync import mirror_repo, push_branch_bb_to_gh, sync_repo_config_bb_to_gh

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
        console.print("\n\n  ✗ Forcing exit...")
        _cleanup()
        sys.exit(1)
    _shutdown_requested = True
    console.print(f"\n\n  ❌ {sig_name} received. Shutting down gracefully...")
    console.print(" (press Ctrl+C again to force)")


def _print_bb_pipeline_scope_warning_if_needed():
    if consume_bb_pipeline_scope_warning():
        console.print("\n  ❌ 403 - BB token missing permission 'read:pipeline:bitbucket'.")
        console.print("   Pipeline vars/environments will not be listed.")
        console.print("   Add 'Pipelines: Read' scope to the token.\n")


def main():
    signal.signal(signal.SIGINT, _handle_shutdown)
    signal.signal(signal.SIGTERM, _handle_shutdown)

    args = parse_args()
    default_log_path = Path("logs") / f"bb2gh_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    log_path = Path(args.log_file) if args.log_file else default_log_path

    try:
        _main_impl(args)
    finally:
        save_console_log(log_path)
        console.print(f"\n📝 Log saved to: {log_path}")


def _main_impl(args):

    if shutil.which("git") is None:
        console.print("ERROR: 'git' not found in PATH.")
        sys.exit(1)

    try:
        bb_username = env_required("BB_USERNAME")
        bb_email = env_required("BB_EMAIL")
        bb_api_token = env_required("BB_API_TOKEN")
        gh_token = env_required("GH_TOKEN")
        gh_org = env_required("GH_ORG")
    except ValueError as exc:
        console.print(str(exc))
        sys.exit(1)
    bb_workspace = env("BB_WORKSPACE", bb_username) or bb_username

    private = not args.public
    gh_headers = {
        "Authorization": f"token {gh_token}",
        "Accept": "application/vnd.github.v3+json",
    }

    if args.gh_name and args.repos and "," in args.repos:
        console.print("ERROR: --gh-name can only be used with a single repo in --repos.")
        sys.exit(1)

    console.print(Panel.fit("[bold]Bitbucket -> GitHub Migration[/bold]", border_style="cyan"))
    console.print(f" Bitbucket workspace : {bb_workspace}")
    console.print(f" GitHub target       : {gh_org}")
    console.print(f" Private repos       : {private}")
    console.print(f" Dry run             : {args.dry_run}")
    if args.repos:
        console.print(f" Selected repos      : {args.repos}")
    if args.exclude:
        console.print(f" Excluded repos      : {args.exclude}")
    if args.pattern:
        console.print(f" Pattern             : {args.pattern}")
    if args.gh_prefix:
        console.print(f" GitHub prefix       : {args.gh_prefix}")
    if args.force:
        console.print(" Force re-migration  : yes")
    console.print()

    # When --repos is given and no filters need the full list, fetch only those repos.
    needs_full_list = args.list or args.exclude or args.pattern or args.only_private or args.only_public or args.project
    if args.repos and not needs_full_list:
        slugs = [s.strip() for s in args.repos.split(",")]
        fetch_bb_label = f"Fetching {len(slugs)} Bitbucket repo(s)"
        log_copy_start(fetch_bb_label)
        all_repos = []
        for slug in slugs:
            repo = bb_get_repo(bb_email, bb_api_token, bb_workspace, slug)
            if repo:
                all_repos.append(repo)
            else:
                console.print(f"⚠ Repository not found on Bitbucket: {slug}")
        log_copy_done(fetch_bb_label)
        console.print(f"Found {len(all_repos)} repository(ies) on Bitbucket.\n")
        repos = all_repos
    else:
        fetch_bb_label = f"Fetching Bitbucket repositories ({bb_workspace})"
        log_copy_start(fetch_bb_label)
        all_repos = list_bb_repos(bb_email, bb_api_token, bb_workspace)
        log_copy_done(fetch_bb_label)
        console.print(f"Found {len(all_repos)} repository(ies) on Bitbucket.\n")

        if not all_repos:
            console.print("No repositories found. Check credentials and workspace.")
            return

        repos = filter_repos(all_repos, args)

    console.print(f"After filters: {len(repos)} repository(ies) selected.\n")
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
            console.print("DRY RUN - no action was executed.\n")
        _print_bb_pipeline_scope_warning_if_needed()
        return

    if not repos:
        console.print("No repositories match the filters. Nothing to do.")
        return

    load_gh_label = "Loading GitHub repositories"
    log_copy_start(load_gh_label)
    gh_repos_map = list_gh_repos(gh_org, gh_headers)
    log_copy_done(load_gh_label)
    console.print(f"GitHub: {len(gh_repos_map)} accessible repo(s).\n")

    work_dir = Path(tempfile.mkdtemp(prefix="bb2gh_"))
    global _current_work_dir
    _current_work_dir = work_dir

    success, skipped, failed = 0, 0, 0
    manual_tasks_all: list[str] = []

    for repo in repos:
        if _shutdown_requested:
            console.print("\n  ❌ Interrupted by user. Stopping migration...")
            break

        slug = repo["slug"]
        gh_name = args.gh_name if args.gh_name else f"{args.gh_prefix}{slug}"

        console.print(Rule(f"MIGRATING: {slug} -> {gh_org}/{gh_name}", style="cyan"))

        exists = gh_name.lower() in gh_repos_map
        if exists:
            console.print("Repository already exists on GitHub.")

        if not exists:
            created, create_error = create_gh_repo(gh_name, repo["description"], private, gh_headers)
            if not created:
                console.print(f"❌ Failed to create repository: {create_error}")
                failed += 1
                continue
            console.print(f"✓ Repository created on GitHub: {gh_org}/{gh_name}")
            gh_repos_map[gh_name.lower()] = {"name": gh_name}

        did_mirror = False
        if not exists or args.force:
            if not repo["clone_url"]:
                console.print("❌ Clone URL not found in Bitbucket. Skipping...")
                failed += 1
                continue

            mirrored, mirror_error = mirror_repo(
                repo["clone_url"], slug, gh_name, work_dir, bb_username, bb_api_token, gh_token, gh_org
            )
            if mirrored:
                console.print("✓ Code mirror completed.")
                did_mirror = True
            else:
                console.print(f"❌ {mirror_error}")
                failed += 1
                continue
        else:
            console.print("➡️   Existing repository: not overwriting code (use --force for mirror).")

        sync_stats = sync_repo_config_bb_to_gh(bb_email, bb_api_token, bb_workspace, slug, gh_org, gh_name, gh_headers)
        manual_tasks_all.extend(sync_stats["manual_tasks"])

        changes_applied = sync_stats["repo_vars_created"] + sync_stats["envs_created"] + sync_stats["env_vars_created"]
        has_manual = len(sync_stats["manual_tasks"]) > 0

        if sync_stats["errors"] > 0:
            console.print(f"❌ Errors while syncing config: {sync_stats['errors']}")
            for detail in sync_stats.get("error_details", []):
                console.print(f"[status.fail]      - {detail}[/status.fail]")
            failed += 1
            console.print()
            continue

        if exists and not args.force and not did_mirror and changes_applied == 0 and not has_manual:
            console.print("✅ Already synchronized. Nothing to copy.")
            skipped += 1
            console.print()
            continue

        repo_summary = Table(show_header=False, box=None, pad_edge=False)
        repo_summary.add_column("label", style="bold")
        repo_summary.add_column("value")
        repo_summary.add_row("Repo vars copied", str(sync_stats["repo_vars_created"]))
        repo_summary.add_row("Environments created", str(sync_stats["envs_created"]))
        repo_summary.add_row("Environment vars copied", str(sync_stats["env_vars_created"]))
        repo_summary.add_row("Manual actions required", str(len(sync_stats["manual_tasks"])))
        console.print(repo_summary)

        if has_manual:
            manual_table = Table(title="Manual actions", box=None, pad_edge=False)
            manual_table.add_column("Item", style="yellow")
            manual_table.add_column("Action", style="bold")
            for task in sync_stats["manual_tasks"]:
                manual_table.add_row(task, "manual action required")
            console.print(manual_table)

        success += 1
        console.print()

    # --- PR migration ---
    migrate_prs = args.migrate_prs or args.decline_prs
    prs_created = 0
    prs_skipped = 0
    prs_failed = 0
    prs_declined = 0

    if migrate_prs and not _shutdown_requested:
        console.print(Rule("Pull Request Migration", style="magenta"))
        for repo in repos:
            if _shutdown_requested:
                break
            slug = repo["slug"]
            gh_name = args.gh_name if args.gh_name else f"{args.gh_prefix}{slug}"

            try:
                prs = bb_get_pull_requests(bb_email, bb_api_token, bb_workspace, slug)
            except PermissionError as exc:
                console.print(f"  ❌ {slug}: {exc}")
                continue

            if not prs:
                continue

            console.print(f"\n  [bold]{slug}[/bold]: {len(prs)} open PR(s)")

            for pr in prs:
                if _shutdown_requested:
                    break
                title = pr["title"]
                src = pr["source_branch"]
                dst = pr["destination_branch"]
                author = pr["author"]
                bb_id = pr["id"]

                console.print(f"    PR #{bb_id}: {title}  ({src} -> {dst})")

                # Push missing branches
                for branch in (src, dst):
                    import requests as _requests
                    resp = _requests.get(
                        f"https://api.github.com/repos/{gh_org}/{gh_name}/branches/{branch}",
                        headers=gh_headers, timeout=15,
                    )
                    if resp.status_code != 200:
                        console.print(f"      ↳ Pushing branch '{branch}'...")
                        ok_b, err_b = push_branch_bb_to_gh(
                            slug, branch, bb_username, bb_api_token,
                            gh_token, gh_org, gh_name, bb_workspace,
                        )
                        if ok_b:
                            console.print(f"      ↳ Branch '{branch}' pushed OK")
                        else:
                            console.print(f"      ✗ Failed to push '{branch}': {err_b}")

                body = pr["description"]
                if body:
                    body += "\n\n---\n"
                body += f"_Migrated from Bitbucket PR #{bb_id} (by {author})_"

                ok, detail = gh_create_pull_request(
                    gh_org, gh_name, title, body, src, dst, gh_headers,
                )
                if ok:
                    console.print(f"      ✓ Created: {detail}")
                    prs_created += 1
                    if args.decline_prs:
                        comment = f"This pull request has been moved to GitHub: {detail}"
                        bb_comment_pull_request(bb_email, bb_api_token, bb_workspace, slug, bb_id, comment)
                        declined, decline_err = bb_decline_pull_request(
                            bb_email, bb_api_token, bb_workspace, slug, bb_id,
                        )
                        if declined:
                            console.print(f"      ✓ Declined on Bitbucket")
                            prs_declined += 1
                        else:
                            console.print(f"      ⚠ Failed to decline: {decline_err}")
                else:
                    if "already exists" in detail.lower():
                        console.print(f"      ➡️  PR already exists on GitHub")
                        prs_skipped += 1
                    else:
                        console.print(f"      ✗ Failed: {detail}")
                        prs_failed += 1

    shutil.rmtree(work_dir, ignore_errors=True)
    _current_work_dir = None

    console.print()
    console.print(Panel.fit("[bold]Migration Summary[/bold]", border_style="green"))
    console.print(f"Success : {success}")
    console.print(f"Skipped : {skipped} (already synchronized)")
    console.print(f"Failed  : {failed}")
    console.print(f"Total   : {len(repos)}")

    if migrate_prs:
        console.print()
        console.print(Panel.fit("[bold]Pull Requests[/bold]", border_style="magenta"))
        console.print(f"PRs created  : {prs_created}")
        console.print(f"PRs skipped  : {prs_skipped} (already exist)")
        console.print(f"PRs failed   : {prs_failed}")
        if args.decline_prs:
            console.print(f"PRs declined : {prs_declined}")

    if manual_tasks_all:
        console.print()
        console.print(Panel.fit("[bold yellow]ALERT - Manual tasks required[/bold yellow]", border_style="yellow"))
        unique_tasks = list(dict.fromkeys(manual_tasks_all))
        for t in unique_tasks:
            console.print(f"🔒 {t}")

    _print_bb_pipeline_scope_warning_if_needed()
