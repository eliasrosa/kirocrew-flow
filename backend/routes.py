"""Rotas do app kirocrew-flow registradas no gateway in-process."""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

from aiohttp import web

# Garante que a raiz do repo está no sys.path antes de importar os módulos de
# orquestração do backend (que por sua vez importam flow/ e deployment/).
_APP_ROOT = Path(__file__).parent.parent
if str(_APP_ROOT) not in sys.path:
    sys.path.insert(0, str(_APP_ROOT))

from backend import dispatch as dispatch_mod  # noqa: E402
from backend import issues as issues_mod  # noqa: E402
from flow.ports.issue_provider import ProviderError  # noqa: E402


async def _start_loops(app: web.Application) -> None:
    """Hook on_startup: inicia os 4 loops asyncio de polling da esteira."""
    app_root = Path(__file__).parent.parent
    if str(app_root) not in sys.path:
        sys.path.insert(0, str(app_root))

    try:
        from backend.server import _run_stage_loop
        from deployment.deployment import (
            _STAGE_CONFLITO,
            _STAGE_DEV,
            _STAGE_MERGE,
            _STAGE_REVIEWER,
        )

        app["crewflow_tasks"] = [
            asyncio.create_task(
                _run_stage_loop(
                    _STAGE_DEV,
                    int(os.environ.get("CREWFLOW_DEV_INTERVAL", "300")),
                )
            ),
            asyncio.create_task(
                _run_stage_loop(
                    _STAGE_REVIEWER,
                    int(os.environ.get("CREWFLOW_REVIEWER_INTERVAL", "180")),
                )
            ),
            asyncio.create_task(
                _run_stage_loop(
                    _STAGE_MERGE,
                    int(os.environ.get("CREWFLOW_MERGE_INTERVAL", "120")),
                )
            ),
            asyncio.create_task(
                _run_stage_loop(
                    _STAGE_CONFLITO,
                    int(os.environ.get("CREWFLOW_CONFLITO_INTERVAL", "300")),
                )
            ),
        ]
        print("[kirocrew-flow] on_startup: 4 loops asyncio iniciados", flush=True)
    except Exception as exc:
        print(f"[kirocrew-flow] on_startup error: {exc}", flush=True)


async def _stop_loops(app: web.Application) -> None:
    """Hook on_cleanup: cancela os loops asyncio e limpa a lista."""
    for task in app.get("crewflow_tasks", []):
        task.cancel()
    app["crewflow_tasks"] = []
    print("[kirocrew-flow] on_cleanup: loops cancelados", flush=True)


def register_routes(app: web.Application) -> None:
    """Registra as rotas HTTP e hooks de ciclo de vida no app do gateway.

    Chamado pelo gateway com o ``web.Application`` de forma idêntica ao Issue Radar
    (``_mod.register_routes(app)``). Usa ``app.router`` para as rotas e
    ``app.on_startup`` / ``app.on_cleanup`` para os loops asyncio.

    Args:
        app: instância de ``aiohttp.web.Application`` do gateway.
    """
    app.router.add_get("/api/apps/kirocrew-flow/health", handle_health)
    app.router.add_get("/api/apps/kirocrew-flow/issues", handle_issues)
    app.router.add_post("/api/apps/kirocrew-flow/dispatch", handle_dispatch)

    app.on_startup.append(_start_loops)
    app.on_cleanup.append(_stop_loops)


async def handle_health(request: web.Request) -> web.Response:
    return web.json_response({"ok": True, "app": "kirocrew-flow", "version": "1.0.0"})


async def handle_issues(request: web.Request) -> web.Response:
    """Lista issues por estágio da esteira (crewflow:*), agrupadas em colunas.

    Zero-token / cache-first: consome ``provider.list_by_state`` (leitura de
    labels) via a orquestração em ``backend.issues``. Erros de provider ou
    setup degradam para colunas vazias (HTTP 200), nunca um 500.
    """
    try:
        loop = asyncio.get_running_loop()
        columns = await loop.run_in_executor(None, issues_mod.collect_columns)
    except ProviderError as exc:
        print(f"[kirocrew-flow] handle_issues provider error: {exc}", flush=True)
        columns = issues_mod.empty_columns()
    except Exception as exc:
        print(f"[kirocrew-flow] handle_issues error: {exc}", flush=True)
        columns = issues_mod.empty_columns()
    return web.json_response({"columns": columns})


async def handle_dispatch(request: web.Request) -> web.Response:
    """Force dispatch manual de uma issue (body: {"repo", "number"}).

    Marca a issue em ``crewflow:todo`` se necessário e dispara o estágio dev
    pelo mesmo caminho do cron (``_run_stage`` + ``_STAGE_DEV``) via executor.
    """
    try:
        body = await request.json()
    except Exception:
        return web.json_response(
            {"ok": False, "error": "corpo JSON inválido"}, status=400
        )

    try:
        repo, number = dispatch_mod.validate_body(body)
    except dispatch_mod.DispatchError as exc:
        return web.json_response({"ok": False, "error": str(exc)}, status=400)

    try:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, dispatch_mod.ensure_todo, repo, number)
        await loop.run_in_executor(None, dispatch_mod.run_dev_stage)
    except ProviderError as exc:
        print(f"[kirocrew-flow] handle_dispatch provider error: {exc}", flush=True)
        return web.json_response({"ok": False, "error": str(exc)}, status=502)
    except Exception as exc:
        print(f"[kirocrew-flow] handle_dispatch error: {exc}", flush=True)
        return web.json_response({"ok": False, "error": str(exc)}, status=500)

    return web.json_response({"ok": True, "dispatched": True})
