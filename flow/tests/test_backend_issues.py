"""Testes de unidade para backend.issues (Fase 4 — GET /issues por estágio).

Exercitam o caminho REAL de agrupamento em colunas (``collect_columns`` e o
helper ``_column_for``), com o provider e o ``age_min`` mockados para que
NADA toque a rede — mesmo estilo de mock de flow/tests/test_adapter_github.py
(interceptamos no provider/transport, nunca no HTTP).

Regras de coluna verificadas (fluxo.md):
  crewflow:todo                     -> todo
  crewflow:dev                      -> dev
  crewflow:review                   -> review
  crewflow:review + crewflow:reviewed -> reviewed
  crewflow:done                     -> done
  qualquer estado + crewflow:blocked -> blocked (blocked vence o estado)
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest import mock

# Garante que o raiz do repo está no path para importar backend/
_REPO_ROOT = str(Path(__file__).parent.parent.parent)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from backend import issues as issues_mod  # noqa: E402
from flow.config.squad import SquadConfig  # noqa: E402
from flow.domain.state import Modifier, State  # noqa: E402

_COLUMN_KEYS = ("todo", "dev", "review", "reviewed", "done", "blocked")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _item(number: int, labels: list[str], title: str = "[gw] Fix") -> dict:
    """Item normalizado como o adapter GitHub retorna (key=url)."""
    url = f"https://github.com/owner/repo/issues/{number}"
    return {"key": url, "title": title, "labels": labels, "url": url}


class _FakeProvider:
    """Provider fake que satisfaz a superfície usada por backend.issues.

    ``list_by_state`` retorna os itens cujo conjunto de labels contém a
    label de estado pedida — igual ao contrato do adapter real.
    """

    def __init__(self, items: list[dict]) -> None:
        self._items = items

    def list_by_state(self, project: str, state: str) -> list[dict]:
        return [it for it in self._items if state in it["labels"]]


def _fake_squad() -> SquadConfig:
    return SquadConfig(
        id="test-squad",
        name="Test Squad",
        issue_provider="github",
        projects=["owner/repo"],
        repos=frozenset({"repo", "owner/repo"}),
        workflow_template="versao-c",
    )


def _collect(items: list[dict], tmp_path: Path) -> dict[str, list[dict]]:
    """Roda collect_columns com provider fake e I/O totalmente mockado."""
    provider = _FakeProvider(items)
    with mock.patch.object(
        issues_mod, "load_squads", return_value=[_fake_squad()]
    ), mock.patch.object(
        issues_mod, "provider_for", return_value=provider
    ), mock.patch.object(
        issues_mod.scan_cache, "open_cache",
        return_value=__import__("sqlite3").connect(str(tmp_path / "cache.db")),
    ), mock.patch.object(
        issues_mod, "_age_min_from_gh", return_value=0
    ), mock.patch.object(
        issues_mod.scan_cache, "get_running_since", return_value=None
    ), mock.patch.object(
        issues_mod.scan_cache, "set_hash"
    ):
        return issues_mod.collect_columns()


# ---------------------------------------------------------------------------
# _column_for — lógica pura de mapeamento
# ---------------------------------------------------------------------------


class TestColumnFor:
    def test_todo(self) -> None:
        assert issues_mod._column_for(State.TODO, frozenset()) == "todo"

    def test_dev(self) -> None:
        assert issues_mod._column_for(State.DEV, frozenset()) == "dev"

    def test_review(self) -> None:
        assert issues_mod._column_for(State.REVIEW, frozenset()) == "review"

    def test_review_with_reviewed_goes_to_reviewed(self) -> None:
        assert (
            issues_mod._column_for(State.REVIEW, frozenset({Modifier.REVIEWED}))
            == "reviewed"
        )

    def test_done(self) -> None:
        assert issues_mod._column_for(State.DONE, frozenset()) == "done"

    def test_blocked_wins_over_state(self) -> None:
        assert (
            issues_mod._column_for(State.DEV, frozenset({Modifier.BLOCKED}))
            == "blocked"
        )

    def test_blocked_wins_even_in_review_reviewed(self) -> None:
        mods = frozenset({Modifier.REVIEWED, Modifier.BLOCKED})
        assert issues_mod._column_for(State.REVIEW, mods) == "blocked"

    def test_non_column_state_omitted(self) -> None:
        assert issues_mod._column_for(State.SPEC, frozenset()) is None
        assert issues_mod._column_for(None, frozenset()) is None


# ---------------------------------------------------------------------------
# collect_columns — caminho real de agrupamento
# ---------------------------------------------------------------------------


class TestCollectColumnsPlacement:
    def test_todo_item_goes_to_todo(self, tmp_path: Path) -> None:
        cols = _collect([_item(1, ["crewflow:todo"])], tmp_path)
        assert [c["number"] for c in cols["todo"]] == [1]

    def test_dev_item_goes_to_dev(self, tmp_path: Path) -> None:
        cols = _collect([_item(2, ["crewflow:dev"])], tmp_path)
        assert [c["number"] for c in cols["dev"]] == [2]

    def test_review_item_goes_to_review(self, tmp_path: Path) -> None:
        cols = _collect([_item(3, ["crewflow:review"])], tmp_path)
        assert [c["number"] for c in cols["review"]] == [3]

    def test_review_reviewed_goes_to_reviewed(self, tmp_path: Path) -> None:
        cols = _collect(
            [_item(4, ["crewflow:review", "crewflow:reviewed"])], tmp_path
        )
        assert [c["number"] for c in cols["reviewed"]] == [4]
        assert cols["review"] == []

    def test_done_item_goes_to_done(self, tmp_path: Path) -> None:
        cols = _collect([_item(5, ["crewflow:done"])], tmp_path)
        assert [c["number"] for c in cols["done"]] == [5]

    def test_blocked_wins_over_state(self, tmp_path: Path) -> None:
        cols = _collect(
            [_item(6, ["crewflow:dev", "crewflow:blocked"])], tmp_path
        )
        assert [c["number"] for c in cols["blocked"]] == [6]
        assert cols["dev"] == []

    def test_multiple_columns_populated(self, tmp_path: Path) -> None:
        items = [
            _item(1, ["crewflow:todo"]),
            _item(2, ["crewflow:dev"]),
            _item(3, ["crewflow:review"]),
            _item(4, ["crewflow:review", "crewflow:reviewed"]),
            _item(5, ["crewflow:done"]),
            _item(7, ["crewflow:todo", "crewflow:blocked"]),
        ]
        cols = _collect(items, tmp_path)
        assert [c["number"] for c in cols["todo"]] == [1]
        assert [c["number"] for c in cols["dev"]] == [2]
        assert [c["number"] for c in cols["review"]] == [3]
        assert [c["number"] for c in cols["reviewed"]] == [4]
        assert [c["number"] for c in cols["done"]] == [5]
        assert [c["number"] for c in cols["blocked"]] == [7]


class TestCollectColumnsCardShape:
    def test_card_has_expected_keys(self, tmp_path: Path) -> None:
        cols = _collect([_item(9, ["crewflow:dev"], title="[gw] X")], tmp_path)
        card = cols["dev"][0]
        assert set(card.keys()) == {"number", "title", "repo", "url", "age_min"}
        assert card["number"] == 9
        assert card["title"] == "[gw] X"
        assert card["repo"] == "owner/repo"
        assert card["url"] == "https://github.com/owner/repo/issues/9"

    def test_age_min_degrades_to_zero_without_network(self, tmp_path: Path) -> None:
        cols = _collect([_item(9, ["crewflow:dev"])], tmp_path)
        assert cols["dev"][0]["age_min"] == 0


class TestCollectColumnsEmpty:
    def test_no_squads_returns_empty_columns(self) -> None:
        with mock.patch.object(issues_mod, "load_squads", return_value=[]):
            cols = issues_mod.collect_columns()
        assert cols == {key: [] for key in _COLUMN_KEYS}

    def test_empty_columns_has_all_keys(self) -> None:
        assert set(issues_mod.empty_columns().keys()) == set(_COLUMN_KEYS)
