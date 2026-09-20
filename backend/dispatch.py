"""Orquestração da rota POST /dispatch — force dispatch manual de uma issue.

Marca a issue em ``crewflow:todo`` (se ainda não estiver) e dispara o estágio
dev pelo MESMO caminho do cron (``deployment.deployment._run_stage`` com
``_STAGE_DEV``), reusando ``BackendCronCtx``. Como ``_run_stage`` é síncrono e
faz I/O bloqueante, o handler o roda em executor — igual ao
``backend.server._run_stage_loop``.

Consome ``flow/`` e ``deployment/`` apenas por import; nenhuma modificação no
motor. O acesso ao provider é mockável (patch de ``provider_for`` ou do
transport) para que os testes nunca toquem a rede.

## Honestidade do ``dispatched`` (review iteração 2, issues #1 e #3)

O motor (``deployment/``) é INTOCÁVEL, então ``_run_stage`` não recebe o
``repo``/``number`` do request: ele carrega a SUA PRÓPRIA config
(``deployment.config.yaml``), varre os repos configurados lá e só despacha de
fato quando ``auto_dispatch`` é ``true`` (o default documentado é ``false`` —
"só avisa até você confiar"). Portanto NÃO dá para afirmar às cegas que a issue
pedida foi despachada.

Para não mentir ao chamador, ``run_dev_stage(repo)`` inspeciona a config do
deployment ANTES de rodar a varredura e classifica o resultado:

  - ``DISPATCHED``            — auto_dispatch=true E o repo está na config do
                               deployment: a varredura dev roda de fato pelo
                               caminho do cron; este é o caso de sucesso genuíno
                               que devolve ``{"ok": true, "dispatched": true}``.
  - ``AUTO_DISPATCH_OFF``     — auto_dispatch=false: a varredura roda mas só
                               AVISA; nada é despachado.
  - ``REPO_NOT_CONFIGURED``   — o repo do request não está em ``repos`` da
                               config do deployment; a issue marcada nunca será
                               varrida por este cron (divergência de config,
                               issue #3).
  - ``NO_CONFIG``             — o deployment não tem config; nada roda.

Em todos os casos a label ``crewflow:todo`` já foi aplicada por ``ensure_todo``,
então o próximo tick do cron pega a issue SE o repo estiver configurado. O campo
``dispatched`` só é ``true`` quando a varredura dev efetivamente disparou.
"""
from __future__ import annotations

import logging
import sys
from enum import StrEnum
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

from deployment.deployment import (  # noqa: E402
    _STAGE_DEV,
    _load_config,
    _run_stage,
)

logger = logging.getLogger(__name__)


class DispatchError(ValueError):
    """Erro de validação/execução do dispatch manual (mapeado para 4xx/5xx)."""


class DispatchOutcome(StrEnum):
    """Resultado honesto da varredura dev disparada por /dispatch.

    Só ``DISPATCHED`` representa disparo genuíno; os demais explicam por que
    nada foi despachado apesar de a label ``crewflow:todo`` ter sido aplicada.
    """

    DISPATCHED = "dispatched"
    AUTO_DISPATCH_OFF = "auto_dispatch_disabled"
    REPO_NOT_CONFIGURED = "repo_not_configured"
    NO_CONFIG = "no_config"


# Mensagens legíveis por resultado (expostas no campo ``detail`` da resposta).
_OUTCOME_DETAIL: dict[DispatchOutcome, str] = {
    DispatchOutcome.DISPATCHED: (
        "issue marcada crewflow:todo e varredura dev disparada pelo caminho do cron"
    ),
    DispatchOutcome.AUTO_DISPATCH_OFF: (
        "issue marcada crewflow:todo; a varredura dev rodou em modo aviso "
        "(auto_dispatch=false), então nada foi despachado — habilite auto_dispatch "
        "na config do deployment para o dispatch automático"
    ),
    DispatchOutcome.REPO_NOT_CONFIGURED: (
        "issue marcada crewflow:todo, mas o repo não está em 'repos' da config do "
        "deployment; o cron dev não varre este repo — adicione-o à config para que "
        "a issue seja despachada"
    ),
    DispatchOutcome.NO_CONFIG: (
        "issue marcada crewflow:todo, mas a config do deployment não foi encontrada; "
        "o cron dev não pôde rodar"
    ),
}


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


def _repo_configured_in_deployment(repo: str, cfg: dict) -> bool:
    """True se o repo do request está na lista ``repos`` da config do deployment.

    Casa pelo nome completo ``owner/repo`` ou pelo sufixo ``repo`` — mesma
    tolerância de ``_provider_name_for_repo`` — porque a config pode listar o
    repo em qualquer das duas formas.
    """
    repos = cfg.get("repos") or []
    short = repo.split("/")[-1]
    return any(r == repo or r.split("/")[-1] == short for r in repos)


def run_dev_stage(repo: str) -> DispatchOutcome:
    """Dispara o estágio dev pelo caminho do cron e reporta o resultado real.

    Reusa ``BackendCronCtx`` e ``_run_stage(ctx, _STAGE_DEV)`` — o MESMO caminho
    do cron. Antes de rodar, inspeciona a config do deployment para classificar
    honestamente o resultado (ver docstring do módulo); ``_run_stage`` roda em
    todos os casos com config presente para manter o caminho idêntico ao cron,
    mas o ``DispatchOutcome`` reflete se algo foi de fato despachado.

    Import local de ``BackendCronCtx`` para manter o ctx acoplado ao ponto de
    uso e evitar qualquer ciclo de import na carga do módulo pelo gateway.

    Args:
        repo: ``owner/repo`` do request — usado só para checar se está na config
              do deployment; ``_run_stage`` varre por conta própria.

    Returns:
        O ``DispatchOutcome`` que descreve o que realmente aconteceu.
    """
    from backend.ctx import BackendCronCtx

    try:
        cfg = _load_config()
    except RuntimeError:
        # Sem config o cron não roda; a label todo fica aplicada para depois.
        logger.warning(
            "dispatch: config do deployment ausente — varredura dev não executada"
        )
        return DispatchOutcome.NO_CONFIG

    if not _repo_configured_in_deployment(repo, cfg):
        logger.warning(
            "dispatch: repo %s não está na config do deployment — cron dev não o varre",
            repo,
        )
        return DispatchOutcome.REPO_NOT_CONFIGURED

    auto = bool(cfg.get("auto_dispatch", False))

    ctx = BackendCronCtx()
    _run_stage(ctx, _STAGE_DEV)

    if not auto:
        return DispatchOutcome.AUTO_DISPATCH_OFF
    return DispatchOutcome.DISPATCHED


def outcome_detail(outcome: DispatchOutcome) -> str:
    """Mensagem legível para o campo ``detail`` da resposta de /dispatch."""
    return _OUTCOME_DETAIL[outcome]


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
