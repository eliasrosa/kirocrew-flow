# kirocrew-flow

**KiroCrew Flow** — orquestração de esteira de desenvolvimento multi-squad sobre o
**[Kiro Crew](https://github.com/kirodotdev)**: os fluxos de trabalho são **grafos**,
o estado de cada task vive em **labels `crewflow:*`** na própria issue, e o polling
é **zero-token**.

> ⚠️ **Não é standalone.** Depende do Kiro Crew rodando na máquina: usa o loopback
> interno do gateway (`POST /api/chat`) e o formato de *cron de script* do Kiro Crew.

## Princípios

1. **A issue É o estado.** Label = estado atual, comentário = histórico auditável.
2. **Zero-token no polling.** O scan é Python puro — token só gasto quando há trabalho real.
3. **Merge é SEMPRE manual.** A automação abre o PR e para. Nenhum merge, nenhum deploy automatizado.
4. **Gates humanos são invioláveis.** Aprovação de spec, review e QA são sempre de pessoas.
5. **Exceções são auditáveis.** O bypass do HML (hotfix direto pra PRD) exige justificativa e é rastreado.

## Modelo de labels

Duas dimensões independentes.

### Estados — 1 por vez, nesta ordem

```
crewflow:spec → crewflow:ready → crewflow:todo → crewflow:dev → crewflow:review → crewflow:qa → crewflow:done
```

### Modificadores — 0..N, sobrepõem ao estado

| Label | Significado |
|---|---|
| `crewflow:blocked` | Para tudo (prioridade sobre o estado) |
| `crewflow:running` | Trabalho em andamento |
| `crewflow:reviewed` | Lock anti-loop: já analisado neste SHA |
| `crewflow:hml-bypass` | Exceção auditada: hotfix pulou o HML (exige justificativa) |
| `crewflow:changes-requested` | Reviewer pediu mudança — dev corrige na mesma PR e re-submete |

### Tipo de fluxo (routing) e prioridade

`crewflow:feature` · `crewflow:bug` · `crewflow:hotfix` · `crewflow:debt`  
`crewflow:p1` · `crewflow:p2` · `crewflow:p3`

Aplique todas num repo:
```bash
./scripts/setup-labels.sh owner/repo
```

## Como funciona

```
squads/*.yaml → SquadConfig → scan_candidates() → executor.decide() → deployment (run/run_<stage>)
```

1. `scan_candidates()` varre as issues por labels `crewflow:*` sem gastar token — compara hash do estado atual com o cache SQLite, e só processa o que mudou.
2. `executor.decide()` decide a ação (DISPATCH_DEV, DISPATCH_REVIEWER, DISPATCH_REWORK, NOTIFY_HUMAN, BLOCK, REBRAND, MERGE_PR ou SKIP) com base no template da squad e no estado da issue.
3. O driving adapter em `deployment/deployment.py` executa a ação: dispara sessão one-shot, notifica humano, aplica rebrand de template ou faz o merge squash + labels de um PR aprovado.

A sessão one-shot **nunca mergeia e nunca faz deploy**. Ela entrega o PR em `crewflow:review` e encerra.

### Cron por estágio (dev / reviewer / merge / conflito)

O dispatch pode rodar como **crons independentes, uma por estágio do fluxo**, em vez
de um único scan monolítico. Cada estágio é uma cron observadora do estado (padrão
"cron-monitor por estágio"): filtra só as labels do seu estágio e executa só as ações
que lhe pertencem.

| Cron | Entrypoint | Estado observado | Ação |
|---|---|---|---|
| `crewflow-dev` | `deployment.py:run_dev` | `crewflow:todo` (+ `crewflow:spec`/`crewflow:ready`/`crewflow:qa` p/ avisos) | dispatch dev / re-trabalho (modelo forte) |
| `crewflow-reviewer` | `deployment.py:run_reviewer` | `crewflow:review` | dispatch reviewer (modelo mais leve/rápido) |
| `crewflow-merge` | `deployment.py:run_merge` | `crewflow:review` + `crewflow:reviewed` aprovado | merge squash + labels |
| `crewflow-conflito` | `deployment.py:run_conflito` | PRs com `crewflow:conflito` | roteia/notifica (resolução é BO #4, futuro) |

O cron `crewflow-dev` também é o dono das ações informativas que nascem do scan de
`todo`/`spec`: spec inválida, bypass bloqueado, rebrand e notificações de humano. Por
isso ele varre não só `crewflow:todo` mas também `crewflow:spec`/`crewflow:ready`/`crewflow:qa`:
esses estados geram `NOTIFY_HUMAN` (aprovação do TL, priorização, validação em HML) e,
sem o cron dev varrê-los, uma implantação 100% por estágio deixaria de emitir esses avisos.

Ganhos da separação:

1. **Observabilidade** — cada cron tem seu log isolado (`stages.<stage>.log`, default
   `~/.kiro/crew/crons/deployment-<stage>.log`), com histórico próprio por estágio.
2. **Modelo por ação** — cada estágio manda seu próprio modelo no `POST /api/chat`
   (`stages.<stage>.model`, threaded na chave JSON `model` do body): modelo forte no
   dev, mais leve/rápido no reviewer.
3. **Blast radius menor** — se a cron de merge quebra, dev e reviewer seguem rodando.
4. **Interval por estágio** — cada cron varre na sua cadência (`stages.<stage>.interval`);
   o reviewer pode varrer mais rápido que o dev.

O scan zero-token é preservado: cada cron escopa o scan só aos estados do seu estágio.

> **`crewflow:merge` continua SEMPRE manual.** A cron de merge só executa o fluxo de
> squash + labels já existente para PRs aprovados — não há política nova de auto-merge.
> A resolução automática de conflitos fica para o BO #4; a cron `crewflow-conflito`
> apenas surface/roteia os PRs em conflito.

**Compatibilidade:** se a config **não** define o bloco `stages:`, nada muda — o
deployment cai no comportamento monolítico atual, uma única cron `crewflow-scan` →
`deployment.py:run` que varre tudo e executa todas as ações num ciclo só. O body do
`POST /api/chat` também continua idêntico (sem a chave `model`) quando nenhum modelo
por estágio é configurado.

## Fluxos disponíveis (Fase 1)

| Template | Quando usar |
|---|---|
| `feature` (Versão C) | Feature nova. Review ANTES do QA, sequencial. |
| `bug` | Correção de bug. Mesma ordem da Versão C. |
| `hotfix` | Incidente em PRD. GATE 0 filtra o que é realmente urgente. |
| `debt` | Refatoração sem mudança de comportamento. TL aprova; QA valida equivalência. |

Diagramas em [`docs/diagramas/`](docs/diagramas/README.md).

## Setup

Pré-requisito: Kiro Crew rodando + `gh` autenticado (`gh auth status`).

### 1. Configure a squad

Crie `squads/minha-squad.yaml` com base em `squads/example.yaml`:

```yaml
id: minha-squad
name: Squad Exemplo
issue_provider: jira   # ou github
project: VGAT          # chave do projeto Jira
repos:
  - org/api-gateway2
  - org/api-subscription2
workflow_template: versao-c
routing:
  - match:
      labels:
        - crewflow:hotfix
    workflow: hotfix-flow
  - default: feature-flow
```

> **PyYAML (recomendado para routing complexo):** o parser embutido (`_mini_yaml`) suporta
> escalares, listas simples, mapeamentos de 1 nível, e listas de dicts — tanto no formato
> inline (`{labels: [...]}`) quanto multi-linha. Para garantir compatibilidade total com YAML
> arbitrário, instale PyYAML:
>
> ```bash
> pip install "kirocrew-flow[yaml]"
> # ou: pip install pyyaml
> ```
>
> Sem PyYAML o fallback cobre os casos de uso do squad config padrão.

### 2. Configure o cron

```bash
# SEMPRE usar o script de instalação — não copie manualmente
./scripts/install-cron.sh

# O script copia deployment.py, aplica o patch de sys.path e
# copia deployment.config.yaml (se não existir).
# Edite ~/.kiro/crew/crons/deployment.config.yaml com seus paths.
```

Ao final, o `install-cron.sh` imprime as linhas de `cron_add(...)` para você registrar
no dashboard do Kiro Crew. O que ele emite depende da config:

**Sem bloco `stages:` (monolítico — comportamento padrão):**

```
cron_add(name="crewflow-scan",
         script="~/.kiro/crew/crons/deployment.py:run",
         every=600)
```

**Com bloco `stages:` (uma cron por estágio):** ele emite N linhas, uma por estágio
configurado, cada uma no entrypoint `run_<stage>` e no `interval` da config (ou no
default por estágio: dev=600, reviewer=180, merge=300, conflito=900):

```
cron_add(name="crewflow-dev",
         script="~/.kiro/crew/crons/deployment.py:run_dev",
         every=600)

cron_add(name="crewflow-reviewer",
         script="~/.kiro/crew/crons/deployment.py:run_reviewer",
         every=180)

cron_add(name="crewflow-merge",
         script="~/.kiro/crew/crons/deployment.py:run_merge",
         every=300)

cron_add(name="crewflow-conflito",
         script="~/.kiro/crew/crons/deployment.py:run_conflito",
         every=900)
```

Cada estágio aceita `model`, `interval` e `log` próprios sob o mapa `stages:` da
config — veja `config.example.yaml` para o schema completo. Omitir `stages:` mantém
a cron única `crewflow-scan`.

### 3. Aplique as labels

```bash
./scripts/setup-labels.sh owner/repo
```

### 4. Comece no modo de aviso

Deixe `auto_dispatch: false` (só avisa). Quando confiar, mude para `true`.

## Estrutura do código

```
flow/
├── domain/      ← regras de negócio puras (sem I/O), testáveis sem mock
│   ├── state.py — Estado, Modificador, is_dispatchable()
│   └── gates.py — can_leave_spec(), triage_hotfix(), validate_hml_bypass()
├── ports/       ← contrato do provider (IssueProvider Protocol)
├── adapters/    ← GitHub e Jira (transport + normalization + client)
├── scan/        ← zero-token polling + cache SQLite
├── executor/    ← decide() por template (feature/bug/hotfix/debt)
├── audit/       ← comentário estruturado <!-- KIRO-FLOW-STATE -->
├── prompts/     ← templates MD editáveis por estágio (dev, reviewer, …)
└── config/      ← SquadConfig + workflow templates

deployment/      ← cron de script do Kiro Crew (driving adapter)
squads/          ← configurações de squad (*.yaml)
workflows/       ← templates de workflow (*.yaml)
resources/mermaid/ ← fonte dos diagramas (.mmd)
docs/            ← VISION.md, ARCHITECTURE.md, ROADMAP.md, diagramas/
```

Ver `.kiro/steering/arquitetura.md` para convenções de código e como adicionar um novo provedor.

### Editar o prompt de uma sessão one-shot

Os prompts ficam em `flow/prompts/`:
- `dev.md` — sessão de implementação (o agente que abre o PR)
- `reviewer.md` — sessão de code review

Edite o MD livremente. Placeholders usam `{{nome}}`. Se um placeholder referenciar
uma variável que o motor não fornece, o dispatch **falha explicitamente** (fail-closed)
em vez de mandar o prompt quebrado. Em caso de arquivo ausente, o motor usa o fallback
embutido em `deployment.py`.

## Desenvolvimento

```bash
# Lint
python3 -m ruff check flow/

# Testes + cobertura
python3 -m pytest flow/tests/ --cov=flow --cov-report=term-missing

# Tudo junto
python3 -m ruff check flow/ && python3 -m pytest flow/tests/ --cov=flow --cov-fail-under=75
```

260 testes, 82% cobertura, ruff limpo (Fase 1).

## Dry-run — inspecionar sem despachar

Antes de ativar o `auto_dispatch`, use o modo dry-run para validar o que o motor faria:

```bash
CREWFLOW_DRY_RUN=1 python3 deployment/deployment.py
```

Ou via config (`deployment.config.yaml`):

```yaml
dry_run: true
```

Saída esperada:

```
[DRY-RUN] ──────────────────────────────────────────
[DRY-RUN] 2 issue(s) processada(s) pelo scan
[DRY-RUN] Decisões (nenhuma será executada):

[DRY-RUN] owner/repo#73 → DISPATCH_DEV (template via executor) — [repo] feat: dry-run
[DRY-RUN] owner/repo#74 → NOTIFY_HUMAN tl — [repo] Fix: aguarda gate-tl

[DRY-RUN] ── Nenhuma sessão despachada, label alterada ou notificação enviada. ──
```

Garantias do modo dry-run:
- O scan roda normalmente (lê issues, executa o executor, decide ações)
- `_dispatch()` **não** é chamado — nenhuma sessão one-shot é aberta
- `provider.set_labels()` **não** é chamado — nenhuma label é alterada
- `ctx.notify()` **não** é chamado — nenhuma notificação é enviada
- Nenhum lock é criado

## Roadmap

| Fase | Estado |
|---|---|
| **Fase 1** — fluxos fixos, sem editor | ✅ Concluída (set/2026) |
| **Fase 2** — editor read-only no dashboard | 🔲 Planejada |
| **Fase 3** — canvas editável estilo n8n | 🔲 Futura |

Ver [`docs/ROADMAP.md`](docs/ROADMAP.md) para detalhes.

## Segurança / privacidade

- Repos, chat_id e paths vivem no `config.yaml` (gitignored). O `config.example.yaml` só tem placeholders.
- O disparo usa o segredo interno do gateway apenas em loopback (localhost).
