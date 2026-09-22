"""Pacote ``deployment.flow`` — driving adapter da esteira, um arquivo por cron.

Refatoração do antigo ``deployment/deployment.py`` monolítico (issue de refactor
+ issue #195). A lógica comum vive em ``base.py``; cada cron
(``dev``/``reviewer``/``merge``/``conflict``/``rework``/``qa_notify``/``qa_refused``)
expõe uma função ``run(ctx)`` que delega para ``base.run_stage``.

O módulo de compatibilidade ``deployment/deployment.py`` re-exporta toda a
superfície pública e privada deste pacote (via ``base``) para que os imports e
``mock.patch`` históricos continuem funcionando sem edição.
"""

from __future__ import annotations

from deployment.flow.base import (
    run,
    run_conflito,
    run_dev,
    run_merge,
    run_qa_notify,
    run_qa_refused,
    run_reviewer,
    run_rework,
)

__all__ = [
    "run",
    "run_conflito",
    "run_dev",
    "run_merge",
    "run_qa_notify",
    "run_qa_refused",
    "run_reviewer",
    "run_rework",
]
