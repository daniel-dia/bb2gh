from __future__ import annotations

import requests

from bb2gh.env import env

GH_API = "https://api.github.com"


def gh_repo_exists(name: str, gh_headers: dict) -> bool:
    resp = requests.get(f"{GH_API}/repos/{env('GH_ORG')}/{name}", headers=gh_headers, timeout=15)
    return resp.status_code == 200


def gh_authenticated_user(gh_headers: dict) -> str:
    resp = requests.get(f"{GH_API}/user", headers=gh_headers, timeout=15)
    resp.raise_for_status()
    return resp.json()["login"]


def list_gh_repos(gh_org: str, gh_headers: dict) -> dict[str, dict]:
    repos = {}
    user = gh_authenticated_user(gh_headers)
    if user == gh_org:
        url = f"{GH_API}/user/repos?per_page=100&type=all"
    else:
        url = f"{GH_API}/orgs/{gh_org}/repos?per_page=100&type=all"

    while url:
        resp = requests.get(url, headers=gh_headers, timeout=30)
        if resp.status_code != 200:
            break
        for r in resp.json():
            repos[r["name"].lower()] = {
                "name": r["name"],
                "private": r.get("private", True),
                "default_branch": r.get("default_branch", ""),
                "description": r.get("description", "") or "",
                "has_wiki": r.get("has_wiki", False),
                "has_issues": r.get("has_issues", False),
            }
        url = None
        links = resp.headers.get("Link", "")
        for part in links.split(","):
            if 'rel="next"' in part:
                url = part.split("<")[1].split(">", 1)[0]

    return repos


def create_gh_repo(name: str, description: str, private: bool, gh_headers: dict) -> bool:
    gh_org = env("GH_ORG")
    user = gh_authenticated_user(gh_headers)
    endpoint = f"{GH_API}/user/repos" if user == gh_org else f"{GH_API}/orgs/{gh_org}/repos"

    payload = {"name": name, "description": description, "private": private}
    resp = requests.post(endpoint, headers=gh_headers, json=payload, timeout=30)
    if resp.status_code in (200, 201):
        print(f"✓ Repo criado no GitHub: {gh_org}/{name}")
        return True

    print(f"✗ Falha ao criar repo: {resp.status_code} — {resp.text[:200]}")
    return False


def gh_get_secrets(gh_org: str, name: str, gh_headers: dict) -> list[str]:
    try:
        resp = requests.get(f"{GH_API}/repos/{gh_org}/{name}/actions/secrets", headers=gh_headers, timeout=15)
        if resp.status_code != 200:
            return []
        return [s["name"] for s in resp.json().get("secrets", [])]
    except requests.RequestException:
        return []


def gh_get_variables(gh_org: str, name: str, gh_headers: dict) -> list[dict]:
    try:
        resp = requests.get(f"{GH_API}/repos/{gh_org}/{name}/actions/variables", headers=gh_headers, timeout=15)
        if resp.status_code != 200:
            return []
        return [{"name": v["name"], "value": v["value"]} for v in resp.json().get("variables", [])]
    except requests.RequestException:
        return []


def gh_get_environments(gh_org: str, name: str, gh_headers: dict) -> list[str]:
    try:
        resp = requests.get(f"{GH_API}/repos/{gh_org}/{name}/environments", headers=gh_headers, timeout=15)
        if resp.status_code != 200:
            return []
        return [e["name"] for e in resp.json().get("environments", [])]
    except requests.RequestException:
        return []


def gh_get_deploy_keys(gh_org: str, name: str, gh_headers: dict) -> list[dict]:
    try:
        resp = requests.get(f"{GH_API}/repos/{gh_org}/{name}/keys", headers=gh_headers, timeout=15)
        if resp.status_code != 200:
            return []
        return [{"title": k.get("title", ""), "read_only": k.get("read_only", True)} for k in resp.json()]
    except requests.RequestException:
        return []


def gh_get_environment_variables(gh_org: str, repo: str, env_name: str, gh_headers: dict) -> dict[str, str]:
    try:
        resp = requests.get(
            f"{GH_API}/repos/{gh_org}/{repo}/environments/{env_name}/variables",
            headers=gh_headers,
            timeout=15,
        )
        if resp.status_code != 200:
            return {}
        return {v.get("name", ""): v.get("value", "") for v in resp.json().get("variables", [])}
    except requests.RequestException:
        return {}


def gh_get_environment_secrets(gh_org: str, repo: str, env_name: str, gh_headers: dict) -> set[str]:
    try:
        resp = requests.get(
            f"{GH_API}/repos/{gh_org}/{repo}/environments/{env_name}/secrets",
            headers=gh_headers,
            timeout=15,
        )
        if resp.status_code != 200:
            return set()
        return {s.get("name", "") for s in resp.json().get("secrets", [])}
    except requests.RequestException:
        return set()


def gh_ensure_environment(gh_org: str, repo: str, env_name: str, gh_headers: dict) -> bool:
    try:
        resp = requests.put(
            f"{GH_API}/repos/{gh_org}/{repo}/environments/{env_name}",
            headers=gh_headers,
            timeout=15,
        )
        return resp.status_code in (200, 201)
    except requests.RequestException:
        return False


def gh_set_repo_variable(gh_org: str, repo: str, key: str, value: str, gh_headers: dict) -> bool:
    try:
        payload = {"name": key, "value": value}
        create = requests.post(
            f"{GH_API}/repos/{gh_org}/{repo}/actions/variables",
            headers=gh_headers,
            json=payload,
            timeout=15,
        )
        if create.status_code in (201, 204):
            return True
        if create.status_code in (409, 422):
            update = requests.patch(
                f"{GH_API}/repos/{gh_org}/{repo}/actions/variables/{key}",
                headers=gh_headers,
                json={"name": key, "value": value},
                timeout=15,
            )
            return update.status_code in (200, 204)
        return False
    except requests.RequestException:
        return False


def gh_set_environment_variable(
    gh_org: str,
    repo: str,
    env_name: str,
    key: str,
    value: str,
    gh_headers: dict,
) -> bool:
    try:
        payload = {"name": key, "value": value}
        create = requests.post(
            f"{GH_API}/repos/{gh_org}/{repo}/environments/{env_name}/variables",
            headers=gh_headers,
            json=payload,
            timeout=15,
        )
        if create.status_code in (201, 204):
            return True
        if create.status_code in (409, 422):
            update = requests.patch(
                f"{GH_API}/repos/{gh_org}/{repo}/environments/{env_name}/variables/{key}",
                headers=gh_headers,
                json={"name": key, "value": value},
                timeout=15,
            )
            return update.status_code in (200, 204)
        return False
    except requests.RequestException:
        return False