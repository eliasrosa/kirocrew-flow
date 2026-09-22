"""KiroCrew Flow — stub de compatibilidade do driving adapter.

Historicamente toda a lógica do cron vivia neste arquivo monolítico
(~3400 linhas). A esteira foi refatorada para o pacote ``deployment/flow/``,
com um arquivo por cron sobre uma base comum:

    deployment/
      deployment.py          ← este stub de compatibilidade
      flow/
        __init__.py
        base.py              ← lógica comum (FlowStage, run_stage, dispatch,
                               prompts, helpers de estado, entrypoints legados)
        dev.py               ← run(ctx) → flow:develop-waiting
        reviewer.py          ← run(ctx) → flow:review-waiting
        merge.py             ← run(ctx) → flow:review-approved + flow:qa-approved
        conflict.py          ← run(ctx) → flow:merge-conflict
        rework.py            ← run(ctx) → flow:review-refused (gate humano, notifica TL)
        qa_notify.py         ← run(ctx) → flow:qa-waiting (notifica QA)
        qa_refused.py        ← run(ctx) → flow:qa-refused (gate humano, notifica TL+dev)

## Compatibilidade

Este módulo NÃO redefine nada: ele aliasa ``deployment.deployment`` para o
módulo ``deployment.flow.base``. O efeito é que ``deployment.deployment`` e
``deployment.flow.base`` são o MESMO objeto de módulo. Consequências:

  * ``from deployment.deployment import run, run_dev, _run_stage, _dispatch, ...``
    continua resolvendo todos os símbolos (públicos e privados) — eles são
    atributos do módulo base.
  * ``mock.patch("deployment.deployment.<colaborador>")`` continua funcionando:
    como o módulo é o mesmo objeto que ``base``, o patch altera exatamente o
    namespace global onde as funções (``run``, ``run_dev``, ``_run_stage``,
    etc.) resolvem seus colaboradores. Nenhum teste precisou ser editado.

Os nomes legados dos entrypoints por estágio são preservados por ``base``:
``run_dev`` (dev), ``run_reviewer`` (reviewer), ``run_merge`` (merge),
``run_conflito`` (conflict) — além dos novos ``run_rework``/``run_qa_notify``/
``run_qa_refused`` (issue #195) e do orquestrador monolítico ``run``.

## Instalação do cron

Use sempre ``scripts/install-cron.sh``, que copia a pasta ``deployment/flow/``
inteira para ``~/.kiro/crew/crons/`` e aplica o patch de sys.path. Os crons
apontam para a subpasta, por exemplo:

    script="~/.kiro/crew/crons/deployment/flow/dev.py:run"
"""

from __future__ import annotations

import sys

from deployment.flow import base as _base

# ── Re-export explícito (para type-checkers e leitores) ───────────────────
# O aliasing de sys.modules abaixo é um truque de RUNTIME que o mypy não
# enxerga. Para que ``from deployment.deployment import <nome>`` continue
# type-checkando (o CI roda ``mypy flow/`` que segue os imports até aqui),
# re-exportamos explicitamente toda a superfície pública e privada que os
# testes e o backend consomem. Em runtime estes binds são inofensivos: o
# módulo é substituído por ``base`` logo em seguida, de modo que a fonte única
# de verdade continua sendo ``deployment.flow.base``.
from deployment.flow.base import (  # noqa: F401,E402
    DEAD_SESSION_TIMEOUT_SECS,
    LABEL_BLOCKED,
    LABEL_DEV,
    LABEL_REVIEW,
    FlowStage,
    _active_sessions,
    _apply_state_transition,
    _build_implicit_to_explicit_map,
    _check_installed_version,
    _clean_stale_worktree,
    _collect_implicit_state,
    _CONFIG_CANDIDATES,
    _conflict_prompt,
    _conflict_resolver_has_active,
    _DEV_PROMPT_FALLBACK,
    _DISPATCH_BACKSTOP_SECS,
    _dispatch,
    _dispatch_conflict_resolver,
    _dispatch_prompt,
    _dispatch_reviewer,
    _dispatch_rework,
    _dispatch_stale_lock,
    _dry_run_report,
    _execute_auto_merges,
    _HERE,
    _is_dead_session,
    _is_issue_closed,
    _issue_has_active_session,
    _load_config,
    _lock_is_stale,
    _log_cycle_summary,
    _log_shadow_divergences,
    _mini_yaml,
    _MODULE_DIR,
    _notify_human_actions,
    _notify_reviewers,
    _NOTIFY_STAGE_STATES,
    _post_reviewer_result_on_pr,
    _pr_exists,
    _recover_dead_session,
    _REPO_ROOT,
    _repo_has_active,
    _resource_headroom_ok,
    _reviewer_has_active,
    _reviewer_prompt,
    _rework_has_active,
    _rework_prompt,
    _REWORK_PROMPT_FALLBACK,
    _CONFLICT_PROMPT_FALLBACK,
    _run_notify_stage,
    _run_stage,
    _scan_result_to_issue,
    _sessdir,
    _STAGE_ACTIONS,
    _STAGE_CONFLITO,
    _STAGE_DEV,
    _STAGE_MERGE,
    _STAGE_QA_NOTIFY,
    _STAGE_QA_REFUSED,
    _STAGE_REVIEWER,
    _STAGE_REWORK,
    _stage_model,
    _try_acquire_dispatch_lock,
    _update_issue_with_pr_ref,
    _worktree_path,
    clear_running_since,
    get_running_since,
    logger,
    open_cache,
    provider_for,
    render_prompt,
    run,
    run_conflito,
    run_dev,
    run_merge,
    run_qa_notify,
    run_qa_refused,
    run_reviewer,
    run_rework,
    run_stage,
    scan_candidates,
    set_running_since,
)

# Aliasa este módulo para o módulo base: ambos passam a ser o MESMO objeto.
# Isso garante que os imports históricos e os mock.patch("deployment.deployment.X")
# continuem operando sobre o namespace onde as funções realmente executam.
sys.modules[__name__] = _base
