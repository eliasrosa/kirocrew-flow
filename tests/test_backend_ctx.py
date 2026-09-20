"""Testes de unidade para backend.ctx.BackendCronCtx."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

# Garante que a raiz do repo esteja no sys.path para importar backend/ e o stub
# kirocrew_client (mesma estratégia usada em backend/server.py).
APP_ROOT = Path(__file__).parent.parent
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from backend.ctx import BackendCronCtx  # noqa: E402


def _make_client() -> MagicMock:
    """CrewClient fake com send_notification assíncrono mockado."""
    client = MagicMock()
    client.send_notification = AsyncMock()
    return client


def test_message_retorna_string_passada() -> None:
    client = _make_client()
    ctx = BackendCronCtx(client, message="ola mundo")
    assert ctx.message == "ola mundo"


def test_message_default_vazia() -> None:
    client = _make_client()
    ctx = BackendCronCtx(client)
    assert ctx.message == ""


def test_notify_chama_send_notification_com_running_loop() -> None:
    client = _make_client()
    ctx = BackendCronCtx(client)

    async def _run() -> None:
        ctx.notify("mensagem de teste")
        # notify agenda uma task no loop corrente; cedemos controle para
        # garantir que ela execute antes de asserir.
        await asyncio.sleep(0)

    asyncio.run(_run())

    client.send_notification.assert_awaited_once_with("mensagem de teste")


def test_notify_fallback_sem_running_loop() -> None:
    """Sem loop rodando, notify usa asyncio.run internamente."""
    client = _make_client()
    ctx = BackendCronCtx(client)

    ctx.notify("fallback")

    client.send_notification.assert_awaited_once_with("fallback")
