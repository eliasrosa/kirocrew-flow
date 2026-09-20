"""Teste de paridade entre ActionKind e _STAGE_ACTIONS — o gate anti-órfã.

No modo por-estágio (crons crewflow-dev/reviewer/merge/conflito, issue #87), o
_run_stage() filtra as decisões do executor por ``allowed_actions =
_STAGE_ACTIONS[stage]``. Qualquer ActionKind de dispatch/mutação que NÃO esteja
mapeada a algum estágio é descartada silenciosamente — foi exatamente essa a
regressão do bug do conflito de merge órfão: MARK_CONFLITO e
DISPATCH_CONFLICT_RESOLVER não estavam em estágio nenhum e nunca rodavam.

Este teste é o gate real:

1. Toda ActionKind acionável (dispatch de sessão ou mutação de label) TEM que
   estar em algum estágio de _STAGE_ACTIONS.
2. As únicas exceções permitidas são as ações NÃO roteadas por estágio — o
   conjunto sentinela documentado abaixo (SKIP/BLOCK/REBRAND/NOTIFY_HUMAN).
   Estas são tratadas de forma uniforme (ou são no-ops) e não disparam um
   efeito colateral específico de um cron.
3. Se alguém adicionar uma nova ActionKind ao executor sem mapeá-la a um
   estágio NEM listá-la como sentinela, este teste quebra (red) — forçando uma
   decisão consciente.
"""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = str(Path(__file__).parent.parent.parent)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

import unittest  # noqa: E402

from deployment.deployment import (  # noqa: E402
    _STAGE_ACTIONS,
    _STAGE_CONFLITO,
    _STAGE_DEV,
    _STAGE_MERGE,
    _STAGE_REVIEWER,
)
from flow.executor.executor import ActionKind  # noqa: E402

# Ações que NÃO são roteadas por estágio, por design. Cada uma listada com o
# motivo — adicionar uma nova ActionKind aqui deve ser uma decisão consciente.
#
#   SKIP         — no-op; nenhum efeito colateral, todo estágio simplesmente ignora.
#   BLOCK        — marca crewflow:blocked; tratado fora do slicing por estágio.
#   REBRAND      — troca de template (GATE 0 hotfix); não é dispatch de cron.
#   NOTIFY_HUMAN — notifica humano; tratado de forma uniforme, não pertence a um cron.
_NON_STAGE_ROUTED: frozenset[str] = frozenset({
    ActionKind.SKIP.value,
    ActionKind.BLOCK.value,
    ActionKind.REBRAND.value,
    ActionKind.NOTIFY_HUMAN.value,
})


class TestStageActionsParity(unittest.TestCase):
    """Nenhuma ActionKind acionável pode ficar órfã de _STAGE_ACTIONS."""

    @property
    def mapped_actions(self) -> frozenset[str]:
        """União de todas as ações mapeadas a algum estágio."""
        mapped: set[str] = set()
        for actions in _STAGE_ACTIONS.values():
            mapped |= set(actions)
        return frozenset(mapped)

    # ------------------------------------------------------------------
    # Cobertura total
    # ------------------------------------------------------------------

    def test_toda_actionkind_acionavel_esta_mapeada(self) -> None:
        """Toda ActionKind fora do conjunto sentinela DEVE estar em algum estágio.

        Este é o teste que quebra quando alguém adiciona uma nova ActionKind ao
        executor sem mapeá-la a um estágio nem listá-la como não-roteada.
        """
        all_actions = {a.value for a in ActionKind}
        expected_mapped = all_actions - _NON_STAGE_ROUTED
        self.assertEqual(
            self.mapped_actions,
            expected_mapped,
            "\n\nDivergência entre _STAGE_ACTIONS e ActionKind:\n"
            f"  ações mapeadas a estágios : {sorted(self.mapped_actions)}\n"
            f"  esperado (todas menos sentinelas): {sorted(expected_mapped)}\n"
            f"  órfãs (emitidas mas sem estágio): {sorted(expected_mapped - self.mapped_actions)}\n"
            f"  extras (mapeadas mas inexistentes/sentinela): {sorted(self.mapped_actions - expected_mapped)}\n\n"
            "Se você adicionou uma nova ActionKind, mapeie-a a um estágio em\n"
            "_STAGE_ACTIONS ou liste-a em _NON_STAGE_ROUTED com justificativa.",
        )

    def test_nenhuma_actionkind_fica_orfa(self) -> None:
        """Itera cada ActionKind: se não é sentinela, tem que estar mapeada."""
        for action in ActionKind:
            if action.value in _NON_STAGE_ROUTED:
                continue
            self.assertIn(
                action.value,
                self.mapped_actions,
                f"\n\nActionKind {action.name} ({action.value!r}) é acionável mas "
                f"não está em nenhum estágio de _STAGE_ACTIONS.\n"
                f"No modo por-estágio ela seria descartada silenciosamente (regressão #87).\n"
                f"Mapeie-a a um estágio ou liste-a em _NON_STAGE_ROUTED.",
            )

    def test_mapeamento_nao_referencia_acao_inexistente(self) -> None:
        """Toda string em _STAGE_ACTIONS deve corresponder a uma ActionKind real."""
        valid = {a.value for a in ActionKind}
        for stage, actions in _STAGE_ACTIONS.items():
            for action_str in actions:
                self.assertIn(
                    action_str,
                    valid,
                    f"\n\nEstágio {stage!r} mapeia {action_str!r}, que não é uma "
                    f"ActionKind válida. Ações válidas: {sorted(valid)}",
                )

    # ------------------------------------------------------------------
    # Regression lock explícito para o bug do conflito de merge órfão
    # ------------------------------------------------------------------

    def test_mark_conflito_esta_mapeado(self) -> None:
        """Regression lock: mark_conflito NÃO pode voltar a ficar órfão."""
        self.assertIn(
            ActionKind.MARK_CONFLITO.value,
            self.mapped_actions,
            "mark_conflito ficou órfão de _STAGE_ACTIONS — PR com conflito de "
            "merge nunca recebe crewflow:conflito no modo por-estágio.",
        )

    def test_dispatch_conflict_resolver_esta_mapeado(self) -> None:
        """Regression lock: dispatch_conflict_resolver NÃO pode voltar a ficar órfão."""
        self.assertIn(
            ActionKind.DISPATCH_CONFLICT_RESOLVER.value,
            self.mapped_actions,
            "dispatch_conflict_resolver ficou órfão de _STAGE_ACTIONS — a sessão "
            "de resolução de conflito (conflict.md) nunca é despachada no modo por-estágio.",
        )

    def test_conflito_actions_no_estagio_correto(self) -> None:
        """mark_conflito no reviewer; dispatch_conflict_resolver no conflito."""
        self.assertIn(ActionKind.MARK_CONFLITO.value, _STAGE_ACTIONS[_STAGE_REVIEWER])
        self.assertIn(
            ActionKind.DISPATCH_CONFLICT_RESOLVER.value, _STAGE_ACTIONS[_STAGE_CONFLITO]
        )

    def test_todos_os_estagios_conhecidos_estao_no_mapa(self) -> None:
        """_STAGE_ACTIONS cobre exatamente os quatro estágios definidos."""
        self.assertEqual(
            set(_STAGE_ACTIONS),
            {_STAGE_DEV, _STAGE_REVIEWER, _STAGE_MERGE, _STAGE_CONFLITO},
        )


if __name__ == "__main__":
    unittest.main()
