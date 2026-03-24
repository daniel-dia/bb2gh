import argparse
import fnmatch


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Migrate repositories from Bitbucket to GitHub.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Required environment variables:
  BB_USERNAME       Bitbucket username
  BB_EMAIL          Atlassian account email (used for API authentication)
  BB_API_TOKEN      Bitbucket API Token (scopes: Repositories:Read and Pipelines:Read)
  GH_TOKEN          GitHub Personal Access Token (scope: repo)
  GH_ORG            Destination GitHub organization or username

Optional environment variables:
  BB_WORKSPACE      Bitbucket workspace (default: BB_USERNAME)
        """,
    )

    sel = p.add_argument_group("repository selection")
    sel.add_argument("--repos", "-r", help="Comma-separated list of slugs to migrate (e.g. repo1,repo2)")
    sel.add_argument("--exclude", "-e", help="Comma-separated list of slugs to EXCLUDE from migration")
    sel.add_argument("--pattern", help="Glob pattern to filter repos by slug (e.g. 'api-*', '*-service')")
    sel.add_argument("--only-private", action="store_true", help="Migrate only private Bitbucket repos")
    sel.add_argument("--only-public", action="store_true", help="Migrate only public Bitbucket repos")
    sel.add_argument("--project", "-p", help="Filter by Bitbucket project (name or key, e.g. 'Development')")

    dest = p.add_argument_group("destination configuration")
    dest.add_argument("--public", action="store_true", help="Create repos as PUBLIC on GitHub (default: private)")
    dest.add_argument("--gh-name", help="Custom name on GitHub (only works with a single repo in --repos)")
    dest.add_argument(
        "--gh-prefix",
        help="Prefix to add to the repo name on GitHub (e.g. 'bb-' -> 'bb-my-repo')",
        default="",
    )

    behav = p.add_argument_group("behavior")
    behav.add_argument("--dry-run", "-n", action="store_true", help="Only list repos that would be migrated, without executing")
    behav.add_argument("--plan", action="store_true", help="Show detailed plan: compare BB vs GH, list vars, secrets, envs, deploy keys")
    behav.add_argument("--force", "-f", action="store_true", help="Force migration even if repo already exists on GitHub (push --mirror)")
    behav.add_argument("--list", "-l", action="store_true", help="List all Bitbucket repos and exit")

    return p.parse_args()


def filter_repos(repos: list[dict], args: argparse.Namespace) -> list[dict]:
    filtered = repos

    if args.repos:
        slugs = {s.strip() for s in args.repos.split(",")}
        filtered = [r for r in filtered if r["slug"] in slugs]

    if args.exclude:
        excluded = {s.strip() for s in args.exclude.split(",")}
        filtered = [r for r in filtered if r["slug"] not in excluded]

    if args.pattern:
        filtered = [r for r in filtered if fnmatch.fnmatch(r["slug"], args.pattern)]

    if args.only_private:
        filtered = [r for r in filtered if r["is_private"]]
    elif args.only_public:
        filtered = [r for r in filtered if not r["is_private"]]

    if args.project:
        proj = args.project.lower()
        filtered = [
            r
            for r in filtered
            if r.get("project_key", "").lower() == proj or r.get("project_name", "").lower() == proj
        ]

    return filtered
