# bb2gh — Migração Bitbucket → GitHub

Script Python para migrar repositórios de um workspace do Bitbucket para o GitHub, com controle granular sobre quais repos migrar e como.

## Funcionalidades

- Migra **todos** os repos ou apenas os que você escolher
- Filtra por nome, pattern (glob), visibilidade (público/privado)
- Exclui repos específicos da migração
- Renomeia repos no destino (prefixo ou nome customizado)
- Modo dry-run para ver o que seria feito sem executar
- Detecta repos que já existem no GitHub e pula (ou força com `--force`)
- Preserva **todos os branches, tags e histórico** (mirror push)
- **Migra pull requests abertos** do Bitbucket para o GitHub
- Salva um log/sumário da execução em arquivo (`logs/bb2gh_YYYYMMDD_HHMMSS.log`)

---

## Pré-requisitos

1. **Python 3.7+**
2. **git** instalado e no PATH
3. **Credenciais** (veja abaixo)

### Instalar dependências

```bash
pip install -r requirements.txt
```

---

## Configuração de credenciais

Defina estas variáveis de ambiente **antes** de rodar o script:

| Variável | Obrigatória | Descrição |
|---|---|---|
| `BB_USERNAME` | Sim | Seu username do Bitbucket |
| `BB_EMAIL` | Sim | Email da sua conta Atlassian (usado para autenticação na API) |
| `BB_API_TOKEN` | Sim | [API Token](https://id.atlassian.com/manage-profile/security/api-tokens) com scopes `read:repository:bitbucket`, `read:pipeline:bitbucket` e `read:pullrequest:bitbucket` |
| `GH_TOKEN` | Sim | [Personal Access Token](https://github.com/settings/tokens) do GitHub com scope `repo` |
| `GH_ORG` | Sim | Username ou organização de destino no GitHub |
| `BB_WORKSPACE` | Não | Workspace do Bitbucket (padrão: mesmo que `BB_USERNAME`) |

### Permissões necessárias no Bitbucket

No token do Bitbucket, use no minimo:

- `Repositories:Read` (listar repositorios, clone mirror e deploy keys)
- `Pipelines:Read` (listar pipeline variables e deployment environments)
- `Pull requests:Read` (listar pull requests abertos para migração)

Sem `Pipelines:Read`, o plano pode mostrar 0 environments/variables por falta de permissao (erro 403 na API).
Sem `Pull requests:Read`, o script de migração de PRs não conseguirá listar os PRs (erro 403 na API).

### Exemplo (Linux/macOS)

```bash
export BB_USERNAME="meu-user"
export BB_EMAIL="meu-email@empresa.com"
export BB_API_TOKEN="meu-api-token"
export GH_TOKEN="ghp_xxxxxxxxxxxxxxxxxxxx"
export GH_ORG="meu-user-github"
export BB_WORKSPACE="meu-workspace"   # opcional
```

### Exemplo (Windows PowerShell)

```powershell
$env:BB_USERNAME = "meu-user"
$env:BB_EMAIL = "meu-email@empresa.com"
$env:BB_API_TOKEN = "meu-api-token"
$env:GH_TOKEN = "ghp_xxxxxxxxxxxxxxxxxxxx"
$env:GH_ORG = "meu-user-github"
```

> **Dica:** Crie um arquivo `.env` e use `source .env` para não ter que exportar toda vez. Não commite esse arquivo!

---

## Como usar

### Listar todos os repos do Bitbucket

```bash
python migrate.py --list
```

### Dry run — ver o que seria migrado sem fazer nada

```bash
python migrate.py --dry-run
```

### Migrar TUDO

```bash
python migrate.py
```

### Migrar repos específicos

```bash
python migrate.py --repos meu-api,meu-frontend
```

### Excluir repos da migração

```bash
python migrate.py --exclude repo-antigo,repo-lixo
```

### Filtrar por pattern (glob)

```bash
# Todos que começam com "api-"
python migrate.py --pattern "api-*"

# Todos que terminam com "-service"
python migrate.py --pattern "*-service"
```

### Migrar só repos privados

```bash
python migrate.py --only-private
```

### Migrar só repos públicos

```bash
python migrate.py --only-public
```

### Criar repos como públicos no GitHub

```bash
python migrate.py --public
```

### Renomear repo no destino

```bash
# Um repo com nome novo
python migrate.py --repos meu-repo --gh-name novo-nome
```

### Adicionar prefixo a todos os repos

```bash
# Vai criar: bb-repo1, bb-repo2, etc.
python migrate.py --gh-prefix "bb-"
```

### Forçar re-migração (repo já existe no GitHub)

```bash
python migrate.py --repos meu-repo --force
```

### Combinar opções

```bash
# Migrar apenas repos privados que começam com "api-", como públicos no GitHub
python migrate.py --only-private --pattern "api-*" --public --dry-run
```

### Definir caminho customizado para o log

```bash
python migrate.py --dry-run --log-file ./logs/minha-execucao.log
```

### Migrar pull requests abertos do Bitbucket para o GitHub

> **Pré-requisito:** o repo já deve ter sido migrado (mirror push) para que os branches existam no GitHub.

```bash
# Ver quais PRs seriam migrados (sem criar nada)
python3 scripts/migrate_prs.py --repos meu-repo --dry-run

# Migrar PRs abertos
python3 scripts/migrate_prs.py --repos meu-repo

# Vários repos de uma vez
python3 scripts/migrate_prs.py --repos repo1,repo2,repo3

# Com prefixo no nome do repo no GitHub
python3 scripts/migrate_prs.py --repos meu-repo --gh-prefix bb-
```

Cada PR criado no GitHub inclui uma nota no body indicando o ID original e autor do Bitbucket. PRs duplicados (mesmo head/base) são detectados e pulados automaticamente.

---

## Referência de opções

```
python migrate.py --help
```

| Opção | Curta | Descrição |
|---|---|---|
| `--repos` | `-r` | Lista de slugs separados por vírgula |
| `--exclude` | `-e` | Repos a excluir, separados por vírgula |
| `--pattern` | | Glob pattern para filtrar (ex: `api-*`) |
| `--only-private` | | Migrar apenas repos privados |
| `--only-public` | | Migrar apenas repos públicos |
| `--public` | | Criar repos como públicos no GitHub |
| `--gh-name` | | Nome customizado (apenas 1 repo) |
| `--gh-prefix` | | Prefixo para nome no GitHub |
| `--dry-run` | `-n` | Simular sem executar |
| `--force` | `-f` | Forçar push mesmo se já existir |
| `--list` | `-l` | Apenas listar repos e sair |
| `--log-file` | | Caminho do arquivo de log/sumário |

---

## Como funciona

1. Lista todos os repos do workspace no Bitbucket via API
2. Aplica os filtros que você definiu (repos, exclude, pattern, visibilidade)
3. Para cada repo selecionado:
   - Verifica se já existe no GitHub
   - Cria o repo no GitHub (via API)
   - Faz `git clone --bare` do Bitbucket
   - Faz `git push --mirror` para o GitHub
   - Limpa os arquivos temporários
4. Exibe um resumo da migração

---

## Criando as credenciais

### Bitbucket API Token

> App Passwords foram descontinuados em setembro de 2025. Use API Tokens com scopes.

Link direto:
- https://id.atlassian.com/manage-profile/security/api-tokens

1. Clique no seu avatar no canto superior direito do Bitbucket
2. Vá em **Account settings**
3. Na página da Atlassian Account, clique na aba **Security**
4. Clique em **Create and manage API tokens**
5. Clique em **Create API token with scopes**
6. Dê um nome ao token e defina uma data de expiração, clique **Next**
7. Selecione **Bitbucket** como app, clique **Next**
8. Marque os scopes **Repositories:Read**, **Pipelines:Read** e **Pull requests:Read**, clique **Next**
9. Revise e clique **Create token**
10. Copie o token gerado → use como `BB_API_TOKEN`

> O token só é exibido uma vez e não pode ser recuperado depois.

### GitHub Personal Access Token

1. Acesse https://github.com/settings/tokens
2. Clique **Generate new token (classic)**
3. Marque o scope **repo** (acesso completo a repos privados)
4. Copie o token → use como `GH_TOKEN`

---

## Troubleshooting

| Problema | Solução |
|---|---|
| `ERRO: variável de ambiente X não definida` | Exporte a variável faltante |
| `401 Unauthorized` no Bitbucket | Verifique `BB_EMAIL` (email Atlassian, não username) e `BB_API_TOKEN` |
| `403` ao ler variables/environments no Bitbucket | O token não tem `Pipelines:Read`; recrie o token com essa permissão |
| `403` ao listar pull requests no Bitbucket | O token não tem `Pull requests:Read`; recrie o token com essa permissão |
| `401/403` no GitHub | Verifique `GH_TOKEN` e se tem scope `repo` |
| Repo já existe no GitHub | Use `--force` para forçar o push |
| `git` não encontrado | Instale o git: `sudo apt install git` |