"""Testes de integração end-to-end do KiroCrew Flow.

Cobre o loop completo sem I/O real:
  squads/*.yaml → SquadConfig → scan_candidates() → executor.decide() → deployment.run()

O provider é mockado em memória. Nenhuma rede, nenhum Jira, nenhum GitHub.
O objetivo é garantir que as camadas se conectam corretamente e que o
comportamento end-to-end corresponde ao que está nos diagramas.
"""

from __future__ import annotations

import sqlite3
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import Any
from unittest import mock

import pytest

# Garante que deployment/ é importável (mesmo caminho que o cron usa)
_REPO_ROOT = str(Path(__file__).parent.parent.parent)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from flow.audit.state_comment import StateComment  # noqa: E402
from flow.audit.state_comment import render as render_comment  # noqa: E402
from flow.config.squad import SquadConfig, _parse_squad  # noqa: E402
from flow.domain.state import State  # noqa: E402
from flow.executor.executor import ActionKind, decide  # noqa: E402
from flow.scan.cache import _SCHEMA, compute_hash  # noqa: E402
from flow.scan.scanner import ScanResult, SquadScanConfig, scan_candidates  # noqa: E402

# ---------------------------------------------------------------------------
# Fixtures e helpers
# ---------------------------------------------------------------------------

SQUAD_DICT: dict[str, Any] = {
    "id": "test-squad",
    "issue_provider": "github",
    "repos": ["owner/api-gateway2", "owner/api-subscription2"],
    "routing": [
        {"match": {"labels": ["crewflow:hotfix"]}, "workflow": "hotfix-flow"},
        {"match": {"labels": ["crewflow:bug"]}, "workflow": "bug-flow"},
        {"match": {"labels": ["crewflow:debt"]}, "workflow": "debt-flow"},
        {"default": "feature-flow"},
    ],
}


@pytest.fixture
def squad() -> SquadConfig:
    return _parse_squad(SQUAD_DICT)


@pytest.fixture
def conn() -> sqlite3.Connection:
    db = sqlite3.connect(":memory:")
    db.execute(_SCHEMA)
    db.commit()
    return db


def _item(key: str, title: str, labels: list[str]) -> dict:
    return {"key": key, "title": title, "labels": labels, "parent_key": None}


def _mock_provider(items_by_state: dict[str, list[dict]]) -> mock.MagicMock:
    """Cria um provider mockado que retorna items específicos por estado."""
    provider = mock.MagicMock()
    provider.list_by_state.side_effect = lambda project, state: items_by_state.get(state, [])
    provider.get_state_comment.return_value = None
    provider.set_labels.return_value = None
    provider.upsert_state_comment.return_value = None
    return provider


def _scan_cfg(squad: SquadConfig) -> SquadScanConfig:
    return SquadScanConfig(
        squad_id=squad.id,
        issue_provider=squad.issue_provider,
        projects=tuple(squad.projects),
        repos=squad.repos,
    )


# ---------------------------------------------------------------------------
# E2E: Feature flow completo
# ---------------------------------------------------------------------------

class TestFeatureFlowE2E:
    def test_todo_vira_dispatch_dev(
        self, squad: SquadConfig, conn: sqlite3.Connection
    ) -> None:
        """Issue em crewflow:todo → executor decide DISPATCH_DEV."""
        item = _item(
            "https://github.com/owner/api-gateway2/issues/42",
            "[api-gateway2] Implementar validação de split",
            ["crewflow:todo", "crewflow:feature"],
        )
        # O scanner itera pelos dois repos da squad — o mock retorna o item em
        # AMBOS os projetos. A deduplication por key garante que a issue produz
        # EXATAMENTE um ScanResult por ciclo, não "ao menos um" (issue #43).
        provider = _mock_provider({"crewflow:todo": [item]})
        cfg = _scan_cfg(squad)

        results = scan_candidates(cfg, provider, conn)
        candidates = [r for r in results if r.dispatch_candidate]

        # Exatamente 1 candidato com a key correta — não uma duplicata por projeto
        assert len(candidates) == 1
        r = candidates[0]
        assert r.item.key == item["key"]
        assert r.current_state is State.TODO

        decision = decide(r, squad=squad)
        assert decision.action is ActionKind.DISPATCH_DEV
        assert "crewflow:dev" in decision.add_labels
        assert "crewflow:running" in decision.add_labels
        assert "crewflow:todo" in decision.remove_labels

    def test_review_sem_reviewed_vira_dispatch_reviewer(
        self, squad: SquadConfig, conn: sqlite3.Connection
    ) -> None:
        """Issue em crewflow:review sem lock → executor decide DISPATCH_REVIEWER."""
        item = _item(
            "https://github.com/owner/api-gateway2/issues/42",
            "[api-gateway2] Fix",
            ["crewflow:review", "crewflow:feature"],
        )
        provider = _mock_provider({"crewflow:review": [item]})
        cfg = _scan_cfg(squad)

        results = scan_candidates(cfg, provider, conn)
        # REVIEW não é dispatch_candidate, mas muda de hash → aparece no resultado
        r = next((x for x in results if x.current_state is State.REVIEW), None)
        assert r is not None

        decision = decide(r, squad=squad)
        assert decision.action is ActionKind.DISPATCH_REVIEWER
        assert "crewflow:reviewed" in decision.add_labels

    def test_review_com_reviewed_skip(
        self, squad: SquadConfig, conn: sqlite3.Connection
    ) -> None:
        """Issue em crewflow:review + crewflow:reviewed → SKIP (lock anti-loop)."""
        item = _item(
            "https://github.com/owner/api-gateway2/issues/42",
            "[api-gateway2] Fix",
            ["crewflow:review", "crewflow:reviewed", "crewflow:feature"],
        )
        provider = _mock_provider({"crewflow:review": [item]})
        cfg = _scan_cfg(squad)

        results = scan_candidates(cfg, provider, conn)
        r = next((x for x in results if x.current_state is State.REVIEW), None)
        assert r is not None

        decision = decide(r, squad=squad)
        assert decision.action is ActionKind.SKIP

    def test_blocked_nao_e_despachado(
        self, squad: SquadConfig, conn: sqlite3.Connection
    ) -> None:
        """Issue em crewflow:todo + crewflow:blocked → não despachada."""
        item = _item(
            "https://github.com/owner/api-gateway2/issues/42",
            "[api-gateway2] Fix",
            ["crewflow:todo", "crewflow:blocked", "crewflow:feature"],
        )
        provider = _mock_provider({"crewflow:todo": [item]})
        cfg = _scan_cfg(squad)

        results = scan_candidates(cfg, provider, conn)
        candidates = [r for r in results if r.dispatch_candidate]

        assert len(candidates) == 0

    def test_spec_invalida_flagrada(
        self, squad: SquadConfig, conn: sqlite3.Connection
    ) -> None:
        """Issue em crewflow:spec sem repo no título → spec_valid=False."""
        item = _item(
            "https://github.com/owner/api-gateway2/issues/10",
            "Fix sem colchete de repo",
            ["crewflow:spec", "crewflow:feature"],
        )
        provider = _mock_provider({"crewflow:spec": [item]})
        cfg = _scan_cfg(squad)

        results = scan_candidates(cfg, provider, conn)
        spec_invalid = [r for r in results if r.spec_valid is False]

        assert len(spec_invalid) == 1
        assert spec_invalid[0].item.key == item["key"]


# ---------------------------------------------------------------------------
# E2E: Deduplication por key em squad com múltiplos projetos (issue #43)
# ---------------------------------------------------------------------------

class TestMultiProjectDedupE2E:
    """Comportamento esperado quando a mesma issue aparece em mais de um projeto.

    Uma squad GitHub-first tem múltiplos repos (``projects``). O scanner varre
    todos. Se a mesma issue (mesma ``key`` canônica) for listada por mais de um
    projeto no mesmo ciclo, ela deve produzir EXATAMENTE UM ``ScanResult`` — não
    uma duplicata por projeto. A deduplication é por key e determinística, não
    depende do hash já gravado no cache pelo primeiro projeto (issue #43).
    """

    def test_mesma_issue_em_dois_projetos_produz_um_resultado(
        self, squad: SquadConfig, conn: sqlite3.Connection
    ) -> None:
        item = _item(
            "https://github.com/owner/api-gateway2/issues/43",
            "[api-gateway2] Bug de duplicata",
            ["crewflow:todo", "crewflow:bug"],
        )
        # squad tem 2 projetos; o mock retorna o MESMO item para ambos.
        provider = _mock_provider({"crewflow:todo": [item]})
        assert len(squad.projects) == 2  # pré-condição do cenário
        cfg = _scan_cfg(squad)

        results = scan_candidates(cfg, provider, conn)

        # Exatamente 1 resultado para a issue — sem duplicata por projeto.
        matching = [r for r in results if r.item.key == item["key"]]
        assert len(matching) == 1
        assert matching[0].changed is True  # primeiro ciclo
        assert matching[0].dispatch_candidate is True

    def test_dedup_e_por_key_nao_por_hash(
        self, squad: SquadConfig, conn: sqlite3.Connection
    ) -> None:
        """Mesmo com o cache VAZIO (nenhum hash gravado), o segundo projeto não
        reintroduz a issue — a dedup é por key, não efeito colateral do hash."""
        item = _item(
            "https://github.com/owner/api-gateway2/issues/43",
            "[api-gateway2] Bug de duplicata",
            ["crewflow:todo", "crewflow:bug"],
        )
        provider = _mock_provider({"crewflow:todo": [item]})
        cfg = _scan_cfg(squad)

        results = scan_candidates(cfg, provider, conn)
        assert len([r for r in results if r.item.key == item["key"]]) == 1

    def test_issues_distintas_em_projetos_distintos_nao_sao_deduplicadas(
        self, squad: SquadConfig, conn: sqlite3.Connection
    ) -> None:
        """Dedup é por key: issues diferentes coexistem normalmente."""
        item_a = _item(
            "https://github.com/owner/api-gateway2/issues/1",
            "[api-gateway2] Fix A",
            ["crewflow:todo", "crewflow:bug"],
        )
        item_b = _item(
            "https://github.com/owner/api-subscription2/issues/2",
            "[api-subscription2] Fix B",
            ["crewflow:todo", "crewflow:bug"],
        )
        provider = _mock_provider({"crewflow:todo": [item_a, item_b]})
        cfg = _scan_cfg(squad)

        results = scan_candidates(cfg, provider, conn)
        keys = {r.item.key for r in results if r.dispatch_candidate}
        assert keys == {item_a["key"], item_b["key"]}


# ---------------------------------------------------------------------------
# E2E: Hotfix flow
# ---------------------------------------------------------------------------

class TestHotfixFlowE2E:
    def test_hotfix_com_p1_despacha(
        self, squad: SquadConfig, conn: sqlite3.Connection
    ) -> None:
        """Hotfix com p1 → DISPATCH_DEV (vai para produção)."""
        item = _item(
            "https://github.com/owner/api-gateway2/issues/99",
            "[api-gateway2] Fix urgente checkout",
            ["crewflow:todo", "crewflow:hotfix", "crewflow:p1"],
        )
        provider = _mock_provider({"crewflow:todo": [item]})
        cfg = _scan_cfg(squad)

        results = scan_candidates(cfg, provider, conn)
        candidates = [r for r in results if r.dispatch_candidate]
        assert len(candidates) == 1  # dedup por key: 1 resultado mesmo em 2 projetos (issue #43)

        decision = decide(candidates[0], squad=squad)
        assert decision.action is ActionKind.DISPATCH_DEV

    def test_hotfix_sem_p1_rebaixa_para_bug(
        self, squad: SquadConfig, conn: sqlite3.Connection
    ) -> None:
        """Hotfix sem p1 → REBRAND para bug (GATE 0)."""
        item = _item(
            "https://github.com/owner/api-gateway2/issues/99",
            "[api-gateway2] Ajuste menor",
            ["crewflow:todo", "crewflow:hotfix"],  # sem p1
        )
        provider = _mock_provider({"crewflow:todo": [item]})
        cfg = _scan_cfg(squad)

        results = scan_candidates(cfg, provider, conn)
        r = next((x for x in results if x.changed), None)
        assert r is not None

        decision = decide(r, squad=squad)
        assert decision.action is ActionKind.REBRAND
        assert decision.new_template == "bug"
        assert "crewflow:bug" in decision.add_labels
        assert "crewflow:hotfix" in decision.remove_labels

    def test_bypass_hml_com_justificativa_passa(
        self, squad: SquadConfig, conn: sqlite3.Connection
    ) -> None:
        """Hotfix com hml-bypass + justificativa → passa para QA."""
        sc = StateComment(
            workflow="hotfix (v1)", current_node="qa",
            status="running", repo="api-gateway2"
        )
        sc.add_exception("crewflow:hml-bypass", "Checkout fora do ar", "@elias", "2026-09-15")
        state_comment = render_comment(sc)

        item = _item(
            "https://github.com/owner/api-gateway2/issues/100",
            "[api-gateway2] Fix urgente",
            ["crewflow:qa", "crewflow:hotfix", "crewflow:p1", "crewflow:hml-bypass"],
        )
        provider = _mock_provider({"crewflow:qa": [item]})
        cfg = _scan_cfg(squad)

        results = scan_candidates(cfg, provider, conn)
        r = next((x for x in results if x.current_state is State.QA), None)
        assert r is not None

        decision = decide(r, state_comment=state_comment, squad=squad)
        assert decision.action is not ActionKind.BLOCK

    def test_bypass_hml_sem_justificativa_bloqueia(
        self, squad: SquadConfig, conn: sqlite3.Connection
    ) -> None:
        """Hotfix com hml-bypass sem justificativa → BLOCK."""
        item = _item(
            "https://github.com/owner/api-gateway2/issues/100",
            "[api-gateway2] Fix urgente",
            ["crewflow:qa", "crewflow:hotfix", "crewflow:p1", "crewflow:hml-bypass"],
        )
        provider = _mock_provider({"crewflow:qa": [item]})
        cfg = _scan_cfg(squad)

        results = scan_candidates(cfg, provider, conn)
        r = next((x for x in results if x.current_state is State.QA), None)
        assert r is not None

        decision = decide(r, state_comment=None, squad=squad)
        assert decision.action is ActionKind.BLOCK


# ---------------------------------------------------------------------------
# E2E: Debt flow
# ---------------------------------------------------------------------------

class TestDebtFlowE2E:
    def test_debt_todo_notifica_tl(
        self, squad: SquadConfig, conn: sqlite3.Connection
    ) -> None:
        """Débito técnico em todo → TL deve aprovar (GATE DT)."""
        from flow.executor.executor import HumanRole
        item = _item(
            "https://github.com/owner/api-gateway2/issues/50",
            "[api-gateway2] Refatorar módulo de cache",
            ["crewflow:todo", "crewflow:debt"],
        )
        provider = _mock_provider({"crewflow:todo": [item]})
        cfg = _scan_cfg(squad)

        results = scan_candidates(cfg, provider, conn)
        r = next((x for x in results if x.current_state is State.TODO), None)
        assert r is not None

        decision = decide(r, squad=squad)
        assert decision.action is ActionKind.NOTIFY_HUMAN
        assert decision.notify_role is HumanRole.TL


# ---------------------------------------------------------------------------
# E2E: Cache e idempotência
# ---------------------------------------------------------------------------

class TestCacheE2E:
    def test_segunda_passagem_sem_mudanca_retorna_vazio(
        self, squad: SquadConfig, conn: sqlite3.Connection
    ) -> None:
        """Scan idempotente: sem mudança de labels → sem resultado."""
        item = _item(
            "https://github.com/owner/api-gateway2/issues/42",
            "[api-gateway2] Fix",
            ["crewflow:dev"],
        )
        provider = _mock_provider({"crewflow:dev": [item]})
        cfg = _scan_cfg(squad)

        # Primeira passagem — cria o cache
        results1 = scan_candidates(cfg, provider, conn)
        assert len(results1) > 0  # novo no cache

        # Segunda passagem — sem mudança
        results2 = scan_candidates(cfg, provider, conn)
        assert results2 == []  # nada mudou → silêncio total

    def test_mudanca_de_estado_detectada(
        self, squad: SquadConfig, conn: sqlite3.Connection
    ) -> None:
        """Scan detecta quando labels mudam entre ciclos."""
        from flow.scan.cache import set_hash

        item = _item(
            "https://github.com/owner/api-gateway2/issues/42",
            "[api-gateway2] Fix",
            ["crewflow:todo"],
        )
        # Simula que o cache tinha o estado anterior (dev)
        set_hash(conn, item["key"], compute_hash(["crewflow:dev"]))

        provider = _mock_provider({"crewflow:todo": [item]})
        cfg = _scan_cfg(squad)

        results = scan_candidates(cfg, provider, conn)
        candidates = [r for r in results if r.dispatch_candidate]

        assert len(candidates) == 1  # dedup por key: 1 resultado mesmo em 2 projetos (issue #43)
        assert candidates[0].changed is True


# ---------------------------------------------------------------------------
# E2E: deployment.run() com executor integrado
# ---------------------------------------------------------------------------

class TestDeploymentRunE2E:
    def _make_ctx(self) -> mock.MagicMock:
        ctx = mock.MagicMock()
        ctx._port = 5000
        ctx._secret = "secret"
        ctx.job.id = "test-job"
        return ctx

    def _config(self, **overrides: object) -> dict:
        base = {
            "repos": ["owner/api-gateway2"],
            "auto_dispatch": False,
            "max_concurrent": 2,
            "one_per_repo": True,
            "notify_chat_id": "",
            "squad_id": "test",
            "issue_provider": "github",
            "dev_root": "/tmp/dev",
            "agent": "kirocrew",
            "routing": [
                {"match": {"labels": ["crewflow:hotfix"]}, "workflow": "hotfix-flow"},
                {"default": "feature-flow"},
            ],
        }
        base.update(overrides)
        return base

    def test_feature_todo_avisa_em_fase1(self) -> None:
        """Fase 1 (auto=false): feature em todo → notifica."""
        from deployment.deployment import run

        ctx = self._make_ctx()
        item = _item(
            "https://github.com/owner/api-gateway2/issues/42",
            "[api-gateway2] Fix",
            ["crewflow:todo", "crewflow:feature"],
        )

        with (
            mock.patch("deployment.deployment._load_config",
                       return_value=self._config()),
            mock.patch("deployment.deployment.scan_candidates",
                       return_value=[ScanResult(
                           item=__import__("flow.domain.gates",
                               fromlist=["WorkItem"]).WorkItem(
                               key=item["key"], title=item["title"],
                               labels=frozenset(item["labels"])),
                           current_state=State.TODO,
                           modifiers=frozenset(),
                           dispatch_candidate=True,
                           spec_valid=None,
                           changed=True,
                           reason="test",
                       )]),
            mock.patch("deployment.deployment.open_cache") as mock_cache,
        ):
            mock_cache.return_value = sqlite3.connect(":memory:")
            run(ctx)

        ctx.notify.assert_called()
        msg = ctx.notify.call_args[0][0]
        assert "Fase 1" in msg or "pronta" in msg.lower() or "ready" in msg.lower()

    def test_hotfix_sem_p1_rebrand_aplica_labels(self) -> None:
        """Hotfix sem p1 → executor decide REBRAND → deployment aplica labels."""
        from deployment.deployment import run

        ctx = self._make_ctx()

        from flow.domain.gates import WorkItem
        hotfix_result = ScanResult(
            item=WorkItem(
                key="https://github.com/owner/api-gateway2/issues/99",
                title="[api-gateway2] Ajuste menor",
                labels=frozenset(["crewflow:todo", "crewflow:hotfix"]),
            ),
            current_state=State.TODO,
            modifiers=frozenset(),
            dispatch_candidate=True,
            spec_valid=None,
            changed=True,
            reason="test",
        )

        provider_mock = mock.MagicMock()
        provider_mock.get_state_comment.return_value = None

        with (
            mock.patch("deployment.deployment._load_config",
                       return_value=self._config()),
            mock.patch("deployment.deployment.scan_candidates",
                       return_value=[hotfix_result]),
            mock.patch("deployment.deployment.provider_for",
                       return_value=provider_mock),
            mock.patch("deployment.deployment.open_cache") as mock_cache,
        ):
            mock_cache.return_value = sqlite3.connect(":memory:")
            run(ctx)

        # set_labels deve ter sido chamado com as labels do REBRAND
        provider_mock.set_labels.assert_called_once()
        call_args = provider_mock.set_labels.call_args[0]
        labels_aplicadas = call_args[2]  # terceiro argumento: labels
        assert "crewflow:bug" in labels_aplicadas
        assert "crewflow:hotfix" not in labels_aplicadas

    def test_sem_resultados_silencio_total(self) -> None:
        """Sem nada a fazer: ctx.notify nunca chamado."""
        from deployment.deployment import run

        ctx = self._make_ctx()

        with (
            mock.patch("deployment.deployment._load_config",
                       return_value=self._config()),
            mock.patch("deployment.deployment.scan_candidates",
                       return_value=[]),
            mock.patch("deployment.deployment.open_cache") as mock_cache,
        ):
            mock_cache.return_value = sqlite3.connect(":memory:")
            run(ctx)

        ctx.notify.assert_not_called()


# ---------------------------------------------------------------------------
# E2E: exclusividade de estado na transição (regressão da issue #107)
# ---------------------------------------------------------------------------

class TestStateTransitionExclusivityE2E:
    """A transição de estado nunca deve acumular 2+ labels de estado (#107).

    Cobre o caminho todo→dev→review no adapter de deployment, garantindo que
    cada ``set_labels`` produz exatamente 1 label de estado, preservando
    modificadores/tipo/prioridade.
    """

    def _make_ctx(self) -> mock.MagicMock:
        ctx = mock.MagicMock()
        ctx._port = 5000
        ctx._secret = "secret"
        ctx.job.id = "test-job"
        return ctx

    def _config(self, **overrides: object) -> dict:
        base = {
            "repos": ["owner/api-gateway2"],
            "auto_dispatch": True,
            "max_concurrent": 2,
            "one_per_repo": True,
            "notify_chat_id": "",
            "squad_id": "test",
            "issue_provider": "github",
            "dev_root": "/tmp/dev",
            "agent": "kirocrew",
            "routing": [
                {"match": {"labels": ["crewflow:hotfix"]}, "workflow": "hotfix-flow"},
                {"default": "feature-flow"},
            ],
        }
        base.update(overrides)
        return base

    @staticmethod
    def _state_labels(labels: Iterable[str]) -> set[str]:
        state_values = {s.value for s in State}
        return {lbl for lbl in labels if lbl in state_values}

    def test_apply_decision_labels_com_dois_estados_deixa_um(self) -> None:
        """Reproduz #107: entrada com DOIS estados → saída com exatamente 1."""
        from deployment.deployment import _apply_decision_labels

        # A issue está corrompida: tem todo E review ao mesmo tempo.
        base = [
            "crewflow:todo", "crewflow:review",
            "crewflow:feature", "crewflow:p1", "phase-1",
        ]
        # A decisão move para dev + running (o gatilho do dispatch de dev).
        result = _apply_decision_labels(
            base, ("crewflow:dev", "crewflow:running"), ("crewflow:todo",),
        )

        state_labels = self._state_labels(result)
        assert state_labels == {"crewflow:dev"}, result
        assert len(state_labels) == 1
        # Modificadores/tipo/prioridade/estrangeiras preservados.
        assert "crewflow:running" in result
        assert "crewflow:feature" in result
        assert "crewflow:p1" in result
        assert "phase-1" in result
        # Os estados antigos sumiram.
        assert "crewflow:todo" not in result
        assert "crewflow:review" not in result

    def test_apply_decision_labels_so_modificador_nao_toca_estado(self) -> None:
        """add_labels só com modificador (conflito) preserva o estado atual."""
        from deployment.deployment import _apply_decision_labels

        base = ["crewflow:review", "crewflow:bug"]
        result = _apply_decision_labels(base, ("crewflow:conflito",), ())

        assert self._state_labels(result) == {"crewflow:review"}
        assert "crewflow:conflito" in result
        assert "crewflow:bug" in result

    def test_apply_dev_transition_remove_estado_anterior(self) -> None:
        """_apply_dev_transition aplica todo→dev via set_labels sem acumular."""
        from deployment.deployment import _apply_dev_transition

        provider = mock.MagicMock()
        provider.set_labels.return_value = None
        issue = {
            "number": 107,
            "title": "[api-gateway2] Bug #107",
            "url": "https://github.com/owner/api-gateway2/issues/107",
            "_labels": ["crewflow:todo", "crewflow:feature", "crewflow:p2"],
            "_key": "https://github.com/owner/api-gateway2/issues/107",
        }

        _apply_dev_transition(provider, "owner/api-gateway2", issue)

        provider.set_labels.assert_called_once()
        applied = provider.set_labels.call_args[0][2]
        assert self._state_labels(applied) == {"crewflow:dev"}
        assert "crewflow:todo" not in applied
        assert "crewflow:running" in applied
        assert "crewflow:feature" in applied
        assert "crewflow:p2" in applied

    def test_run_todo_para_dev_nao_acumula_estado(self) -> None:
        """run() com auto_dispatch: dispatch de dev aplica todo→dev via provider."""
        from deployment.deployment import run
        from flow.domain.gates import WorkItem

        ctx = self._make_ctx()
        result = ScanResult(
            item=WorkItem(
                key="https://github.com/owner/api-gateway2/issues/107",
                title="[api-gateway2] Bug #107",
                labels=frozenset(["crewflow:todo", "crewflow:feature", "crewflow:p1"]),
            ),
            current_state=State.TODO,
            modifiers=frozenset(),
            dispatch_candidate=True,
            spec_valid=None,
            changed=True,
            reason="test",
        )

        provider_mock = mock.MagicMock()
        provider_mock.get_state_comment.return_value = None
        provider_mock.set_labels.return_value = None

        with (
            mock.patch("deployment.deployment._load_config",
                       return_value=self._config()),
            mock.patch("deployment.deployment.scan_candidates",
                       return_value=[result]),
            mock.patch("deployment.deployment.provider_for",
                       return_value=provider_mock),
            mock.patch("deployment.deployment._issue_has_active_session",
                       return_value=False),
            mock.patch("deployment.deployment._resource_headroom_ok",
                       return_value=True),
            mock.patch("deployment.deployment._clean_stale_worktree",
                       return_value=False),
            mock.patch("deployment.deployment._active_sessions",
                       return_value=0),
            mock.patch("deployment.deployment._dispatch") as mock_dispatch,
            mock.patch("deployment.deployment.open_cache") as mock_cache,
        ):
            mock_cache.return_value = sqlite3.connect(":memory:")
            run(ctx)

        # A sessão foi realmente disparada...
        mock_dispatch.assert_called_once()
        # ...e a transição todo→dev foi aplicada atomicamente via provider.
        provider_mock.set_labels.assert_called_once()
        applied = provider_mock.set_labels.call_args[0][2]
        assert self._state_labels(applied) == {"crewflow:dev"}
        assert "crewflow:todo" not in applied
        assert "crewflow:running" in applied
        # Tipo/prioridade preservados na transição.
        assert "crewflow:feature" in applied
        assert "crewflow:p1" in applied

    def test_transition_state_review_derruba_dev(self) -> None:
        """A transição dev→review (domínio) nunca mantém crewflow:dev."""
        from flow.domain.state import State as _State
        from flow.domain.state import transition_state

        # A issue está em dev+running; move para review.
        novo = transition_state(
            {"crewflow:dev", "crewflow:running", "crewflow:feature"},
            _State.REVIEW,
        )
        state_labels = self._state_labels(novo)
        assert state_labels == {"crewflow:review"}
        assert "crewflow:dev" not in novo
        assert "crewflow:running" in novo  # modificador preservado
        assert "crewflow:feature" in novo

    def test_apply_review_transition_derruba_estado_residual(self) -> None:
        """_apply_review_transition colapsa todo/dev residual → só review."""
        from deployment.deployment import _apply_review_transition

        provider = mock.MagicMock()
        provider.set_labels.return_value = None
        issue = {
            "number": 107,
            "title": "[api-gateway2] Bug #107",
            "url": "https://github.com/owner/api-gateway2/issues/107",
            # #107: review acumulado com todo residual.
            "_labels": ["crewflow:todo", "crewflow:review", "crewflow:feature", "crewflow:p1"],
            "_key": "https://github.com/owner/api-gateway2/issues/107",
        }

        applied_flag = _apply_review_transition(provider, "owner/api-gateway2", issue)

        assert applied_flag is True
        provider.set_labels.assert_called_once()
        applied = provider.set_labels.call_args[0][2]
        assert self._state_labels(applied) == {"crewflow:review"}
        assert "crewflow:todo" not in applied
        assert "crewflow:dev" not in applied
        assert "crewflow:feature" in applied
        assert "crewflow:p1" in applied

    def test_apply_review_transition_idempotente_nao_reescreve(self) -> None:
        """Issue já só com review → nenhum set_labels redundante."""
        from deployment.deployment import _apply_review_transition

        provider = mock.MagicMock()
        issue = {
            "number": 42,
            "title": "ok",
            "url": "https://github.com/owner/api-gateway2/issues/42",
            "_labels": ["crewflow:review", "crewflow:feature"],
            "_key": "https://github.com/owner/api-gateway2/issues/42",
        }

        applied_flag = _apply_review_transition(provider, "owner/api-gateway2", issue)

        assert applied_flag is False
        provider.set_labels.assert_not_called()

    def test_run_dispatch_reviewer_colapsa_estado_residual(self) -> None:
        """run(): issue em review parseado com todo residual → engine colapsa.

        Prova que o MOTOR (não só o helper de domínio) reescreve as labels para
        exatamente crewflow:review na rota do reviewer, removendo o
        crewflow:todo acumulado da #107.
        """
        from deployment.deployment import run
        from flow.domain.gates import WorkItem

        ctx = self._make_ctx()
        # Issue já roteada como REVIEW pelo scanner, mas com todo residual
        # ainda presente nas labels cruas (o resquício da #107).
        result = ScanResult(
            item=WorkItem(
                key="https://github.com/owner/api-gateway2/issues/107",
                title="[api-gateway2] Bug #107",
                labels=frozenset(["crewflow:review", "crewflow:todo", "crewflow:feature"]),
            ),
            current_state=State.REVIEW,
            modifiers=frozenset(),
            dispatch_candidate=False,
            spec_valid=None,
            changed=True,
            reason="test",
        )

        provider_mock = mock.MagicMock()
        provider_mock.get_state_comment.return_value = None
        provider_mock.get_pr_for_issue.return_value = {"mergeable": "MERGEABLE"}
        provider_mock.list_by_state.return_value = []  # pré-passe defensivo vazio
        provider_mock.set_labels.return_value = None

        with (
            mock.patch("deployment.deployment._load_config",
                       return_value=self._config()),
            mock.patch("deployment.deployment.scan_candidates",
                       return_value=[result]),
            mock.patch("deployment.deployment.provider_for",
                       return_value=provider_mock),
            mock.patch("deployment.deployment._reviewer_has_active",
                       return_value=False),
            mock.patch("deployment.deployment._dispatch_reviewer") as mock_disp_rev,
            mock.patch("deployment.deployment.open_cache") as mock_cache,
        ):
            mock_cache.return_value = sqlite3.connect(":memory:")
            run(ctx)

        # O reviewer foi despachado...
        mock_disp_rev.assert_called_once()
        # ...e o motor colapsou o estado residual para exatamente review.
        assert provider_mock.set_labels.called
        applied = provider_mock.set_labels.call_args_list[-1][0][2]
        assert self._state_labels(applied) == {"crewflow:review"}
        assert "crewflow:todo" not in applied
        assert "crewflow:dev" not in applied
        assert "crewflow:feature" in applied

    def test_run_enforce_review_exclusivity_reconcilia_107_ambigua(self) -> None:
        """run(): #107 ambígua (todo+review) é descartada pelo scanner mas o
        pré-passe defensivo a reconcilia direto na API.

        O scanner nunca emite a issue (parse_state levanta EstadoAmbiguo →
        current_state=None), então ela não aparece em scan_results. O motor
        precisa reconciliá-la mesmo assim: _enforce_review_exclusivity lista as
        issues rotuladas crewflow:review e colapsa as que têm estado extra.
        """
        from deployment.deployment import run

        ctx = self._make_ctx()

        provider_mock = mock.MagicMock()
        provider_mock.get_state_comment.return_value = None
        # A issue #107 corrompida: todo E review ao mesmo tempo.
        provider_mock.list_by_state.return_value = [
            {
                "key": "https://github.com/owner/api-gateway2/issues/107",
                "labels": ["crewflow:todo", "crewflow:review", "crewflow:feature"],
            }
        ]
        provider_mock.set_labels.return_value = None

        with (
            mock.patch("deployment.deployment._load_config",
                       return_value=self._config()),
            # Scanner descarta a issue ambígua — scan_results vazio.
            mock.patch("deployment.deployment.scan_candidates",
                       return_value=[]),
            mock.patch("deployment.deployment.provider_for",
                       return_value=provider_mock),
            mock.patch("deployment.deployment._reviewer_has_active",
                       return_value=False),
            mock.patch("deployment.deployment._dispatch_reviewer"),
            mock.patch("deployment.deployment.open_cache") as mock_cache,
        ):
            mock_cache.return_value = sqlite3.connect(":memory:")
            run(ctx)

        # O motor colapsou a issue ambígua para exatamente crewflow:review.
        provider_mock.set_labels.assert_called_once()
        applied = provider_mock.set_labels.call_args[0][2]
        assert self._state_labels(applied) == {"crewflow:review"}
        assert "crewflow:todo" not in applied
        assert "crewflow:review" in applied
        assert "crewflow:feature" in applied
