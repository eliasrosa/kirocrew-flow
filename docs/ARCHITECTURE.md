# KiroCrew Flow — Arquitetura

## Stack

| Item | Valor |
|---|---|
| Linguagem | Python 3.12 |
| Servidor web | aiohttp |
| Testes | pytest + pytest-cov |
| Linting | ruff |
| Type check | mypy |
| Cache do scan | SQLite (stdlib) |
| YAML | PyYAML com fallback para parser interno |

Sem FastAPI, Flask, Starlette ou Pydantic — o projeto segue a stack do próprio
Kiro Crew, validada lendo o código instalado.

## Padrão arquitetural: hexagonal (ports & adapters)

O motivo prático: a regra de negócio mais importante do fluxo (`can_leave_spec`)
fica testável **sem nenhuma infraestrutura** — nenhuma rede, nenhum banco, nenhum
mock de provider.

```
flow/
├── domain/    ← NÚCLEO: sem I/O, testável sem mock
├── ports/     ← contratos (Protocol)
├── adapters/  ← GitHub e Jira
├── scan/      ← zero-token polling
├── executor/  ← decisões por template
├── audit/     ← comentário de auditoria
└── config/    ← squad config + workflow templates
```

## Regra de isolamento do domínio

`test_domain_boundary.py` verifica por AST que nenhum arquivo em `flow/domain/`
importa infraestrutura. Se quebrar, pare tudo e conserte primeiro.

## Adapters são módulos, não classes

```python
_PROVIDERS = {"github": github_client, "jira": jira_client}
provider_for("jira")  # → o módulo jira_client
```

Um módulo não pode ser verificado estaticamente contra um `Protocol`. O gate que
garante conformidade é `test_provider_parity.py` — compara GitHub (referência)
contra Jira, com um auto-guard que falha se um terceiro adapter entrar no dispatch
sem ser registrado no teste.

Cada adapter tem três camadas:

| Camada | Papel |
|---|---|
| `*_transport.py` | I/O bruto — fachada patchável nos testes |
| `*_normalization.py` | payload do provedor → contrato canônico |
| `*_client.py` | orquestração; satisfaz `IssueProvider` |

O `github_client` expõe funções extras não presentes na porta:
- `get_pr_checks(project, pr_number)` — retorna os checks (CI) de um PR
- `upsert_pr_review_comment(...)` — cria ou atualiza comentário de review no PR
- `merge_pull_request(...)` — merge squash via API

Essas funções são GitHub-only e não fazem parte da porta `IssueProvider`.

## Identidade: projeto + issue key

A chave primária de um item de trabalho é **projeto + issue key** (`VGAT-123`).
O repo é derivado do título (`[repo] Descrição`), não da identidade.

O Jira é projeto-cêntrico por natureza. O GitHub é repo-cêntrico, mas a porta
normaliza para projeto para que o domínio seja agnóstico de provedor.

## Fluxo de uma issue pelo sistema

```
squads/my-squad.yaml
    → SquadConfig.resolve_workflow(labels)  → "hotfix-flow"
    → scan_candidates(config, provider, conn)  → [ScanResult]
    → executor.decide(result, state_comment)   → ExecutorDecision
    → provider.set_labels() + upsert_state_comment() + _dispatch()
```

O `deployment.py` é o **driving adapter** que executa esse loop como cron de
script do Kiro Crew (zero token no polling).

## Crons do App (app.json) e resolução de paths

O `app.json` declara a esteira completa na seção `crons`. Quem instala o App já
ganha os 8 crons de estágio (namespace `flow:*`) + o auto-update, sem
configuração manual.

### `script` (zero-token) em vez de `message` (LLM)

Os crons antigos `crewflow-*` usavam o campo `message`, que dispara uma sessão
de LLM a cada tick (gasta token). Os novos crons `flow-*` usam `script`,
apontando para um entrypoint `run(ctx)` executado diretamente pelo runner de
crons — **zero token** no polling, coerente com o design de scan por labels.

| Cron | script | every (s) |
|---|---|---|
| `flow-develop-waiting` | `deployment/flow/dev.py:run` | 300 |
| `flow-review-waiting` | `deployment/flow/reviewer.py:run` | 180 |
| `flow-review-approved` | `deployment/flow/review_approved.py:run` | 120 |
| `flow-review-refused` | `deployment/flow/rework.py:run` | 3600 |
| `flow-merge-conflict` | `deployment/flow/conflict.py:run` | 300 |
| `flow-qa-waiting` | `deployment/flow/qa_notify.py:run` | 600 |
| `flow-qa-approved` | `deployment/flow/qa_approved.py:run` | 120 |
| `flow-qa-refused` | `deployment/flow/qa_refused.py:run` | 3600 |

### Como o gateway resolve o `script`

Os `script` dos crons do App usam a forma **repo-relativa**
(`deployment/flow/<x>.py:run`), resolvida em relação ao **diretório do App
instalado** (`~/.kiro/crew/apps/kirocrew-flow`). Isso funciona porque a árvore
inteira do repositório é copiada para o diretório do App na instalação, então o
caminho relativo aponta para o arquivo já presente lá.

Isso **contrasta** com os crons registrados manualmente via
`scripts/install-cron.sh`, que usam paths **absolutos expandidos** enraizados em
`~/.kiro/crew/crons/` (ex.: `~/.kiro/crew/crons/deployment/flow/dev.py:run`),
porque aquele script copia os módulos para uma pasta diferente (`crons/`, não
`apps/`).

> **Limitação verificada:** a semântica exata de resolução de `script` de crons
> declarados no App **não pôde ser confirmada em runtime** neste ambiente porque
> a CLI/gateway `kirocrew` não está instalada no sandbox. A forma repo-relativa
> adotada é a que corresponde ao modo como o App é instalado (cópia da árvore do
> repo para o diretório do App). O critério de aceite
> `kirocrew app disable/enable kirocrew-flow` deve ser validado num ambiente com
> o gateway instalado.

### Cron `flow-auto-update`

Mantém a instalação sincronizada com `origin/main`. Roda a cada 300s, `silent`,
e executa `git pull --rebase origin main && ./scripts/install-cron.sh`.

Ele **não** usa uma variável de template `{app_dir}` no `command`, porque esse
placeholder **não é suportado** neste código (o `Makefile` fixa `APP_DIR`
estaticamente e nada consome `{app_dir}`). Em vez disso o cron aponta para
`scripts/auto_update.py:run`, que **se autolocaliza** via
`pathlib.Path(__file__).resolve().parent.parent` (a raiz do repo é o pai de
`scripts/`) e nunca levanta exceção — uma atualização que falha não pode
derrubar o runtime de crons.

### Follow-up operacional

- O cron avulso `kirocrew-flow-pull` (referenciado no commit `d492c02b`, que
  **não está** no histórico local deste repo) pode ser aposentado assim que o
  `flow-auto-update` estiver rodando dentro do App. Isso é uma ação operacional,
  não uma mudança de código neste repositório.
- Após puxar mudanças em `deployment/deployment.py`, `deployment/flow/*.py` ou
  nos prompts, operadores devem reexecutar `./scripts/install-cron.sh` — que é
  exatamente o que o `flow-auto-update` automatiza.

## Workspace isolado por task (Fase 2)

Cada dispatch cria um **worktree efêmero** dedicado, garantindo que múltiplas
tasks rodem em paralelo sem pisar uma na outra.

### Convenção de caminhos

```
<dev_root>/<repo-short>/          ← clone-base (nunca tocado diretamente)
<dev_root>/.esteira-worktrees/
    <repo-short>-<issue_number>/  ← worktree efêmero (criado no dispatch, removido no fim)
```

A função `_worktree_path(dev_root, repo, issue_number)` é a **fonte única de
verdade** do caminho: usada pelo `deployment.py` na limpeza pré-dispatch e pelo
prompt enviado à sessão one-shot. Os dois lados sempre falam do mesmo diretório.

### Fluxo pré-dispatch

```
scan_candidates()
    → executor.decide()
    → _resource_headroom_ok()        ← posture critical suspende dispatch
    → _clean_stale_worktree()        ← remove worktree órfão de sessão anterior
    → _issue_has_active_session()    ← mecanismo primário: worktree + PR + backstop
    → _is_dead_session()             ← detecta sessão morta pelo timeout longo
    → _dispatch()                    ← prompt inclui git worktree add no caminho canônico
```

### Cap de concorrência e detecção de sessão morta

A concorrência é decidida pelo **estado da issue**, não por lock de tempo:

- **Cap primário:** contagem de issues em `flow:develop-running` no scan atual — não locks de arquivo.
- **Backstop anti-duplo-dispatch:** lock de arquivo (2min) — protege o intervalo entre dispatch e o label chegar na API.
- **`_issue_has_active_session()`:** verifica worktree ativo, PR aberto na branch, e backstop lock — retorna `True` se qualquer sinal indicar sessão viva.
- **Detector de sessão morta (`_is_dead_session()`):** issue em running há >40min sem PR, sem worktree, sem backstop lock → sessão morta confirmada.
- **Recuperação fail-closed (`_recover_dead_session()`):** remove `flow:develop-running`, notifica TL, espera redespacho no próximo ciclo. Nunca redespacha sozinho em caso de ambiguidade.
- O headroom de recursos é verificado via `resource_status` do Kiro Crew antes de cada dispatch — posture `critical` adia sem bloquear o ciclo.

| Campo config | Função | Default |
|---|---|---|
| `max_concurrent_tasks` | Cap global de tasks em paralelo | `2` |
| `one_per_repo` | Reservado (não mais usado como guard primário) | `true` |

## Identificação e labels

O prefixo `flow:` é o namespace canônico de estado. O prefixo `crewflow:` é mantido
para metadado (tipo de fluxo, prioridade e `crewflow:blocked` por compatibilidade).
Confluence rejeita `:` — fora de escopo.

Estados (1 por vez, namespace `flow:*`):
```
flow:briefing → flow:planning-specs → flow:planning-review → flow:develop-waiting
  → flow:develop-running → flow:review-waiting → flow:review-approved
  → flow:qa-waiting → flow:qa-testing → flow:qa-approved → flow:done
```

> Labels de estado legadas (`crewflow:spec`, `crewflow:todo`, `crewflow:dev`, etc.)
> foram deprecadas — use `setup-flow-labels.sh` para novos repos.

Modificadores de estado (0..N, namespace `flow:*`):
```
flow:blocked         # para tudo (prioridade sobre o estado)
flow:merge-conflict  # PR com conflito — cron resolve via rebase
flow:reviewed        # lock anti-loop de code review (interno)
```

Metadado (tipo e prioridade, namespace `crewflow:*`):
```
crewflow:feature / crewflow:bug / crewflow:hotfix / crewflow:debt
crewflow:p1 / crewflow:p2 / crewflow:p3
crewflow:blocked   # alias de flow:blocked, mantido por compatibilidade
```

## O comentário de estado

```markdown
<!-- KIRO-FLOW-STATE -->
## 🤖 KiroCrew Flow — Estado

**Workflow:** feature (v1)
**Nó atual:** review
**Status:** running
**Repo:** api-gateway2

### Histórico
| Quando | De → Para | Quem |
|--------|-----------|------|
| 2026-09-15 00:02 | start → dev | system |

### Exceções
| Exceção | Justificativa | Quem | Quando |
|---------|---------------|------|--------|
| `hml-bypass` | Checkout fora do ar | @elias | 2026-09-15 |
<!-- /KIRO-FLOW-STATE -->
```

O comentário não é só registro — é **fonte de pré-condições de merge**. O executor
bloqueia o merge com `hml-bypass` se a seção de Exceções não tiver
justificativa preenchida.

## Detalhes técnicos: para desenvolvedores

Ver `.kiro/steering/arquitetura.md` — cobre convenções de código (StrEnum,
`slots=True`, imports no topo, `with` múltiplos), como adicionar um novo
provedor, e como rodar o CI localmente.
