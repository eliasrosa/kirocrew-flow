"""Testes do scanner principal — mock no provider, sem rede."""

from __future__ import annotations

import sqlite3
from unittest import mock

import pytest

from flow.domain.state import Modifier, State
from flow.ports.issue_provider import ProviderError
from flow.scan.cache import _SCHEMA, compute_hash, set_hash
from flow.scan.scanner import (
    ALWAYS_INCLUDE_MODIFIERS,
    ALWAYS_INCLUDE_STATES,
    ScanResult,
    SquadScanConfig,
    scan_candidates,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def conn() -> sqlite3.Connection:
    db = sqlite3.connect(":memory:")
    db.execute(_SCHEMA)
    db.commit()
    return db


@pytest.fixture
def config() -> SquadScanConfig:
    return SquadScanConfig(
        squad_id="test",
        issue_provider="github",
        projects=("owner/repo",),
        repos=frozenset({"api-gateway2", "api-subscription2"}),
    )


def _item(
    key: str = "VGAT-1",
    title: str = "[api-gateway2] Fix",
    labels: list[str] | None = None,
) -> dict:
    return {"key": key, "title": title, "labels": labels or [], "parent_key": None}


# ---------------------------------------------------------------------------
# scan_candidates
# ---------------------------------------------------------------------------

class TestScanCandidates:
    def test_retorna_candidato_em_todo(self, config: SquadScanConfig, conn: sqlite3.Connection) -> None:
        item = _item("VGAT-1", labels=["crewflow:todo", "crewflow:feature"])
        provider = mock.MagicMock()
        # list_by_state é chamado para cada estado — só "todo" retorna algo
        provider.list_by_state.side_effect = lambda project, s: [item] if s == "crewflow:todo" else []

        results = scan_candidates(config, provider, conn)
        candidates = [r for r in results if r.dispatch_candidate]

        assert len(candidates) == 1
        assert candidates[0].item.key == "VGAT-1"
        assert candidates[0].current_state is State.TODO

    def test_ignora_issue_sem_label_crewflow(self, config: SquadScanConfig, conn: sqlite3.Connection) -> None:
        item = _item("VGAT-1", labels=["bug", "phase-1"])
        provider = mock.MagicMock()
        provider.list_by_state.return_value = [item]

        results = scan_candidates(config, provider, conn)
        assert results == []

    def test_nao_despacha_com_blocked(self, config: SquadScanConfig, conn: sqlite3.Connection) -> None:
        item = _item("VGAT-1", labels=["crewflow:todo", "crewflow:blocked"])
        provider = mock.MagicMock()
        provider.list_by_state.side_effect = lambda p, s: [item] if s == "crewflow:todo" else []

        results = scan_candidates(config, provider, conn)
        candidates = [r for r in results if r.dispatch_candidate]

        assert len(candidates) == 0
        # Mas a issue aparece no resultado com changed=True (primeiro ciclo)
        assert any(r.item.key == "VGAT-1" for r in results)
        assert all(not r.dispatch_candidate for r in results if r.item.key == "VGAT-1")

    def test_nao_despacha_com_running(self, config: SquadScanConfig, conn: sqlite3.Connection) -> None:
        item = _item("VGAT-1", labels=["crewflow:todo", "crewflow:running"])
        provider = mock.MagicMock()
        provider.list_by_state.side_effect = lambda p, s: [item] if s == "crewflow:todo" else []

        results = scan_candidates(config, provider, conn)
        assert all(not r.dispatch_candidate for r in results)

    def test_skip_se_labels_nao_mudaram(self, config: SquadScanConfig, conn: sqlite3.Connection) -> None:
        labels = ["crewflow:dev"]
        item = _item("VGAT-1", labels=labels)
        # Simula cache já populado com o mesmo hash
        set_hash(conn, "VGAT-1", compute_hash(labels))

        provider = mock.MagicMock()
        provider.list_by_state.side_effect = lambda p, s: [item] if s == "crewflow:dev" else []

        results = scan_candidates(config, provider, conn)
        # dev não é candidato E hash não mudou → skip
        assert results == []

    def test_inclui_se_labels_mudaram(self, config: SquadScanConfig, conn: sqlite3.Connection) -> None:
        labels_novos = ["crewflow:todo"]
        item = _item("VGAT-1", labels=labels_novos)
        # Cache tinha hash diferente (era dev antes)
        set_hash(conn, "VGAT-1", compute_hash(["crewflow:dev"]))

        provider = mock.MagicMock()
        provider.list_by_state.side_effect = lambda p, s: [item] if s == "crewflow:todo" else []

        results = scan_candidates(config, provider, conn)
        candidates = [r for r in results if r.dispatch_candidate]

        assert len(candidates) == 1
        assert candidates[0].changed is True

    def test_continua_se_um_projeto_falha(self, config: SquadScanConfig, conn: sqlite3.Connection) -> None:
        """Falha parcial não interrompe o scan dos outros projetos."""
        config_dois = SquadScanConfig(
            squad_id="test",
            issue_provider="github",
            projects=("owner/repo-a", "owner/repo-b"),
            repos=frozenset({"api-gateway2"}),
        )
        item_b = _item("B-1", labels=["crewflow:todo"])

        def list_by_state(project: str, state: str) -> list[dict]:
            if project == "owner/repo-a":
                raise ProviderError("repo-a inacessível")
            return [item_b] if state == "crewflow:todo" else []

        provider = mock.MagicMock()
        provider.list_by_state.side_effect = list_by_state

        # Não deve lançar mesmo com repo-a falhando
        results = scan_candidates(config_dois, provider, conn)
        assert any(r.item.key == "B-1" for r in results)

    def test_valida_spec_zero_token(self, config: SquadScanConfig, conn: sqlite3.Connection) -> None:
        """Issue em spec com título sem repo válido é flagrada (spec_valid=False)."""
        item = _item("VGAT-1", title="Fix sem colchete de repo", labels=["crewflow:spec"])
        provider = mock.MagicMock()
        provider.list_by_state.side_effect = lambda p, s: [item] if s == "crewflow:spec" else []

        results = scan_candidates(config, provider, conn)

        spec_results = [r for r in results if r.current_state is State.SPEC]
        assert len(spec_results) == 1
        assert spec_results[0].spec_valid is False

    def test_spec_valida_com_repo_correto(self, config: SquadScanConfig, conn: sqlite3.Connection) -> None:
        item = _item("VGAT-1", title="[api-gateway2] Fix", labels=["crewflow:spec"])
        provider = mock.MagicMock()
        provider.list_by_state.side_effect = lambda p, s: [item] if s == "crewflow:spec" else []

        results = scan_candidates(config, provider, conn)

        spec_results = [r for r in results if r.current_state is State.SPEC]
        assert len(spec_results) == 1
        assert spec_results[0].spec_valid is True

    def test_scan_result_tem_campos_corretos(self, config: SquadScanConfig, conn: sqlite3.Connection) -> None:
        item = _item("VGAT-1", labels=["crewflow:todo"])
        provider = mock.MagicMock()
        provider.list_by_state.side_effect = lambda p, s: [item] if s == "crewflow:todo" else []

        results = scan_candidates(config, provider, conn)
        assert len(results) == 1
        r = results[0]
        assert isinstance(r, ScanResult)
        assert r.current_state is State.TODO
        assert r.modifiers == frozenset()
        assert r.dispatch_candidate is True
        assert r.changed is True  # primeiro ciclo
        assert r.reason != ""

    def test_dedup_por_key_entre_projetos(self, conn: sqlite3.Connection) -> None:
        """Mesma issue listada por dois projetos → um único ScanResult (issue #43)."""
        config_dois = SquadScanConfig(
            squad_id="test",
            issue_provider="github",
            projects=("owner/repo-a", "owner/repo-b"),
            repos=frozenset({"api-gateway2"}),
        )
        item = _item("VGAT-1", labels=["crewflow:todo", "crewflow:feature"])
        provider = mock.MagicMock()
        # AMBOS os projetos retornam a MESMA issue em crewflow:todo
        provider.list_by_state.side_effect = lambda p, s: [item] if s == "crewflow:todo" else []

        results = scan_candidates(config_dois, provider, conn)

        assert len([r for r in results if r.item.key == "VGAT-1"]) == 1

    def test_dedup_emite_log_debug(self, conn: sqlite3.Connection) -> None:
        """A issue deduplicada gera um log DEBUG identificando a key e o projeto."""
        config_dois = SquadScanConfig(
            squad_id="test",
            issue_provider="github",
            projects=("owner/repo-a", "owner/repo-b"),
            repos=frozenset({"api-gateway2"}),
        )
        item = _item("VGAT-1", labels=["crewflow:todo"])
        provider = mock.MagicMock()
        provider.list_by_state.side_effect = lambda p, s: [item] if s == "crewflow:todo" else []

        with mock.patch("flow.scan.scanner.logger") as mock_logger:
            scan_candidates(config_dois, provider, conn)

        debug_calls = [c for c in mock_logger.debug.call_args_list if "deduplicada" in str(c)]
        assert len(debug_calls) == 1
        # A mensagem carrega a key e o projeto onde foi deduplicada
        assert "VGAT-1" in debug_calls[0].args
        assert "owner/repo-b" in debug_calls[0].args

    def test_issues_distintas_nao_sao_deduplicadas(self, config: SquadScanConfig, conn: sqlite3.Connection) -> None:
        """Dedup é por key: issues diferentes não colidem."""
        item_a = _item("VGAT-1", labels=["crewflow:todo"])
        item_b = _item("VGAT-2", labels=["crewflow:todo"])
        provider = mock.MagicMock()
        provider.list_by_state.side_effect = lambda p, s: [item_a, item_b] if s == "crewflow:todo" else []

        results = scan_candidates(config, provider, conn)
        keys = {r.item.key for r in results if r.dispatch_candidate}
        assert keys == {"VGAT-1", "VGAT-2"}


# ---------------------------------------------------------------------------
# ALWAYS_INCLUDE_STATES — issue #79
# Issues em REVIEW e QA devem aparecer em todos os ciclos, mesmo sem mudança
# de labels, para que o motor possa monitorá-las ativamente.
# ---------------------------------------------------------------------------

class TestAlwaysIncludeStates:
    def test_always_include_states_contem_review_e_qa(self) -> None:
        """ALWAYS_INCLUDE_STATES deve cobrir REVIEW e QA."""
        assert State.REVIEW in ALWAYS_INCLUDE_STATES
        assert State.QA in ALWAYS_INCLUDE_STATES

    def test_review_incluida_sem_mudanca_de_labels(
        self, config: SquadScanConfig, conn: sqlite3.Connection
    ) -> None:
        """Issue em crewflow:review aparece no scan mesmo quando o hash não muda."""
        labels = ["crewflow:review"]
        item = _item("VGAT-1", labels=labels)
        # Pré-popula o cache com o hash atual — simula segundo ciclo
        set_hash(conn, "VGAT-1", compute_hash(labels))

        provider = mock.MagicMock()
        provider.list_by_state.side_effect = lambda p, s: [item] if s == "crewflow:review" else []

        results = scan_candidates(config, provider, conn)

        assert len(results) == 1
        assert results[0].item.key == "VGAT-1"
        assert results[0].current_state is State.REVIEW
        assert results[0].changed is False  # hash igual — mas ainda incluída

    def test_qa_incluida_sem_mudanca_de_labels(
        self, config: SquadScanConfig, conn: sqlite3.Connection
    ) -> None:
        """Issue em crewflow:qa aparece no scan mesmo quando o hash não muda."""
        labels = ["crewflow:qa"]
        item = _item("VGAT-1", labels=labels)
        set_hash(conn, "VGAT-1", compute_hash(labels))

        provider = mock.MagicMock()
        provider.list_by_state.side_effect = lambda p, s: [item] if s == "crewflow:qa" else []

        results = scan_candidates(config, provider, conn)

        assert len(results) == 1
        assert results[0].current_state is State.QA
        assert results[0].changed is False

    def test_todo_sem_mudanca_ainda_filtrado(
        self, config: SquadScanConfig, conn: sqlite3.Connection
    ) -> None:
        """Issue em crewflow:todo sem mudança de labels e sem dispatch NÃO aparece.

        Garante que ALWAYS_INCLUDE_STATES não regride o filtro para outros estados:
        TODO só deve aparecer quando changed=True ou quando é dispatch_candidate.
        """
        # TODO com running não é dispatch_candidate, e hash está no cache
        labels = ["crewflow:todo", "crewflow:running"]
        item = _item("VGAT-1", labels=labels)
        set_hash(conn, "VGAT-1", compute_hash(labels))

        provider = mock.MagicMock()
        provider.list_by_state.side_effect = lambda p, s: [item] if s == "crewflow:todo" else []

        results = scan_candidates(config, provider, conn)

        assert results == []

    def test_review_inclui_mesmo_apos_multiplos_ciclos(
        self, config: SquadScanConfig, conn: sqlite3.Connection
    ) -> None:
        """Simula três ciclos consecutivos: issue em REVIEW deve aparecer nos três."""
        labels = ["crewflow:review"]
        item = _item("VGAT-1", labels=labels)
        provider = mock.MagicMock()
        provider.list_by_state.side_effect = lambda p, s: [item] if s == "crewflow:review" else []

        for ciclo in range(1, 4):
            results = scan_candidates(config, provider, conn)
            assert len(results) == 1, f"ciclo {ciclo}: issue deveria aparecer"
            assert results[0].item.key == "VGAT-1"

    def test_review_dispatch_candidate_e_false(
        self, config: SquadScanConfig, conn: sqlite3.Connection
    ) -> None:
        """dispatch_candidate deve continuar False para REVIEW — não é gatilho."""
        labels = ["crewflow:review"]
        item = _item("VGAT-1", labels=labels)
        set_hash(conn, "VGAT-1", compute_hash(labels))

        provider = mock.MagicMock()
        provider.list_by_state.side_effect = lambda p, s: [item] if s == "crewflow:review" else []

        results = scan_candidates(config, provider, conn)

        assert len(results) == 1
        assert results[0].dispatch_candidate is False


# ---------------------------------------------------------------------------
# Resultado de review sem label de estado — issue de review do modelo de
# label único (crewflow:review-ok / crewflow:review-fail SUBSTITUEM
# crewflow:review). Estas issues não têm State, mas DEVEM sobreviver ao scan
# para que run_merge (REVIEW_OK) e run_conflito/rework (REVIEW_FAIL) as peguem.
# Regressão coberta: antes, _fetch_all_labeled_items só consultava por State e
# _evaluate_item descartava current_state is None, então elas sumiam da esteira.
# ---------------------------------------------------------------------------

class TestReviewResultLabels:
    def test_always_include_modifiers_contem_review_ok_e_fail(self) -> None:
        assert Modifier.REVIEW_OK in ALWAYS_INCLUDE_MODIFIERS
        assert Modifier.REVIEW_FAIL in ALWAYS_INCLUDE_MODIFIERS

    def test_review_ok_sem_estado_e_emitido(
        self, config: SquadScanConfig, conn: sqlite3.Connection
    ) -> None:
        """Issue com APENAS {crewflow:review-ok} (sem crewflow:review) é emitida."""
        item = _item("VGAT-1", labels=["crewflow:review-ok"])
        provider = mock.MagicMock()
        provider.list_by_state.side_effect = (
            lambda p, s: [item] if s == "crewflow:review-ok" else []
        )

        results = scan_candidates(config, provider, conn)

        assert len(results) == 1
        r = results[0]
        assert r.item.key == "VGAT-1"
        assert r.current_state is None  # sem label de estado, como em produção
        assert Modifier.REVIEW_OK in r.modifiers
        assert r.dispatch_candidate is False

    def test_review_fail_sem_estado_e_emitido(
        self, config: SquadScanConfig, conn: sqlite3.Connection
    ) -> None:
        """Issue com APENAS {crewflow:review-fail} (sem crewflow:review) é emitida."""
        item = _item("VGAT-1", labels=["crewflow:review-fail"])
        provider = mock.MagicMock()
        provider.list_by_state.side_effect = (
            lambda p, s: [item] if s == "crewflow:review-fail" else []
        )

        results = scan_candidates(config, provider, conn)

        assert len(results) == 1
        r = results[0]
        assert r.item.key == "VGAT-1"
        assert r.current_state is None
        assert Modifier.REVIEW_FAIL in r.modifiers

    def test_review_ok_incluido_sem_mudanca_de_labels(
        self, config: SquadScanConfig, conn: sqlite3.Connection
    ) -> None:
        """review-ok deve reaparecer em todo ciclo mesmo com hash inalterado."""
        labels = ["crewflow:review-ok", "crewflow:feature"]
        item = _item("VGAT-1", labels=labels)
        # Simula segundo ciclo: hash já gravado no cache.
        set_hash(conn, "VGAT-1", compute_hash(labels))

        provider = mock.MagicMock()
        provider.list_by_state.side_effect = (
            lambda p, s: [item] if s == "crewflow:review-ok" else []
        )

        results = scan_candidates(config, provider, conn)

        assert len(results) == 1
        assert results[0].changed is False  # hash igual — mas ainda incluída
        assert Modifier.REVIEW_OK in results[0].modifiers

    def test_review_fail_reaparece_em_multiplos_ciclos(
        self, config: SquadScanConfig, conn: sqlite3.Connection
    ) -> None:
        labels = ["crewflow:review-fail"]
        item = _item("VGAT-1", labels=labels)
        provider = mock.MagicMock()
        provider.list_by_state.side_effect = (
            lambda p, s: [item] if s == "crewflow:review-fail" else []
        )

        for ciclo in range(1, 4):
            results = scan_candidates(config, provider, conn)
            assert len(results) == 1, f"ciclo {ciclo}: issue deveria aparecer"
            assert Modifier.REVIEW_FAIL in results[0].modifiers

    def test_review_ok_flui_para_merge_pr(
        self, config: SquadScanConfig, conn: sqlite3.Connection
    ) -> None:
        """A ScanResult produzida pelo scan real dispara MERGE_PR no executor.

        Fecha o gap apontado no review: em vez de forjar current_state=State.REVIEW,
        deixa o scan produzir current_state=None a partir de labels crus e verifica
        que decide() ainda decide MERGE_PR sobre o modificador REVIEW_OK.
        """
        from flow.executor.executor import ActionKind, decide

        item = _item("VGAT-1", labels=["crewflow:review-ok"])
        provider = mock.MagicMock()
        provider.list_by_state.side_effect = (
            lambda p, s: [item] if s == "crewflow:review-ok" else []
        )

        results = scan_candidates(config, provider, conn)
        assert len(results) == 1
        scan_result = results[0]
        assert scan_result.current_state is None  # sem label de estado (produção)

        # Comentário de estado com um ReviewerResult aprovado (auto-mergeável),
        # construído pelo renderer real para bater com o parser do executor.
        from flow.audit.state_comment import StateComment, render
        sc = StateComment(workflow="f", current_node="review", status="reviewed", repo="r")
        sc.set_reviewer_result(approved=True, comments=[], sha="abc123")
        state_comment = render(sc)

        decision = decide(
            scan_result,
            state_comment=state_comment,
            auto_merge_on_approve=True,
        )
        # A issue sobrevive ao scan (current_state=None) e o branch de REVIEW_OK
        # é alcançado, decidindo MERGE_PR — não some da esteira.
        assert decision.action is ActionKind.MERGE_PR
        assert "crewflow:done" in decision.add_labels

    def test_review_fail_flui_para_rework(
        self, config: SquadScanConfig, conn: sqlite3.Connection
    ) -> None:
        """A ScanResult produzida pelo scan real dispara DISPATCH_REWORK."""
        from flow.executor.executor import ActionKind, decide

        item = _item("VGAT-1", labels=["crewflow:review-fail"])
        provider = mock.MagicMock()
        provider.list_by_state.side_effect = (
            lambda p, s: [item] if s == "crewflow:review-fail" else []
        )

        results = scan_candidates(config, provider, conn)
        assert len(results) == 1
        scan_result = results[0]

        decision = decide(scan_result)
        assert decision.action is ActionKind.DISPATCH_REWORK
        assert "crewflow:running" in decision.add_labels
        assert "crewflow:review-fail" in decision.remove_labels

    def test_fetch_consulta_labels_de_resultado(
        self, config: SquadScanConfig, conn: sqlite3.Connection
    ) -> None:
        """_fetch_all_labeled_items consulta o provider por review-ok e review-fail."""
        provider = mock.MagicMock()
        provider.list_by_state.return_value = []

        scan_candidates(config, provider, conn)

        queried = {c.args[1] for c in provider.list_by_state.call_args_list}
        assert "crewflow:review-ok" in queried
        assert "crewflow:review-fail" in queried
