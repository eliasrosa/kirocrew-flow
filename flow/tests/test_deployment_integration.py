"""Testes de integração do deployment.py.

Não testa o dispatch real (precisa do Kiro Crew rodando).
Testa a integração entre deployment → scan → domain.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path
from unittest import mock

# Adiciona o repo root ao path (como o deployment.py faz em produção)
_REPO_ROOT = str(Path(__file__).parent.parent.parent)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

import builtins  # noqa: E402
import tempfile  # noqa: E402

import pytest  # noqa: E402

from deployment.deployment import _load_config, _scan_result_to_issue, run  # noqa: E402

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _minimal_config(repos: list[str] | None = None, auto: bool = False) -> dict:
    return {
        "repos": repos or ["owner/repo"],
        "auto_dispatch": auto,
        "max_concurrent": 2,
        "one_per_repo": True,
        "notify_chat_id": "",
        "squad_id": "test",
        "issue_provider": "github",
        "dev_root": "/tmp/dev",
        "agent": "kirocrew",
    }


def _make_scan_result(key: str = "https://github.com/owner/repo/issues/42",
                      title: str = "[api-gateway2] Fix",
                      dispatch: bool = True,
                      spec_valid: bool | None = None) -> object:
    from flow.domain.gates import WorkItem
    from flow.domain.state import State
    from flow.scan.scanner import ScanResult

    return ScanResult(
        item=WorkItem(key=key, title=title, labels=frozenset(["crewflow:todo"])),
        current_state=State.TODO,
        modifiers=frozenset(),
        dispatch_candidate=dispatch,
        spec_valid=spec_valid,
        changed=True,
        reason="CANDIDATO A DISPATCH; labels mudaram" if dispatch else "estado: crewflow:dev",
    )


# ---------------------------------------------------------------------------
# _scan_result_to_issue
# ---------------------------------------------------------------------------

class TestScanResultToIssue:
    def test_extrai_numero_de_url_github(self) -> None:
        r = _make_scan_result("https://github.com/owner/repo/issues/42")
        issue = _scan_result_to_issue(r)
        assert issue["number"] == 42

    def test_extrai_numero_de_chave_jira(self) -> None:
        r = _make_scan_result("VGAT-123")
        issue = _scan_result_to_issue(r)
        assert issue["number"] == 123

    def test_title_preservado(self) -> None:
        r = _make_scan_result(title="[api-gw2] Fix urgente")
        issue = _scan_result_to_issue(r)
        assert issue["title"] == "[api-gw2] Fix urgente"


# ---------------------------------------------------------------------------
# _load_config — fallback sem PyYAML usa o parser compartilhado
# ---------------------------------------------------------------------------

class TestLoadConfigFallback:
    """A config do cron deve suportar o mesmo schema de routing que a squad."""

    def test_routing_multilinha_via_fallback(self, monkeypatch: pytest.MonkeyPatch) -> None:
        real_import = builtins.__import__

        def fake_import(name: str, *args: object, **kwargs: object) -> object:
            if name == "yaml":
                raise ImportError("PyYAML indisponível (forçado no teste)")
            return real_import(name, *args, **kwargs)  # type: ignore[arg-type]

        monkeypatch.setattr(builtins, "__import__", fake_import)

        cfg_text = (
            "repos:\n"
            "  - owner/repo\n"
            "auto_dispatch: false\n"
            "max_concurrent: 2\n"
            "routing:\n"
            "  - match:\n"
            "      labels:\n"
            "        - crewflow:debt\n"
            "    workflow: debt-flow\n"
            "  - default: feature-flow\n"
        )
        with tempfile.NamedTemporaryFile(suffix=".yaml", mode="w", delete=False) as f:
            f.write(cfg_text)
            tmp = f.name

        monkeypatch.setattr("deployment.deployment._CONFIG_CANDIDATES", [tmp])
        cfg = _load_config()

        assert cfg["repos"] == ["owner/repo"]
        assert cfg["auto_dispatch"] is False
        assert cfg["max_concurrent"] == 2
        # O routing multi-linha foi parseado com a MESMA estrutura do PyYAML.
        assert cfg["routing"][0] == {
            "match": {"labels": ["crewflow:debt"]},
            "workflow": "debt-flow",
        }
        assert cfg["routing"][-1] == {"default": "feature-flow"}


# ---------------------------------------------------------------------------
# run() — testes de integração com mocks no scan e no ctx
# ---------------------------------------------------------------------------

class TestRunIntegration:
    def _make_ctx(self) -> mock.MagicMock:
        ctx = mock.MagicMock()
        ctx._port = 5000
        ctx._secret = "secret"
        ctx.job.id = "test-job"
        return ctx

    def test_notifica_candidatos_em_fase_1(self) -> None:
        """Fase 1 (auto=false): avisa sem despachar."""
        ctx = self._make_ctx()
        results = [_make_scan_result()]

        with (
            mock.patch("deployment.deployment._load_config",
                       return_value=_minimal_config(auto=False)),
            mock.patch("deployment.deployment.scan_candidates",
                       return_value=results),
            mock.patch("deployment.deployment.open_cache") as mock_cache,
        ):
            mock_cache.return_value.__enter__ = mock.MagicMock(
                return_value=sqlite3.connect(":memory:"))
            mock_cache.return_value.__exit__ = mock.MagicMock(return_value=False)
            run(ctx)

        ctx.notify.assert_called_once()
        msg = ctx.notify.call_args[0][0]
        assert "Fase 1" in msg or "ready" in msg.lower()

    def test_notifica_spec_invalida(self) -> None:
        """Spec sem repo flagrada sem dispatch."""
        ctx = self._make_ctx()

        # Precisamos que spec_valid=False seja reconhecido corretamente
        # Ajustamos o mock para retornar o resultado correto
        from flow.domain.gates import WorkItem
        from flow.domain.state import State
        from flow.scan.scanner import ScanResult

        spec_result = ScanResult(
            item=WorkItem(key="VGAT-1", title="Fix sem repo",
                          labels=frozenset(["crewflow:spec"])),
            current_state=State.SPEC,
            modifiers=frozenset(),
            dispatch_candidate=False,
            spec_valid=False,
            changed=True,
            reason="SPEC SEM REPO",
        )

        with (
            mock.patch("deployment.deployment._load_config",
                       return_value=_minimal_config(auto=False)),
            mock.patch("deployment.deployment.scan_candidates",
                       return_value=[spec_result]),
            mock.patch("deployment.deployment.open_cache") as mock_cache,
        ):
            mock_cache.return_value.__enter__ = mock.MagicMock(
                return_value=sqlite3.connect(":memory:"))
            mock_cache.return_value.__exit__ = mock.MagicMock(return_value=False)
            run(ctx)

        ctx.notify.assert_called_once()
        msg = ctx.notify.call_args[0][0]
        assert "spec" in msg.lower() or "repo" in msg.lower()

    def test_sem_resultados_nao_notifica(self) -> None:
        """Sem candidatos: nenhuma notificação."""
        ctx = self._make_ctx()

        with (
            mock.patch("deployment.deployment._load_config",
                       return_value=_minimal_config()),
            mock.patch("deployment.deployment.scan_candidates",
                       return_value=[]),
            mock.patch("deployment.deployment.open_cache") as mock_cache,
        ):
            mock_cache.return_value.__enter__ = mock.MagicMock(
                return_value=sqlite3.connect(":memory:"))
            mock_cache.return_value.__exit__ = mock.MagicMock(return_value=False)
            run(ctx)

        ctx.notify.assert_not_called()

    def test_squad_config_inexistente_levanta_erro_early(self) -> None:
        """squad_config apontando para arquivo inexistente deve falhar imediatamente."""
        import pytest

        ctx = self._make_ctx()
        cfg = _minimal_config()
        cfg["squad_config"] = "/tmp/nao-existe-squad-xyz.yaml"

        with (
            mock.patch("deployment.deployment._load_config", return_value=cfg),
            pytest.raises(RuntimeError, match="squad_config"),
        ):
            run(ctx)

        ctx.notify.assert_not_called()


# ---------------------------------------------------------------------------
# Teste de integração do merge automático (GATE 2)
# ---------------------------------------------------------------------------

class TestAutoMergeIntegration:
    def _make_ctx(self) -> mock.MagicMock:
        ctx = mock.MagicMock()
        ctx._port = 5000
        ctx._secret = "secret"
        ctx.job.id = "test-job"
        return ctx

    def _make_review_scan_result(self) -> object:
        """ScanResult em crewflow:review com crewflow:reviewed."""
        from flow.audit.state_comment import StateComment, render
        from flow.domain.gates import WorkItem
        from flow.domain.state import Modifier, State
        from flow.scan.scanner import ScanResult

        sc = StateComment(
            workflow="feature (v1)", current_node="review",
            status="reviewed", repo="owner/repo",
        )
        sc.set_reviewer_result(approved=True, comments=[], sha="abc123")
        state_body = render(sc)

        return ScanResult(
            item=WorkItem(
                key="https://github.com/owner/repo/issues/42",
                title="[owner/repo] Feature X",
                labels=frozenset(["crewflow:review", "crewflow:reviewed", "crewflow:feature"]),
            ),
            current_state=State.REVIEW,
            modifiers=frozenset([Modifier.REVIEWED]),
            dispatch_candidate=False,
            spec_valid=None,
            changed=True,
            reason="reviewer aprovado",
        ), state_body

    def test_merge_automatico_notifica_tl(self) -> None:
        """Quando reviewer aprova sem comentários, notifica TL com sucesso."""
        from flow.audit.state_comment import StateComment, render
        from flow.domain.gates import WorkItem
        from flow.domain.state import Modifier, State
        from flow.scan.scanner import ScanResult

        ctx = self._make_ctx()

        sc = StateComment(
            workflow="feature (v1)", current_node="review",
            status="reviewed", repo="owner/repo",
        )
        sc.set_reviewer_result(approved=True, comments=[], sha="abc123")
        state_body = render(sc)

        result = ScanResult(
            item=WorkItem(
                key="https://github.com/owner/repo/issues/42",
                title="[owner/repo] Feature X",
                labels=frozenset(["crewflow:review", "crewflow:reviewed", "crewflow:feature"]),
            ),
            current_state=State.REVIEW,
            modifiers=frozenset([Modifier.REVIEWED]),
            dispatch_candidate=False,
            spec_valid=None,
            changed=True,
            reason="reviewer aprovado",
        )

        # Simula get_state_comment retornando o state_body com resultado do reviewer
        def _fake_get_state_comment(repo: str, key: str) -> str:
            return state_body

        fake_pr = {"number": 99, "title": "feat: Feature X", "headRefName": "feat/issue-42", "headRefOid": "abc123", "body": "Closes #42"}

        with (
            mock.patch("deployment.deployment._load_config",
                       return_value={**_minimal_config(auto=True), "workflow_params": {"auto_merge_on_approve": True}}),
            mock.patch("deployment.deployment.scan_candidates",
                       return_value=[result]),
            mock.patch("deployment.deployment.open_cache") as mock_cache,
            mock.patch("deployment.deployment.provider_for") as mock_provider_for,
            mock.patch("flow.adapters.github_client.get_pr_for_issue",
                       return_value=fake_pr),
            mock.patch("flow.adapters.github_client.merge_pull_request",
                       return_value={"merged": True}),
            mock.patch("flow.adapters.github_client.get_work_item",
                       return_value={"labels": ["crewflow:review", "crewflow:reviewed", "crewflow:feature"]}),
            mock.patch("flow.adapters.github_client.set_labels"),
            mock.patch("flow.adapters.github_client.upsert_pr_review_comment"),
            mock.patch("flow.adapters.github_client.get_state_comment", return_value=state_body),
            mock.patch("flow.adapters.github_client.upsert_state_comment"),
        ):
            mock_cache.return_value.__enter__ = mock.MagicMock(
                return_value=sqlite3.connect(":memory:"))
            mock_cache.return_value.__exit__ = mock.MagicMock(return_value=False)
            mock_provider = mock.MagicMock()
            mock_provider.get_state_comment = _fake_get_state_comment
            mock_provider.get_pr_for_issue = mock.MagicMock(return_value=fake_pr)
            mock_provider_for.return_value = mock_provider

            run(ctx)

        # Deve notificar sobre o merge automático
        notify_calls = ctx.notify.call_args_list
        msgs = [str(c) for c in notify_calls]
        assert any("mergead" in m.lower() or "automati" in m.lower() for m in msgs), (
            f"Esperava notificação de merge automático, got: {msgs}"
        )


# ---------------------------------------------------------------------------
# Fix 1 — _repo_has_active / _active_sessions com detecção de locks obsoletos
# ---------------------------------------------------------------------------

class TestRepoHasActiveStaleDetection:
    """_repo_has_active deve ignorar locks mais velhos que 2h."""

    def test_lock_recente_bloqueia(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from deployment.deployment import _repo_has_active

        lock = tmp_path / "dashboard_esteira-myrepo-42.jsonl.lock"
        lock.touch()
        # mtime agora = lock recente
        monkeypatch.setattr("deployment.deployment._sessdir", lambda: str(tmp_path))

        assert _repo_has_active("owner/myrepo") is True

    def test_lock_obsoleto_nao_bloqueia(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        import os
        import time

        from deployment.deployment import _repo_has_active

        lock = tmp_path / "dashboard_esteira-myrepo-10.jsonl.lock"
        lock.touch()
        # Define mtime como 3h atrás
        old_ts = time.time() - 3 * 3600
        os.utime(str(lock), (old_ts, old_ts))

        monkeypatch.setattr("deployment.deployment._sessdir", lambda: str(tmp_path))

        assert _repo_has_active("owner/myrepo") is False

    def test_sem_locks_retorna_false(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from deployment.deployment import _repo_has_active

        monkeypatch.setattr("deployment.deployment._sessdir", lambda: str(tmp_path))
        assert _repo_has_active("owner/myrepo") is False

    def test_active_sessions_ignora_locks_obsoletos(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import os
        import time

        from deployment.deployment import _active_sessions

        # 1 lock recente + 1 obsoleto
        recente = tmp_path / "dashboard_esteira-repo1-1.jsonl.lock"
        recente.touch()
        obsoleto = tmp_path / "dashboard_esteira-repo2-2.jsonl.lock"
        obsoleto.touch()
        old_ts = time.time() - 3 * 3600
        os.utime(str(obsoleto), (old_ts, old_ts))

        monkeypatch.setattr("deployment.deployment._sessdir", lambda: str(tmp_path))

        assert _active_sessions() == 1


# ---------------------------------------------------------------------------
# Fix 2 — _pr_exists / guard contra PR duplicado no dispatch
# ---------------------------------------------------------------------------

class TestPrExists:
    """_pr_exists deve chamar gh pr list e retornar True somente quando há PR aberto."""

    def test_retorna_true_quando_pr_existe(self) -> None:
        from deployment.deployment import _pr_exists

        with mock.patch("subprocess.run") as mock_run:
            mock_run.return_value = mock.MagicMock(
                returncode=0,
                stdout='[{"number": 99}]',
                stderr="",
            )
            assert _pr_exists("owner/repo", 42) is True
        mock_run.assert_called_once()
        args = mock_run.call_args[0][0]
        assert "--head" in args
        assert "feat/issue-42" in args

    def test_retorna_false_quando_sem_pr(self) -> None:
        from deployment.deployment import _pr_exists

        with mock.patch("subprocess.run") as mock_run:
            mock_run.return_value = mock.MagicMock(
                returncode=0, stdout="[]", stderr="",
            )
            assert _pr_exists("owner/repo", 42) is False

    def test_retorna_false_em_erro_de_cli(self) -> None:
        from deployment.deployment import _pr_exists

        with mock.patch("subprocess.run") as mock_run:
            mock_run.return_value = mock.MagicMock(
                returncode=1, stdout="", stderr="gh: not authenticated",
            )
            assert _pr_exists("owner/repo", 42) is False

    def test_retorna_false_em_excecao(self) -> None:
        from deployment.deployment import _pr_exists

        with mock.patch("subprocess.run", side_effect=OSError("gh not found")):
            assert _pr_exists("owner/repo", 42) is False


class TestDispatchGuardPrDuplicado:
    """O dispatch deve ser ignorado silenciosamente quando PR já existe."""

    def _make_ctx(self) -> mock.MagicMock:
        ctx = mock.MagicMock()
        ctx._port = 5000
        ctx._secret = "secret"
        ctx.job.id = "test-job"
        return ctx

    def test_dispatch_pulado_quando_pr_ja_existe(self) -> None:
        ctx = self._make_ctx()
        results = [_make_scan_result()]

        with (
            mock.patch("deployment.deployment._load_config",
                       return_value={
                           **{
                               "repos": ["owner/repo"],
                               "auto_dispatch": True,
                               "max_concurrent": 2,
                               "one_per_repo": False,  # desativa o guard de lock
                               "notify_chat_id": "",
                               "squad_id": "test",
                               "issue_provider": "github",
                               "dev_root": "/tmp/dev",
                               "agent": "kirocrew",
                           }
                       }),
            mock.patch("deployment.deployment.scan_candidates", return_value=results),
            mock.patch("deployment.deployment.open_cache") as mock_cache,
            mock.patch("deployment.deployment._active_sessions", return_value=0),
            mock.patch("deployment.deployment._pr_exists", return_value=True),
            mock.patch("deployment.deployment._dispatch") as mock_disp,
        ):
            mock_cache.return_value.__enter__ = mock.MagicMock(
                return_value=sqlite3.connect(":memory:"))
            mock_cache.return_value.__exit__ = mock.MagicMock(return_value=False)
            run(ctx)

        mock_disp.assert_not_called()

    def test_dispatch_executado_quando_sem_pr(self) -> None:
        ctx = self._make_ctx()
        results = [_make_scan_result()]

        with (
            mock.patch("deployment.deployment._load_config",
                       return_value={
                           "repos": ["owner/repo"],
                           "auto_dispatch": True,
                           "max_concurrent": 2,
                           "one_per_repo": False,
                           "notify_chat_id": "",
                           "squad_id": "test",
                           "issue_provider": "github",
                           "dev_root": "/tmp/dev",
                           "agent": "kirocrew",
                       }),
            mock.patch("deployment.deployment.scan_candidates", return_value=results),
            mock.patch("deployment.deployment.open_cache") as mock_cache,
            mock.patch("deployment.deployment._active_sessions", return_value=0),
            mock.patch("deployment.deployment._pr_exists", return_value=False),
            mock.patch("deployment.deployment._dispatch") as mock_disp,
        ):
            mock_cache.return_value.__enter__ = mock.MagicMock(
                return_value=sqlite3.connect(":memory:"))
            mock_cache.return_value.__exit__ = mock.MagicMock(return_value=False)
            run(ctx)

        mock_disp.assert_called_once()


# ---------------------------------------------------------------------------
# Issue #70 — dispatch automático da sessão one-shot do reviewer
# ---------------------------------------------------------------------------

class TestReviewerHasActive:
    """_reviewer_has_active detecta sessão ativa do kiro-reviewer."""

    def test_lock_recente_bloqueia(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from deployment.deployment import _reviewer_has_active

        lock = tmp_path / "dashboard_reviewer-myrepo-42.jsonl.lock"
        lock.touch()
        monkeypatch.setattr("deployment.deployment._sessdir", lambda: str(tmp_path))

        assert _reviewer_has_active("owner/myrepo", 42) is True

    def test_lock_obsoleto_nao_bloqueia(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        import os
        import time

        from deployment.deployment import _reviewer_has_active

        lock = tmp_path / "dashboard_reviewer-myrepo-42.jsonl.lock"
        lock.touch()
        old_ts = time.time() - 3 * 3600
        os.utime(str(lock), (old_ts, old_ts))
        monkeypatch.setattr("deployment.deployment._sessdir", lambda: str(tmp_path))

        assert _reviewer_has_active("owner/myrepo", 42) is False

    def test_sem_lock_retorna_false(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from deployment.deployment import _reviewer_has_active

        monkeypatch.setattr("deployment.deployment._sessdir", lambda: str(tmp_path))
        assert _reviewer_has_active("owner/myrepo", 42) is False

    def test_nao_confunde_com_lock_de_outro_repo(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from deployment.deployment import _reviewer_has_active

        # Lock do repo A não afeta repo B
        lock = tmp_path / "dashboard_reviewer-repo-a-42.jsonl.lock"
        lock.touch()
        monkeypatch.setattr("deployment.deployment._sessdir", lambda: str(tmp_path))

        assert _reviewer_has_active("owner/repo-b", 42) is False

    def test_nao_confunde_com_lock_de_outro_issue(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from deployment.deployment import _reviewer_has_active

        lock = tmp_path / "dashboard_reviewer-myrepo-100.jsonl.lock"
        lock.touch()
        monkeypatch.setattr("deployment.deployment._sessdir", lambda: str(tmp_path))

        assert _reviewer_has_active("owner/myrepo", 99) is False


class TestReviewerPrompt:
    """_reviewer_prompt gera o prompt correto para a sessão one-shot do reviewer."""

    def test_contem_header_com_repo_pr_issue(self) -> None:
        from deployment.deployment import _reviewer_prompt

        prompt = _reviewer_prompt("owner/myrepo", pr_number=99, issue_number=42)

        assert "REPO: owner/myrepo" in prompt
        assert "PR: #99" in prompt
        assert "ISSUE: #42" in prompt

    def test_titulo_da_sessao(self) -> None:
        from deployment.deployment import _reviewer_prompt

        prompt = _reviewer_prompt("owner/myrepo", pr_number=99, issue_number=42)

        assert "SESSION TITLE: review: myrepo PR #99 (issue #42)" in prompt

    def test_contem_instrucao_de_gh_issue_view(self) -> None:
        from deployment.deployment import _reviewer_prompt

        prompt = _reviewer_prompt("owner/myrepo", pr_number=99, issue_number=42)

        assert "gh issue view 42 --repo owner/myrepo" in prompt

    def test_contem_instrucao_de_gh_pr_diff(self) -> None:
        from deployment.deployment import _reviewer_prompt

        prompt = _reviewer_prompt("owner/myrepo", pr_number=99, issue_number=42)

        assert "gh pr diff 99 --repo owner/myrepo" in prompt

    def test_contem_instrucao_de_crewflow_reviewed(self) -> None:
        from deployment.deployment import _reviewer_prompt

        prompt = _reviewer_prompt("owner/myrepo", pr_number=99, issue_number=42)

        assert "crewflow:reviewed" in prompt

    def test_contem_regra_nunca_merge(self) -> None:
        from deployment.deployment import _reviewer_prompt

        prompt = _reviewer_prompt("owner/myrepo", pr_number=99, issue_number=42)

        assert "NUNCA mergeie" in prompt

    def test_short_name_no_titulo(self) -> None:
        """O título usa só o nome curto do repo, não o owner/repo completo."""
        from deployment.deployment import _reviewer_prompt

        prompt = _reviewer_prompt("eliasrosa/kirocrew-flow", pr_number=5, issue_number=70)

        assert "SESSION TITLE: review: kirocrew-flow PR #5 (issue #70)" in prompt

    def test_instrui_postar_no_pr_via_gh_pr_comment(self) -> None:
        """O prompt manda postar o resultado NO PR (passo 7) e NA ISSUE (passo 8).

        Com a issue #88 o resultado completo vai nos dois lugares.
        """
        from deployment.deployment import _reviewer_prompt

        prompt = _reviewer_prompt("owner/myrepo", pr_number=99, issue_number=42)

        # Passo 7: postar no PR (instrução de postar o review completo)
        assert "POSTE O RESULTADO COMPLETO DO REVIEW NO PR" in prompt
        # Passo 8: postar na issue também via gh issue comment
        assert "gh issue comment 42 --repo owner/myrepo" in prompt

    def test_contem_formato_kirocrew_review(self) -> None:
        """O prompt referencia o formato KiroCrew Review do comentário do PR."""
        from deployment.deployment import _reviewer_prompt

        prompt = _reviewer_prompt("owner/myrepo", pr_number=99, issue_number=42)

        assert "## 🤖 KiroCrew Review" in prompt
        assert "**Resultado:**" in prompt
        assert "✅ Aprovado" in prompt
        assert "⚠️ Pedidos de mudança" in prompt
        assert "*Reviewer automático — issue #42*" in prompt

    def test_resultado_completo_na_issue_em_vez_de_referencia_curta(self) -> None:
        """Com a issue #88: resultado completo na issue, não só referência curta.

        O reviewer posta o mesmo comentário nos dois lugares (PR e issue),
        em vez de postar só "Review postado em PR #X — status".
        """
        from deployment.deployment import _reviewer_prompt

        prompt = _reviewer_prompt("owner/myrepo", pr_number=99, issue_number=42)

        # Resultado completo na issue (passo 8)
        assert "POSTE O RESULTADO COMPLETO DO REVIEW NA ISSUE" in prompt
        assert "gh issue comment" in prompt
        # A referência curta já não é o comportamento esperado
        assert "Review postado em PR #99" not in prompt

    def test_preserva_state_comment_na_issue(self) -> None:
        """O prompt continua instruindo o upsert do ReviewerResult NA ISSUE."""
        from deployment.deployment import _reviewer_prompt

        prompt = _reviewer_prompt("owner/myrepo", pr_number=99, issue_number=42)

        assert "upsert_state_comment" in prompt
        assert "<!-- KIRO-FLOW-STATE -->" in prompt
        assert "ReviewerResult" in prompt

    def test_regressao_todos_substrings_antigos(self) -> None:
        """Guard de regressão: todos os substrings previamente asseridos seguem presentes."""
        from deployment.deployment import _reviewer_prompt

        prompt = _reviewer_prompt("owner/myrepo", pr_number=99, issue_number=42)

        assert "REPO: owner/myrepo" in prompt
        assert "PR: #99" in prompt
        assert "ISSUE: #42" in prompt
        assert "SESSION TITLE: review: myrepo PR #99 (issue #42)" in prompt
        assert "gh issue view 42 --repo owner/myrepo" in prompt
        assert "gh pr diff 99 --repo owner/myrepo" in prompt
        assert "crewflow:reviewed" in prompt
        assert "NUNCA mergeie" in prompt

    def test_exemplar_do_pr_derivado_do_helper(self) -> None:
        """Fonte única de verdade: o exemplar do comentário do PR no prompt é
        PRODUZIDO por render_pr_review_comment (cada linha do helper aparece no
        prompt, apenas indentada). Se o helper e o prompt divergirem, quebra.
        """
        from deployment.deployment import _reviewer_prompt
        from flow.audit.state_comment import ReviewerResult, render_pr_review_comment

        prompt = _reviewer_prompt("owner/myrepo", pr_number=99, issue_number=42)

        _rr_ko = ReviewerResult(
            approved=False,
            comments=("<mudança 1>", "<mudança 2>"),
            sha="<sha>",
            reviewer="kiro-reviewer",
        )
        exemplo_mudancas = render_pr_review_comment(_rr_ko, issue_number=42)
        for line in exemplo_mudancas.splitlines():
            assert (f"     {line}" if line else line) in prompt

        _rr_ok = ReviewerResult(approved=True, comments=(), sha="<sha>", reviewer="kiro-reviewer")
        exemplo_aprovado = render_pr_review_comment(_rr_ok, issue_number=42)
        for line in exemplo_aprovado.splitlines():
            assert (f"     {line}" if line else line) in prompt

    def test_resultado_completo_postado_nos_dois_lugares(self) -> None:
        """O prompt instrui a postar resultado completo TANTO no PR quanto na issue.

        Com a issue #88, o reviewer posta o resultado completo em dois lugares —
        PR e issue — em vez de só uma referência curta.
        """
        from deployment.deployment import _reviewer_prompt

        prompt = _reviewer_prompt("owner/myrepo", pr_number=99, issue_number=42)

        # Passo 7: postar no PR
        assert "POSTE O RESULTADO COMPLETO DO REVIEW NO PR" in prompt
        # Passo 8: postar na issue também (completo)
        assert "POSTE O RESULTADO COMPLETO DO REVIEW NA ISSUE" in prompt
        assert "gh issue comment" in prompt
        assert "mesmo corpo completo" in prompt.lower() or "mesmo corpo" in prompt


class TestDispatchReviewerFunction:
    """_dispatch_reviewer faz POST /api/chat com o slot e prompt corretos."""

    def _make_ctx(self) -> mock.MagicMock:
        ctx = mock.MagicMock()
        ctx._port = 5000
        ctx._secret = "secret"
        ctx.job.id = "test-job"
        return ctx

    def _minimal_cfg(self) -> dict:
        return {
            "agent": "kirocrew",
            "notify_chat_id": "",
        }

    def test_busca_pr_pela_branch_correta(self) -> None:
        """_dispatch_reviewer consulta a branch feat/issue-<N> para localizar o PR."""
        from deployment.deployment import _dispatch_reviewer

        ctx = self._make_ctx()
        issue = {"number": 42, "title": "feat: algo"}

        with (
            mock.patch("subprocess.run") as mock_run,
        ):
            mock_run.return_value = mock.MagicMock(
                returncode=0,
                stdout="[]",  # sem PR — só testamos que consultou a branch certa
                stderr="",
            )
            _dispatch_reviewer(ctx, "owner/repo", issue, self._minimal_cfg())

        # Verifica que consultou gh pr list com --head feat/issue-42
        mock_run.assert_called_once()
        args = mock_run.call_args[0][0]
        assert "--head" in args
        assert "feat/issue-42" in args
        assert "--repo" in args
        assert "owner/repo" in args

    def test_fallback_notifica_quando_pr_nao_encontrado(self) -> None:
        from deployment.deployment import _dispatch_reviewer

        ctx = self._make_ctx()
        issue = {"number": 42, "title": "feat: algo"}

        with mock.patch("subprocess.run") as mock_run:
            mock_run.return_value = mock.MagicMock(
                returncode=0,
                stdout="[]",  # sem PR
                stderr="",
            )
            _dispatch_reviewer(ctx, "owner/repo", issue, self._minimal_cfg())

        # Deve notificar que PR não foi encontrado
        ctx.notify.assert_called_once()
        msg = ctx.notify.call_args[0][0]
        assert "não localizado" in msg or "pendente" in msg or "PR" in msg

    def test_fallback_notifica_quando_cli_falha(self) -> None:
        from deployment.deployment import _dispatch_reviewer

        ctx = self._make_ctx()
        issue = {"number": 42, "title": "feat: algo"}

        with mock.patch("subprocess.run", side_effect=OSError("gh not found")):
            _dispatch_reviewer(ctx, "owner/repo", issue, self._minimal_cfg())

        ctx.notify.assert_called_once()
        msg = ctx.notify.call_args[0][0]
        assert "não localizado" in msg or "pendente" in msg or "PR" in msg


class TestRunDispatchReviewer:
    """Integração: run() despacha sessão one-shot do reviewer quando crewflow:review."""

    def _make_ctx(self) -> mock.MagicMock:
        ctx = mock.MagicMock()
        ctx._port = 5000
        ctx._secret = "secret"
        ctx.job.id = "test-job"
        return ctx

    def _make_review_scan_result(self) -> object:
        """ScanResult em crewflow:review sem crewflow:reviewed (antes do dispatch)."""
        from flow.domain.gates import WorkItem
        from flow.domain.state import State
        from flow.scan.scanner import ScanResult

        return ScanResult(
            item=WorkItem(
                key="https://github.com/owner/repo/issues/42",
                title="[owner/repo] Feature X",
                labels=frozenset(["crewflow:review", "crewflow:feature"]),
            ),
            current_state=State.REVIEW,
            modifiers=frozenset(),
            dispatch_candidate=False,
            spec_valid=None,
            changed=True,
            reason="review pendente",
        )

    def test_despacha_reviewer_quando_review_sem_reviewed(self) -> None:
        """Quando issue está em crewflow:review, run() chama _dispatch_reviewer."""
        ctx = self._make_ctx()
        result = self._make_review_scan_result()

        with (
            mock.patch("deployment.deployment._load_config",
                       return_value={
                           "repos": ["owner/repo"],
                           "auto_dispatch": True,
                           "max_concurrent": 2,
                           "one_per_repo": True,
                           "notify_chat_id": "",
                           "squad_id": "test",
                           "issue_provider": "github",
                           "dev_root": "/tmp/dev",
                           "agent": "kirocrew",
                       }),
            mock.patch("deployment.deployment.scan_candidates", return_value=[result]),
            mock.patch("deployment.deployment.open_cache") as mock_cache,
            mock.patch("deployment.deployment.provider_for") as mock_provider_for,
            mock.patch("deployment.deployment._reviewer_has_active", return_value=False),
            mock.patch("deployment.deployment._dispatch_reviewer") as mock_disp_rev,
        ):
            mock_cache.return_value.__enter__ = mock.MagicMock(
                return_value=sqlite3.connect(":memory:"))
            mock_cache.return_value.__exit__ = mock.MagicMock(return_value=False)
            mock_provider = mock.MagicMock()
            mock_provider.get_state_comment.return_value = None
            mock_provider_for.return_value = mock_provider

            run(ctx)

        mock_disp_rev.assert_called_once()
        call_args = mock_disp_rev.call_args
        assert call_args[0][1] == "owner/repo"   # repo
        assert call_args[0][2]["number"] == 42   # issue["number"]

    def test_nao_despacha_reviewer_quando_ja_ativo(self) -> None:
        """Quando sessão do reviewer já está ativa, run() ignora o dispatch."""
        ctx = self._make_ctx()
        result = self._make_review_scan_result()

        with (
            mock.patch("deployment.deployment._load_config",
                       return_value={
                           "repos": ["owner/repo"],
                           "auto_dispatch": True,
                           "max_concurrent": 2,
                           "one_per_repo": True,
                           "notify_chat_id": "",
                           "squad_id": "test",
                           "issue_provider": "github",
                           "dev_root": "/tmp/dev",
                           "agent": "kirocrew",
                       }),
            mock.patch("deployment.deployment.scan_candidates", return_value=[result]),
            mock.patch("deployment.deployment.open_cache") as mock_cache,
            mock.patch("deployment.deployment.provider_for") as mock_provider_for,
            mock.patch("deployment.deployment._reviewer_has_active", return_value=True),
            mock.patch("deployment.deployment._dispatch_reviewer") as mock_disp_rev,
        ):
            mock_cache.return_value.__enter__ = mock.MagicMock(
                return_value=sqlite3.connect(":memory:"))
            mock_cache.return_value.__exit__ = mock.MagicMock(return_value=False)
            mock_provider = mock.MagicMock()
            mock_provider.get_state_comment.return_value = None
            mock_provider_for.return_value = mock_provider

            run(ctx)

        mock_disp_rev.assert_not_called()


# ---------------------------------------------------------------------------
# _post_reviewer_result_on_pr — posta resultado do reviewer no PR
# ---------------------------------------------------------------------------

class TestPostReviewerResultOnPr:
    """_post_reviewer_result_on_pr posta o ReviewerResult no PR e atualiza a issue."""

    def _make_state_comment_with_result(self, approved: bool, comments: list[str]) -> str:
        from flow.audit.state_comment import StateComment, render
        sc = StateComment(
            workflow="feature (v1)",
            current_node="review",
            status="running",
            repo="owner/myrepo",
        )
        sc.set_reviewer_result(approved=approved, comments=comments, sha="abc123")
        return render(sc)

    def test_posta_no_pr_quando_pr_encontrado(self) -> None:
        from deployment.deployment import _post_reviewer_result_on_pr
        from flow.adapters import github_client

        state_comment = self._make_state_comment_with_result(approved=True, comments=[])
        pr = {"number": 10, "headRefName": "feat/issue-42"}

        with mock.patch.object(github_client, "get_pr_for_issue", return_value=pr), \
             mock.patch.object(github_client, "upsert_pr_review_comment") as mock_upsert, \
             mock.patch.object(github_client, "get_state_comment", return_value=state_comment), \
             mock.patch.object(github_client, "upsert_state_comment"):
            _post_reviewer_result_on_pr("owner/myrepo", 42, "https://github.com/owner/myrepo/issues/42", state_comment)

        mock_upsert.assert_called_once()
        body = mock_upsert.call_args[0][2]
        assert "KiroCrew Review" in body
        assert "✅ Aprovado" in body

    def test_nao_posta_se_pr_nao_encontrado(self) -> None:
        from deployment.deployment import _post_reviewer_result_on_pr
        from flow.adapters import github_client

        state_comment = self._make_state_comment_with_result(approved=True, comments=[])

        with mock.patch.object(github_client, "get_pr_for_issue", return_value=None), \
             mock.patch.object(github_client, "upsert_pr_review_comment") as mock_upsert:
            _post_reviewer_result_on_pr("owner/myrepo", 42, "https://github.com/owner/myrepo/issues/42", state_comment)

        mock_upsert.assert_not_called()

    def test_nao_posta_se_reviewer_result_ausente(self) -> None:
        from deployment.deployment import _post_reviewer_result_on_pr
        from flow.adapters import github_client

        state_comment = "comentário normal sem ReviewerResult"

        with mock.patch.object(github_client, "get_pr_for_issue") as mock_pr, \
             mock.patch.object(github_client, "upsert_pr_review_comment") as mock_upsert:
            _post_reviewer_result_on_pr("owner/myrepo", 42, "https://github.com/owner/myrepo/issues/42", state_comment)

        mock_pr.assert_not_called()
        mock_upsert.assert_not_called()

    def test_posta_pedidos_de_mudanca_quando_reprovado(self) -> None:
        from deployment.deployment import _post_reviewer_result_on_pr
        from flow.adapters import github_client

        state_comment = self._make_state_comment_with_result(
            approved=False,
            comments=["Falta cobertura em X", "Nome confuso"],
        )
        pr = {"number": 10, "headRefName": "feat/issue-42"}

        with mock.patch.object(github_client, "get_pr_for_issue", return_value=pr), \
             mock.patch.object(github_client, "upsert_pr_review_comment") as mock_upsert, \
             mock.patch.object(github_client, "get_state_comment", return_value=state_comment), \
             mock.patch.object(github_client, "upsert_state_comment"):
            _post_reviewer_result_on_pr("owner/myrepo", 42, "https://github.com/owner/myrepo/issues/42", state_comment)

        mock_upsert.assert_called_once()
        body = mock_upsert.call_args[0][2]
        assert "⚠️ Pedidos de mudança" in body
        assert "Falta cobertura em X" in body
        assert "Nome confuso" in body

    def test_erro_no_upsert_nao_propaga_excecao(self) -> None:
        """Falha ao postar no PR é silenciosa — o resultado já está na issue."""
        from deployment.deployment import _post_reviewer_result_on_pr
        from flow.adapters import github_client
        from flow.ports.issue_provider import ProviderError

        state_comment = self._make_state_comment_with_result(approved=True, comments=[])
        pr = {"number": 10, "headRefName": "feat/issue-42"}

        with mock.patch.object(github_client, "get_pr_for_issue", return_value=pr), \
             mock.patch.object(github_client, "upsert_pr_review_comment", side_effect=ProviderError("falha")), \
             mock.patch.object(github_client, "get_state_comment", return_value=None):
            # Não deve lançar exceção
            _post_reviewer_result_on_pr("owner/myrepo", 42, "https://github.com/owner/myrepo/issues/42", state_comment)


# ---------------------------------------------------------------------------
# render_pr_review_comment — renderizador do comentário no PR
# ---------------------------------------------------------------------------

class TestRenderPrReviewComment:
    """render_pr_review_comment gera o formato correto para o PR."""

    def test_aprovado_sem_comentarios(self) -> None:
        from flow.audit.state_comment import ReviewerResult, render_pr_review_comment

        rr = ReviewerResult(approved=True, comments=(), sha="abc123")
        body = render_pr_review_comment(rr, issue_number=42, issue_url="https://github.com/owner/repo/issues/42")

        assert "<!-- KIRO-FLOW-REVIEW -->" in body
        assert "<!-- /KIRO-FLOW-REVIEW -->" in body
        assert "✅ Aprovado" in body
        assert "Pedidos de mudança" not in body
        assert "issue #42" in body

    def test_reprovado_com_comentarios(self) -> None:
        from flow.audit.state_comment import ReviewerResult, render_pr_review_comment

        rr = ReviewerResult(approved=False, comments=("Falta teste", "Import errado"), sha="")
        body = render_pr_review_comment(rr, issue_number=10)

        assert "⚠️ Pedidos de mudança" in body
        assert "Falta teste" in body
        assert "Import errado" in body

    def test_marcadores_presentes(self) -> None:
        from flow.audit.state_comment import (
            PR_REVIEW_COMMENT_CLOSE,
            PR_REVIEW_COMMENT_MARKER,
            ReviewerResult,
            render_pr_review_comment,
        )

        rr = ReviewerResult(approved=True, comments=())
        body = render_pr_review_comment(rr)

        assert PR_REVIEW_COMMENT_MARKER in body
        assert PR_REVIEW_COMMENT_CLOSE in body

    def test_sha_aparece_quando_fornecido(self) -> None:
        from flow.audit.state_comment import ReviewerResult, render_pr_review_comment

        rr = ReviewerResult(approved=True, comments=(), sha="deadbeef")
        body = render_pr_review_comment(rr)

        assert "deadbeef" in body

    def test_sem_sha_nao_aparece_linha_sha(self) -> None:
        from flow.audit.state_comment import ReviewerResult, render_pr_review_comment

        rr = ReviewerResult(approved=True, comments=(), sha="")
        body = render_pr_review_comment(rr)

        assert "**SHA:**" not in body


# ---------------------------------------------------------------------------
# upsert_pr_review_comment — upsert no PR (github_client)
# ---------------------------------------------------------------------------

class TestUpsertPrReviewComment:
    """upsert_pr_review_comment cria ou atualiza o comentário de review no PR."""

    def test_cria_se_nenhum_existente(self) -> None:
        from flow.adapters import github_client, github_transport

        with mock.patch.object(github_transport, "get_pr_comments", return_value=[]), \
             mock.patch.object(github_transport, "create_pr_comment") as mock_create:
            github_client.upsert_pr_review_comment("owner/repo", 10, "<!-- KIRO-FLOW-REVIEW --> body")

        mock_create.assert_called_once_with("owner/repo", 10, "<!-- KIRO-FLOW-REVIEW --> body")

    def test_atualiza_se_ja_existe(self) -> None:
        from flow.adapters import github_client, github_transport

        existing = [{"id": 999, "body": "<!-- KIRO-FLOW-REVIEW --> old body <!-- /KIRO-FLOW-REVIEW -->"}]
        with mock.patch.object(github_transport, "get_pr_comments", return_value=existing), \
             mock.patch.object(github_transport, "update_pr_comment") as mock_update:
            github_client.upsert_pr_review_comment("owner/repo", 10, "<!-- KIRO-FLOW-REVIEW --> new body")

        mock_update.assert_called_once_with("owner/repo", 999, "<!-- KIRO-FLOW-REVIEW --> new body")

    def test_nao_cria_duplicata(self) -> None:
        from flow.adapters import github_client, github_transport

        existing = [{"id": 999, "body": "<!-- KIRO-FLOW-REVIEW --> old body <!-- /KIRO-FLOW-REVIEW -->"}]
        with mock.patch.object(github_transport, "get_pr_comments", return_value=existing), \
             mock.patch.object(github_transport, "create_pr_comment") as mock_create, \
             mock.patch.object(github_transport, "update_pr_comment"):
            github_client.upsert_pr_review_comment("owner/repo", 10, "body")

        mock_create.assert_not_called()


def _make_dispatch_scan_result(
    key: str = "https://github.com/owner/repo/issues/42",
    title: str = "[owner/repo] Fix",
) -> object:
    from flow.domain.gates import WorkItem
    from flow.domain.state import State
    from flow.scan.scanner import ScanResult

    return ScanResult(
        item=WorkItem(key=key, title=title, labels=frozenset(["crewflow:todo", "crewflow:feature"])),
        current_state=State.TODO,
        modifiers=frozenset(),
        dispatch_candidate=True,
        spec_valid=None,
        changed=True,
        reason="CANDIDATO A DISPATCH; labels mudaram",
    )


class TestDryRun:
    """dry_run=True/CREWFLOW_DRY_RUN=1 — scan roda, efeitos colaterais não."""

    def _make_ctx(self) -> mock.MagicMock:
        ctx = mock.MagicMock()
        ctx._port = 5000
        ctx._secret = "secret"
        ctx.job.id = "test-job"
        return ctx

    def _dry_run_config(self, dry_run_in_config: bool = False) -> dict:
        cfg: dict = {
            "repos": ["owner/repo"],
            "auto_dispatch": True,
            "max_concurrent": 2,
            "one_per_repo": True,
            "notify_chat_id": "",
            "squad_id": "test",
            "issue_provider": "github",
            "dev_root": "/tmp/dev",
            "agent": "kirocrew",
        }
        if dry_run_in_config:
            cfg["dry_run"] = True
        return cfg

    def test_dispatch_nao_chamado_em_dry_run_via_env(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """CREWFLOW_DRY_RUN=1 → _dispatch NÃO é chamado."""
        monkeypatch.setenv("CREWFLOW_DRY_RUN", "1")
        ctx = self._make_ctx()
        result = _make_dispatch_scan_result()

        with (
            mock.patch("deployment.deployment._load_config", return_value=self._dry_run_config()),
            mock.patch("deployment.deployment.scan_candidates", return_value=[result]),
            mock.patch("deployment.deployment.open_cache") as mock_cache,
            mock.patch("deployment.deployment.provider_for") as mock_provider_for,
            mock.patch("deployment.deployment._dispatch") as mock_dispatch,
        ):
            mock_cache.return_value.__enter__ = mock.MagicMock(
                return_value=sqlite3.connect(":memory:"))
            mock_cache.return_value.__exit__ = mock.MagicMock(return_value=False)
            mock_provider_for.return_value = mock.MagicMock()

            run(ctx)

        mock_dispatch.assert_not_called()

    def test_dispatch_nao_chamado_em_dry_run_via_config(self) -> None:
        """dry_run: true na config → _dispatch NÃO é chamado."""
        ctx = self._make_ctx()
        result = _make_dispatch_scan_result()

        with (
            mock.patch(
                "deployment.deployment._load_config",
                return_value=self._dry_run_config(dry_run_in_config=True),
            ),
            mock.patch("deployment.deployment.scan_candidates", return_value=[result]),
            mock.patch("deployment.deployment.open_cache") as mock_cache,
            mock.patch("deployment.deployment.provider_for") as mock_provider_for,
            mock.patch("deployment.deployment._dispatch") as mock_dispatch,
        ):
            mock_cache.return_value.__enter__ = mock.MagicMock(
                return_value=sqlite3.connect(":memory:"))
            mock_cache.return_value.__exit__ = mock.MagicMock(return_value=False)
            mock_provider_for.return_value = mock.MagicMock()

            run(ctx)

        mock_dispatch.assert_not_called()

    def test_notify_nao_chamado_em_dry_run(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Nenhuma notificação enviada no modo dry-run."""
        monkeypatch.setenv("CREWFLOW_DRY_RUN", "1")
        ctx = self._make_ctx()
        result = _make_dispatch_scan_result()

        with (
            mock.patch("deployment.deployment._load_config", return_value=self._dry_run_config()),
            mock.patch("deployment.deployment.scan_candidates", return_value=[result]),
            mock.patch("deployment.deployment.open_cache") as mock_cache,
            mock.patch("deployment.deployment.provider_for") as mock_provider_for,
        ):
            mock_cache.return_value.__enter__ = mock.MagicMock(
                return_value=sqlite3.connect(":memory:"))
            mock_cache.return_value.__exit__ = mock.MagicMock(return_value=False)
            mock_provider_for.return_value = mock.MagicMock()

            run(ctx)

        ctx.notify.assert_not_called()

    def test_set_labels_nao_chamado_em_dry_run(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """provider.set_labels NÃO é chamado no modo dry-run (nenhuma label alterada)."""
        monkeypatch.setenv("CREWFLOW_DRY_RUN", "1")
        ctx = self._make_ctx()
        result = _make_dispatch_scan_result()

        with (
            mock.patch("deployment.deployment._load_config", return_value=self._dry_run_config()),
            mock.patch("deployment.deployment.scan_candidates", return_value=[result]),
            mock.patch("deployment.deployment.open_cache") as mock_cache,
            mock.patch("deployment.deployment.provider_for") as mock_provider_for,
        ):
            mock_cache.return_value.__enter__ = mock.MagicMock(
                return_value=sqlite3.connect(":memory:"))
            mock_cache.return_value.__exit__ = mock.MagicMock(return_value=False)
            mock_provider = mock.MagicMock()
            mock_provider_for.return_value = mock_provider

            run(ctx)

        mock_provider.set_labels.assert_not_called()

    def test_dry_run_imprime_relatorio_stdout(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        """dry-run imprime as decisões no stdout em formato legível."""
        monkeypatch.setenv("CREWFLOW_DRY_RUN", "1")
        ctx = self._make_ctx()
        result = _make_dispatch_scan_result(
            key="https://github.com/owner/repo/issues/42",
            title="[owner/repo] Feature X",
        )

        with (
            mock.patch("deployment.deployment._load_config", return_value=self._dry_run_config()),
            mock.patch("deployment.deployment.scan_candidates", return_value=[result]),
            mock.patch("deployment.deployment.open_cache") as mock_cache,
            mock.patch("deployment.deployment.provider_for") as mock_provider_for,
        ):
            mock_cache.return_value.__enter__ = mock.MagicMock(
                return_value=sqlite3.connect(":memory:"))
            mock_cache.return_value.__exit__ = mock.MagicMock(return_value=False)
            mock_provider_for.return_value = mock.MagicMock()

            run(ctx)

        captured = capsys.readouterr()
        assert "[DRY-RUN]" in captured.out
        assert "DISPATCH_DEV" in captured.out
        assert "#42" in captured.out

    def test_sem_dry_run_dispatch_e_chamado(self) -> None:
        """Sem dry-run, _dispatch É chamado normalmente (regressão)."""
        ctx = self._make_ctx()
        result = _make_dispatch_scan_result()

        with (
            mock.patch("deployment.deployment._load_config", return_value=self._dry_run_config()),
            mock.patch("deployment.deployment.scan_candidates", return_value=[result]),
            mock.patch("deployment.deployment.open_cache") as mock_cache,
            mock.patch("deployment.deployment.provider_for") as mock_provider_for,
            mock.patch("deployment.deployment._active_sessions", return_value=0),
            mock.patch("deployment.deployment._repo_has_active", return_value=False),
            mock.patch("deployment.deployment._pr_exists", return_value=False),
            mock.patch("deployment.deployment._dispatch") as mock_dispatch,
        ):
            mock_cache.return_value.__enter__ = mock.MagicMock(
                return_value=sqlite3.connect(":memory:"))
            mock_cache.return_value.__exit__ = mock.MagicMock(return_value=False)
            mock_provider_for.return_value = mock.MagicMock()

            run(ctx)

        mock_dispatch.assert_called_once()

    def test_dry_run_env_vazia_nao_ativa(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """CREWFLOW_DRY_RUN='' (variável vazia) NÃO ativa o dry-run."""
        monkeypatch.setenv("CREWFLOW_DRY_RUN", "")
        ctx = self._make_ctx()
        result = _make_dispatch_scan_result()

        with (
            mock.patch("deployment.deployment._load_config", return_value=self._dry_run_config()),
            mock.patch("deployment.deployment.scan_candidates", return_value=[result]),
            mock.patch("deployment.deployment.open_cache") as mock_cache,
            mock.patch("deployment.deployment.provider_for") as mock_provider_for,
            mock.patch("deployment.deployment._active_sessions", return_value=0),
            mock.patch("deployment.deployment._repo_has_active", return_value=False),
            mock.patch("deployment.deployment._pr_exists", return_value=False),
            mock.patch("deployment.deployment._dispatch") as mock_dispatch,
        ):
            mock_cache.return_value.__enter__ = mock.MagicMock(
                return_value=sqlite3.connect(":memory:"))
            mock_cache.return_value.__exit__ = mock.MagicMock(return_value=False)
            mock_provider_for.return_value = mock.MagicMock()

            run(ctx)

        mock_dispatch.assert_called_once()


# ---------------------------------------------------------------------------
# Issue #84 — resumo do ciclo no log
# ---------------------------------------------------------------------------

class TestLogCycleSummary:
    """_log_cycle_summary emite 1 linha de resumo e notifica quando chat_id configurado."""

    def _make_ctx(self) -> mock.MagicMock:
        ctx = mock.MagicMock()
        return ctx

    def test_log_contém_todos_os_contadores(self) -> None:
        from deployment.deployment import _log_cycle_summary

        ctx = self._make_ctx()
        with mock.patch("deployment.deployment.logger") as mock_log:
            _log_cycle_summary(
                ctx=ctx,
                chat_id="",
                scan_total=7,
                dispatch_dev=2,
                dispatch_reviewer=1,
                dispatch_rework=0,
                merge_pr=0,
                notify_human=1,
                block=0,
                rebrand=0,
                spec_invalid=1,
            )
        mock_log.info.assert_called_once()
        msg = mock_log.info.call_args[0][0]
        assert "scan:7" in msg
        assert "dispatch_dev:2" in msg
        assert "dispatch_reviewer:1" in msg
        assert "merge_pr:0" in msg
        assert "notify_human:1" in msg
        assert "block:0" in msg
        assert "rebrand:0" in msg
        assert "skip:2" in msg  # 7 total - 5 ações = 2 skips

    def test_skip_calculado_corretamente(self) -> None:
        from deployment.deployment import _log_cycle_summary

        ctx = self._make_ctx()
        with mock.patch("deployment.deployment.logger") as mock_log:
            _log_cycle_summary(
                ctx=ctx,
                chat_id="",
                scan_total=5,
                dispatch_dev=0,
                dispatch_reviewer=0,
                dispatch_rework=0,
                merge_pr=0,
                notify_human=0,
                block=0,
                rebrand=0,
                spec_invalid=0,
            )
        msg = mock_log.info.call_args[0][0]
        assert "skip:5" in msg

    def test_tudo_zerado_ciclo_vazio(self) -> None:
        from deployment.deployment import _log_cycle_summary

        ctx = self._make_ctx()
        with mock.patch("deployment.deployment.logger") as mock_log:
            _log_cycle_summary(
                ctx=ctx,
                chat_id="",
                scan_total=0,
                dispatch_dev=0,
                dispatch_reviewer=0,
                dispatch_rework=0,
                merge_pr=0,
                notify_human=0,
                block=0,
                rebrand=0,
                spec_invalid=0,
            )
        msg = mock_log.info.call_args[0][0]
        assert "scan:0" in msg
        assert "skip:0" in msg
        ctx.notify.assert_not_called()

    def test_notifica_quando_chat_id_configurado(self) -> None:
        from deployment.deployment import _log_cycle_summary

        ctx = self._make_ctx()
        with mock.patch("deployment.deployment.logger"):
            _log_cycle_summary(
                ctx=ctx,
                chat_id="8620515309",
                scan_total=3,
                dispatch_dev=1,
                dispatch_reviewer=0,
                dispatch_rework=0,
                merge_pr=0,
                notify_human=0,
                block=0,
                rebrand=0,
                spec_invalid=0,
            )
        ctx.notify.assert_called_once()
        msg = ctx.notify.call_args[0][0]
        assert "scan:3" in msg
        assert "dispatch_dev:1" in msg

    def test_nao_notifica_sem_chat_id(self) -> None:
        from deployment.deployment import _log_cycle_summary

        ctx = self._make_ctx()
        with mock.patch("deployment.deployment.logger"):
            _log_cycle_summary(
                ctx=ctx,
                chat_id="",
                scan_total=3,
                dispatch_dev=1,
                dispatch_reviewer=0,
                dispatch_rework=0,
                merge_pr=0,
                notify_human=0,
                block=0,
                rebrand=0,
                spec_invalid=0,
            )
        ctx.notify.assert_not_called()

    def test_prefixo_deployment_ciclo_concluido(self) -> None:
        from deployment.deployment import _log_cycle_summary

        ctx = self._make_ctx()
        with mock.patch("deployment.deployment.logger") as mock_log:
            _log_cycle_summary(
                ctx=ctx,
                chat_id="",
                scan_total=1,
                dispatch_dev=1,
                dispatch_reviewer=0,
                dispatch_rework=0,
                merge_pr=0,
                notify_human=0,
                block=0,
                rebrand=0,
                spec_invalid=0,
            )
        msg = mock_log.info.call_args[0][0]
        assert msg.startswith("deployment: ciclo concluído")


class TestRunEmiteCicleSummary:
    """run() deve emitir o resumo do ciclo em todos os casos, incluindo tudo SKIP."""

    def _make_ctx(self) -> mock.MagicMock:
        ctx = mock.MagicMock()
        ctx._port = 5000
        ctx._secret = "secret"
        ctx.job.id = "test-job"
        return ctx

    def test_resumo_emitido_quando_tudo_skip(self) -> None:
        """Quando scan retorna vazio, o resumo ainda deve ser logado."""
        ctx = self._make_ctx()

        with (
            mock.patch("deployment.deployment._load_config",
                       return_value=_minimal_config()),
            mock.patch("deployment.deployment.scan_candidates",
                       return_value=[]),
            mock.patch("deployment.deployment.open_cache") as mock_cache,
            mock.patch("deployment.deployment._log_cycle_summary") as mock_summary,
        ):
            mock_cache.return_value.__enter__ = mock.MagicMock(
                return_value=sqlite3.connect(":memory:"))
            mock_cache.return_value.__exit__ = mock.MagicMock(return_value=False)
            run(ctx)

        mock_summary.assert_called_once()
        kw = mock_summary.call_args.kwargs
        assert kw["scan_total"] == 0
        assert kw["dispatch_dev"] == 0

    def test_resumo_emitido_com_dispatch_dev(self) -> None:
        """Ciclo com dispatch_dev deve refletir o contador correto no resumo."""
        ctx = self._make_ctx()
        results = [_make_scan_result()]

        with (
            mock.patch("deployment.deployment._load_config",
                       return_value=_minimal_config(auto=False)),
            mock.patch("deployment.deployment.scan_candidates",
                       return_value=results),
            mock.patch("deployment.deployment.open_cache") as mock_cache,
            mock.patch("deployment.deployment._log_cycle_summary") as mock_summary,
        ):
            mock_cache.return_value.__enter__ = mock.MagicMock(
                return_value=sqlite3.connect(":memory:"))
            mock_cache.return_value.__exit__ = mock.MagicMock(return_value=False)
            run(ctx)

        mock_summary.assert_called_once()
        kw = mock_summary.call_args.kwargs
        assert kw["scan_total"] == 1
        assert kw["dispatch_dev"] == 1
        assert kw["dispatch_reviewer"] == 0
# Workspace isolado por task (#92)
# ---------------------------------------------------------------------------

from deployment.deployment import (  # noqa: E402
    _clean_stale_worktree,
    _resource_headroom_ok,
    _worktree_path,
)


class TestWorktreePath:
    """_worktree_path() retorna convenção canônica consistente."""

    def test_caminho_canônico(self) -> None:
        path = _worktree_path("/home/user/dev", "owner/my-repo", 42)
        assert path == "/home/user/dev/.esteira-worktrees/my-repo-42"

    def test_usa_short_do_repo(self) -> None:
        path = _worktree_path("/dev", "org/project-name", 7)
        assert "project-name-7" in path

    def test_sem_slash_extra(self) -> None:
        path = _worktree_path("/home/user/dev", "owner/repo", 1)
        assert "//" not in path


class TestCleanStaleWorktree:
    """_clean_stale_worktree() remove worktrees órfãos antes do dispatch."""

    def test_retorna_false_quando_nao_existe(self, tmp_path: Path) -> None:
        """Sem worktree no disco → retorna False sem erro."""
        dev_root = str(tmp_path)
        result = _clean_stale_worktree(dev_root, "owner/repo", 99)
        assert result is False

    def test_remove_worktree_via_git(self, tmp_path: Path) -> None:
        """Worktree órfão presente → chama git worktree remove e retorna True."""
        dev_root = str(tmp_path)
        wt = tmp_path / ".esteira-worktrees" / "repo-5"
        wt.mkdir(parents=True)

        with mock.patch("subprocess.run") as mock_run:
            mock_run.return_value = mock.MagicMock(returncode=0, stderr="")
            result = _clean_stale_worktree(dev_root, "owner/repo", 5)

        assert result is True
        call_args = mock_run.call_args[0][0]
        assert "git" in call_args
        assert "worktree" in call_args
        assert "remove" in call_args

    def test_fallback_shutil_quando_git_falha(self, tmp_path: Path) -> None:
        """git worktree remove falha → shutil.rmtree usado como fallback."""
        import subprocess
        dev_root = str(tmp_path)
        wt = tmp_path / ".esteira-worktrees" / "repo-6"
        wt.mkdir(parents=True)
        (wt / "file.txt").write_text("stub")

        with mock.patch("subprocess.run") as mock_run:
            # Primeira chamada (git worktree remove) falha
            mock_run.side_effect = [
                subprocess.CalledProcessError(1, "git", stderr="not a worktree"),
                mock.MagicMock(returncode=0),  # git worktree prune ok
            ]
            result = _clean_stale_worktree(dev_root, "owner/repo", 6)

        assert result is True
        # O diretório deve ter sido removido pelo shutil
        assert not wt.exists()

    def test_nao_propaga_excecao_quando_tudo_falha(
        self, tmp_path: Path
    ) -> None:
        """Falha total → retorna False sem propagar exceção."""
        dev_root = str(tmp_path)
        wt = tmp_path / ".esteira-worktrees" / "repo-7"
        wt.mkdir(parents=True)

        with mock.patch("subprocess.run", side_effect=RuntimeError("boom")):
            result = _clean_stale_worktree(dev_root, "owner/repo", 7)

        assert result is False


class TestResourceHeadroomOk:
    """_resource_headroom_ok() honra resource_status do Kiro Crew."""

    def _make_ctx(self) -> mock.MagicMock:
        ctx = mock.MagicMock()
        ctx._port = 5000
        ctx._secret = "secret"
        return ctx

    def test_retorna_true_quando_kc_indisponivel(self) -> None:
        """ImportError (sem Kiro Crew) → fail-open, retorna True."""
        ctx = self._make_ctx()

        with mock.patch.dict("sys.modules", {"kiro_crew.loopback_http": None}):
            result = _resource_headroom_ok(ctx, 2)

        assert result is True

    def test_retorna_true_para_posture_ample(self) -> None:
        ctx = self._make_ctx()

        mock_resp = mock.MagicMock()
        mock_resp.__enter__ = mock.MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = mock.MagicMock(return_value=False)
        mock_resp.read.return_value = b'{"posture": "ample"}'

        mock_loopback = mock.MagicMock()
        mock_loopback.loopback_urlopen.return_value = mock_resp

        with mock.patch.dict("sys.modules", {"kiro_crew.loopback_http": mock_loopback}):
            result = _resource_headroom_ok(ctx, 2)

        assert result is True

    def test_retorna_true_para_posture_tight(self) -> None:
        ctx = self._make_ctx()

        mock_resp = mock.MagicMock()
        mock_resp.__enter__ = mock.MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = mock.MagicMock(return_value=False)
        mock_resp.read.return_value = b'{"posture": "tight"}'

        mock_loopback = mock.MagicMock()
        mock_loopback.loopback_urlopen.return_value = mock_resp

        with mock.patch.dict("sys.modules", {"kiro_crew.loopback_http": mock_loopback}):
            result = _resource_headroom_ok(ctx, 2)

        assert result is True

    def test_retorna_false_para_posture_critical(self) -> None:
        ctx = self._make_ctx()

        mock_resp = mock.MagicMock()
        mock_resp.__enter__ = mock.MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = mock.MagicMock(return_value=False)
        mock_resp.read.return_value = b'{"posture": "critical"}'

        mock_loopback = mock.MagicMock()
        mock_loopback.loopback_urlopen.return_value = mock_resp

        with mock.patch.dict("sys.modules", {"kiro_crew.loopback_http": mock_loopback}):
            result = _resource_headroom_ok(ctx, 2)

        assert result is False

    def test_fail_open_quando_excecao(self) -> None:
        """Qualquer exceção → fail-open, retorna True."""
        ctx = self._make_ctx()

        mock_loopback = mock.MagicMock()
        mock_loopback.loopback_urlopen.side_effect = OSError("connection refused")

        with mock.patch.dict("sys.modules", {"kiro_crew.loopback_http": mock_loopback}):
            result = _resource_headroom_ok(ctx, 2)

        assert result is True


class TestParallelDispatchIsolation:
    """Paralelismo: dois dispatches sem colisão de worktree; cap de max_concurrent respeitado."""

    def _make_ctx(self) -> mock.MagicMock:
        ctx = mock.MagicMock()
        ctx._port = 5000
        ctx._secret = "secret"
        ctx.job.id = "test-job"
        return ctx

    def _auto_config(self, max_concurrent: int = 3) -> dict:
        return {
            "repos": ["owner/repo-a", "owner/repo-b"],
            "auto_dispatch": True,
            "max_concurrent_tasks": max_concurrent,
            "one_per_repo": False,  # desligado para testar isolamento por worktree
            "notify_chat_id": "",
            "squad_id": "test",
            "issue_provider": "github",
            "dev_root": "/tmp/dev",
            "agent": "kirocrew",
        }

    def test_dois_repos_diferentes_despacham_em_paralelo(self) -> None:
        """Duas issues em repos diferentes são despachadas na mesma rodada."""
        ctx = self._make_ctx()
        result_a = _make_dispatch_scan_result(
            key="https://github.com/owner/repo-a/issues/1",
            title="[repo-a] Feature A",
        )
        result_b = _make_dispatch_scan_result(
            key="https://github.com/owner/repo-b/issues/2",
            title="[repo-b] Feature B",
        )

        with (
            mock.patch("deployment.deployment._load_config",
                       return_value=self._auto_config(max_concurrent=3)),
            mock.patch("deployment.deployment.scan_candidates",
                       return_value=[result_a, result_b]),
            mock.patch("deployment.deployment.open_cache") as mock_cache,
            mock.patch("deployment.deployment.provider_for") as mock_provider_for,
            mock.patch("deployment.deployment._active_sessions", return_value=0),
            mock.patch("deployment.deployment._repo_has_active", return_value=False),
            mock.patch("deployment.deployment._pr_exists", return_value=False),
            mock.patch("deployment.deployment._resource_headroom_ok", return_value=True),
            mock.patch("deployment.deployment._clean_stale_worktree"),
            mock.patch("deployment.deployment._dispatch") as mock_dispatch,
        ):
            mock_cache.return_value.__enter__ = mock.MagicMock(
                return_value=sqlite3.connect(":memory:"))
            mock_cache.return_value.__exit__ = mock.MagicMock(return_value=False)
            mock_provider_for.return_value = mock.MagicMock()
            run(ctx)

        # Ambas as issues devem ter sido despachadas
        assert mock_dispatch.call_count == 2

    def test_cap_max_concurrent_tasks_respeitado(self) -> None:
        """Com max_concurrent_tasks=1 e 2 candidatos, só 1 é despachado."""
        ctx = self._make_ctx()
        result_a = _make_dispatch_scan_result(
            key="https://github.com/owner/repo-a/issues/10",
            title="[repo-a] Task 10",
        )
        result_b = _make_dispatch_scan_result(
            key="https://github.com/owner/repo-b/issues/11",
            title="[repo-b] Task 11",
        )

        with (
            mock.patch("deployment.deployment._load_config",
                       return_value=self._auto_config(max_concurrent=1)),
            mock.patch("deployment.deployment.scan_candidates",
                       return_value=[result_a, result_b]),
            mock.patch("deployment.deployment.open_cache") as mock_cache,
            mock.patch("deployment.deployment.provider_for") as mock_provider_for,
            mock.patch("deployment.deployment._active_sessions", return_value=0),
            mock.patch("deployment.deployment._repo_has_active", return_value=False),
            mock.patch("deployment.deployment._pr_exists", return_value=False),
            mock.patch("deployment.deployment._resource_headroom_ok", return_value=True),
            mock.patch("deployment.deployment._clean_stale_worktree"),
            mock.patch("deployment.deployment._dispatch") as mock_dispatch,
        ):
            mock_cache.return_value.__enter__ = mock.MagicMock(
                return_value=sqlite3.connect(":memory:"))
            mock_cache.return_value.__exit__ = mock.MagicMock(return_value=False)
            mock_provider_for.return_value = mock.MagicMock()
            run(ctx)

        # Só 1 deve ter sido despachado
        assert mock_dispatch.call_count == 1

    def test_resource_critical_adia_dispatch(self) -> None:
        """Posture critical → nenhuma sessão despachada mesmo com vagas disponíveis."""
        ctx = self._make_ctx()
        result = _make_dispatch_scan_result()

        with (
            mock.patch("deployment.deployment._load_config",
                       return_value=self._auto_config(max_concurrent=3)),
            mock.patch("deployment.deployment.scan_candidates", return_value=[result]),
            mock.patch("deployment.deployment.open_cache") as mock_cache,
            mock.patch("deployment.deployment.provider_for") as mock_provider_for,
            mock.patch("deployment.deployment._active_sessions", return_value=0),
            mock.patch("deployment.deployment._repo_has_active", return_value=False),
            mock.patch("deployment.deployment._pr_exists", return_value=False),
            mock.patch("deployment.deployment._resource_headroom_ok", return_value=False),
            mock.patch("deployment.deployment._clean_stale_worktree"),
            mock.patch("deployment.deployment._dispatch") as mock_dispatch,
        ):
            mock_cache.return_value.__enter__ = mock.MagicMock(
                return_value=sqlite3.connect(":memory:"))
            mock_cache.return_value.__exit__ = mock.MagicMock(return_value=False)
            mock_provider_for.return_value = mock.MagicMock()
            run(ctx)

        mock_dispatch.assert_not_called()

    def test_clean_worktree_chamado_antes_dispatch(self) -> None:
        """_clean_stale_worktree() é chamado para cada issue antes de despachar."""
        ctx = self._make_ctx()
        result = _make_dispatch_scan_result(
            key="https://github.com/owner/repo/issues/42",
            title="[repo] Fix",
        )

        with (
            mock.patch("deployment.deployment._load_config",
                       return_value=self._auto_config()),
            mock.patch("deployment.deployment.scan_candidates", return_value=[result]),
            mock.patch("deployment.deployment.open_cache") as mock_cache,
            mock.patch("deployment.deployment.provider_for") as mock_provider_for,
            mock.patch("deployment.deployment._active_sessions", return_value=0),
            mock.patch("deployment.deployment._repo_has_active", return_value=False),
            mock.patch("deployment.deployment._pr_exists", return_value=False),
            mock.patch("deployment.deployment._resource_headroom_ok", return_value=True),
            mock.patch("deployment.deployment._clean_stale_worktree") as mock_clean,
            mock.patch("deployment.deployment._dispatch"),
        ):
            mock_cache.return_value.__enter__ = mock.MagicMock(
                return_value=sqlite3.connect(":memory:"))
            mock_cache.return_value.__exit__ = mock.MagicMock(return_value=False)
            mock_provider_for.return_value = mock.MagicMock()
            run(ctx)

        mock_clean.assert_called_once()
        # Verifica que o número de issue correto foi passado
        call_kwargs = mock_clean.call_args
        assert 42 in call_kwargs[0] or 42 in call_kwargs[1].values()

    def test_max_concurrent_tasks_alias_compat(self) -> None:
        """max_concurrent_tasks tem precedência sobre max_concurrent (compat backward)."""
        ctx = self._make_ctx()
        result_a = _make_dispatch_scan_result(
            key="https://github.com/owner/repo-a/issues/20",
            title="[repo-a] Task 20",
        )
        result_b = _make_dispatch_scan_result(
            key="https://github.com/owner/repo-b/issues/21",
            title="[repo-b] Task 21",
        )
        # max_concurrent=5 mas max_concurrent_tasks=1 → cap de 1 deve vencer
        cfg = self._auto_config()
        cfg["max_concurrent"] = 5
        cfg["max_concurrent_tasks"] = 1

        with (
            mock.patch("deployment.deployment._load_config", return_value=cfg),
            mock.patch("deployment.deployment.scan_candidates",
                       return_value=[result_a, result_b]),
            mock.patch("deployment.deployment.open_cache") as mock_cache,
            mock.patch("deployment.deployment.provider_for") as mock_provider_for,
            mock.patch("deployment.deployment._active_sessions", return_value=0),
            mock.patch("deployment.deployment._repo_has_active", return_value=False),
            mock.patch("deployment.deployment._pr_exists", return_value=False),
            mock.patch("deployment.deployment._resource_headroom_ok", return_value=True),
            mock.patch("deployment.deployment._clean_stale_worktree"),
            mock.patch("deployment.deployment._dispatch") as mock_dispatch,
        ):
            mock_cache.return_value.__enter__ = mock.MagicMock(
                return_value=sqlite3.connect(":memory:"))
            mock_cache.return_value.__exit__ = mock.MagicMock(return_value=False)
            mock_provider_for.return_value = mock.MagicMock()
            run(ctx)

        assert mock_dispatch.call_count == 1


# ===========================================================================
# Concorrência dirigida por ESTADO (issue #90) — FEAT-002
# ===========================================================================

from deployment.deployment import (  # noqa: E402
    _DEAD_SESSION_SECS_DEFAULT,
    _dead_session_secs,
    _dev_dispatch_allowed,
    _is_session_dead,
    _recover_dead_session,
    _state_allows_dispatch,
)


def _running_state_body(short_repo: str = "repo-a", minutes_ago: int = 120) -> str:
    """Renderiza um state_comment com uma transição para crewflow:running no passado."""
    from datetime import UTC, datetime, timedelta

    from flow.audit.state_comment import StateComment, render

    when = (datetime.now(tz=UTC) - timedelta(minutes=minutes_ago)).strftime("%Y-%m-%d %H:%M")
    sc = StateComment(
        workflow="feature (v1)", current_node="dev", status="running", repo=short_repo,
    )
    sc.add_transition(
        from_state="crewflow:todo", to_state="crewflow:running", actor="system", when=when,
    )
    return render(sc)


def _running_item(url: str, title: str = "[repo-a] busy") -> dict:
    """Item normalizado de uma issue em andamento (carrega crewflow:running)."""
    return {
        "key": url,
        "title": title,
        "labels": ["crewflow:dev", "crewflow:running"],
        "state_comment": None,
        "parent_key": None,
    }


class TestDeadSessionSecsConfig:
    """_dead_session_secs: default 40 min, sobrescrevível via config."""

    def test_default_40_min(self) -> None:
        assert _dead_session_secs(None) == _DEAD_SESSION_SECS_DEFAULT == 2400

    def test_override_por_segundos(self) -> None:
        assert _dead_session_secs({"dead_session_secs": 90}) == 90

    def test_override_por_minutos(self) -> None:
        assert _dead_session_secs({"dead_session_minutes": 10}) == 600

    def test_segundos_tem_precedencia_sobre_minutos(self) -> None:
        assert _dead_session_secs({"dead_session_secs": 120, "dead_session_minutes": 99}) == 120

    def test_valor_invalido_cai_no_default(self) -> None:
        assert _dead_session_secs({"dead_session_secs": "abc"}) == _DEAD_SESSION_SECS_DEFAULT
        assert _dead_session_secs({"dead_session_secs": -5}) == _DEAD_SESSION_SECS_DEFAULT


class TestStateDrivenDispatchGate:
    """(1) TRANSIÇÃO DIRIGIDA POR ESTADO — one_per_repo avaliado pelo estado da issue."""

    def test_repo_livre_permite_dispatch(self) -> None:
        provider = mock.MagicMock()
        provider.list_by_state.return_value = []
        assert _state_allows_dispatch(provider, "owner/repo-a", one_per_repo=True) is True

    def test_repo_com_issue_running_esta_ocupado(self) -> None:
        provider = mock.MagicMock()

        def _by_state(repo: str, state: str) -> list[dict]:
            if state == "crewflow:running":
                return [_running_item("https://github.com/owner/repo-a/issues/7")]
            return []

        provider.list_by_state.side_effect = _by_state
        assert _state_allows_dispatch(provider, "owner/repo-a", one_per_repo=True) is False

    def test_one_per_repo_desligado_sempre_permite(self) -> None:
        provider = mock.MagicMock()
        provider.list_by_state.return_value = [
            _running_item("https://github.com/owner/repo-a/issues/7")
        ]
        assert _state_allows_dispatch(provider, "owner/repo-a", one_per_repo=False) is True

    def test_falha_do_provider_fecha_fechado(self) -> None:
        """Consulta ao provider levanta → None (fail-closed, não despacha)."""
        provider = mock.MagicMock()
        provider.list_by_state.side_effect = RuntimeError("gh down")
        assert _state_allows_dispatch(provider, "owner/repo-a", one_per_repo=True) is None

    def test_segunda_issue_no_mesmo_repo_e_enfileirada(self) -> None:
        """run(): duas issues no MESMO repo — a segunda é enfileirada (repo ocupado)."""
        ctx = mock.MagicMock()
        ctx._port = 5000
        ctx._secret = "secret"
        ctx.job.id = "test-job"

        result_a = _make_dispatch_scan_result(
            key="https://github.com/owner/repo-a/issues/1", title="[repo-a] A",
        )
        result_b = _make_dispatch_scan_result(
            key="https://github.com/owner/repo-a/issues/2", title="[repo-a] B",
        )
        cfg = {
            "repos": ["owner/repo-a"],
            "auto_dispatch": True,
            "max_concurrent_tasks": 5,
            "one_per_repo": True,
            "notify_chat_id": "",
            "squad_id": "test",
            "issue_provider": "github",
            "dev_root": "/tmp/dev",
            "agent": "kirocrew",
        }

        provider = mock.MagicMock()
        provider.list_by_state.return_value = []  # repo começa livre

        # Depois da 1ª dispatch, o gate por estado passa a reportar o repo ocupado.
        state = {"busy": False}

        def _gate(prov: object, repo: str, one_per_repo: bool) -> bool:
            return not state["busy"]

        def _dispatch_side_effect(*args: object, **kwargs: object) -> None:
            state["busy"] = True

        with (
            mock.patch("deployment.deployment._load_config", return_value=cfg),
            mock.patch("deployment.deployment.scan_candidates",
                       return_value=[result_a, result_b]),
            mock.patch("deployment.deployment.open_cache") as mock_cache,
            mock.patch("deployment.deployment.provider_for", return_value=provider),
            mock.patch("deployment.deployment._active_sessions", return_value=0),
            mock.patch("deployment.deployment._pr_exists", return_value=False),
            mock.patch("deployment.deployment._session_write_is_recent", return_value=None),
            mock.patch("deployment.deployment._state_allows_dispatch", side_effect=_gate),
            mock.patch("deployment.deployment._resource_headroom_ok", return_value=True),
            mock.patch("deployment.deployment._clean_stale_worktree"),
            mock.patch("deployment.deployment._dispatch",
                       side_effect=_dispatch_side_effect) as mock_dispatch,
        ):
            mock_cache.return_value.__enter__ = mock.MagicMock(
                return_value=sqlite3.connect(":memory:"))
            mock_cache.return_value.__exit__ = mock.MagicMock(return_value=False)
            run(ctx)

        # Apenas a primeira issue foi despachada; a segunda ficou na fila.
        assert mock_dispatch.call_count == 1


class TestDeadSessionDetection:
    """(2) DETECÇÃO DE SESSÃO MORTA — só True quando os 4 sinais valem."""

    def _provider_running(self, minutes_ago: int) -> mock.MagicMock:
        provider = mock.MagicMock()
        provider.get_state_comment.return_value = _running_state_body(minutes_ago=minutes_ago)
        return provider

    def test_morta_quando_todos_sinais_batem(self, tmp_path: Path) -> None:
        provider = self._provider_running(minutes_ago=120)  # >40min
        with (
            mock.patch("deployment.deployment._pr_exists", return_value=False),
            mock.patch("deployment.deployment._worktree_is_active", return_value=False),
            mock.patch("deployment.deployment._session_write_is_recent", return_value=False),
        ):
            issue = {"number": 7, "title": "[repo-a] busy",
                     "url": "https://github.com/owner/repo-a/issues/7"}
            assert _is_session_dead(str(tmp_path), "owner/repo-a", 7, provider, issue) is True

    def test_nao_morta_se_pr_aberto(self, tmp_path: Path) -> None:
        provider = self._provider_running(minutes_ago=120)
        with (
            mock.patch("deployment.deployment._pr_exists", return_value=True),
            mock.patch("deployment.deployment._worktree_is_active", return_value=False),
            mock.patch("deployment.deployment._session_write_is_recent", return_value=False),
        ):
            issue = {"number": 7, "title": "x",
                     "url": "https://github.com/owner/repo-a/issues/7"}
            assert _is_session_dead(str(tmp_path), "owner/repo-a", 7, provider, issue) is False

    def test_nao_morta_se_worktree_ativo(self, tmp_path: Path) -> None:
        provider = self._provider_running(minutes_ago=120)
        with (
            mock.patch("deployment.deployment._pr_exists", return_value=False),
            mock.patch("deployment.deployment._worktree_is_active", return_value=True),
            mock.patch("deployment.deployment._session_write_is_recent", return_value=False),
        ):
            issue = {"number": 7, "title": "x",
                     "url": "https://github.com/owner/repo-a/issues/7"}
            assert _is_session_dead(str(tmp_path), "owner/repo-a", 7, provider, issue) is False

    def test_nao_morta_se_escrita_recente(self, tmp_path: Path) -> None:
        provider = self._provider_running(minutes_ago=120)
        with (
            mock.patch("deployment.deployment._pr_exists", return_value=False),
            mock.patch("deployment.deployment._worktree_is_active", return_value=False),
            mock.patch("deployment.deployment._session_write_is_recent", return_value=True),
        ):
            issue = {"number": 7, "title": "x",
                     "url": "https://github.com/owner/repo-a/issues/7"}
            assert _is_session_dead(str(tmp_path), "owner/repo-a", 7, provider, issue) is False

    def test_nao_morta_se_running_recente(self, tmp_path: Path) -> None:
        """crewflow:running há menos que o timeout → não morta."""
        provider = self._provider_running(minutes_ago=5)  # <40min
        with (
            mock.patch("deployment.deployment._pr_exists", return_value=False),
            mock.patch("deployment.deployment._worktree_is_active", return_value=False),
            mock.patch("deployment.deployment._session_write_is_recent", return_value=False),
        ):
            issue = {"number": 7, "title": "x",
                     "url": "https://github.com/owner/repo-a/issues/7"}
            assert _is_session_dead(str(tmp_path), "owner/repo-a", 7, provider, issue) is False


class TestFailClosedAmbiguity:
    """(4) FAIL-CLOSED em sinal incerto — não declara morta, não despacha."""

    def test_state_comment_ilegivel_nao_declara_morta(self, tmp_path: Path) -> None:
        provider = mock.MagicMock()
        provider.get_state_comment.side_effect = RuntimeError("gh timeout")
        with (
            mock.patch("deployment.deployment._pr_exists", return_value=False),
            mock.patch("deployment.deployment._worktree_is_active", return_value=False),
            mock.patch("deployment.deployment._session_write_is_recent", return_value=False),
        ):
            issue = {"number": 7, "title": "x",
                     "url": "https://github.com/owner/repo-a/issues/7"}
            # idade de running desconhecida → fail-closed
            assert _is_session_dead(str(tmp_path), "owner/repo-a", 7, provider, issue) is False

    def test_worktree_incerto_nao_declara_morta(self, tmp_path: Path) -> None:
        provider = mock.MagicMock()
        provider.get_state_comment.return_value = _running_state_body(minutes_ago=120)
        with (
            mock.patch("deployment.deployment._pr_exists", return_value=False),
            mock.patch("deployment.deployment._worktree_is_active", return_value=None),
            mock.patch("deployment.deployment._session_write_is_recent", return_value=False),
        ):
            issue = {"number": 7, "title": "x",
                     "url": "https://github.com/owner/repo-a/issues/7"}
            assert _is_session_dead(str(tmp_path), "owner/repo-a", 7, provider, issue) is False

    def test_gate_provider_incerto_enfileira(self) -> None:
        """_dev_dispatch_allowed com estado incerto → 'queue' (não despacha)."""
        ctx = mock.MagicMock()
        provider = mock.MagicMock()
        provider.list_by_state.side_effect = RuntimeError("gh down")
        cfg = {"dev_root": "/tmp/dev", "max_concurrent_tasks": 2}
        issue = {"number": 7, "title": "x",
                 "url": "https://github.com/owner/repo-a/issues/7"}
        with mock.patch("deployment.deployment._pr_exists", return_value=False):
            decision = _dev_dispatch_allowed(
                ctx, provider, "owner/repo-a", issue, cfg, one_per_repo=True,
            )
        assert decision == "queue"


class TestRecoverDeadSession:
    """(2b) RECUPERAÇÃO — remove crewflow:running e recoloca em crewflow:todo."""

    def test_recover_move_para_todo_e_remove_running(self) -> None:
        provider = mock.MagicMock()
        provider.get_work_item.return_value = {
            "key": "https://github.com/owner/repo-a/issues/7",
            "title": "[repo-a] busy",
            "labels": ["crewflow:dev", "crewflow:running"],
        }
        provider.get_state_comment.return_value = _running_state_body(minutes_ago=120)
        ctx = mock.MagicMock()
        issue = {"number": 7, "title": "[repo-a] busy",
                 "url": "https://github.com/owner/repo-a/issues/7"}

        _recover_dead_session(provider, "owner/repo-a", issue, ctx, chat_id="C1")

        provider.set_labels.assert_called_once()
        _proj, _key, new_labels = provider.set_labels.call_args[0]
        assert "crewflow:running" not in new_labels
        assert "crewflow:dev" not in new_labels
        assert "crewflow:todo" in new_labels
        provider.upsert_state_comment.assert_called_once()
        ctx.notify.assert_called_once()


class TestAntiDoubleDispatch:
    """(3) ANTI-DUPLO-DISPATCH — backstop curto impede redisparo em segundos."""

    def test_backstop_impede_redisparo(self) -> None:
        ctx = mock.MagicMock()
        provider = mock.MagicMock()
        provider.list_by_state.return_value = []  # repo livre por estado
        cfg = {"dev_root": "/tmp/dev", "max_concurrent_tasks": 2}
        issue = {"number": 7, "title": "x",
                 "url": "https://github.com/owner/repo-a/issues/7"}
        with (
            mock.patch("deployment.deployment._pr_exists", return_value=False),
            # escrita da sessão dentro do backstop → 'skip'
            mock.patch("deployment.deployment._session_write_is_recent", return_value=True),
        ):
            decision = _dev_dispatch_allowed(
                ctx, provider, "owner/repo-a", issue, cfg, one_per_repo=True,
            )
        assert decision == "skip"

    def test_sem_backstop_permite_dispatch(self) -> None:
        ctx = mock.MagicMock()
        provider = mock.MagicMock()
        provider.list_by_state.return_value = []
        cfg = {"dev_root": "/tmp/dev", "max_concurrent_tasks": 2}
        issue = {"number": 7, "title": "x",
                 "url": "https://github.com/owner/repo-a/issues/7"}
        with (
            mock.patch("deployment.deployment._pr_exists", return_value=False),
            mock.patch("deployment.deployment._session_write_is_recent", return_value=None),
            mock.patch("deployment.deployment._resource_headroom_ok", return_value=True),
        ):
            decision = _dev_dispatch_allowed(
                ctx, provider, "owner/repo-a", issue, cfg, one_per_repo=True,
            )
        assert decision == "dispatch"

    def test_pr_duplicado_gera_skip(self) -> None:
        ctx = mock.MagicMock()
        provider = mock.MagicMock()
        cfg = {"dev_root": "/tmp/dev", "max_concurrent_tasks": 2}
        issue = {"number": 7, "title": "x",
                 "url": "https://github.com/owner/repo-a/issues/7"}
        with mock.patch("deployment.deployment._pr_exists", return_value=True):
            decision = _dev_dispatch_allowed(
                ctx, provider, "owner/repo-a", issue, cfg, one_per_repo=True,
            )
        assert decision == "skip"


class TestDeadSessionDoesNotTrapQueue:
    """(5) SESSÃO MORTA NÃO PRENDE A FILA — recuperação libera o próximo ciclo."""

    def test_repo_ocupado_com_sessao_morta_e_recuperado(self) -> None:
        """Repo ocupado por issue morta → _dev_dispatch_allowed recupera e enfileira;
        o próximo ciclo (repo livre) despacha."""
        ctx = mock.MagicMock()
        provider = mock.MagicMock()
        # Repo ocupado: issue #9 em running.
        provider.list_by_state.side_effect = lambda repo, state: (
            [_running_item("https://github.com/owner/repo-a/issues/9")]
            if state == "crewflow:running" else []
        )
        provider.get_work_item.return_value = {
            "key": "https://github.com/owner/repo-a/issues/9",
            "title": "[repo-a] dead",
            "labels": ["crewflow:dev", "crewflow:running"],
        }
        provider.get_state_comment.return_value = _running_state_body(minutes_ago=120)
        cfg = {"dev_root": "/tmp/dev", "max_concurrent_tasks": 2}
        issue = {"number": 10, "title": "x",
                 "url": "https://github.com/owner/repo-a/issues/10"}

        with (
            mock.patch("deployment.deployment._pr_exists", return_value=False),
            mock.patch("deployment.deployment._worktree_is_active", return_value=False),
            mock.patch("deployment.deployment._session_write_is_recent", return_value=False),
        ):
            # Ciclo 1: repo ocupado por sessão morta → recupera, mas enfileira.
            decision1 = _dev_dispatch_allowed(
                ctx, provider, "owner/repo-a", issue, cfg, one_per_repo=True,
            )
        assert decision1 == "queue"
        # A recuperação recolocou a issue morta em crewflow:todo.
        provider.set_labels.assert_called_once()
        _proj, _key, new_labels = provider.set_labels.call_args[0]
        assert "crewflow:running" not in new_labels
        assert "crewflow:todo" in new_labels

        # Ciclo 2: repo agora livre (issue recuperada saiu de running) → despacha.
        provider2 = mock.MagicMock()
        provider2.list_by_state.return_value = []
        with (
            mock.patch("deployment.deployment._pr_exists", return_value=False),
            mock.patch("deployment.deployment._session_write_is_recent", return_value=None),
            mock.patch("deployment.deployment._resource_headroom_ok", return_value=True),
        ):
            decision2 = _dev_dispatch_allowed(
                ctx, provider2, "owner/repo-a", issue, cfg, one_per_repo=True,
            )
        assert decision2 == "dispatch"

    def test_recuperacao_via_mesmo_provider_libera_redispatch(self) -> None:
        """(finding 4) Prova end-to-end: a ESCRITA REAL de labels feita pela
        recuperação (set_labels no MESMO provider) é o que faz o próximo
        _dev_dispatch_allowed retornar 'dispatch'.

        Em vez de trocar por um provider "fresco" no ciclo 2, mantemos UM ÚNICO
        provider com estado de labels mutável: list_by_state lê o estado atual,
        set_labels muta esse estado. Assim, a transição running→todo escrita por
        _recover_dead_session realimenta a próxima consulta de estado."""
        ctx = mock.MagicMock()
        dead_key = "https://github.com/owner/repo-a/issues/9"

        # Estado de labels compartilhado (source of truth do provider mock).
        label_store: dict[str, list[str]] = {
            dead_key: ["crewflow:dev", "crewflow:running"],
        }

        def _item_for(key: str) -> dict:
            return {
                "key": key,
                "title": "[repo-a] dead",
                "labels": list(label_store.get(key, [])),
                "state_comment": None,
                "parent_key": None,
            }

        provider = mock.MagicMock()

        # list_by_state deriva do estado ATUAL de label_store (como um provider real).
        def _list_by_state(repo: str, state: str) -> list[dict]:
            return [
                _item_for(key)
                for key, labels in label_store.items()
                if state in labels
            ]

        provider.list_by_state.side_effect = _list_by_state
        provider.get_work_item.side_effect = lambda repo, num: _item_for(dead_key)
        provider.get_state_comment.return_value = _running_state_body(minutes_ago=120)

        # set_labels ESCREVE de volta no estado compartilhado (efeito real).
        def _set_labels(repo: str, key: str, labels: list[str]) -> None:
            label_store[key] = list(labels)

        provider.set_labels.side_effect = _set_labels

        cfg = {"dev_root": "/tmp/dev", "max_concurrent_tasks": 2}
        issue = {"number": 10, "title": "x",
                 "url": "https://github.com/owner/repo-a/issues/10"}

        # Sanidade: antes da recuperação, o repo está ocupado por estado.
        assert _state_allows_dispatch(provider, "owner/repo-a", one_per_repo=True) is False

        # Ciclo 1: sessão morta é detectada e recuperada (escreve labels reais);
        # o ciclo atual ainda enfileira para não competir com a recuperação.
        with (
            mock.patch("deployment.deployment._pr_exists", return_value=False),
            mock.patch("deployment.deployment._worktree_is_active", return_value=False),
            mock.patch("deployment.deployment._session_write_is_recent", return_value=False),
        ):
            decision1 = _dev_dispatch_allowed(
                ctx, provider, "owner/repo-a", issue, cfg, one_per_repo=True,
            )
        assert decision1 == "queue"

        # A escrita real removeu running/dev e adicionou todo NO MESMO provider.
        assert label_store[dead_key] == ["crewflow:todo"]
        # E o estado agora reporta o repo como LIVRE (sem trocar de provider).
        assert _state_allows_dispatch(provider, "owner/repo-a", one_per_repo=True) is True

        # Ciclo 2: MESMO provider, cujo estado foi realimentado pela recuperação
        # do ciclo 1 → o gate real retorna 'dispatch' por causa da escrita real.
        with (
            mock.patch("deployment.deployment._pr_exists", return_value=False),
            mock.patch("deployment.deployment._session_write_is_recent", return_value=None),
            mock.patch("deployment.deployment._resource_headroom_ok", return_value=True),
        ):
            decision2 = _dev_dispatch_allowed(
                ctx, provider, "owner/repo-a", issue, cfg, one_per_repo=True,
            )
        assert decision2 == "dispatch"
