"""Cron flow-merge — processa ``flow:review-approved`` e ``flow:qa-approved``.

Executa o merge squash automático dos PRs aprovados. Intervalo curto: 120s.

Registro (uma vez):
    cron_add(name="flow-merge",
             script="~/.kiro/crew/crons/deployment/flow/merge.py:run",
             every=120)
"""

from __future__ import annotations

import os as _os
import sys as _sys

# Import absoluto (não relativo): o loader de cron do Kiro Crew pode executar
# este arquivo POR CAMINHO como script top-level (sem contexto de pacote), caso
# em que ``from .base import ...`` levantaria "attempted relative import with no
# known parent package". Garantimos que o diretório-pai do pacote ``deployment``
# esteja no sys.path e importamos ``deployment.flow.base`` de forma absoluta.
_PKG_PARENT = _os.path.dirname(
    _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
)
if _PKG_PARENT not in _sys.path:
    _sys.path.insert(0, _PKG_PARENT)

from deployment.flow.base import FlowStage, run_stage  # noqa: E402


def run(ctx: object) -> None:
    """Cron flow-merge — processa flow:review-approved + flow:qa-approved."""
    run_stage(ctx, FlowStage.MERGE)
