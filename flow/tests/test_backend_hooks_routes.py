"""Testes de unidade para backend.routes e backend.hooks.

Critérios de aceite (issue #155):
- register_routes registra as 3 rotas esperadas via duck-typing
- handle_health retorna {"ok": true, "app": "kirocrew-flow", "version": "1.0.0"}
- handle_issues retorna {"issues": [], "note": "TODO Fase 4"}
- handle_dispatch retorna {"ok": true, "note": "TODO Fase 4"}
- on_startup cria 4 tasks asyncio e imprime log
- on_shutdown cancela tasks e limpa a lista
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from unittest import mock

import pytest

# Garante que o raiz do repo está no path para importar backend/
_REPO_ROOT = str(Path(__file__).parent.parent.parent)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from backend.routes import (  # noqa: E402
    handle_dispatch,
    handle_health,
    handle_issues,
    register_routes,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_request() -> mock.MagicMock:
    """Retorna um mock mínimo de web.Request."""
    return mock.MagicMock()


def _parse_body(response: object) -> dict:  # type: ignore[type-arg]
    """Lê o body de um web.Response como dict, aceitando bytes ou str."""
    raw = getattr(response, "body", None)
    if isinstance(raw, (bytes, bytearray)):
        return json.loads(raw)  # type: ignore[arg-type]
    return json.loads(str(raw))


class _FakeRegistry:
    """Implementação mínima de duck-typing para RouteRegistry do gateway."""

    def __init__(self) -> None:
        self.routes: list[tuple[str, str, object]] = []

    def add_route(self, method: str, path: str, handler: object) -> None:
        self.routes.append((method, path, handler))


# ---------------------------------------------------------------------------
# Tests: register_routes
# ---------------------------------------------------------------------------


class TestRegisterRoutes:
    def test_registers_three_routes(self) -> None:
        registry = _FakeRegistry()
        register_routes(registry)
        assert len(registry.routes) == 3

    def test_health_route_registered(self) -> None:
        registry = _FakeRegistry()
        register_routes(registry)
        methods_paths = [(m, p) for m, p, _ in registry.routes]
        assert ("GET", "/apps/kirocrew-flow/api/health") in methods_paths

    def test_issues_route_registered(self) -> None:
        registry = _FakeRegistry()
        register_routes(registry)
        methods_paths = [(m, p) for m, p, _ in registry.routes]
        assert ("GET", "/apps/kirocrew-flow/api/issues") in methods_paths

    def test_dispatch_route_registered(self) -> None:
        registry = _FakeRegistry()
        register_routes(registry)
        methods_paths = [(m, p) for m, p, _ in registry.routes]
        assert ("POST", "/apps/kirocrew-flow/api/dispatch") in methods_paths

    def test_handlers_are_callable(self) -> None:
        registry = _FakeRegistry()
        register_routes(registry)
        for _, _, handler in registry.routes:
            assert callable(handler)


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
# Tests: handle_issues
# ---------------------------------------------------------------------------


class TestHandleIssues:
    def test_returns_empty_issues_list(self) -> None:
        loop = asyncio.get_event_loop()
        response = loop.run_until_complete(handle_issues(_make_request()))
        body = _parse_body(response)
        assert body["issues"] == []

    def test_returns_todo_note(self) -> None:
        loop = asyncio.get_event_loop()
        response = loop.run_until_complete(handle_issues(_make_request()))
        body = _parse_body(response)
        assert "note" in body
        assert "TODO" in body["note"]


# ---------------------------------------------------------------------------
# Tests: handle_dispatch
# ---------------------------------------------------------------------------


class TestHandleDispatch:
    def test_returns_ok_true(self) -> None:
        loop = asyncio.get_event_loop()
        response = loop.run_until_complete(handle_dispatch(_make_request()))
        body = _parse_body(response)
        assert body["ok"] is True

    def test_returns_todo_note(self) -> None:
        loop = asyncio.get_event_loop()
        response = loop.run_until_complete(handle_dispatch(_make_request()))
        body = _parse_body(response)
        assert "note" in body
        assert "TODO" in body["note"]


# ---------------------------------------------------------------------------
# Tests: hooks on_startup / on_shutdown
# ---------------------------------------------------------------------------


class TestHooksOnStartup:
    def test_on_startup_creates_four_tasks(self, capsys: pytest.CaptureFixture) -> None:  # type: ignore[type-arg]
        """on_startup deve criar 4 tasks asyncio e imprimir log de confirmação."""
        import backend.hooks as hooks_module

        # Reset state
        hooks_module._LOOP_TASKS.clear()

        with mock.patch("backend.hooks.asyncio.get_event_loop") as mock_get_loop:
            fake_loop = mock.MagicMock()
            fake_tasks = [mock.MagicMock() for _ in range(4)]
            fake_loop.create_task.side_effect = fake_tasks
            mock_get_loop.return_value = fake_loop

            # Patch os imports internos do on_startup
            fake_run_stage_loop = mock.MagicMock()
            with (
                mock.patch.dict(
                    "sys.modules",
                    {
                        "backend.server": mock.MagicMock(_run_stage_loop=fake_run_stage_loop),
                        "deployment.deployment": mock.MagicMock(
                            _STAGE_DEV="dev",
                            _STAGE_REVIEWER="reviewer",
                            _STAGE_MERGE="merge",
                            _STAGE_CONFLITO="conflito",
                        ),
                    },
                ),
            ):
                hooks_module.on_startup()

        assert len(hooks_module._LOOP_TASKS) == 4
        captured = capsys.readouterr()
        assert "on_startup" in captured.out
        assert "4 loops asyncio iniciados" in captured.out

        # Cleanup
        hooks_module._LOOP_TASKS.clear()

    def test_on_startup_handles_import_error_gracefully(
        self, capsys: pytest.CaptureFixture  # type: ignore[type-arg]
    ) -> None:
        """on_startup não deve propagar exceção se imports falharem."""
        import backend.hooks as hooks_module

        hooks_module._LOOP_TASKS.clear()

        # Simula falha no import de backend.server
        with mock.patch.dict("sys.modules", {"backend.server": None}):  # type: ignore[dict-item]
            hooks_module.on_startup()

        captured = capsys.readouterr()
        # Deve ter caído no except e logado o erro
        assert "error" in captured.out.lower() or "on_startup" in captured.out

        hooks_module._LOOP_TASKS.clear()


class TestHooksOnShutdown:
    def test_on_shutdown_cancels_all_tasks(self, capsys: pytest.CaptureFixture) -> None:  # type: ignore[type-arg]
        """on_shutdown deve cancelar todas as tasks e limpar a lista."""
        import backend.hooks as hooks_module

        fake_tasks = [mock.MagicMock() for _ in range(4)]
        hooks_module._LOOP_TASKS.extend(fake_tasks)

        hooks_module.on_shutdown()

        for task in fake_tasks:
            task.cancel.assert_called_once()

        assert hooks_module._LOOP_TASKS == []

        captured = capsys.readouterr()
        assert "on_shutdown" in captured.out

    def test_on_shutdown_with_empty_list_does_not_raise(self) -> None:
        """on_shutdown com lista vazia não deve lançar exceção."""
        import backend.hooks as hooks_module

        hooks_module._LOOP_TASKS.clear()
        hooks_module.on_shutdown()  # não deve lançar
