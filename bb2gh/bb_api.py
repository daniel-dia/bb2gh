from __future__ import annotations

import requests

BB_API = "https://api.bitbucket.org/2.0"

_bb_pipeline_scope_warned = False


def consume_bb_pipeline_scope_warning() -> bool:
    global _bb_pipeline_scope_warned
    warned = _bb_pipeline_scope_warned
    _bb_pipeline_scope_warned = False
    return warned


def list_bb_repos(bb_email: str, bb_api_token: str, bb_workspace: str) -> list[dict]:
    repos = []
    url = f"{BB_API}/repositories/{bb_workspace}?pagelen=100"

    while url:
        resp = requests.get(url, auth=(bb_email, bb_api_token), timeout=30)
        resp.raise_for_status()
        data = resp.json()

        for repo in data.get("values", []):
            repos.append(_parse_repo(repo))

        url = data.get("next")

    return repos


def _parse_repo(repo: dict) -> dict:
    clone_url = None
    for link in repo.get("links", {}).get("clone", []):
        if link["name"] == "https":
            clone_url = link["href"]
            break

    return {
        "slug": repo["slug"],
        "name": repo.get("name", repo["slug"]),
        "description": repo.get("description", "") or "",
        "clone_url": clone_url,
        "is_private": repo.get("is_private", True),
        "language": repo.get("language", ""),
        "updated_on": repo.get("updated_on", ""),
        "project_key": repo.get("project", {}).get("key", ""),
        "project_name": repo.get("project", {}).get("name", ""),
        "default_branch": repo.get("mainbranch", {}).get("name", "") if repo.get("mainbranch") else "",
        "has_wiki": repo.get("has_wiki", False),
        "has_issues": repo.get("has_issues", False),
    }


def bb_get_repo(bb_email: str, bb_api_token: str, bb_workspace: str, slug: str) -> dict | None:
    url = f"{BB_API}/repositories/{bb_workspace}/{slug}"
    resp = requests.get(url, auth=(bb_email, bb_api_token), timeout=30)
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    return _parse_repo(resp.json())


def bb_get_pipeline_variables(bb_email: str, bb_api_token: str, workspace: str, slug: str) -> list[dict]:
    global _bb_pipeline_scope_warned
    url = f"{BB_API}/repositories/{workspace}/{slug}/pipelines_config/variables/?pagelen=100"
    variables = []
    while url:
        try:
            resp = requests.get(url, auth=(bb_email, bb_api_token), timeout=15)
            if resp.status_code == 404:
                return []
            if resp.status_code == 403:
                if not _bb_pipeline_scope_warned:
                    _bb_pipeline_scope_warned = True
                return []
            resp.raise_for_status()
            data = resp.json()
            for v in data.get("values", []):
                variables.append(
                    {
                        "key": v.get("key", ""),
                        "secured": v.get("secured", False),
                        "value": v.get("value", "***") if not v.get("secured") else "***",
                    }
                )
            url = data.get("next")
        except requests.RequestException:
            return variables
    return variables


def bb_get_environments(bb_email: str, bb_api_token: str, workspace: str, slug: str) -> list[dict]:
    global _bb_pipeline_scope_warned
    url = f"{BB_API}/repositories/{workspace}/{slug}/environments/?pagelen=100"
    envs = []
    while url:
        try:
            resp = requests.get(url, auth=(bb_email, bb_api_token), timeout=15)
            if resp.status_code == 404:
                return []
            if resp.status_code == 403:
                if not _bb_pipeline_scope_warned:
                    _bb_pipeline_scope_warned = True
                return []
            resp.raise_for_status()
            data = resp.json()
            for e in data.get("values", []):
                envs.append(
                    {
                        "name": e.get("name", ""),
                        "type": e.get("environment_type", {}).get("name", ""),
                        "uuid": e.get("uuid", ""),
                    }
                )
            url = data.get("next")
        except requests.RequestException:
            return envs
    return envs


def bb_get_env_variables(bb_email: str, bb_api_token: str, workspace: str, slug: str, env_uuid: str) -> list[dict]:
    url = f"{BB_API}/repositories/{workspace}/{slug}/deployments_config/environments/{env_uuid}/variables?pagelen=100"
    variables = []
    while url:
        try:
            resp = requests.get(url, auth=(bb_email, bb_api_token), timeout=15)
            if resp.status_code in (403, 404):
                return []
            resp.raise_for_status()
            data = resp.json()
            for v in data.get("values", []):
                variables.append(
                    {
                        "key": v.get("key", ""),
                        "secured": v.get("secured", False),
                        "value": v.get("value", "") if not v.get("secured") else "",
                    }
                )
            url = data.get("next")
        except requests.RequestException:
            return variables
    return variables


def bb_get_pull_requests(bb_email: str, bb_api_token: str, workspace: str, slug: str, state: str = "OPEN") -> list[dict]:
    url = f"{BB_API}/repositories/{workspace}/{slug}/pullrequests?state={state}&pagelen=50"
    prs: list[dict] = []
    while url:
        try:
            resp = requests.get(url, auth=(bb_email, bb_api_token), timeout=30)
            if resp.status_code == 404:
                return []
            if resp.status_code == 403:
                raise PermissionError(
                    "BB token missing scope 'read:pullrequest:bitbucket'. "
                    "Add 'Pull requests: Read' to the App Password."
                )
            resp.raise_for_status()
            data = resp.json()
            for pr in data.get("values", []):
                prs.append({
                    "id": pr.get("id"),
                    "title": pr.get("title", ""),
                    "description": pr.get("description", "") or "",
                    "state": pr.get("state", ""),
                    "source_branch": pr.get("source", {}).get("branch", {}).get("name", ""),
                    "destination_branch": pr.get("destination", {}).get("branch", {}).get("name", ""),
                    "author": pr.get("author", {}).get("display_name", ""),
                    "created_on": pr.get("created_on", ""),
                    "updated_on": pr.get("updated_on", ""),
                })
            url = data.get("next")
        except requests.RequestException:
            return prs
    return prs


def bb_comment_pull_request(
    bb_email: str, bb_api_token: str, workspace: str, slug: str, pr_id: int, message: str,
) -> bool:
    url = f"{BB_API}/repositories/{workspace}/{slug}/pullrequests/{pr_id}/comments"
    resp = requests.post(
        url, auth=(bb_email, bb_api_token), json={"content": {"raw": message}}, timeout=15,
    )
    return resp.status_code in (200, 201)


def bb_decline_pull_request(
    bb_email: str, bb_api_token: str, workspace: str, slug: str, pr_id: int,
) -> tuple[bool, str]:
    url = f"{BB_API}/repositories/{workspace}/{slug}/pullrequests/{pr_id}/decline"
    resp = requests.post(url, auth=(bb_email, bb_api_token), timeout=15)
    if resp.status_code in (200, 201):
        return True, ""
    return False, f"{resp.status_code} — {resp.text[:200]}"


def bb_get_deploy_keys(bb_email: str, bb_api_token: str, workspace: str, slug: str) -> list[dict]:
    url = f"{BB_API}/repositories/{workspace}/{slug}/deploy-keys?pagelen=100"
    keys = []
    while url:
        try:
            resp = requests.get(url, auth=(bb_email, bb_api_token), timeout=15)
            if resp.status_code == 404:
                return []
            resp.raise_for_status()
            data = resp.json()
            for k in data.get("values", []):
                keys.append({"label": k.get("label", ""), "id": k.get("id", "")})
            url = data.get("next")
        except requests.RequestException:
            return keys
    return keys