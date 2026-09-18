"""Testes de roteamento das crons por estágio (FEAT-002 / BO #1).

Cada estágio (dev / reviewer / merge / conflito) vira uma cron de script
independente que varre só as labels do seu estágio e executa só as ações do
seu estágio. Estes testes exercem o caminho REAL de roteamento em run_dev /
run_reviewer / run_merge / run_conflito e falhariam se o filtro por estágio
fosse revertido (ex.: se run_dev voltasse a despachar reviewer/merge).

Seguem os mesmos padrões de mock de test_deployment_integration.py:
mock em _load_config, scan_candidates, open_cache, provider_for,
_dispatch/_dispatch_reviewer/_execute_auto_merges e subprocess.
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
    _chat_body,
    _stage_log_path,
    _stage_model,
    run,
    run_conflito,
    run_dev,
    run_merge,
    run_reviewer,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ctx() -> mock.MagicMock:
    ctx = mock.MagicMock()
    ctx._port = 5000
    ctx._secret = "secret"
    ctx.job.id = "test-job"
    return ctx


def _cfg(stages: dict | None = None, auto: bool = True) -> dict:
    cfg: dict = {
        "repos": ["owner/repo"],
        "auto_dispatch": auto,
        "max_concurrent": 2,
        "one_per_repo": False,
        "notify_chat_id": "",
        "squad_id": "test",
        "issue_provider": "github",
        "dev_root": "/tmp/dev",
        "agent": "kirocrew",
    }
    if stages is not None:
        cfg["stages"] = stages
    return cfg


def _todo_result(key: str = "https://github.com/owner/repo/issues/42") -> object:
    from flow.domain.gates import WorkItem
    from flow.domain.state import State
    from flow.scan.scanner import ScanResult

    return ScanResult(
        item=WorkItem(key=key, title="[owner/repo] Feature", labels=frozenset(["crewflow:todo", "crewflow:feature"])),
        current_state=State.TODO,
        modifiers=frozenset(),
        dispatch_candidate=True,
        spec_valid=None,
        changed=True,
        reason="CANDIDATO A DISPATCH",
    )


def _review_result(key: str = "https://github.com/owner/repo/issues/43") -> object:
    from flow.domain.gates import WorkItem
    from flow.domain.state import State
    from flow.scan.scanner import ScanResult

    return ScanResult(
        item=WorkItem(key=key, title="[owner/repo] Review", labels=frozenset(["crewflow:review", "crewflow:feature"])),
        current_state=State.REVIEW,
        modifiers=frozenset(),
        dispatch_candidate=False,
        spec_valid=None,
        changed=True,
        reason="review pendente",
    )


def _reviewed_result(key: str = "https://github.com/owner/repo/issues/44") -> tuple[object, str]:
    from flow.audit.state_comment import StateComment, render
    from flow.domain.gates import WorkItem
    from flow.domain.state import Modifier, State
    from flow.scan.scanner import ScanResult

    sc = StateComment(workflow="feature (v1)", current_node="review", status="reviewed", repo="owner/repo")
    sc.set_reviewer_result(approved=True, comments=[], sha="abc123")
    body = render(sc)

    result = ScanResult(
        item=WorkItem(key=key, title="[owner/repo] Merge", labels=frozenset(["crewflow:review", "crewflow:reviewed", "crewflow:feature"])),
        current_state=State.REVIEW,
        modifiers=frozenset([Modifier.REVIEWED]),
        dispatch_candidate=False,
        spec_valid=None,
        changed=True,
        reason="reviewer aprovado",
    )
    return result, body


def _conflito_result(key: str = "https://github.com/owner/repo/issues/45") -> object:
    from flow.domain.gates import WorkItem
    from flow.domain.state import State
    from flow.scan.scanner import ScanResult

    return ScanResult(
        item=WorkItem(key=key, title="[owner/repo] Conflito", labels=frozenset(["crewflow:review", "crewflow:conflito"])),
        current_state=State.REVIEW,
        modifiers=frozenset(),
        dispatch_candidate=False,
        spec_valid=None,
        changed=True,
        reason="PR em conflito",
    )


class _Patches:
    """Context manager que aplica os mocks comuns a todos os testes de estágio."""

    def __init__(self, cfg: dict, results: list) -> None:
        self.cfg = cfg
        self.results = results
        self._ctxs: list = []

    def __enter__(self) -> dict:
        provider = mock.MagicMock()
        provider.get_state_comment.return_value = None
        provider.get_pr_for_issue.return_value = None

        patchers = {
            "load_config": mock.patch("deployment.deployment._load_config", return_value=self.cfg),
            "scan": mock.patch("deployment.deployment.scan_candidates", return_value=self.results),
            "cache": mock.patch("deployment.deployment.open_cache"),
            "provider_for": mock.patch("deployment.deployment.provider_for", return_value=provider),
            "dispatch": mock.patch("deployment.deployment._dispatch"),
            "dispatch_reviewer": mock.patch("deployment.deployment._dispatch_reviewer"),
            "dispatch_rework": mock.patch("deployment.deployment._dispatch_rework"),
            "execute_auto_merges": mock.patch("deployment.deployment._execute_auto_merges"),
            "route_conflito": mock.patch("deployment.deployment._route_conflito"),
            "active_sessions": mock.patch("deployment.deployment._active_sessions", return_value=0),
            "repo_has_active": mock.patch("deployment.deployment._repo_has_active", return_value=False),
            "reviewer_has_active": mock.patch("deployment.deployment._reviewer_has_active", return_value=False),
            "pr_exists": mock.patch("deployment.deployment._pr_exists", return_value=False),
            "clean_wt": mock.patch("deployment.deployment._clean_stale_worktree", return_value=False),
            "headroom": mock.patch("deployment.deployment._resource_headroom_ok", return_value=True),
        }
        started = {name: p.start() for name, p in patchers.items()}
        self._ctxs = list(patchers.values())
        cache_mock = started["cache"]
        cache_mock.return_value.__enter__ = mock.MagicMock(return_value=sqlite3.connect(":memory:"))
        cache_mock.return_value.__exit__ = mock.MagicMock(return_value=False)
        started["provider"] = provider
        return started

    def __exit__(self, *exc: object) -> None:
        for p in self._ctxs:
            p.stop()


# ---------------------------------------------------------------------------
# (a) run_dev — só dispatch dev; ignora review/reviewed/conflito
# ---------------------------------------------------------------------------

class TestRunDev:
    def test_dispatcha_dev_e_ignora_outros_estagios(self) -> None:
        reviewed, _body = _reviewed_result()
        results = [_todo_result(), _review_result(), reviewed, _conflito_result()]
        with _Patches(_cfg(), results) as m:
            run_dev(_ctx())
        m["dispatch"].assert_called_once()
        m["dispatch_reviewer"].assert_not_called()
        m["execute_auto_merges"].assert_not_called()
        m["route_conflito"].assert_not_called()

    def test_scan_escopado_ao_estado_todo(self) -> None:
        """run_dev escopa o scan a State.TODO (zero-token do estágio)."""
        with _Patches(_cfg(), [_todo_result()]) as m:
            run_dev(_ctx())
        scan_cfg = m["scan"].call_args[0][0]
        from flow.domain.state import State
        assert scan_cfg.states == frozenset({State.TODO})


# ---------------------------------------------------------------------------
# (b) run_reviewer — só dispatch reviewer; ignora todo/reviewed
# ---------------------------------------------------------------------------

class TestRunReviewer:
    def test_dispatcha_reviewer_e_ignora_dev_e_merge(self) -> None:
        reviewed, _body = _reviewed_result()
        results = [_todo_result(), _review_result(), reviewed]
        with _Patches(_cfg(), results) as m:
            run_reviewer(_ctx())
        m["dispatch_reviewer"].assert_called_once()
        m["dispatch"].assert_not_called()
        m["execute_auto_merges"].assert_not_called()

    def test_scan_escopado_a_review(self) -> None:
        with _Patches(_cfg(), [_review_result()]) as m:
            run_reviewer(_ctx())
        from flow.domain.state import State
        assert m["scan"].call_args[0][0].states == frozenset({State.REVIEW})


# ---------------------------------------------------------------------------
# (c) run_merge — só MERGE_PR; ignora todo/review-only
# ---------------------------------------------------------------------------

class TestRunMerge:
    def test_merge_e_ignora_dev_e_reviewer(self) -> None:
        reviewed, body = _reviewed_result()
        results = [_todo_result(), _review_result(), reviewed]
        with _Patches(_cfg(), results) as m:
            # o estado reviewed precisa do state_comment para decidir MERGE_PR
            m["provider"].get_state_comment.return_value = body
            m["provider"].get_pr_for_issue.return_value = {
                "number": 99, "headRefName": "feat/issue-44", "headRefOid": "abc123",
            }
            run_merge(_ctx())
        m["execute_auto_merges"].assert_called_once()
        m["dispatch"].assert_not_called()
        m["dispatch_reviewer"].assert_not_called()

    def test_review_sem_reviewed_nao_faz_merge(self) -> None:
        """run_merge não deve executar merge para itens em review sem aprovação."""
        with _Patches(_cfg(), [_review_result()]) as m:
            run_merge(_ctx())
        m["execute_auto_merges"].assert_not_called()


# ---------------------------------------------------------------------------
# (d) run_conflito — só itens crewflow:conflito; ignora o resto
# ---------------------------------------------------------------------------

class TestRunConflito:
    def test_roteia_conflito_e_ignora_outros(self) -> None:
        reviewed, _body = _reviewed_result()
        results = [_todo_result(), _review_result(), reviewed, _conflito_result()]
        with _Patches(_cfg(), results) as m:
            run_conflito(_ctx())
        m["route_conflito"].assert_called_once()
        # o item roteado é o do label crewflow:conflito
        routed = m["route_conflito"].call_args[0][1]
        assert len(routed) == 1
        assert "crewflow:conflito" in routed[0].item.labels
        m["dispatch"].assert_not_called()
        m["dispatch_reviewer"].assert_not_called()
        m["execute_auto_merges"].assert_not_called()

    def test_sem_conflito_nao_roteia(self) -> None:
        with _Patches(_cfg(), [_todo_result(), _review_result()]) as m:
            run_conflito(_ctx())
        m["route_conflito"].assert_not_called()


# ---------------------------------------------------------------------------
# (e) modelo por estágio threaded no body do POST /api/chat
# ---------------------------------------------------------------------------

class TestPerStageModel:
    def test_modelo_do_dev_threaded_no_dispatch(self) -> None:
        stages = {"dev": {"model": "modelo-forte"}}
        with _Patches(_cfg(stages=stages), [_todo_result()]) as m:
            run_dev(_ctx())
        m["dispatch"].assert_called_once()
        assert m["dispatch"].call_args.kwargs["model"] == "modelo-forte"

    def test_modelo_do_reviewer_threaded_no_dispatch(self) -> None:
        stages = {"reviewer": {"model": "modelo-leve"}}
        with _Patches(_cfg(stages=stages), [_review_result()]) as m:
            run_reviewer(_ctx())
        m["dispatch_reviewer"].assert_called_once()
        assert m["dispatch_reviewer"].call_args.kwargs["model"] == "modelo-leve"

    def test_sem_modelo_configurado_passa_none(self) -> None:
        with _Patches(_cfg(), [_todo_result()]) as m:
            run_dev(_ctx())
        assert m["dispatch"].call_args.kwargs["model"] is None

    def test_stage_model_resolve_da_config(self) -> None:
        cfg = _cfg(stages={"dev": {"model": "x"}, "reviewer": {}})
        assert _stage_model(cfg, "dev") == "x"
        assert _stage_model(cfg, "reviewer") is None
        assert _stage_model(cfg, "merge") is None
        assert _stage_model(cfg, None) is None

    def test_stage_model_sem_bloco_stages(self) -> None:
        assert _stage_model(_cfg(), "dev") is None


# ---------------------------------------------------------------------------
# _chat_body — contrato do body do POST /api/chat
# ---------------------------------------------------------------------------

class TestChatBody:
    def test_sem_modelo_body_inalterado(self) -> None:
        """Sem model: body byte-for-byte igual ao histórico (sem a chave model)."""
        import json
        body = json.loads(_chat_body("msg", "kirocrew", "slot-1"))
        assert body == {
            "message": "msg",
            "agent": "kirocrew",
            "slot": "slot-1",
            "memory_mode": "temporary",
        }
        assert "model" not in body

    def test_com_modelo_adiciona_chave_model(self) -> None:
        import json
        body = json.loads(_chat_body("msg", "kirocrew", "slot-1", model="forte"))
        assert body["model"] == "forte"

    def test_modelo_vazio_nao_adiciona_chave(self) -> None:
        import json
        body = json.loads(_chat_body("msg", "kirocrew", "slot-1", model=""))
        assert "model" not in body


# ---------------------------------------------------------------------------
# (f) backward compat — run() (monolítico) processa TODAS as ações
# ---------------------------------------------------------------------------

class TestBackwardCompat:
    def test_run_monolitico_processa_todos_os_tipos(self) -> None:
        """run() (sem estágio) executa dev, reviewer, merge e conflito num ciclo."""
        reviewed, body = _reviewed_result()
        results = [_todo_result(), _review_result(), reviewed, _conflito_result()]
        with _Patches(_cfg(), results) as m:
            m["provider"].get_state_comment.return_value = body
            m["provider"].get_pr_for_issue.return_value = {
                "number": 99, "headRefName": "feat/issue-44", "headRefOid": "abc123",
            }
            run(_ctx())
        # Comportamento monolítico: TODAS as categorias executam no mesmo ciclo.
        m["dispatch"].assert_called_once()
        m["dispatch_reviewer"].assert_called_once()
        m["execute_auto_merges"].assert_called_once()
        m["route_conflito"].assert_called_once()

    def test_run_monolitico_scan_sem_escopo_de_estados(self) -> None:
        """run() não escopa o scan — states=None (varre todos os estados)."""
        with _Patches(_cfg(), [_todo_result()]) as m:
            run(_ctx())
        assert m["scan"].call_args[0][0].states is None

    def test_run_sem_model_no_body_do_dispatch(self) -> None:
        """run() monolítico nunca adiciona model (compat total)."""
        with _Patches(_cfg(), [_todo_result()]) as m:
            run(_ctx())
        assert m["dispatch"].call_args.kwargs["model"] is None


# ---------------------------------------------------------------------------
# Log por estágio
# ---------------------------------------------------------------------------

class TestStageLog:
    def test_log_path_default_por_estagio(self) -> None:
        path = _stage_log_path(_cfg(), "dev")
        assert path.endswith("deployment-dev.log")

    def test_log_path_da_config(self, tmp_path: Path) -> None:
        log = str(tmp_path / "meu-dev.log")
        cfg = _cfg(stages={"dev": {"log": log}})
        assert _stage_log_path(cfg, "dev") == log

    def test_estagios_tem_logs_distintos(self) -> None:
        p_dev = _stage_log_path(_cfg(), "dev")
        p_rev = _stage_log_path(_cfg(), "reviewer")
        assert p_dev != p_rev

    def test_run_dev_configura_log_isolado(self, tmp_path: Path) -> None:
        """run_dev anexa (e remove) um FileHandler isolado do estágio."""
        import logging as _logging

        from deployment.deployment import logger as dep_logger

        log = str(tmp_path / "dev.log")
        before = list(dep_logger.handlers)
        with _Patches(_cfg(stages={"dev": {"log": log}}), [_todo_result()]):
            run_dev(_ctx())
        # O handler do estágio foi removido ao fim (sem vazamento entre ciclos).
        assert list(dep_logger.handlers) == before
        # E o arquivo de log do estágio foi criado.
        assert Path(log).exists()
        # E não sobrou nenhum FileHandler do estágio pendurado.
        assert not any(
            isinstance(h, _logging.FileHandler) and getattr(h, "name", "") == "crewflow-stage-dev"
            for h in dep_logger.handlers
        )
