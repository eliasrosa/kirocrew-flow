"""Testes de unidade para backend.dispatch (Fase 4 — POST /dispatch).

Exercitam o caminho REAL de force dispatch:
  - validate_body: validação de {"repo","number"}
  - ensure_todo: marca crewflow:todo só quando o estado diverge (idempotente)
  - run_dev_stage: dispara deployment._run_stage(ctx, _STAGE_DEV)

O provider e o ``_run_stage`` são mockados para que NADA toque a rede nem
dispare a esteira de verdade — mesmo estilo de flow/tests/test_adapter_github.py.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest import mock

import pytest

# Garante que o raiz do repo está no path para importar backend/
_REPO_ROOT = str(Path(__file__).parent.parent.parent)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from backend import dispatch as dispatch_mod  # noqa: E402
from backend.dispatch import DispatchError  # noqa: E402

# ---------------------------------------------------------------------------
# validate_body
# ---------------------------------------------------------------------------


class TestValidateBody:
    def test_valid_body_returns_repo_and_int(self) -> None:
        assert dispatch_mod.validate_body(
            {"repo": "owner/repo", "number": 42}
        ) == ("owner/repo", 42)

    def test_number_as_string_is_coerced(self) -> None:
        assert dispatch_mod.validate_body(
            {"repo": "owner/repo", "number": "42"}
        ) == ("owner/repo", 42)

    def test_repo_is_stripped(self) -> None:
        repo, _number = dispatch_mod.validate_body(
            {"repo": "  owner/repo  ", "number": 1}
        )
        assert repo == "owner/repo"

    def test_missing_repo_raises(self) -> None:
        with pytest.raises(DispatchError):
            dispatch_mod.validate_body({"number": 42})

    def test_missing_number_raises(self) -> None:
        with pytest.raises(DispatchError):
            dispatch_mod.validate_body({"repo": "owner/repo"})

    def test_non_dict_raises(self) -> None:
        with pytest.raises(DispatchError):
            dispatch_mod.validate_body(["not", "a", "dict"])

    def test_non_positive_number_raises(self) -> None:
        with pytest.raises(DispatchError):
            dispatch_mod.validate_body({"repo": "owner/repo", "number": 0})

    def test_non_numeric_number_raises(self) -> None:
        with pytest.raises(DispatchError):
            dispatch_mod.validate_body({"repo": "owner/repo", "number": "abc"})


# ---------------------------------------------------------------------------
# ensure_todo — só persiste quando o estado diverge
# ---------------------------------------------------------------------------


class _FakeProvider:
    """Provider fake: get_work_item devolve labels fixas; set_labels é espiado."""

    def __init__(self, labels: list[str]) -> None:
        self._labels = labels
        self.set_labels = mock.MagicMock()

    def get_work_item(self, project: str, key: str) -> dict:
        return {"labels": list(self._labels)}


_STATE_LABELS = frozenset(
    {
        "crewflow:spec",
        "crewflow:ready",
        "crewflow:todo",
        "crewflow:dev",
        "crewflow:review",
        "crewflow:qa",
        "crewflow:done",
    }
)


class TestEnsureTodo:
    def test_transitions_to_todo_when_in_other_state(self) -> None:
        provider = _FakeProvider(["crewflow:dev", "crewflow:bug", "phase-1"])
        with mock.patch.object(
            dispatch_mod, "provider_for", return_value=provider
        ), mock.patch.object(
            dispatch_mod, "load_squads", return_value=[]
        ):
            dispatch_mod.ensure_todo("owner/repo", 42)

        provider.set_labels.assert_called_once()
        args = provider.set_labels.call_args[0]
        assert args[0] == "owner/repo"
        assert args[1] == "42"
        new_labels = set(args[2])
        # Exatamente um label de estado, e ele é crewflow:todo.
        state_labels = new_labels & _STATE_LABELS
        assert state_labels == {"crewflow:todo"}
        # Modificadores/labels externos preservados.
        assert "crewflow:bug" in new_labels
        assert "phase-1" in new_labels

    def test_no_write_when_already_todo(self) -> None:
        provider = _FakeProvider(["crewflow:todo", "phase-1"])
        with mock.patch.object(
            dispatch_mod, "provider_for", return_value=provider
        ), mock.patch.object(
            dispatch_mod, "load_squads", return_value=[]
        ):
            dispatch_mod.ensure_todo("owner/repo", 42)

        provider.set_labels.assert_not_called()

    def test_uses_provider_for_matching_squad(self) -> None:
        """_provider_name_for_repo consulta as squads para achar o provider."""
        provider = _FakeProvider(["crewflow:dev"])
        from flow.config.squad import SquadConfig

        squad = SquadConfig(
            id="s",
            name="S",
            issue_provider="github",
            projects=["owner/repo"],
            repos=frozenset({"repo"}),
            workflow_template="versao-c",
        )
        with mock.patch.object(
            dispatch_mod, "provider_for", return_value=provider
        ) as pf, mock.patch.object(
            dispatch_mod, "load_squads", return_value=[squad]
        ):
            dispatch_mod.ensure_todo("owner/repo", 42)
        pf.assert_called_once_with("github")


# ---------------------------------------------------------------------------
# run_dev_stage — dispara _run_stage(ctx, _STAGE_DEV)
# ---------------------------------------------------------------------------


class TestRunDevStage:
    def test_invokes_run_stage_with_dev_constant(self) -> None:
        with mock.patch.object(dispatch_mod, "_run_stage") as run_m:
            dispatch_mod.run_dev_stage()

        run_m.assert_called_once()
        args = run_m.call_args[0]
        # ctx é o primeiro argumento; o estágio é a constante _STAGE_DEV.
        assert args[1] == dispatch_mod._STAGE_DEV

    def test_ctx_is_backend_cron_ctx(self) -> None:
        from backend.ctx import BackendCronCtx

        with mock.patch.object(dispatch_mod, "_run_stage") as run_m:
            dispatch_mod.run_dev_stage()

        ctx = run_m.call_args[0][0]
        assert isinstance(ctx, BackendCronCtx)
