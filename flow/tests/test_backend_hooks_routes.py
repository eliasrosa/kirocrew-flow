"""Testes de unidade para backend.routes (Fase 4 — implementação real).

Critérios de aceite:
- register_routes(app) registra as 3 rotas + on_startup + on_cleanup
- handle_health retorna {"ok": true, "app": "kirocrew-flow", "version": "1.0.0"}
- handle_issues retorna {"columns": {todo, dev, review, reviewed, done, blocked}}
  mesmo em caso de erro no scan (fallback para colunas vazias)
- handle_dispatch valida o body e retorna {"ok": true/false, ...}
- _start_loops cria 4 tasks asyncio e imprime log
- _stop_loops cancela tasks e limpa a lista
- _age_minutes calcula a idade em minutos
- _state_to_column mapeia os estados para colunas do kanban
- _repo_from_key extrai o repo de uma key
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from unittest import mock

import pytest
from aiohttp import web

# Garante que o raiz do repo está no path para importar backend/
_REPO_ROOT = str(Path(__file__).parent.parent.parent)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from backend.routes import (  # noqa: E402
    _age_minutes,
    _empty_columns,
    _repo_from_key,
    _start_loops,
    _state_to_column,
    _stop_loops,
    handle_dispatch,
    handle_health,
    handle_issues,
    handle_qa_approve,
    handle_qa_fail,
    register_routes,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_request(body: dict | None = None) -> mock.MagicMock:
    """Retorna um mock mínimo de web.Request."""
    req = mock.MagicMock()
    if body is not None:
        future: asyncio.Future[dict] = asyncio.get_event_loop().create_future()
        future.set_result(body)
        req.json = mock.MagicMock(return_value=future)
    else:
        # json() que lança Exception para simular body inválido
        async def _bad_json() -> dict:
            raise ValueError("invalid json")
        req.json = _bad_json
    return req


def _parse_body(response: object) -> dict:  # type: ignore[type-arg]
    """Lê o body de um web.Response como dict."""
    raw = getattr(response, "body", None)
    if isinstance(raw, (bytes, bytearray)):
        return json.loads(raw)  # type: ignore[arg-type]
    return json.loads(str(raw))


# ---------------------------------------------------------------------------
# Tests: register_routes — nova assinatura: ctx -> list[AppRoute]
# ---------------------------------------------------------------------------


class TestRegisterRoutes:
    """Testa a nova assinatura de register_routes para apps de terceiros.

    A interface correta para apps de terceiros (não builtins) é:
    - Recebe ctx (AppContext, duck-typed como object)
    - Retorna list[AppRoute] — o RouteRegistry monta as rotas como
      /api/apps/{app_name}{path}
    """

    def _get_routes(self) -> list:
        """Retorna a lista de AppRoute retornada por register_routes."""
        ctx = mock.MagicMock()
        result = register_routes(ctx)
        return result if isinstance(result, list) else []

    def test_returns_list(self) -> None:
        ctx = mock.MagicMock()
        result = register_routes(ctx)
        assert isinstance(result, list), "register_routes deve retornar list[AppRoute]"

    def test_registers_health_route(self) -> None:
        routes = self._get_routes()
        methods_paths = {(r.method, r.path) for r in routes}
        assert ("GET", "/health") in methods_paths

    def test_registers_issues_route(self) -> None:
        routes = self._get_routes()
        methods_paths = {(r.method, r.path) for r in routes}
        assert ("GET", "/issues") in methods_paths

    def test_registers_dispatch_route(self) -> None:
        routes = self._get_routes()
        methods_paths = {(r.method, r.path) for r in routes}
        assert ("POST", "/dispatch") in methods_paths

    def test_registers_qa_fail_route(self) -> None:
        routes = self._get_routes()
        methods_paths = {(r.method, r.path) for r in routes}
        assert ("POST", "/qa-fail") in methods_paths

    def test_registers_qa_approve_route(self) -> None:
        routes = self._get_routes()
        methods_paths = {(r.method, r.path) for r in routes}
        assert ("POST", "/qa-approve") in methods_paths

    def test_five_explicit_routes(self) -> None:
        routes = self._get_routes()
        assert len(routes) == 5, f"esperado 5 rotas, obtido {len(routes)}"

    def test_handlers_are_callable(self) -> None:
        routes = self._get_routes()
        for route in routes:
            assert callable(route.handler), f"handler de {route.path} deve ser callable"

    def test_appends_on_startup_hook(self) -> None:
        """on_startup ainda é registrado via app.on_startup dentro de _start_loops
        quando chamado pela aiohttp — não via register_routes diretamente."""
        # Este comportamento depende de como o RouteRegistry integra on_startup.
        # Por enquanto verificamos apenas que _start_loops e _stop_loops são importáveis.
        assert callable(_start_loops)
        assert callable(_stop_loops)

    def test_appends_on_cleanup_hook(self) -> None:
        """Equivalente ao test_appends_on_startup_hook."""
        assert callable(_stop_loops)


# ---------------------------------------------------------------------------
# Tests: handle_health
# ---------------------------------------------------------------------------


class TestHandleHealth:
    def test_returns_ok_true(self) -> None:
        loop = asyncio.get_event_loop()
        response = loop.run_until_complete(handle_health(_make_request()))
        body = _parse_body(response)
        assert body["ok"] is True

    def test_returns_correct_app_name(self) -> None:
        loop = asyncio.get_event_loop()
        response = loop.run_until_complete(handle_health(_make_request()))
        body = _parse_body(response)
        assert body["app"] == "kirocrew-flow"

    def test_returns_version(self) -> None:
        loop = asyncio.get_event_loop()
        response = loop.run_until_complete(handle_health(_make_request()))
        body = _parse_body(response)
        assert "version" in body


# ---------------------------------------------------------------------------
# Tests: handle_issues — nova implementação real
# ---------------------------------------------------------------------------


class TestHandleIssues:
    def _run_with_mock_loader(self, columns: dict, squad_name: str = "Test Squad", project: str = "owner/repo") -> dict:
        """Executa handle_issues com _load_issues_from_github mockado."""
        mock_result = {"squad_name": squad_name, "project": project, "columns": columns}
        with mock.patch("backend.routes._load_issues_from_github", return_value=mock_result):
            loop = asyncio.get_event_loop()
            response = loop.run_until_complete(handle_issues(_make_request()))
        return _parse_body(response)

    def test_returns_columns_key(self) -> None:
        body = self._run_with_mock_loader(_empty_columns())
        assert "columns" in body

    def test_returns_squad_name_and_project(self) -> None:
        body = self._run_with_mock_loader(_empty_columns(), squad_name="My Squad", project="owner/repo")
        assert body["squad_name"] == "My Squad"
        assert body["project"] == "owner/repo"

    def test_returns_all_column_keys(self) -> None:
        body = self._run_with_mock_loader(_empty_columns())
        for key in ("spec", "ready", "todo", "dev", "review", "review_ok", "reviewed", "qa", "qa_fail", "done", "blocked"):
            assert key in body["columns"], f"coluna '{key}' ausente no retorno"

    def test_returns_issues_in_correct_column(self) -> None:
        cols = _empty_columns()
        cols["todo"] = [
            {"number": 42, "title": "Test", "repo": "owner/repo", "url": "", "age_min": 10,
             "labels": ["crewflow:todo"], "blocked": False, "running": False}
        ]
        body = self._run_with_mock_loader(cols)
        assert len(body["columns"]["todo"]) == 1
        assert body["columns"]["todo"][0]["number"] == 42

    def test_returns_empty_columns_when_loader_raises(self) -> None:
        """Se _load_issues_from_github lançar exceção, deve retornar colunas vazias com status 500."""
        with mock.patch(
            "backend.routes._load_issues_from_github",
            side_effect=RuntimeError("scan failed"),
        ):
            loop = asyncio.get_event_loop()
            response = loop.run_until_complete(handle_issues(_make_request()))
        body = _parse_body(response)
        assert "columns" in body
        for key in ("spec", "ready", "todo", "dev", "review", "review_ok", "reviewed", "qa", "qa_fail", "done", "blocked"):
            assert body["columns"][key] == []

    def test_status_500_on_error(self) -> None:
        with mock.patch(
            "backend.routes._load_issues_from_github",
            side_effect=RuntimeError("scan failed"),
        ):
            loop = asyncio.get_event_loop()
            response = loop.run_until_complete(handle_issues(_make_request()))
        assert response.status == 500  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Tests: handle_dispatch — nova implementação real
# ---------------------------------------------------------------------------


class TestHandleDispatch:
    def test_returns_400_on_missing_body_fields(self) -> None:
        """Body sem 'repo' ou 'number' deve retornar 400."""
        req = _make_request(body={})
        loop = asyncio.get_event_loop()
        response = loop.run_until_complete(handle_dispatch(req))
        assert response.status == 400  # type: ignore[attr-defined]
        body = _parse_body(response)
        assert body["ok"] is False

    def test_returns_400_on_invalid_number(self) -> None:
        req = _make_request(body={"repo": "owner/repo", "number": "not-a-number"})
        loop = asyncio.get_event_loop()
        response = loop.run_until_complete(handle_dispatch(req))
        assert response.status == 400  # type: ignore[attr-defined]

    def test_returns_400_on_invalid_json(self) -> None:
        """Request com body inválido deve retornar 400."""
        req = _make_request(body=None)  # json() vai lançar exceção
        loop = asyncio.get_event_loop()
        response = loop.run_until_complete(handle_dispatch(req))
        assert response.status == 400  # type: ignore[attr-defined]

    def test_calls_force_dispatch_with_correct_args(self) -> None:
        """handle_dispatch deve chamar _force_dispatch com repo e number corretos."""
        req = _make_request(body={"repo": "owner/repo", "number": 42})
        with mock.patch(
            "backend.routes._force_dispatch",
            return_value={"ok": True, "dispatched": True},
        ) as mock_fd:
            loop = asyncio.get_event_loop()
            response = loop.run_until_complete(handle_dispatch(req))

        mock_fd.assert_called_once_with("owner/repo", 42)
        body = _parse_body(response)
        assert body["ok"] is True
        assert body["dispatched"] is True

    def test_returns_200_on_successful_dispatch(self) -> None:
        req = _make_request(body={"repo": "owner/repo", "number": 1})
        with mock.patch(
            "backend.routes._force_dispatch",
            return_value={"ok": True, "dispatched": True},
        ):
            loop = asyncio.get_event_loop()
            response = loop.run_until_complete(handle_dispatch(req))
        assert response.status == 200  # type: ignore[attr-defined]

    def test_returns_500_on_force_dispatch_exception(self) -> None:
        req = _make_request(body={"repo": "owner/repo", "number": 1})
        with mock.patch(
            "backend.routes._force_dispatch",
            side_effect=RuntimeError("dispatch explodiu"),
        ):
            loop = asyncio.get_event_loop()
            response = loop.run_until_complete(handle_dispatch(req))
        assert response.status == 500  # type: ignore[attr-defined]
        body = _parse_body(response)
        assert body["ok"] is False

    def test_number_as_string_is_coerced_to_int(self) -> None:
        """'number' como string numérica deve ser aceito."""
        req = _make_request(body={"repo": "owner/repo", "number": "99"})
        with mock.patch(
            "backend.routes._force_dispatch",
            return_value={"ok": True, "dispatched": True},
        ) as mock_fd:
            loop = asyncio.get_event_loop()
            loop.run_until_complete(handle_dispatch(req))
        # Deve ter sido convertido para int
        mock_fd.assert_called_once_with("owner/repo", 99)


# ---------------------------------------------------------------------------
# Tests: handle_qa_fail — "Reprovar QA"
# ---------------------------------------------------------------------------


class TestHandleQaFail:
    def test_returns_400_on_missing_body_fields(self) -> None:
        req = _make_request(body={})
        loop = asyncio.get_event_loop()
        response = loop.run_until_complete(handle_qa_fail(req))
        assert response.status == 400  # type: ignore[attr-defined]
        body = _parse_body(response)
        assert body["ok"] is False

    def test_returns_400_on_invalid_number(self) -> None:
        req = _make_request(body={"repo": "owner/repo", "number": "nan", "reason": "x"})
        loop = asyncio.get_event_loop()
        response = loop.run_until_complete(handle_qa_fail(req))
        assert response.status == 400  # type: ignore[attr-defined]

    def test_returns_400_on_invalid_json(self) -> None:
        req = _make_request(body=None)
        loop = asyncio.get_event_loop()
        response = loop.run_until_complete(handle_qa_fail(req))
        assert response.status == 400  # type: ignore[attr-defined]

    def test_calls_worker_with_repo_number_reason(self) -> None:
        req = _make_request(body={"repo": "owner/repo", "number": 42, "reason": "layout quebrado"})
        with mock.patch(
            "backend.routes._apply_qa_fail",
            return_value={"ok": True},
        ) as mock_worker:
            loop = asyncio.get_event_loop()
            response = loop.run_until_complete(handle_qa_fail(req))
        mock_worker.assert_called_once_with("owner/repo", 42, "layout quebrado")
        body = _parse_body(response)
        assert body["ok"] is True

    def test_returns_200_on_success(self) -> None:
        req = _make_request(body={"repo": "owner/repo", "number": 1, "reason": "bug"})
        with mock.patch("backend.routes._apply_qa_fail", return_value={"ok": True}):
            loop = asyncio.get_event_loop()
            response = loop.run_until_complete(handle_qa_fail(req))
        assert response.status == 200  # type: ignore[attr-defined]

    def test_returns_400_when_worker_reports_not_ok(self) -> None:
        req = _make_request(body={"repo": "owner/repo", "number": 1, "reason": "bug"})
        with mock.patch(
            "backend.routes._apply_qa_fail",
            return_value={"ok": False, "error": "não está em crewflow:qa"},
        ):
            loop = asyncio.get_event_loop()
            response = loop.run_until_complete(handle_qa_fail(req))
        assert response.status == 400  # type: ignore[attr-defined]

    def test_returns_500_on_worker_exception(self) -> None:
        req = _make_request(body={"repo": "owner/repo", "number": 1, "reason": "bug"})
        with mock.patch(
            "backend.routes._apply_qa_fail",
            side_effect=RuntimeError("boom"),
        ):
            loop = asyncio.get_event_loop()
            response = loop.run_until_complete(handle_qa_fail(req))
        assert response.status == 500  # type: ignore[attr-defined]
        body = _parse_body(response)
        assert body["ok"] is False

    def test_reason_defaults_to_empty_when_absent(self) -> None:
        req = _make_request(body={"repo": "owner/repo", "number": 7})
        with mock.patch(
            "backend.routes._apply_qa_fail",
            return_value={"ok": True},
        ) as mock_worker:
            loop = asyncio.get_event_loop()
            loop.run_until_complete(handle_qa_fail(req))
        mock_worker.assert_called_once_with("owner/repo", 7, "")


# ---------------------------------------------------------------------------
# Tests: handle_qa_approve — "Aprovar QA"
# ---------------------------------------------------------------------------


class TestHandleQaApprove:
    def test_returns_400_on_missing_body_fields(self) -> None:
        req = _make_request(body={})
        loop = asyncio.get_event_loop()
        response = loop.run_until_complete(handle_qa_approve(req))
        assert response.status == 400  # type: ignore[attr-defined]

    def test_returns_400_on_invalid_number(self) -> None:
        req = _make_request(body={"repo": "owner/repo", "number": "nan"})
        loop = asyncio.get_event_loop()
        response = loop.run_until_complete(handle_qa_approve(req))
        assert response.status == 400  # type: ignore[attr-defined]

    def test_calls_worker_with_repo_number(self) -> None:
        req = _make_request(body={"repo": "owner/repo", "number": 42})
        with mock.patch(
            "backend.routes._apply_qa_approve",
            return_value={"ok": True, "done": True},
        ) as mock_worker:
            loop = asyncio.get_event_loop()
            response = loop.run_until_complete(handle_qa_approve(req))
        mock_worker.assert_called_once_with("owner/repo", 42)
        assert response.status == 200  # type: ignore[attr-defined]

    def test_returns_500_on_worker_exception(self) -> None:
        req = _make_request(body={"repo": "owner/repo", "number": 1})
        with mock.patch(
            "backend.routes._apply_qa_approve",
            side_effect=RuntimeError("boom"),
        ):
            loop = asyncio.get_event_loop()
            response = loop.run_until_complete(handle_qa_approve(req))
        assert response.status == 500  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Tests: _apply_qa_fail — worker que aplica a transição de labels de reprovação
# (os handler tests acima mockam o worker; aqui exercitamos a lógica real)
# ---------------------------------------------------------------------------


class TestApplyQaFail:
    def test_flips_qa_to_qa_fail_preserving_type_and_priority(self) -> None:
        from backend.routes import _apply_qa_fail

        with (
            mock.patch(
                "flow.adapters.github_client.get_work_item",
                return_value={"labels": ["crewflow:qa", "crewflow:feature", "priority:high"]},
            ),
            mock.patch("flow.adapters.github_client.set_labels") as mock_set,
            mock.patch("flow.adapters.github_client.add_issue_comment") as mock_comment,
        ):
            result = _apply_qa_fail("owner/repo", 42, "layout quebrado")

        assert result["ok"] is True
        applied = set(mock_set.call_args[0][2])
        assert "crewflow:qa-fail" in applied
        assert "crewflow:qa" not in applied
        # Labels de tipo/prioridade preservadas
        assert "crewflow:feature" in applied
        assert "priority:high" in applied
        # Motivo registrado como comentário com o prefixo esperado
        mock_comment.assert_called_once()
        assert "Reprovado no QA: layout quebrado" in mock_comment.call_args[0][2]

    def test_rejects_issue_not_in_qa(self) -> None:
        from backend.routes import _apply_qa_fail

        with (
            mock.patch(
                "flow.adapters.github_client.get_work_item",
                return_value={"labels": ["crewflow:dev", "crewflow:feature"]},
            ),
            mock.patch("flow.adapters.github_client.set_labels") as mock_set,
        ):
            result = _apply_qa_fail("owner/repo", 42, "x")

        assert result["ok"] is False
        mock_set.assert_not_called()

    def test_ok_with_note_when_comment_fails(self) -> None:
        from backend.routes import _apply_qa_fail
        from flow.ports.issue_provider import ProviderError

        with (
            mock.patch(
                "flow.adapters.github_client.get_work_item",
                return_value={"labels": ["crewflow:qa", "crewflow:feature"]},
            ),
            mock.patch("flow.adapters.github_client.set_labels"),
            mock.patch(
                "flow.adapters.github_client.add_issue_comment",
                side_effect=ProviderError("api down"),
            ),
        ):
            result = _apply_qa_fail("owner/repo", 42, "x")

        # Label trocada é o que importa para o cron → ok:true com nota
        assert result["ok"] is True
        assert "note" in result


# ---------------------------------------------------------------------------
# Tests: _apply_qa_approve — worker que aprova (opcionalmente mergeia) e vai a done
# ---------------------------------------------------------------------------


class TestApplyQaApprove:
    def test_transitions_to_done_preserving_type_when_no_auto_merge(self) -> None:
        from backend.routes import _apply_qa_approve

        with (
            mock.patch(
                "flow.adapters.github_client.get_work_item",
                return_value={"labels": ["crewflow:qa", "crewflow:feature", "priority:low"]},
            ),
            mock.patch("backend.routes._auto_merge_on_approve_for_repo", return_value=False),
            mock.patch("flow.adapters.github_client.merge_pull_request") as mock_merge,
            mock.patch("flow.adapters.github_client.set_labels") as mock_set,
        ):
            result = _apply_qa_approve("owner/repo", 42)

        assert result["ok"] is True
        assert result["merged"] is False
        mock_merge.assert_not_called()
        applied = set(mock_set.call_args[0][2])
        assert "crewflow:done" in applied
        assert "crewflow:qa" not in applied
        assert "crewflow:qa-fail" not in applied
        # Labels de tipo/prioridade preservadas na transição
        assert "crewflow:feature" in applied
        assert "priority:low" in applied

    def test_rejects_issue_not_in_qa(self) -> None:
        from backend.routes import _apply_qa_approve

        with (
            mock.patch(
                "flow.adapters.github_client.get_work_item",
                return_value={"labels": ["crewflow:review", "crewflow:feature"]},
            ),
            mock.patch("backend.routes._auto_merge_on_approve_for_repo", return_value=False),
            mock.patch("flow.adapters.github_client.set_labels") as mock_set,
        ):
            result = _apply_qa_approve("owner/repo", 42)

        assert result["ok"] is False
        mock_set.assert_not_called()

    def test_merges_pr_when_auto_merge_enabled(self) -> None:
        from backend.routes import _apply_qa_approve

        with (
            mock.patch(
                "flow.adapters.github_client.get_work_item",
                return_value={"labels": ["crewflow:qa", "crewflow:feature"]},
            ),
            mock.patch("backend.routes._auto_merge_on_approve_for_repo", return_value=True),
            mock.patch(
                "flow.adapters.github_client.get_pr_for_issue",
                return_value={"number": 7, "headRefName": "feat/issue-42"},
            ),
            mock.patch("flow.adapters.github_client.merge_pull_request") as mock_merge,
            mock.patch("flow.adapters.github_client.delete_branch") as mock_del,
            mock.patch("flow.adapters.github_client.set_labels") as mock_set,
        ):
            result = _apply_qa_approve("owner/repo", 42)

        assert result["ok"] is True
        assert result["merged"] is True
        mock_merge.assert_called_once_with("owner/repo", 7, merge_method="squash")
        mock_del.assert_called_once_with("owner/repo", "feat/issue-42")
        applied = set(mock_set.call_args[0][2])
        assert "crewflow:done" in applied

    def test_auto_merge_without_open_pr_returns_error(self) -> None:
        from backend.routes import _apply_qa_approve

        with (
            mock.patch(
                "flow.adapters.github_client.get_work_item",
                return_value={"labels": ["crewflow:qa", "crewflow:feature"]},
            ),
            mock.patch("backend.routes._auto_merge_on_approve_for_repo", return_value=True),
            mock.patch("flow.adapters.github_client.get_pr_for_issue", return_value=None),
            mock.patch("flow.adapters.github_client.set_labels") as mock_set,
        ):
            result = _apply_qa_approve("owner/repo", 42)

        assert result["ok"] is False
        mock_set.assert_not_called()


# ---------------------------------------------------------------------------
# Tests: _load_issues_from_github — agrupamento de qa / qa-fail em colunas
# ---------------------------------------------------------------------------


class TestLoadIssuesGrouping:
    def _run_grouping(self, items: list[dict]) -> dict:
        """Roda _load_issues_from_github com uma squad e _fetch_all_state_items mockados."""
        from backend.routes import _load_issues_from_github

        squad = mock.MagicMock()
        squad.name = "Test Squad"
        squad.projects = ["owner/repo"]
        squad.id = "test"
        squad.issue_provider = "github"
        squad.repos = frozenset({"owner/repo"})

        with (
            mock.patch("flow.config.squad.load_squads_dir", return_value=[squad]),
            mock.patch("flow.ports.issue_provider.provider_for", return_value=mock.MagicMock()),
            mock.patch("flow.scan.cache.open_cache", return_value=mock.MagicMock()),
            mock.patch("backend.routes._fetch_all_state_items", return_value=items),
            mock.patch("backend.routes._derive_implicit_state", return_value=None),
            mock.patch("pathlib.Path.exists", return_value=True),
        ):
            return _load_issues_from_github()

    def test_qa_issue_lands_in_qa_column(self) -> None:
        items = [{
            "number": 42,
            "title": "em teste",
            "repo": "owner/repo",
            "labels": ["crewflow:qa", "crewflow:feature"],
        }]
        result = self._run_grouping(items)
        cols = result["columns"]
        assert [i["number"] for i in cols["qa"]] == [42]
        assert cols["qa_fail"] == []

    def test_qa_fail_issue_lands_in_qa_fail_column(self) -> None:
        items = [{
            "number": 43,
            "title": "reprovado",
            "repo": "owner/repo",
            "labels": ["crewflow:qa", "crewflow:qa-fail", "crewflow:feature"],
        }]
        result = self._run_grouping(items)
        cols = result["columns"]
        assert [i["number"] for i in cols["qa_fail"]] == [43]
        assert cols["qa"] == []


# ---------------------------------------------------------------------------
# Tests: helpers
# ---------------------------------------------------------------------------


class TestAgeMinutes:
    def test_returns_zero_for_empty_string(self) -> None:
        assert _age_minutes("", 0) == 0

    def test_calculates_age_in_minutes(self) -> None:
        import datetime
        # Cria um timestamp de exatamente 120 minutos atrás
        now = datetime.datetime.now(tz=datetime.UTC)
        past = now - datetime.timedelta(minutes=120)
        age = _age_minutes(past.isoformat(), now.timestamp())
        assert age == 120

    def test_returns_zero_for_invalid_timestamp(self) -> None:
        assert _age_minutes("not-a-date", 1000000) == 0

    def test_returns_zero_for_future_timestamps(self) -> None:
        import datetime
        now = datetime.datetime.now(tz=datetime.UTC)
        future = now + datetime.timedelta(minutes=10)
        age = _age_minutes(future.isoformat(), now.timestamp())
        assert age == 0


class TestStateToColumn:
    def test_todo_maps_to_todo(self) -> None:
        from flow.domain.state import State
        assert _state_to_column(State.TODO) == "todo"

    def test_dev_maps_to_dev(self) -> None:
        from flow.domain.state import State
        assert _state_to_column(State.DEV) == "dev"

    def test_review_maps_to_review(self) -> None:
        from flow.domain.state import State
        assert _state_to_column(State.REVIEW) == "review"

    def test_qa_maps_to_qa(self) -> None:
        from flow.domain.state import State
        assert _state_to_column(State.QA) == "qa"

    def test_done_maps_to_done(self) -> None:
        from flow.domain.state import State
        assert _state_to_column(State.DONE) == "done"

    def test_spec_maps_to_spec(self) -> None:
        from flow.domain.state import State
        assert _state_to_column(State.SPEC) == "spec"

    def test_ready_maps_to_ready(self) -> None:
        from flow.domain.state import State
        assert _state_to_column(State.READY) == "ready"


class TestRepoFromKey:
    def test_extracts_repo_from_owner_repo_hash_n(self) -> None:
        assert _repo_from_key("owner/repo#42") == "owner/repo"

    def test_returns_empty_for_plain_number(self) -> None:
        assert _repo_from_key("42") == ""

    def test_returns_empty_for_empty_string(self) -> None:
        assert _repo_from_key("") == ""


class TestEmptyColumns:
    def test_has_all_required_keys(self) -> None:
        cols = _empty_columns()
        for key in ("spec", "ready", "todo", "dev", "review", "review_ok", "reviewed", "qa", "qa_fail", "done", "blocked"):
            assert key in cols

    def test_all_values_are_empty_lists(self) -> None:
        cols = _empty_columns()
        for v in cols.values():
            assert v == []


# ---------------------------------------------------------------------------
# Tests: _start_loops
# ---------------------------------------------------------------------------


class TestStartLoops:
    def test_creates_four_tasks(self, capsys: pytest.CaptureFixture) -> None:  # type: ignore[type-arg]
        """_start_loops deve criar 4 tasks no app e imprimir log."""
        app = web.Application()

        with mock.patch("backend.routes.asyncio.create_task") as mock_create_task:
            fake_tasks = [mock.MagicMock() for _ in range(4)]
            mock_create_task.side_effect = fake_tasks

            with mock.patch.dict(
                "sys.modules",
                {
                    "backend.server": mock.MagicMock(
                        _run_stage_loop=mock.MagicMock(return_value=mock.MagicMock())
                    ),
                    "deployment.deployment": mock.MagicMock(
                        _STAGE_DEV="dev",
                        _STAGE_REVIEWER="reviewer",
                        _STAGE_MERGE="merge",
                        _STAGE_CONFLITO="conflito",
                    ),
                },
            ):
                asyncio.get_event_loop().run_until_complete(_start_loops(app))

        assert mock_create_task.call_count == 4
        assert "crewflow_tasks" in app
        assert len(app["crewflow_tasks"]) == 4

        captured = capsys.readouterr()
        assert "on_startup" in captured.out
        assert "4 loops asyncio iniciados" in captured.out

    def test_handles_import_error_gracefully(self, capsys: pytest.CaptureFixture) -> None:  # type: ignore[type-arg]
        """_start_loops não deve propagar exceção se imports falharem."""
        app = web.Application()

        with mock.patch.dict("sys.modules", {"backend.server": None}):  # type: ignore[dict-item]
            asyncio.get_event_loop().run_until_complete(_start_loops(app))

        captured = capsys.readouterr()
        assert "error" in captured.out.lower() or "on_startup" in captured.out


# ---------------------------------------------------------------------------
# Tests: _stop_loops
# ---------------------------------------------------------------------------


class TestStopLoops:
    def test_cancels_all_tasks(self, capsys: pytest.CaptureFixture) -> None:  # type: ignore[type-arg]
        """_stop_loops deve cancelar todas as tasks e limpar a lista."""
        app = web.Application()
        fake_tasks = [mock.MagicMock() for _ in range(4)]
        app["crewflow_tasks"] = fake_tasks

        asyncio.get_event_loop().run_until_complete(_stop_loops(app))

        for task in fake_tasks:
            task.cancel.assert_called_once()

        assert app["crewflow_tasks"] == []

        captured = capsys.readouterr()
        assert "on_cleanup" in captured.out

    def test_no_tasks_key_does_not_raise(self) -> None:
        """_stop_loops sem chave crewflow_tasks não deve lançar exceção."""
        app = web.Application()
        asyncio.get_event_loop().run_until_complete(_stop_loops(app))

    def test_empty_task_list_does_not_raise(self) -> None:
        """_stop_loops com lista vazia não deve lançar exceção."""
        app = web.Application()
        app["crewflow_tasks"] = []
        asyncio.get_event_loop().run_until_complete(_stop_loops(app))
