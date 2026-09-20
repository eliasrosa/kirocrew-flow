"""Rotas do app kirocrew-flow registradas no RouteRegistry in-gateway."""
from __future__ import annotations

from aiohttp import web


def register_routes(registry) -> None:
    """Registra as rotas HTTP do app no RouteRegistry do gateway.

    Args:
        registry: RouteRegistry do gateway (duck-typing — não importar diretamente).
    """
    registry.add_route("GET", "/apps/kirocrew-flow/api/health", handle_health)
    registry.add_route("GET", "/apps/kirocrew-flow/api/issues", handle_issues)
    registry.add_route("POST", "/apps/kirocrew-flow/api/dispatch", handle_dispatch)


async def handle_health(request: web.Request) -> web.Response:
    return web.json_response({"ok": True, "app": "kirocrew-flow", "version": "1.0.0"})


async def handle_issues(request: web.Request) -> web.Response:
    """Lista issues por estágio (crewflow:*). Placeholder para Fase 4."""
    return web.json_response({"issues": [], "note": "TODO Fase 4"})


async def handle_dispatch(request: web.Request) -> web.Response:
    """Force dispatch manual de uma issue. Placeholder para Fase 4."""
    return web.json_response({"ok": True, "note": "TODO Fase 4"})
