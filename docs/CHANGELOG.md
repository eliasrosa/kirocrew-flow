# Changelog

Histórico de mudanças significativas do kirocrew-flow.

---

## [Unreleased]

### Adicionado
- `test: smoke test do cron flow-develop-waiting com dispatch sidebar` (#221)
  - Valida que o cron `flow-develop-waiting` cria sessão sidebar corretamente após o fix de dispatch (PRs #223–#225).

---

## 2026-09-23

### Corrigido
- `fix: remover webhook path — usar sempre create slot + send` (#225)
  - Remove o caminho via webhook token; dispatch usa exclusivamente `POST /api/chat/slots` + `POST /api/chat` para garantir sessão `dashboard:*` no sidebar.
- `fix: criar slot antes do POST /api/chat para sessão Crew no sidebar` (#224)
  - Introduz fluxo de dois passos: cria o slot primeiro (`/api/chat/slots`) e então envia a mensagem (`/api/chat`). Causa raiz do dispatch caindo em sessão CLI invisível.
- `fix: subprocess curl sem KIRO_SESSION_ID para criar sessão Crew` (#223)
  - Remove `KIRO_SESSION_ID` do ambiente do subprocess para que o gateway classifique a sessão como Crew (sidebar) em vez de CLI.
- `fix: restaurar repo + fixes do deployment.py (revert #220 + aplicação correta)` (#222)
  - Reverte deleção acidental de 117 arquivos (commit de HEAD detached corrompido) e reaaplica os fixes corretos do #220.
- `fix: backstop lock em subdir + urlopen padrão + .local_secret fallback` (#220)
  - Mover lock do backstop para subdiretório dedicado; trocar `loopback_urlopen` por `urllib.request.urlopen` padrão; adicionar fallback para leitura do secret via `.local_secret`.
- `fix: ler .local_secret quando ctx._secret vazio no fallback loopback` (#217)
  - Garante que o secret interno seja carregado de `~/.kiro/crew/.local_secret` quando `ctx._secret` estiver vazio no cron runner.
- `fix: dispatch de sessão cria sessão sidebar (X-Session-Key + _run_raw)` (#216)
  - Corrige `X-Session-Key` de `cron:{job_id}` para `dashboard:{slot}`; troca `_run` por `_run_raw` em `edit_issue_labels` para evitar `ProviderError` no parse de URL.

### Adicionado
- `feat: monitor zero-token automático ao despachar dev (#211)` (#213)
  - Cria automaticamente um cron leve de watch-issue ao despachar sessão dev, notificando via `ctx.notify` (Telegram) sem custo de LLM.
- `fix: dispatch de sessões via webhook para crons script-based (#212)` (#214)
  - Investigação da causa raiz do dispatch não criar sessão sidebar; base para os fixes subsequentes.
- `chore: adiciona comentário webhook-test-ok no README` (#218)

---

## 2026-09-22

### Corrigido
- `fix: rebase em origin/main antes do primeiro commit (prompts dev + rework)` (#209)
- `fix: transição de label atômica no executor antes de despachar sessão (#207)` (#210)
- `fix: base.py não encontra deployment.py no layout instalado` (#200)
- `fix: import relativo quebra os crons flow/ no runtime (ImportError)` (#198)

### Adicionado
- `feat: atualizar app.json — crons flow:* + auto-update do app` (#205)
- `refactor: dividir cron flow-merge em flow-review-approved + flow-qa-approved` (#202)
- `refactor: deployment.py monolítico -> módulos flow/ por cron` (#197)
- `feat: QA como seção separada na UI + botões Aprovar/Reprovar (#188)` (#194)
- `feat: deprecar labels de estado crewflow:* em setup-labels.sh e docs` (#193)

---

## 2026-09-20

### Adicionado
- `feat: migrar namespace crewflow:* → flow:* (labels + executor + crons + UI)` (#192)
  - Migração completa do namespace de labels e lógica do executor para `flow:*`.
