# KiroCrew Flow — Visão do Projeto

> App do ecossistema Kiro Crew para gerenciar fluxos de desenvolvimento multi-squad.

## O que é

**KiroCrew Flow** é um gerenciador de fluxos de desenvolvimento que:
- Centraliza e orquestra todo o ciclo de vida de tasks (feature, bug, hotfix, debt)
- Suporta múltiplas squads, cada uma com seus repos, fluxos e regras
- Executa automaticamente, com **zero token no agendamento** (observação é script puro)
- Rastreia cada task por labels no Jira/GitHub, visível pra todo o time

**Prefixo:** `crewflow:`

## Diferencial central: ZERO-TOKEN no agendamento

O problema de outros modelos:
1. Uma automação por repositório — não escala pra multi-squad/multi-repo
2. Agendamento gasta token mesmo parado — insustentável

**KiroCrew Flow resolve:**
- **Observação = script determinístico, ZERO token** — varre múltiplos repos numa passada via API
- **Token só na AÇÃO** — só gasta quando o scan detecta trabalho real e dispara um agente
- **Multi-repo nativo** — um observador cobre todos os repos das squads configuradas
- **Gating de estado** — compara estado atual vs. último visto, só age na diferença

## Modelo conceitual

```
┌─────────────────────────────────────────────────────────────┐
│  SCHEDULER (cron, a cada 5min)                              │
│  └─ conductor:run (script puro, zero token)                 │
└─────────────────────────────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│  SCAN — lê issues do Jira/GitHub por labels                 │
│  └─ Compara com cache local (hash de labels)                │
│  └─ Se mudou: marca pra processar                           │
└─────────────────────────────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│  MATCH — determina qual workflow rodar                      │
│  └─ Lê label flow:* → identifica fluxo                      │
│  └─ Lê label aguardando-* → identifica nó atual             │
└─────────────────────────────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│  EXECUTE — dispara ação (aqui gasta token)                  │
│  └─ Se actor=automation → dispara agente/subagente          │
│  └─ Se actor=humano → só notifica/atualiza estado           │
└─────────────────────────────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│  PERSIST — atualiza estado                                  │
│  └─ Troca labels na issue                                   │
│  └─ Adiciona comentário de auditoria                        │
│  └─ Atualiza cache local                                    │
└─────────────────────────────────────────────────────────────┘
```

## Faseamento

| Fase | Escopo |
|------|--------|
| **Fase 1** | Motor com fluxos fixos, labels, scan, execução |
| **Fase 2** | Alertas (Telegram/Teams), log de execuções, views read-only |
| **Fase 3** | Dashboard por papel, single pane of glass, workflow builder editável |
| **Fase 4** | Visão multi-squad (Tech Manager), integração QA |
| **Fase 5** | Frontend desacoplado, eventos centralizados |

## Princípios

1. **Zero-token no agendamento** — observação é código, não LLM
2. **Jira/GitHub como fonte da verdade** — estado nas labels, histórico em comentários
3. **Multi-squad nativo** — um observador, múltiplos repos e times
4. **Documentação como Definition of Done** — se não está documentado, não está pronto
5. **Modo auto e manual** — funciona com ou sem automação full na máquina do dev
