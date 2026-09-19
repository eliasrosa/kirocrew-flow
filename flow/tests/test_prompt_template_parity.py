"""Teste de paridade template<->código — o gate que evita o bug da #116.

O loader de prompts (flow/prompts/loader.py) é fail-closed: se um template
``flow/prompts/<stage>.md`` referencia ``{{variavel}}`` que o dispatcher
correspondente em ``deployment/deployment.py`` NÃO fornece, o render levanta
``PromptRenderError`` e o dispatch aborta. Isso é o comportamento correto do
loader (issue #86), mas em produção travou a esteira por ~12h (issue #110/#116)
quando reviewer.md ganhou ``{{head_sha}}`` e o script instalado no cron ainda
não passava esse argumento.

Este teste é o gate que quebra o CI ANTES de o descompasso chegar ao cron:
para cada template, extrai os placeholders com a MESMA regex do loader e
confere que o dispatcher fornece todas as variáveis referenciadas.

Duas decisões de design copiadas de flow/tests/test_provider_parity.py:

1. A tabela STAGES é a fonte da verdade de quem verifica quem.
2. O teste se AUTO-PROTEGE: um template novo em flow/prompts/ sem entrada na
   tabela faz o teste falhar — senão um template novo passaria sem verificação.
"""

from __future__ import annotations

import sys
import unittest
from collections.abc import Callable
from pathlib import Path
from typing import ClassVar
from unittest import mock

_REPO_ROOT = str(Path(__file__).parent.parent.parent)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

import deployment.deployment as dep  # noqa: E402
from flow.prompts.loader import _PLACEHOLDER_RE, _PROMPTS_DIR  # noqa: E402

# Inputs sintéticos reutilizados por todos os dispatchers.
_REPO = "owner/repo"
_ISSUE: dict = {
    "number": 42,
    "title": "Corrige bug X",
    "url": "https://github.com/owner/repo/issues/42",
}
_CFG: dict = {
    "agent": "kirocrew",
    "dev_root": "/tmp/dev",
    "notify_chat_id": "",
    "vault_root": "",
}
_PR_NUMBER = 7
_ITERATION = 2
_HEAD_SHA = "abc123"


def _invoke_dev(capture: dict[str, str]) -> None:
    dep._dispatch_prompt(_REPO, _ISSUE, _CFG)


def _invoke_reviewer(capture: dict[str, str]) -> None:
    dep._reviewer_prompt(_REPO, _PR_NUMBER, _ISSUE["number"], head_sha=_HEAD_SHA)


def _invoke_rework(capture: dict[str, str]) -> None:
    dep._rework_prompt(_REPO, _ISSUE, _PR_NUMBER, _ITERATION, _CFG)


def _invoke_conflict(capture: dict[str, str]) -> None:
    dep._conflict_prompt(_REPO, _ISSUE, _PR_NUMBER, _CFG)


# Mapa stage -> função que invoca o dispatcher correspondente.
# Auto-guard: todo template flow/prompts/*.md TEM que ter entrada aqui.
STAGES: dict[str, Callable[[dict[str, str]], None]] = {
    "dev": _invoke_dev,
    "reviewer": _invoke_reviewer,
    "rework": _invoke_rework,
    "conflict": _invoke_conflict,
}


def _placeholders_do_template(stage: str) -> set[str]:
    """Extrai os placeholders {{var}} do template do estágio, via regex do loader."""
    conteudo = (_PROMPTS_DIR / f"{stage}.md").read_text(encoding="utf-8")
    return set(_PLACEHOLDER_RE.findall(conteudo))


def _variaveis_fornecidas(stage: str) -> set[str]:
    """Invoca o dispatcher do estágio e captura as variáveis passadas a render_prompt.

    Faz monkeypatch de ``deployment.deployment.render_prompt`` (o dispatcher chama
    esse nome, pois deployment.py faz ``from flow.prompts.loader import render_prompt``)
    para capturar os kwargs sem de fato renderizar. subprocess.run é mockado porque
    ``_conflict_prompt`` roda ``gh repo view`` e ``_reviewer_prompt`` monta exemplos.
    """
    capturado: dict[str, str] = {}

    def _fake_render(stage_arg: str, fallback: str | None = None, **variables: str) -> str:
        capturado.update(variables)
        return "prompt-fake"

    fake_proc = mock.MagicMock(returncode=0, stdout="main", stderr="")
    with (
        mock.patch.object(dep, "render_prompt", side_effect=_fake_render),
        mock.patch("subprocess.run", return_value=fake_proc),
    ):
        STAGES[stage](capturado)
    return set(capturado)


class TestPromptTemplateParity(unittest.TestCase):
    """Todo placeholder de template deve ter variável fornecida pelo dispatcher."""

    stages: ClassVar[dict[str, Callable[[dict[str, str]], None]]] = STAGES

    # ------------------------------------------------------------------
    # Auto-guard
    # ------------------------------------------------------------------

    def test_a_tabela_cobre_todos_os_templates(self) -> None:
        """Todo flow/prompts/*.md TEM que estar na tabela STAGES.

        Sem isso, adicionar flow/prompts/deploy.md e esquecer de registrá-lo
        aqui deixaria o gate passando sem verificar o template novo.
        """
        templates = {p.stem for p in _PROMPTS_DIR.glob("*.md")}
        tabela = set(self.stages)
        faltando = templates - tabela
        self.assertFalse(
            faltando,
            f"\n\nTemplates em flow/prompts/ AUSENTES da tabela STAGES deste teste:\n"
            f"  {sorted(faltando)!r}\n\n"
            f"Adicione cada um a STAGES (com o dispatcher correspondente) antes de "
            f"continuar. Sem isso, o gate passa mesmo que o template novo referencie "
            f"variáveis que nenhum dispatcher fornece.",
        )

    def test_tabela_nao_tem_stages_fantasmas(self) -> None:
        """A tabela não pode mapear stages sem template no disco."""
        templates = {p.stem for p in _PROMPTS_DIR.glob("*.md")}
        fantasmas = set(self.stages) - templates
        self.assertFalse(
            fantasmas,
            f"Stages na tabela sem template em flow/prompts/: {sorted(fantasmas)!r}",
        )

    # ------------------------------------------------------------------
    # Paridade
    # ------------------------------------------------------------------

    def test_todo_placeholder_tem_variavel_no_dispatcher(self) -> None:
        """Para cada stage, placeholders do template <= variáveis fornecidas."""
        for stage in sorted(self.stages):
            placeholders = _placeholders_do_template(stage)
            fornecidas = _variaveis_fornecidas(stage)
            faltando = placeholders - fornecidas
            self.assertFalse(
                faltando,
                f"\n\nDescompasso template<->código no stage {stage!r}:\n"
                f"  template flow/prompts/{stage}.md referencia: {sorted(faltando)!r}\n"
                f"  mas o dispatcher NÃO passa essa(s) variável(is) a render_prompt.\n\n"
                f"Isso reproduz o bug da #116 (loader fail-closed aborta o dispatch).\n"
                f"Ou o template referencia var a mais, ou o dispatcher deixou de passá-la.\n"
                f"  placeholders do template : {sorted(placeholders)!r}\n"
                f"  variáveis do dispatcher  : {sorted(fornecidas)!r}",
            )


if __name__ == "__main__":
    unittest.main()
