#!/usr/bin/env python3
"""
Gera bitbucket_repos.md com todos os repositórios do workspace,
agrupados por projeto.

Requer:
    BB_EMAIL       - e-mail da conta Bitbucket
    BB_API_TOKEN   - App password do Bitbucket
    BB_WORKSPACE   - workspace slug (opcional; padrão = prefixo do e-mail)

Uso:
    python3 scripts/list_repos.py [--out caminho/saida.md]
"""
import argparse
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bb2gh.bb_api import list_bb_repos
from bb2gh.env import env, env_required
from bb2gh.gh_api import list_gh_repos

# Status values:
#   Somente no BB  – exists only in Bitbucket
#   Somente no GH  – exists only in GitHub
#   Em ambos       – present in both (BB still authoritative)
#   Migrado        – present in both and GH is now the authority
#                    (mark manually by adding slug to MIGRATED_SLUGS below)

MIGRATED_SLUGS: set[str] = set()


def main() -> None:
    parser = argparse.ArgumentParser(description="Lista repos do Bitbucket em Markdown.")
    parser.add_argument("--out", default="bitbucket_repos.md", help="Arquivo de saída (default: bitbucket_repos.md)")
    args = parser.parse_args()

    try:
        bb_email = env_required("BB_EMAIL")
        bb_api_token = env_required("BB_API_TOKEN")
    except ValueError as e:
        print(e)
        sys.exit(1)

    bb_workspace = env("BB_WORKSPACE") or bb_email.split("@")[0]
    gh_token = env("GH_TOKEN")
    gh_org   = env("GH_ORG")

    print(f"Buscando repositórios do workspace: {bb_workspace} ...")
    repos = list_bb_repos(bb_email, bb_api_token, bb_workspace)
    print(f"  {len(repos)} repositórios encontrados no Bitbucket.")

    gh_repos: dict[str, dict] = {}
    if gh_token and gh_org:
        gh_headers = {"Authorization": f"token {gh_token}", "Accept": "application/vnd.github+json"}
        print(f"Buscando repositórios do GitHub ({gh_org}) ...")
        gh_repos = list_gh_repos(gh_org, gh_headers)
        print(f"  {len(gh_repos)} repositórios encontrados no GitHub.")
    else:
        print("  GH_TOKEN / GH_ORG não definidos; status do GitHub omitido.")

    # Agrupar por projeto (usado apenas para o contador no cabeçalho)
    by_project: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for r in repos:
        key = (r["project_key"] or "—", r["project_name"] or "Sem Projeto")
        by_project[key].append(r)

    # Repos que existem no GH mas não no BB
    bb_slugs = {r["slug"].lower() for r in repos}
    gh_only = sorted(s for s in gh_repos if s not in bb_slugs)

    lines: list[str] = [
        f"# Repositórios Bitbucket — `{bb_workspace}`\n",
        f"_Total: {len(repos)} no BB · {len(gh_repos)} no GH · {len(gh_only)} somente no GH_\n",
        "| Repositório | Projeto | Linguagem | Branch padrão | Status | Atualizado |",
        "|-------------|---------|-----------|:-------------:|:------:|:----------:|",
    ]

    all_repos = sorted(repos, key=lambda r: (r.get("project_name") or "").lower() + r["name"].lower())
    for r in all_repos:
        pname = r.get("project_name") or "Sem Projeto"
        pkey  = r.get("project_key") or "—"
        lang  = r["language"] or "—"
        branch = r["default_branch"] or "—"
        updated = (r["updated_on"] or "")[:10]
        clone_url = r["clone_url"] or ""
        slug_lower = r["slug"].lower()

        if slug_lower in MIGRATED_SLUGS:
            status = "Migrado"
        elif slug_lower in gh_repos:
            status = "Em ambos"
        elif gh_repos:
            status = "Somente no BB"
        else:
            status = "—"

        lines.append(
            f"| [{r['name']}]({clone_url}) | {pname} (`{pkey}`) | {lang} | {branch} | {status} | {updated} |"
        )

    # Linhas para repos que existem somente no GH
    if gh_only:
        lines.append("")
        lines.append("## Somente no GitHub\n")
        lines.append("| Repositório | Status |")
        lines.append("|-------------|:------:|")
        for slug in gh_only:
            gh_url = f"https://github.com/{gh_org}/{slug}"
            lines.append(f"| [{slug}]({gh_url}) | Somente no GH |")

    md = "\n".join(lines)

    out_path = Path(args.out)
    out_path.write_text(md, encoding="utf-8")
    print(f"Markdown salvo em: {out_path}")


if __name__ == "__main__":
    main()
