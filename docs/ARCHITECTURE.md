# KiroCrew Flow — Arquitetura e Modelo de Dados

## Visão geral

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│   SQUADS        │────▶│   WORKFLOWS     │────▶│   ISSUES        │
│   (config)      │     │   (grafos)      │     │   (estado)      │
└─────────────────┘     └─────────────────┘     └─────────────────┘
        │                       │                       │
        ▼                       ▼                       ▼
   squads/*.yaml          workflows/*.yaml        Jira/GitHub
   (repos, routing)       (nodes, edges)          (labels, comments)
```

## Entidades

### 1. Squad

Espaço isolado de um time. Cada squad tem seus próprios repos, fluxos e regras.

```yaml
# squads/my-squad.yaml
squad:
  id: "my-squad"
  name: "My Squad"
  
  # Provider de issues (jira ou github)
  issue_provider: "jira"  # ou "github"
  jira:
    project: "PROJ"
    base_url: "https://your-instance.atlassian.net"
  
  # Repositórios monitorados
  repos:
    - owner: "org"
      name: "repo-name"
      default_branch: "main"
  
  # Fluxos ativos
  workflows:
    - "feature"
    - "bug"
    - "hotfix"
  
  # Routing: como saber qual fluxo usar
  routing:
    - match:
        labels: ["feature", "enhancement"]
      workflow: "feature"
    - match:
        labels: ["bug"]
      workflow: "bug"
    - match:
        labels: ["hotfix", "incident"]
      workflow: "hotfix"
    - default: "feature"
```

### 2. Workflow

Grafo de nós que define o fluxo. Suporta fork/join pra paralelo, gates pra decisão.

```yaml
# workflows/feature.yaml
workflow:
  id: "feature"
  name: "Feature Flow"
  version: 1
  
  nodes:
    - id: "start"
      type: "event"
      name: "Task aberta"
      next: "spec"
    
    - id: "spec"
      type: "action"
      actor: "human"         # Quem executa: human ou automation
      name: "Escrever spec"
      next: "validate-spec"
    
    - id: "validate-spec"
      type: "gate"           # Decisão com múltiplas saídas
      actor: "human"
      name: "Validar spec"
      outcomes:
        approved: "implement"
        rejected: "spec"
    
    - id: "implement"
      type: "action"
      actor: "automation"    # Crew executa
      agent: "kf-dev"        # Qual agente
      name: "Implementar"
      next: "review"
    
    - id: "review"
      type: "gate"
      actor: "human"
      name: "Code review"
      outcomes:
        approved: "merge"
        rejected: "implement"
    
    - id: "merge"
      type: "action"
      actor: "automation"
      name: "Merge e deploy"
      next: "end"
    
    - id: "end"
      type: "event"
      name: "Concluído"
```

### 3. Estado da Issue (não é entidade separada)

O estado da task é armazenado **diretamente na issue** via labels e comentários:

**Labels de estado:**
```
# Fase (em qual nó está)
aguardando-spec | em-spec
aguardando-implementacao | em-implementacao
aguardando-review | em-review
pronto-pra-merge | em-prd

# Fluxo (qual workflow)
flow:feature | flow:bug | flow:hotfix

# Sinais
acao-necessaria | bloqueado | segurar | urgent

# Lock (opcional)
crewflow-ativo    # Tem um crew trabalhando agora
```

**Comentário estruturado:**
```markdown
<!-- KIRO-FLOW-STATE -->
## 🤖 KiroCrew Flow — Estado

**Workflow:** feature (v1)
**Nó atual:** implement
**Status:** running

### Histórico
| Quando | De → Para | Quem |
|--------|-----------|------|
| 2024-01-15 10:00 | start → spec | system |
| 2024-01-15 14:30 | spec → implement | user:john |
<!-- /KIRO-FLOW-STATE -->
```

### 4. Scan State (cache local)

Cache local pra evitar reprocessar issues que não mudaram:

```yaml
# Armazenado em SQLite ou arquivo
scan_state:
  last_run: "2024-01-15T10:00:00Z"
  
  issues:
    "jira:PROJ-123":
      labels_hash: "abc123"
      last_node: "implement"
    "jira:PROJ-124":
      labels_hash: "def456"
      last_node: "review"
```

## Modos de operação

| Modo | Descrição |
|------|-----------|
| **Auto** | Cron roda, scan detecta, dispara automaticamente |
| **Manual** | Dev controla labels, dá trigger quando quiser (`crewflow run PROJ-123`) |

O estado (labels) é o mesmo em ambos os modos. O que muda é quem dispara.

## Auditoria

Toda ação do KiroCrew Flow adiciona um comentário na issue:

```markdown
---
🤖 **KiroCrew Flow** — Implementação iniciada
**Quando:** 2024-01-15 10:30
**Trigger:** auto
**Branch:** `release/PROJ-123-feature-name`

---
```

Isso garante rastreabilidade completa de quem fez o quê e quando.

## Storage

| Dado | Onde |
|------|------|
| Estado da task | Jira/GitHub (labels + comentário) |
| Config das squads | YAML no repo |
| Cache do scan | SQLite local |
| Log de execuções | SQLite local |
