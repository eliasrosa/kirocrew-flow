"""Contexto sintético que simula o ctx do cron do Kiro Crew para uso nos loops asyncio."""
from __future__ import annotations  # noqa: I001
import asyncio
from kirocrew_client import CrewClient


class BackendCronCtx:
    """Substitui o ctx injetado pelo Kiro Crew nos scripts de cron.

    O deployment.py usa ctx apenas para:
    - ctx.notify(text) — enviar mensagem ao usuário
    - ctx.message      — argumento do cron (normalmente vazio nos estágios)
    """

    def __init__(self, client: CrewClient, message: str = "") -> None:
        self._client = client
        self.message = message

    def notify(self, text: str) -> None:
        """Envia notificação via kirocrew-client (fire-and-forget)."""
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self._client.send_notification(text))  # noqa: RUF006
        except RuntimeError:
            asyncio.run(self._client.send_notification(text))
