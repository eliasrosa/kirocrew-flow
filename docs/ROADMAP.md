# KiroCrew Flow — Roadmap

## Fases

### Fase 1 — Motor básico (em progresso)
- [x] Scan de issues por labels
- [x] Disparo de sessão one-shot
- [x] Labels padrão da esteira
- [ ] Estrutura de squads (multi-repo)
- [ ] Workflows como grafo (YAML)
- [ ] Routing por labels
- [ ] Comentários de auditoria

### Fase 2 — Observabilidade
- [ ] Sistema de alertas (Telegram, Teams, Slack)
- [ ] Log de execuções (SQLite)
- [ ] Métricas (tempo de execução, taxa de erro, tokens)
- [ ] Views read-only no dashboard

### Fase 3 — Dashboard e Builder
- [ ] Dashboard por papel (Dev, QA, Tech Lead)
- [ ] Single pane of glass (gerenciar PRs, issues sem sair do app)
- [ ] Workflow builder visual (estilo n8n)
- [ ] Specs inline (Confluence/docs)
- [ ] Telemetria de adoção (auto vs manual)

### Fase 4 — Multi-squad e QA
- [ ] Visão Tech Manager (overview de múltiplas squads)
- [ ] Drill-down macro → micro
- [ ] Integração QA (Zephyr, Playwright)
- [ ] Evidências inline (screenshots, logs)

### Fase 5 — Escala
- [ ] Eventos centralizados (Postgres)
- [ ] Frontend desacoplado (sem licença Kiro Crew)
- [ ] API pública

---

## Ideias no backlog

### Sistema de alertas
Notificar eventos importantes em canal do time:
- Crew terminou etapa
- Precisa de ação humana
- Erro/bloqueio
- QA/Review aprovado
- Deploy concluído

### Spec Wizard
Fluxo guiado de especificação com:
- Perguntas estratégicas (contexto, impacto, abordagem)
- Checklist de impacto (outros casos de uso, outras squads, breaking changes)
- Geração automática de spec

### Telemetria de adoção
Registrar se o trigger foi `auto` ou `manual` pra:
- Identificar quem precisa de máquina melhor
- Ver taxa de adoção da automação
- Priorizar apoio/treinamento

### Views por papel

| View | Pra quem | O que mostra |
|------|----------|--------------|
| Dev | Desenvolvedor | Minhas tasks, meu crew, fila, PRs |
| QA | QA | Aguardando teste, em teste, sub-bugs |
| Tech Lead | TL | Quem trabalha com o quê, blockers |
| Roadmap | Todos | Andamento épicos, cronograma |
| Overview | TL/PM | Sprint, burndown, saúde |

### Integração QA
- Zephyr: cenários, execuções, status
- Playwright: rodar testes, evidências
- Rastreabilidade: task → código → teste → evidência

### Frontend desacoplado
- Crews publicam eventos pra banco central
- Frontend lê do banco (sem licença Kiro Crew)
- Libera acesso pra quem precisar (stakeholders, produto)

---

## Princípios de design

1. **Zero-token no agendamento** — polling é código puro
2. **Estado na issue** — labels + comentários, não banco separado
3. **Multi-squad nativo** — um observador, N repos
4. **Modo auto e manual** — funciona em qualquer máquina
5. **Documentação = Definition of Done** — código reflete docs
6. **Auditoria completa** — toda ação vira comentário
