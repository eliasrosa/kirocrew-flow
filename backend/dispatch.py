"""Orquestração da rota POST /dispatch — force dispatch manual de uma issue.

Marca a issue em ``crewflow:todo`` (se ainda não estiver) e dispara o estágio
dev pelo MESMO caminho do cron (``deployment.deployment._run_stage`` com
``_STAGE_DEV``), reusando ``BackendCronCtx``. Como ``_run_stage`` é síncrono e
faz I/O bloqueante, o handler o roda em executor — igual ao
``backend.server._run_stage_loop``.

Consome ``flow/`` e ``deployment/`` apenas por import; nenhuma modificação no
motor. O acesso ao provider é mockável (patch de ``provider_for`` ou do
transport) para que os testes nunca toquem a rede.
"""
from __future__ import annotations

import sys
from pathlib import Path

from backend.issues import load_squads
from flow.domain.state import State, parse_state, transition_state
from flow.ports.issue_provider import provider_for

# Garante que a raiz do repo está no sys.path antes de importar
# deployment.deployment (idêntico ao guard de backend/routes._start_loops e
# backend/server.py). deployment.py puxa flow/ que precisa ser importável.
_APP_ROOT = Path(__file__).parent.parent
if str(_APP_ROOT) not in sys.path:
    sys.path.insert(0, str(_APP_ROOT))

from deployment.deployment import _STAGE_DEV, _run_stage  # noqa: E402


class DispatchError(ValueError):
    """Erro de validação/execução do dispatch manual (mapeado para 4xx/5xx)."""


def _provider_name_for_repo(repo: str) -> str:
    """Descobre o issue_provider da squad que contém o repo dado.

    Faz best-effort: casa pelo sufixo ``repo`` ou pelo projeto completo.
    Cai em ``github`` quando nenhuma squad casa (provider_for degrada bem).
    """
    for squad in load_squads():
        for project in squad.projects:
            if project == repo or project.split("/")[-1] == repo.split("/")[-1]:
                return squad.issue_provider
    return "github"


def ensure_todo(repo: str, number: int) -> None:
    """Marca a issue como ``crewflow:todo`` se ainda não estiver nesse estado.

    Lê as labels atuais via provider, e só persiste se o estado divergir —
    idempotente e sem escrita desnecessária.
    """
    provider = provider_for(_provider_name_for_repo(repo))
    item = provider.get_work_item(repo, str(number))
    labels = frozenset(item.get("labels") or [])
    if parse_state(labels) is State.TODO:
        return
    new_labels = transition_state(labels, State.TODO)
    provider.set_labels(repo, str(number), sorted(new_labels))


def run_dev_stage() -> None:
    """Dispara o estágio dev pelo caminho do cron, reusando BackendCronCtx.

    Import local de BackendCronCtx para manter o ctx acoplado ao ponto de uso
    e evitar qualquer ciclo de import na carga do módulo pelo gateway.
    """
    from backend.ctx import BackendCronCtx

    ctx = BackendCronCtx()
    _run_stage(ctx, _STAGE_DEV)


def validate_body(body: object) -> tuple[str, int]:
    """Valida o corpo do POST /dispatch e retorna (repo, number).

    Levanta ``DispatchError`` com mensagem clara se ``repo`` ou ``number``
    estiverem ausentes/ inválidos.
    """
    if not isinstance(body, dict):
        raise DispatchError("corpo deve ser um objeto JSON com 'repo' e 'number'")
    repo = body.get("repo")
    number = body.get("number")
    if not isinstance(repo, str) or not repo.strip():
        raise DispatchError("campo 'repo' ausente ou inválido (esperado 'owner/repo')")
    try:
        number_int = int(number)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise DispatchError("campo 'number' ausente ou inválido (esperado inteiro)") from exc
    if number_int <= 0:
        raise DispatchError("campo 'number' deve ser um inteiro positivo")
    return repo.strip(), number_int
