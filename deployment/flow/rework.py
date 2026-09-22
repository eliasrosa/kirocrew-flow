"""Cron flow-rework — processa ``flow:review-refused`` (gate humano).

**Gate humano inviolável (fluxo.md).** Quando o reviewer reprova, este cron
apenas NOTIFICA o TL — NUNCA despacha uma sessão automaticamente. O fluxo para
e aguarda decisão manual (TL/dev move para develop-waiting).

Registro (uma vez):
    cron_add(name="flow-rework",
             script="~/.kiro/crew/crons/deployment/flow/rework.py:run",
             every=300)
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
    """Cron flow-rework — processa flow:review-refused (notifica TL, não despacha)."""
    run_stage(ctx, FlowStage.REWORK)
