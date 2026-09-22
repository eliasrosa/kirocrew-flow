"""Testes para os crons de notificação da issue #195.

Valida os três novos entrypoints por estágio, todos NOTIFICATION-ONLY:

  - run_rework      → flow:review-refused (gate humano, notifica TL, NUNCA despacha)
  - run_qa_notify   → flow:qa-waiting     (notifica QA)
  - run_qa_refused  → flow:qa-refused     (gate humano, notifica TL + dev, NUNCA despacha)

Regra inviolável (fluxo.md): review-refused e qa-refused são gates humanos —
o cron apenas notifica o papel correto e para. Sem dispatch automático.

Estes testes exercitam o caminho real de ``_run_notify_stage``; se a lógica dos
novos crons for revertida (ou o roteamento por estado quebrar), eles falham.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path
from unittest import mock

_REPO_ROOT = str(Path(__file__).parent.parent.parent)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from deployment.deployment import (  # noqa: E402
    _NOTIFY_STAGE_STATES,
    FlowStage,
    run_qa_notify,
    run_qa_refused,
    run_rework,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_ctx() -> mock.MagicMock:
    ctx = mock.MagicMock()
    ctx._port = 5000
    ctx._secret = "secret"
    ctx.job.id = "test-job"
    return ctx


def _base_config(**overrides: object) -> dict:
    cfg: dict = {
        "repos": ["owner/repo"],
        "auto_dispatch": True,
        "max_concurrent_tasks": 2,
        "one_per_repo": False,
        "notify_chat_id": "",
        "squad_id": "test",
        "issue_provider": "github",
        "dev_root": "/tmp/dev",
        "agent": "kirocrew",
    }
    cfg.update(overrides)
    return cfg


def _make_scan_result(state_label: str, modifiers: list[str] | None = None) -> object:
    from flow.domain.gates import WorkItem
    from flow.domain.state import parse_modifiers, parse_state
    from flow.scan.scanner import ScanResult

    labels_set = frozenset([state_label] + (modifiers or []))
    state = parse_state(labels_set)
    mods = parse_modifiers(labels_set)

    return ScanResult(
        item=WorkItem(
            key="https://github.com/owner/repo/issues/42",
            title="[owner/repo] Test issue",
            labels=labels_set,
        ),
        current_state=state,
        modifiers=mods,
        dispatch_candidate=False,
        spec_valid=None,
        changed=True,
        reason="test",
    )


def _patched_run(entrypoint, ctx, result, cfg=None):
    """Executa um entrypoint de notificação com scan/config mockados.

    Patches todos os colaboradores de I/O; retorna sem tocar em rede/disco.
    """
    cfg = cfg or _base_config()
    with (
        mock.patch("deployment.deployment._load_config", return_value=cfg),
        mock.patch("deployment.deployment.scan_candidates", return_value=[result]),
        mock.patch("deployment.deployment.open_cache") as mock_cache,
        mock.patch("deployment.deployment.provider_for") as mock_pf,
        mock.patch("deployment.deployment._dispatch") as mock_dispatch,
        mock.patch("deployment.deployment._dispatch_rework") as mock_rework,
        mock.patch("deployment.deployment._dispatch_reviewer") as mock_rev,
        mock.patch("deployment.deployment._dispatch_conflict_resolver") as mock_conf,
        mock.patch("deployment.deployment._execute_auto_merges") as mock_merge,
    ):
        mock_cache.return_value.__enter__ = mock.MagicMock(
            return_value=sqlite3.connect(":memory:"))
        mock_cache.return_value.__exit__ = mock.MagicMock(return_value=False)
        provider = mock.MagicMock()
        provider.get_state_comment = mock.MagicMock(return_value=None)
        mock_pf.return_value = provider
        entrypoint(ctx)
    return {
        "dispatch": mock_dispatch,
        "rework": mock_rework,
        "reviewer": mock_rev,
        "conflict": mock_conf,
        "merge": mock_merge,
    }


# ---------------------------------------------------------------------------
# Mapeamento de estágios de notificação
# ---------------------------------------------------------------------------

class TestNotifyStageStates:
    def test_mapeamento_cobre_os_tres_estagios(self) -> None:
        assert _NOTIFY_STAGE_STATES[FlowStage.REWORK] == "flow:review-refused"
        assert _NOTIFY_STAGE_STATES[FlowStage.QA_NOTIFY] == "flow:qa-waiting"
        assert _NOTIFY_STAGE_STATES[FlowStage.QA_REFUSED] == "flow:qa-refused"

    def test_estagios_de_notificacao_nao_estao_em_stage_actions(self) -> None:
        """NOTIFY_HUMAN é transversal — os estágios de notificação não entram em _STAGE_ACTIONS."""
        from deployment.deployment import _STAGE_ACTIONS

        for stage in _NOTIFY_STAGE_STATES:
            assert stage not in _STAGE_ACTIONS


# ---------------------------------------------------------------------------
# run_rework — flow:review-refused (gate humano)
# ---------------------------------------------------------------------------

class TestRunRework:
    def test_notifica_tl_para_review_refused(self) -> None:
        ctx = _make_ctx()
        result = _make_scan_result("flow:review-refused")
        mocks = _patched_run(run_rework, ctx, result)

        # Gate humano: NUNCA despacha
        mocks["rework"].assert_not_called()
        mocks["dispatch"].assert_not_called()
        # Notifica o TL
        ctx.notify.assert_called()
        msg = " ".join(str(c.args[0]) for c in ctx.notify.call_args_list)
        assert "TL" in msg or "GATE" in msg

    def test_ignora_issue_de_outro_estagio(self) -> None:
        """run_rework não age em flow:develop-waiting (pertence ao cron dev)."""
        ctx = _make_ctx()
        result = _make_scan_result("flow:develop-waiting")
        mocks = _patched_run(run_rework, ctx, result)

        mocks["rework"].assert_not_called()
        mocks["dispatch"].assert_not_called()
        # Nenhuma notificação de gate humano para uma issue que não é do estágio
        for call in ctx.notify.call_args_list:
            assert "GATE DT" not in str(call.args[0])

    def test_nao_despacha_mesmo_com_auto_dispatch(self) -> None:
        """Gate humano é inviolável: mesmo com auto_dispatch=True não despacha."""
        ctx = _make_ctx()
        result = _make_scan_result("flow:review-refused")
        mocks = _patched_run(run_rework, ctx, result, cfg=_base_config(auto_dispatch=True))
        mocks["rework"].assert_not_called()
        mocks["dispatch"].assert_not_called()


# ---------------------------------------------------------------------------
# run_qa_notify — flow:qa-waiting (aviso ao QA)
# ---------------------------------------------------------------------------

class TestRunQaNotify:
    def test_notifica_qa_para_qa_waiting(self) -> None:
        ctx = _make_ctx()
        result = _make_scan_result("flow:qa-waiting")
        mocks = _patched_run(run_qa_notify, ctx, result)

        # Não despacha nada
        mocks["dispatch"].assert_not_called()
        mocks["rework"].assert_not_called()
        mocks["reviewer"].assert_not_called()
        # Notifica o QA
        ctx.notify.assert_called()
        msg = " ".join(str(c.args[0]) for c in ctx.notify.call_args_list)
        assert "QA" in msg

    def test_ignora_review_refused(self) -> None:
        """run_qa_notify não age em flow:review-refused (pertence ao cron rework)."""
        ctx = _make_ctx()
        result = _make_scan_result("flow:review-refused")
        _patched_run(run_qa_notify, ctx, result)

        # Nenhuma notificação de "aguarda ação do QA" para outro estado
        for call in ctx.notify.call_args_list:
            assert "aguarda ação do QA" not in str(call.args[0])


# ---------------------------------------------------------------------------
# run_qa_refused — flow:qa-refused (gate humano, TL + dev)
# ---------------------------------------------------------------------------

class TestRunQaRefused:
    def test_notifica_tl_e_dev_para_qa_refused(self) -> None:
        ctx = _make_ctx()
        result = _make_scan_result("flow:qa-refused")
        mocks = _patched_run(run_qa_refused, ctx, result)

        # Gate humano: NUNCA despacha
        mocks["dispatch"].assert_not_called()
        mocks["rework"].assert_not_called()
        # Deve notificar (TL via executor + aviso extra ao dev)
        ctx.notify.assert_called()
        msg = " ".join(str(c.args[0]) for c in ctx.notify.call_args_list)
        assert "qa_refused" in msg or "QA reprovou" in msg
        assert "Dev" in msg or "dev" in msg

    def test_ignora_issue_de_outro_estagio(self) -> None:
        ctx = _make_ctx()
        result = _make_scan_result("flow:qa-waiting")
        _patched_run(run_qa_refused, ctx, result)

        for call in ctx.notify.call_args_list:
            assert "QA reprovou" not in str(call.args[0])

    def test_nao_despacha_mesmo_com_auto_dispatch(self) -> None:
        ctx = _make_ctx()
        result = _make_scan_result("flow:qa-refused")
        mocks = _patched_run(run_qa_refused, ctx, result, cfg=_base_config(auto_dispatch=True))
        mocks["dispatch"].assert_not_called()
        mocks["rework"].assert_not_called()
