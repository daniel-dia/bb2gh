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
            clone_url = None
            for link in repo.get("links", {}).get("clone", []):
                if link["name"] == "https":
                    clone_url = link["href"]
                    break

            repos.append(
                {
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
            )

        url = data.get("next")

    return repos


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