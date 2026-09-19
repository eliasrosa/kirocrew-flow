"""Testes da correção estrutural do bug #116 (FEAT-002).

Cobre dois comportamentos de deployment/deployment.py:

1. ``_dispatch_reviewer`` NÃO propaga ``PromptRenderError`` — degrada
   graciosamente (loga, notifica o humano, retorna) igual a _dispatch_rework
   e _dispatch_conflict_resolver.
2. ``_warn_if_installed_script_stale`` detecta divergência entre o cron
   instalado e o deployment.py do repo, tolerando ausência e ignorando o
   patch de sys.path do install-cron.sh (sem falso positivo).
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest import mock

_REPO_ROOT = str(Path(__file__).parent.parent.parent)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

import deployment.deployment as dep  # noqa: E402
from flow.prompts.loader import PromptRenderError  # noqa: E402


def _make_ctx() -> mock.MagicMock:
    ctx = mock.MagicMock()
    ctx._port = 5000
    ctx._secret = "secret"
    ctx.job.id = "test-job"
    return ctx


def _issue() -> dict:
    return {"number": 42, "title": "Bug X", "url": "https://x/issues/42"}


# ---------------------------------------------------------------------------
# _dispatch_reviewer — degradação graciosa (critério 3)
# ---------------------------------------------------------------------------

class TestDispatchReviewerNaoAborta:
    def test_prompt_render_error_nao_propaga(self) -> None:
        """PromptRenderError em _reviewer_prompt não escapa de _dispatch_reviewer."""
        ctx = _make_ctx()
        cfg = {"agent": "kirocrew", "notify_chat_id": "chat-1"}

        fake_pr = mock.MagicMock(returncode=0, stdout='[{"number": 7}]', stderr="")

        with (
            mock.patch("subprocess.run", return_value=fake_pr),
            mock.patch.object(
                dep, "_reviewer_prompt",
                side_effect=PromptRenderError("variável 'head_sha' faltando"),
            ),
        ):
            # Não deve levantar — degrada graciosamente (não chega ao POST).
            dep._dispatch_reviewer(ctx, "owner/repo", _issue(), cfg)

        # Notificou o humano sobre o template desatualizado
        ctx.notify.assert_called()
        msg = ctx.notify.call_args[0][0]
        assert "install-cron" in msg or "template" in msg.lower()

    def test_sem_pr_apenas_notifica(self) -> None:
        """Sem PR localizado, notifica e retorna sem tentar renderizar prompt."""
        ctx = _make_ctx()
        cfg = {"agent": "kirocrew", "notify_chat_id": ""}

        empty_pr = mock.MagicMock(returncode=0, stdout="[]", stderr="")
        with (
            mock.patch("subprocess.run", return_value=empty_pr),
            mock.patch.object(dep, "_reviewer_prompt") as mock_prompt,
        ):
            dep._dispatch_reviewer(ctx, "owner/repo", _issue(), cfg)

        mock_prompt.assert_not_called()
        ctx.notify.assert_called()

    def test_prompt_ok_despacha_normalmente(self) -> None:
        """Com prompt válido, o dispatch segue e notifica sucesso."""
        ctx = _make_ctx()
        cfg = {"agent": "kirocrew", "notify_chat_id": ""}

        fake_pr = mock.MagicMock(returncode=0, stdout='[{"number": 7}]', stderr="")

        # kiro_crew só existe em runtime; injeta um stub para o import lazy.
        fake_loop = mock.MagicMock()
        fake_loop.return_value.__enter__ = mock.MagicMock(return_value=mock.MagicMock())
        fake_loop.return_value.__exit__ = mock.MagicMock(return_value=False)
        fake_module = mock.MagicMock()
        fake_module.loopback_urlopen = fake_loop

        with (
            mock.patch("subprocess.run", return_value=fake_pr),
            mock.patch.object(dep, "_reviewer_prompt", return_value="PROMPT"),
            mock.patch.dict(
                sys.modules, {"kiro_crew.loopback_http": fake_module}
            ),
        ):
            dep._dispatch_reviewer(ctx, "owner/repo", _issue(), cfg)

        fake_loop.assert_called_once()


# ---------------------------------------------------------------------------
# _warn_if_installed_script_stale — detecção de divergência (critério 2)
# ---------------------------------------------------------------------------

# Bloco original no repo (sem patch de sys.path).
_REPO_SRC = (
    "import os\n"
    "_HERE = os.path.dirname(os.path.abspath(__file__))\n"
    "_REPO_ROOT = os.path.dirname(_HERE)\n"
    "if _REPO_ROOT not in sys.path:\n"
    "    sys.path.insert(0, _REPO_ROOT)\n"
    "\n"
    "def run():\n"
    "    pass\n"
)

# Mesmo conteúdo lógico, mas com o patch de sys.path que o install-cron.sh injeta.
_INSTALLED_SRC_PATCHED = (
    "import os\n"
    "_HERE = os.path.dirname(os.path.abspath(__file__))\n"
    "_REPO_ROOT = os.path.dirname(_HERE)\n"
    "# Quando instalado em ~/.kiro/crew/crons/, _REPO_ROOT aponta para ~/.kiro/crew/\n"
    "# onde flow/ não existe. Adicionamos o caminho real do repo:\n"
    '_FLOW_ROOT = "/home/user/repo"\n'
    "if _FLOW_ROOT not in sys.path:\n"
    "    sys.path.insert(0, _FLOW_ROOT)\n"
    "if _REPO_ROOT not in sys.path:\n"
    "    sys.path.insert(0, _REPO_ROOT)\n"
    "\n"
    "def run():\n"
    "    pass\n"
)

# Instalado divergente: uma função a mais que o repo não tem (código velho).
_INSTALLED_SRC_STALE = _INSTALLED_SRC_PATCHED + "\ndef velho():\n    pass\n"


class TestWarnIfInstalledScriptStale:
    def test_normalizacao_ignora_patch_syspath(self) -> None:
        """Repo e instalado (só diferindo no patch) normalizam para o mesmo texto."""
        assert (
            dep._normalize_deployment_source(_REPO_SRC)
            == dep._normalize_deployment_source(_INSTALLED_SRC_PATCHED)
        )

    def test_sem_script_instalado_nao_avisa(self) -> None:
        """Sem arquivo instalado (dev local) não emite warning."""
        with (
            mock.patch("os.path.exists", return_value=False),
            mock.patch.object(dep.logger, "warning") as mock_warn,
        ):
            dep._warn_if_installed_script_stale()
        mock_warn.assert_not_called()

    def test_instalado_identico_nao_avisa(self) -> None:
        """Instalado idêntico ao repo (modulo patch) não emite warning."""
        reads = iter([_INSTALLED_SRC_PATCHED, _REPO_SRC])

        m = mock.mock_open()
        m.return_value.read.side_effect = lambda *a, **k: next(reads)

        with (
            mock.patch("os.path.exists", return_value=True),
            mock.patch("os.path.abspath", side_effect=lambda p: p),
            mock.patch("builtins.open", m),
            mock.patch.object(dep, "_INSTALLED_SCRIPT_PATH", "/fake/installed.py"),
            mock.patch.object(dep, "__file__", "/fake/repo.py"),
            mock.patch.object(dep.logger, "warning") as mock_warn,
        ):
            dep._warn_if_installed_script_stale()
        mock_warn.assert_not_called()

    def test_instalado_divergente_avisa(self) -> None:
        """Instalado divergente do repo emite warning pedindo install-cron.sh."""
        reads = iter([_INSTALLED_SRC_STALE, _REPO_SRC])

        m = mock.mock_open()
        m.return_value.read.side_effect = lambda *a, **k: next(reads)

        with (
            mock.patch("os.path.exists", return_value=True),
            mock.patch("os.path.abspath", side_effect=lambda p: p),
            mock.patch("builtins.open", m),
            mock.patch.object(dep, "_INSTALLED_SCRIPT_PATH", "/fake/installed.py"),
            mock.patch.object(dep, "__file__", "/fake/repo.py"),
            mock.patch.object(dep.logger, "warning") as mock_warn,
        ):
            dep._warn_if_installed_script_stale()
        mock_warn.assert_called_once()
        msg = mock_warn.call_args[0][0]
        assert "install-cron.sh" in msg

    def test_modulo_em_execucao_e_o_instalado_nao_avisa(self) -> None:
        """Se o módulo em execução JÁ é o instalado, não há o que comparar."""
        with (
            mock.patch("os.path.abspath", return_value="/same/path.py"),
            mock.patch.object(dep, "_INSTALLED_SCRIPT_PATH", "/same/path.py"),
            mock.patch.object(dep.logger, "warning") as mock_warn,
        ):
            dep._warn_if_installed_script_stale()
        mock_warn.assert_not_called()

    def test_erro_de_leitura_nao_aborta(self) -> None:
        """Erro de leitura vira warning e não propaga exceção."""
        with (
            mock.patch("os.path.exists", return_value=True),
            mock.patch("os.path.abspath", side_effect=lambda p: p),
            mock.patch("builtins.open", side_effect=OSError("boom")),
            mock.patch.object(dep, "_INSTALLED_SCRIPT_PATH", "/fake/installed.py"),
            mock.patch.object(dep, "__file__", "/fake/repo.py"),
            mock.patch.object(dep.logger, "warning") as mock_warn,
        ):
            dep._warn_if_installed_script_stale()  # não deve levantar
        mock_warn.assert_called_once()
