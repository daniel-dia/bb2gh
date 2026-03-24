import argparse
import fnmatch


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Migra repositórios do Bitbucket para o GitHub.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Variáveis de ambiente obrigatórias:
  BB_USERNAME       Username do Bitbucket
  BB_EMAIL          Email da conta Atlassian (usado para autenticação na API)
  BB_API_TOKEN      API Token do Bitbucket (scopes: Repositories:Read e Pipelines:Read)
  GH_TOKEN          Personal Access Token do GitHub (scope: repo)
  GH_ORG            Organização ou username de destino no GitHub

Variáveis de ambiente opcionais:
  BB_WORKSPACE      Workspace do Bitbucket (padrão: BB_USERNAME)
        """,
    )

    sel = p.add_argument_group("seleção de repositórios")
    sel.add_argument("--repos", "-r", help="Lista de slugs separados por vírgula para migrar (ex: repo1,repo2)")
    sel.add_argument("--exclude", "-e", help="Lista de slugs separados por vírgula para EXCLUIR da migração")
    sel.add_argument("--pattern", help="Glob pattern para filtrar repos pelo slug (ex: 'api-*', '*-service')")
    sel.add_argument("--only-private", action="store_true", help="Migrar apenas repos privados do Bitbucket")
    sel.add_argument("--only-public", action="store_true", help="Migrar apenas repos públicos do Bitbucket")
    sel.add_argument("--project", "-p", help="Filtrar por projeto do Bitbucket (nome ou key, ex: 'Development')")

    dest = p.add_argument_group("configuração de destino")
    dest.add_argument("--public", action="store_true", help="Criar repos como PÚBLICOS no GitHub (padrão: privado)")
    dest.add_argument("--gh-name", help="Nome customizado no GitHub (só funciona com --repos de um único repo)")
    dest.add_argument(
        "--gh-prefix",
        help="Prefixo para adicionar ao nome do repo no GitHub (ex: 'bb-' → 'bb-meu-repo')",
        default="",
    )

    behav = p.add_argument_group("comportamento")
    behav.add_argument("--dry-run", "-n", action="store_true", help="Apenas listar repos que seriam migrados, sem executar nada")
    behav.add_argument("--plan", action="store_true", help="Mostrar plano detalhado: comparar BB vs GH, listar vars, secrets, envs, deploy keys")
    behav.add_argument("--force", "-f", action="store_true", help="Forçar migração mesmo se o repo já existir no GitHub (push --mirror)")
    behav.add_argument("--list", "-l", action="store_true", help="Listar todos os repos do Bitbucket e sair")

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
