#!/usr/bin/env python3
"""
Migrate open pull requests from Bitbucket to GitHub.

Fetches all open PRs from a Bitbucket repo (or list of repos) and
creates corresponding PRs on GitHub.  Missing branches are
automatically fetched from Bitbucket and pushed to GitHub before
creating the PR.

Requer:
    BB_USERNAME    - Bitbucket username
    BB_EMAIL       - Atlassian account email
    BB_API_TOKEN   - Bitbucket App password (Repositories: Read + Pull Requests: Read)
    BB_WORKSPACE   - Bitbucket workspace slug (optional; default = BB_USERNAME)
    GH_TOKEN       - GitHub Personal Access Token (repo scope)
    GH_ORG         - Destination GitHub org or username

Usage:
    python3 scripts/migrate_prs.py --repos repo1,repo2
    python3 scripts/migrate_prs.py --repos repo1 --dry-run
"""
import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import quote, urlsplit, urlunsplit

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv()

import requests

from bb2gh.bb_api import bb_get_pull_requests, bb_comment_pull_request, bb_decline_pull_request
from bb2gh.env import env, env_required
from bb2gh.gh_api import gh_create_pull_request


def _with_basic_auth(url: str, username: str, password: str) -> str:
    parsed = urlsplit(url)
    host = parsed.hostname or parsed.netloc.split("@")[-1]
    if parsed.port:
        host = f"{host}:{parsed.port}"
    user = quote(username, safe="")
    pwd = quote(password, safe="")
    netloc = f"{user}:{pwd}@{host}"
    return urlunsplit((parsed.scheme, netloc, parsed.path, parsed.query, parsed.fragment))


def _gh_branch_exists(gh_org: str, repo: str, branch: str, gh_headers: dict) -> bool:
    resp = requests.get(
        f"https://api.github.com/repos/{gh_org}/{repo}/branches/{branch}",
        headers=gh_headers, timeout=15,
    )
    return resp.status_code == 200


def _push_branch_bb_to_gh(
    slug: str, branch: str, bb_username: str, bb_api_token: str,
    gh_token: str, gh_org: str, gh_repo: str, bb_workspace: str,
) -> tuple[bool, str]:
    """Clone from BB and push a single branch to GH."""
    work_dir = Path(tempfile.mkdtemp(prefix="bb2gh_branch_"))
    local_path = work_dir / slug
    bb_url = _with_basic_auth(
        f"https://bitbucket.org/{bb_workspace}/{slug}.git", bb_username, bb_api_token,
    )
    gh_url = _with_basic_auth(
        f"https://github.com/{gh_org}/{gh_repo}.git", "x-access-token", gh_token,
    )
    max_retries = 3
    try:
        result = subprocess.run(
            ["git", "clone", "--single-branch", "--branch", branch, bb_url, str(local_path)],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            return False, f"clone failed: {result.stderr[:200]}"

        subprocess.run(
            ["git", "config", "http.postBuffer", "524288000"],
            capture_output=True, text=True, cwd=str(local_path),
        )
        subprocess.run(
            ["git", "config", "http.version", "HTTP/1.1"],
            capture_output=True, text=True, cwd=str(local_path),
        )
        subprocess.run(
            ["git", "config", "http.lowSpeedLimit", "1000"],
            capture_output=True, text=True, cwd=str(local_path),
        )
        subprocess.run(
            ["git", "config", "http.lowSpeedTime", "60"],
            capture_output=True, text=True, cwd=str(local_path),
        )

        last_err = ""
        for attempt in range(1, max_retries + 1):
            result = subprocess.run(
                ["git", "push", gh_url, f"{branch}:{branch}"],
                capture_output=True, text=True, cwd=str(local_path),
            )
            if result.returncode == 0:
                return True, ""
            last_err = result.stderr[:200]
            if attempt < max_retries:
                import time
                print(f"      ⟳ Push attempt {attempt}/{max_retries} failed, retrying...")
                time.sleep(2 * attempt)
        return False, f"push failed after {max_retries} attempts: {last_err}"
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Migrate open PRs from Bitbucket to GitHub.")
    p.add_argument("--repos", "-r", required=True, help="Comma-separated repo slugs")
    p.add_argument("--dry-run", "-n", action="store_true", help="List PRs without creating them on GitHub")
    p.add_argument("--decline", action="store_true", help="Decline the BB PR after creating it on GitHub (adds comment with GH link)")
    p.add_argument("--gh-prefix", default="", help="Prefix added to the repo name on GitHub")
    return p.parse_args()


def main() -> None:
    args = parse_args()

    try:
        bb_username = env_required("BB_USERNAME")
        bb_email = env_required("BB_EMAIL")
        bb_api_token = env_required("BB_API_TOKEN")
        gh_token = env_required("GH_TOKEN")
        gh_org = env_required("GH_ORG")
    except ValueError as exc:
        print(exc)
        sys.exit(1)

    bb_workspace = env("BB_WORKSPACE") or env("BB_USERNAME")
    gh_headers = {
        "Authorization": f"token {gh_token}",
        "Accept": "application/vnd.github+json",
    }

    slugs = [s.strip() for s in args.repos.split(",") if s.strip()]
    total_created = 0
    total_skipped = 0
    total_failed = 0

    for slug in slugs:
        gh_repo_name = f"{args.gh_prefix}{slug}"
        print(f"\n{'='*60}")
        print(f"Repo: {slug} -> {gh_org}/{gh_repo_name}")
        print(f"{'='*60}")

        prs = bb_get_pull_requests(bb_email, bb_api_token, bb_workspace, slug)
        if not prs:
            print("  No open PRs found.")
            continue

        print(f"  Found {len(prs)} open PR(s):\n")

        for pr in prs:
            title = pr["title"]
            src = pr["source_branch"]
            dst = pr["destination_branch"]
            author = pr["author"]
            bb_id = pr["id"]

            print(f"  PR #{bb_id}: {title}")
            print(f"    {src} -> {dst}  (by {author})")

            if args.dry_run:
                print("    [dry-run] would create PR on GitHub")
                total_skipped += 1
                continue

            # Ensure both branches exist on GitHub before creating the PR
            branches_ok = True
            for branch in (src, dst):
                if not _gh_branch_exists(gh_org, gh_repo_name, branch, gh_headers):
                    print(f"    ↳ Branch '{branch}' missing on GitHub, pushing...")
                    ok_push, push_err = _push_branch_bb_to_gh(
                        slug, branch, bb_username, bb_api_token,
                        gh_token, gh_org, gh_repo_name, bb_workspace,
                    )
                    if ok_push:
                        print(f"    ↳ Branch '{branch}' pushed OK")
                    else:
                        print(f"    ✗ Failed to push branch '{branch}': {push_err}")
                        branches_ok = False

            if not branches_ok:
                print(f"    ✗ Skipping PR #{bb_id}: branch push failed")
                total_failed += 1
                continue

            body = pr["description"]
            if body:
                body += "\n\n---\n"
            body += f"_Migrated from Bitbucket PR #{bb_id} (by {author})_"

            ok, detail = gh_create_pull_request(
                gh_org, gh_repo_name, title, body, src, dst, gh_headers
            )
            if ok:
                print(f"    ✓ Created: {detail}")
                total_created += 1
                if args.decline:
                    comment = f"This pull request has been moved to GitHub: {detail}"
                    bb_comment_pull_request(bb_email, bb_api_token, bb_workspace, slug, bb_id, comment)
                    declined, decline_err = bb_decline_pull_request(
                        bb_email, bb_api_token, bb_workspace, slug, bb_id,
                    )
                    if declined:
                        print(f"    ✓ Declined on Bitbucket")
                    else:
                        print(f"    ⚠ Failed to decline on Bitbucket: {decline_err}")
            else:
                print(f"    ✗ Skipped: {detail}")
                if "already exists" in detail.lower():
                    total_skipped += 1
                    if args.decline:
                        bb_decline_pull_request(
                            bb_email, bb_api_token, bb_workspace, slug, bb_id,
                        )
                        print(f"    ✓ Declined on Bitbucket (PR already exists on GitHub)")
                else:
                    total_failed += 1

    print(f"\nDone. created={total_created}  skipped={total_skipped}  failed={total_failed}")


if __name__ == "__main__":
    main()
