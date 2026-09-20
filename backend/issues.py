"""Orquestração da rota GET /issues — lista issues por estágio da esteira.

Consome o motor (``flow/``) apenas por import; nenhuma lógica de negócio vive
aqui além do agrupamento em colunas e da montagem dos cards para a UI.

Zero-token: a listagem por label é uma leitura barata; o cache SQLite do scan
(``flow.scan.cache``) é usado no mesmo estilo do scanner para que chamadas
repetidas não reprocessem issues cujas labels não mudaram.

O item normalizado do GitHub NÃO carrega timestamp (o transport pede apenas
number/title/labels/url). Como ``flow/`` é intocável, o ``age_min`` é obtido
aqui em ``backend/``: primeiro do ``running_since`` do cache, senão de uma
chamada leve ao ``gh`` (mockável). Quando NENHUMA fonte responde (cache frio e
gh indisponível/offline), o ``age_min`` é ``None`` — "idade desconhecida" — e a
UI mostra ``—`` em vez de fingir "0m" (review iteração 2, issue #4). ``0`` fica
reservado para o caso real de idade < 1 minuto.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from flow.config.squad import SquadConfig, load_squad, load_squads_dir
from flow.domain.state import Modifier, State, parse_modifiers, parse_state
from flow.ports.issue_provider import provider_for
from flow.scan import cache as scan_cache

# Chaves de coluna expostas pela API (ordem canônica da esteira + blocked).
#
# NOTA sobre crewflow:qa (review iteração 2, issue #2): o estado crewflow:qa é
# um estado de primeira classe em fluxo.md (deploy HML manual + QA testa), mas o
# board é DELIBERADAMENTE de "5 colunas de estágio (todo → dev → review →
# reviewed → done) + blocked", exatamente como a task especifica. QA fica FORA
# do board por spec: não tem coluna e não é listado em _LISTED_STATES abaixo,
# então uma issue em QA simplesmente não aparece no Kanban (é uma etapa manual
# de humano, não um estágio da esteira automatizada). Isto é intencional, não um
# esquecimento — adicionar uma coluna QA divergiria da spec da task.
_COLUMN_KEYS: tuple[str, ...] = ("todo", "dev", "review", "reviewed", "done", "blocked")

# Estados que listamos por provider.list_by_state — os que geram colunas.
# crewflow:qa é omitido de propósito (ver NOTA acima): não gera coluna, então
# não há razão de gastar uma chamada de listagem com ele.
_LISTED_STATES: tuple[State, ...] = (State.TODO, State.DEV, State.REVIEW, State.DONE)

_ENV_SQUAD_CONFIG = "CREWFLOW_SQUAD_CONFIG"


def empty_columns() -> dict[str, list[dict[str, Any]]]:
    """Estrutura de colunas vazia (fallback seguro, nunca 500)."""
    return {key: [] for key in _COLUMN_KEYS}


def _repo_root() -> Path:
    """Raiz do repo, idêntica ao APP_ROOT de backend/server.py."""
    return Path(__file__).parent.parent


def load_squads() -> list[SquadConfig]:
    """Descobre as squads configuradas.

    Ordem de resolução:
      1. Override via env ``CREWFLOW_SQUAD_CONFIG`` (caminho de um único YAML).
      2. Todos os ``squads/*.yaml`` do repo (``load_squads_dir`` já ignora
         ``example.yaml`` e arquivos iniciados por ``_``).

    Retorna lista vazia se nada for encontrado (nunca levanta para o HTTP).
    """
    override = os.environ.get(_ENV_SQUAD_CONFIG, "").strip()
    if override:
        return [load_squad(override)]
    squads_dir = _repo_root() / "squads"
    if not squads_dir.is_dir():
        return []
    return load_squads_dir(squads_dir)


def _parse_number(key: str) -> int:
    """Extrai o número da issue do key/url (mesma regex do deployment)."""
    m = re.search(r"[#\-/](\d+)$", key)
    return int(m.group(1)) if m else 0


def _parse_repo(url: str, fallback: str) -> str:
    """Deriva ``owner/repo`` da url, com fallback para o projeto da squad."""
    stripped = url.strip()
    for prefix in ("https://github.com/", "http://github.com/"):
        if stripped.startswith(prefix):
            stripped = stripped[len(prefix):]
            break
    else:
        return fallback
    stripped = re.sub(r"/issues/\d+.*$", "", stripped)
    parts = [p for p in stripped.split("/") if p]
    if len(parts) >= 2:
        return f"{parts[0]}/{parts[1]}"
    return fallback


def _column_for(state: State | None, modifiers: frozenset[Modifier]) -> str | None:
    """Mapeia (estado, modificadores) para a chave da coluna, ou None p/ omitir.

    Prioridade: blocked vence o estado (fluxo.md). REVIEW+REVIEWED → 'reviewed';
    REVIEW sem reviewed → 'review'. TODO/DEV/DONE mapeiam direto. Demais estados
    (spec/ready/qa) não têm coluna e são omitidos.
    """
    if Modifier.BLOCKED in modifiers:
        return "blocked"
    if state is State.REVIEW:
        return "reviewed" if Modifier.REVIEWED in modifiers else "review"
    if state is State.TODO:
        return "todo"
    if state is State.DEV:
        return "dev"
    if state is State.DONE:
        return "done"
    return None


def _age_min_from_gh(repo: str, number: int) -> int | None:
    """Calcula minutos desde a criação da issue via gh CLI (mockável).

    Vive em ``backend/`` (não em ``flow/``) para não tocar o motor. Retorna
    ``None`` em qualquer falha (gh ausente, offline, JSON inválido) — "idade
    desconhecida", nunca propaga erro nem bloqueia a listagem.
    """
    if not repo or number <= 0:
        return None
    try:
        result = subprocess.run(
            [
                "gh", "issue", "view", str(number),
                "--repo", repo,
                "--json", "createdAt",
            ],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (FileNotFoundError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    try:
        created_raw = json.loads(result.stdout).get("createdAt")
    except (json.JSONDecodeError, AttributeError):
        return None
    return _minutes_since_iso(created_raw)


def _minutes_since_iso(iso_ts: str | None) -> int | None:
    """Minutos decorridos desde um timestamp ISO-8601, ou ``None`` se inválido.

    Distingue "idade desconhecida" (``None``, timestamp ausente/ilegível) de
    "idade zero" (``0``, criado há menos de um minuto).
    """
    if not iso_ts:
        return None
    try:
        parsed = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    delta = datetime.now(UTC) - parsed
    return max(0, int(delta.total_seconds() // 60))


def _age_min(conn: object, key: str, repo: str, number: int) -> int | None:
    """Idade em minutos no estágio atual, ou ``None`` se desconhecida.

    Preferência: ``running_since`` do cache (zero-token). Se ausente, faz uma
    chamada leve ao ``gh`` pelo ``createdAt``. Retorna ``None`` quando nenhuma
    fonte responde — a UI mostra ``—`` em vez de "0m" (review issue #4).
    """
    running_since = scan_cache.get_running_since(conn, key)  # type: ignore[arg-type]
    if running_since:
        minutes = _minutes_since_iso(running_since)
        if minutes is not None:
            return minutes
    return _age_min_from_gh(repo, number)


def _card(item: dict[str, Any], project: str) -> dict[str, Any]:
    """Monta o card no formato exato esperado pela UI (age_min preenchido depois).

    ``age_min`` inicia como ``None`` (idade desconhecida) e é sobrescrito por
    ``_collect_squad`` quando alguma fonte de tempo responde.
    """
    key = str(item.get("key") or item.get("url") or "")
    url = str(item.get("url") or key)
    number = _parse_number(key)
    repo = _parse_repo(url, project)
    return {
        "number": number,
        "title": str(item.get("title") or ""),
        "repo": repo,
        "url": url,
        "age_min": None,
    }


def _collect_squad(
    squad: SquadConfig, columns: dict[str, list[dict[str, Any]]]
) -> None:
    """Coleta as issues de uma squad e as agrupa nas colunas (in-place)."""
    provider = provider_for(squad.issue_provider)
    conn = scan_cache.open_cache(squad.id)
    try:
        seen: set[str] = set()
        for project in squad.projects:
            for state in _LISTED_STATES:
                for item in provider.list_by_state(project, state.value):
                    key = str(item.get("key") or item.get("url") or "")
                    if not key or key in seen:
                        continue
                    seen.add(key)
                    labels = frozenset(item.get("labels") or [])
                    parsed_state = parse_state(labels)
                    modifiers = parse_modifiers(labels)
                    column = _column_for(parsed_state, modifiers)
                    if column is None:
                        continue
                    card = _card(item, project)
                    # Mantém o cache aquecido no mesmo estilo do scanner.
                    scan_cache.set_hash(
                        conn, key, scan_cache.compute_hash(list(labels))
                    )
                    card["age_min"] = _age_min(
                        conn, key, card["repo"], card["number"]
                    )
                    columns[column].append(card)
    finally:
        conn.close()


def collect_columns() -> dict[str, list[dict[str, Any]]]:
    """Constrói o dict de colunas para todas as squads configuradas.

    Nunca levanta por ausência de config: retorna colunas vazias. Erros de
    provider (ProviderError/ProviderSetupError) são tratados na camada HTTP.
    """
    columns = empty_columns()
    for squad in load_squads():
        _collect_squad(squad, columns)
    return columns
