"""Placeholder LOCAL de DEV/CI para o módulo `kirocrew_client` do runtime do Kiro Crew.

Em produção, o runtime do Kiro Crew injeta o cliente real (`CrewClient`) que fala
com o gateway da plataforma. Aqui NÃO temos esse módulo disponível (não está em
nenhum registry, nem no pyproject), então este pacote fornece uma implementação
mínima e sem dependências apenas para que:

- os módulos em `backend/` consigam fazer `from kirocrew_client import CrewClient`
  no topo do arquivo sem quebrar em dev/CI;
- os testes de unidade consigam importar e mockar o cliente.

Este stub NÃO deve ser adicionado às dependências de runtime do projeto: em
produção o cliente verdadeiro é fornecido pela plataforma.
"""
from __future__ import annotations

from typing import Any


class CrewClient:
    """Stub de dev do cliente do Kiro Crew (async context manager).

    Reproduz apenas a superfície usada pelo código de `backend/`:
    construção com `app_name`, uso como async context manager e envio de
    notificações. Nenhuma chamada de rede real acontece aqui.
    """

    def __init__(self, app_name: str = "", **kwargs: Any) -> None:
        self.app_name = app_name

    async def __aenter__(self) -> CrewClient:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def send_notification(self, text: str) -> None:
        """No-op no stub de dev; o cliente real envia a notificação ao usuário."""
        return None
