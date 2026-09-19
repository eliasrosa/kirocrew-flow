"""Testes de flow/domain/state.py.

Todos sem mock — é exatamente o ponto da arquitetura hexagonal.
Os casos vieram do desenho dos 4 fluxos (feature, bug, hotfix, débito).
"""

import pytest

from flow.domain.state import (
    DISPATCH_TRIGGER,
    STOP_MODIFIERS,
    EstadoAmbiguo,
    Modifier,
    State,
    can_transition,
    is_dispatchable,
    parse_modifiers,
    parse_state,
    transition_state,
)

STATE_VALUES = {s.value for s in State}

# ---------------------------------------------------------------------------
# Constantes e enum
# ---------------------------------------------------------------------------

class TestStateConstants:
    def test_gatilho_e_todo(self) -> None:
        assert DISPATCH_TRIGGER is State.TODO

    def test_stop_modifiers_contem_blocked_e_running(self) -> None:
        assert Modifier.BLOCKED in STOP_MODIFIERS
        assert Modifier.RUNNING in STOP_MODIFIERS

    def test_hml_bypass_nao_e_stop_modifier(self) -> None:
        """hml-bypass é exceção auditada, não impede dispatch."""
        assert Modifier.HML_BYPASS not in STOP_MODIFIERS

    def test_reviewed_nao_e_stop_modifier(self) -> None:
        """reviewed é lock anti-loop, não impede dispatch da issue."""
        assert Modifier.REVIEWED not in STOP_MODIFIERS

    def test_valores_das_labels_tem_prefixo_crewflow(self) -> None:
        for s in State:
            assert s.value.startswith("crewflow:"), s
        for m in Modifier:
            assert m.value.startswith("crewflow:"), m


class TestStateOrdering:
    def test_spec_vem_antes_de_done(self) -> None:
        assert State.SPEC < State.DONE

    def test_todo_vem_antes_de_review(self) -> None:
        assert State.TODO < State.REVIEW

    def test_qa_vem_depois_de_review(self) -> None:
        assert State.QA > State.REVIEW

    def test_lista_de_estados_na_ordem_canonica(self) -> None:
        esperado = [
            State.SPEC, State.READY, State.TODO,
            State.DEV, State.REVIEW, State.QA, State.DONE,
        ]
        assert list(State) == esperado


# ---------------------------------------------------------------------------
# parse_state
# ---------------------------------------------------------------------------

class TestParseState:
    def test_retorna_none_sem_label_de_estado(self) -> None:
        assert parse_state({"bug", "phase-1", "enhancement"}) is None

    def test_retorna_none_com_set_vazio(self) -> None:
        assert parse_state(set()) is None

    def test_extrai_estado_correto(self) -> None:
        assert parse_state({"crewflow:dev", "phase-1"}) is State.DEV

    def test_ignora_labels_nao_relacionadas(self) -> None:
        labels = {"crewflow:qa", "crewflow:running", "documentation"}
        assert parse_state(labels) is State.QA

    def test_dois_estados_lancam_erro(self) -> None:
        with pytest.raises(EstadoAmbiguo) as exc_info:
            parse_state({"crewflow:dev", "crewflow:qa"})
        assert "crewflow:dev" in str(exc_info.value)
        assert "crewflow:qa" in str(exc_info.value)

    def test_tres_estados_tambem_lancam_erro(self) -> None:
        with pytest.raises(EstadoAmbiguo):
            parse_state({"crewflow:spec", "crewflow:dev", "crewflow:qa"})

    def test_hml_bypass_nao_e_estado(self) -> None:
        """hml-bypass é modificador, não substitui o estado."""
        resultado = parse_state({"crewflow:qa", "crewflow:hml-bypass"})
        assert resultado is State.QA

    def test_aceita_frozenset(self) -> None:
        labels = frozenset({"crewflow:ready"})
        assert parse_state(labels) is State.READY


# ---------------------------------------------------------------------------
# parse_modifiers
# ---------------------------------------------------------------------------

class TestParseModifiers:
    def test_retorna_frozenset_vazio_sem_modificadores(self) -> None:
        assert parse_modifiers({"crewflow:dev", "phase-1"}) == frozenset()

    def test_extrai_blocked(self) -> None:
        result = parse_modifiers({"crewflow:blocked", "crewflow:dev"})
        assert Modifier.BLOCKED in result

    def test_extrai_multiplos_modificadores(self) -> None:
        labels = {"crewflow:running", "crewflow:reviewed", "crewflow:dev"}
        result = parse_modifiers(labels)
        assert result == frozenset({Modifier.RUNNING, Modifier.REVIEWED})

    def test_ignora_labels_desconhecidas(self) -> None:
        labels = {"crewflow:hml-bypass", "something:unknown", "phase-1"}
        result = parse_modifiers(labels)
        assert result == frozenset({Modifier.HML_BYPASS})

    def test_retorna_frozenset(self) -> None:
        result = parse_modifiers({"crewflow:blocked"})
        assert isinstance(result, frozenset)


# ---------------------------------------------------------------------------
# is_dispatchable
# ---------------------------------------------------------------------------

class TestIsDispatchable:
    def test_todo_sem_modificadores_e_despachavel(self) -> None:
        assert is_dispatchable(State.TODO, frozenset())

    def test_todo_com_blocked_nao_e_despachavel(self) -> None:
        """blocked tem prioridade sobre o estado gatilho."""
        assert not is_dispatchable(State.TODO, frozenset({Modifier.BLOCKED}))

    def test_todo_com_running_nao_e_despachavel(self) -> None:
        """outro executor já pegou."""
        assert not is_dispatchable(State.TODO, frozenset({Modifier.RUNNING}))

    def test_dev_nao_e_despachavel(self) -> None:
        assert not is_dispatchable(State.DEV, frozenset())

    def test_spec_nao_e_despachavel(self) -> None:
        assert not is_dispatchable(State.SPEC, frozenset())

    def test_none_nao_e_despachavel(self) -> None:
        """issue fora da esteira."""
        assert not is_dispatchable(None, frozenset())

    def test_hml_bypass_nao_impede_dispatch(self) -> None:
        """hml-bypass é auditável, não para o dispatch."""
        assert is_dispatchable(State.TODO, frozenset({Modifier.HML_BYPASS}))

    def test_reviewed_nao_impede_dispatch(self) -> None:
        """reviewed é lock anti-loop do review, não do todo."""
        assert is_dispatchable(State.TODO, frozenset({Modifier.REVIEWED}))

    def test_combinacao_de_stop_modifiers(self) -> None:
        mods = frozenset({Modifier.BLOCKED, Modifier.RUNNING})
        assert not is_dispatchable(State.TODO, mods)

    def test_done_nao_e_despachavel(self) -> None:
        assert not is_dispatchable(State.DONE, frozenset())


# ---------------------------------------------------------------------------
# can_transition
# ---------------------------------------------------------------------------

class TestCanTransition:
    def test_avanco_sequencial_valido(self) -> None:
        pares_validos = [
            (State.SPEC,   State.READY),
            (State.READY,  State.TODO),
            (State.TODO,   State.DEV),
            (State.DEV,    State.REVIEW),
            (State.REVIEW, State.QA),
            (State.QA,     State.DONE),
        ]
        for de, para in pares_validos:
            assert can_transition(de, para), f"{de} → {para} deveria ser válido"

    def test_done_e_terminal(self) -> None:
        for outro in State:
            assert not can_transition(State.DONE, outro), (
                f"DONE → {outro} não deveria ser válido"
            )

    def test_retorno_para_dev_valido_apos_review(self) -> None:
        """Gate reprova: volta pro dev."""
        assert can_transition(State.REVIEW, State.DEV)

    def test_retorno_para_dev_valido_apos_qa(self) -> None:
        assert can_transition(State.QA, State.DEV)

    def test_pulo_de_mais_de_um_passo_invalido(self) -> None:
        assert not can_transition(State.SPEC, State.DEV)
        assert not can_transition(State.SPEC, State.TODO)
        assert not can_transition(State.READY, State.DEV)

    def test_spec_nao_pode_voltar_para_dev(self) -> None:
        """DEV é antes de SPEC na order; spec → dev seria pular pra frente de 2."""
        assert not can_transition(State.SPEC, State.DEV)

    def test_todo_nao_volta_para_dev_pois_ja_e_anterior(self) -> None:
        """TODO → DEV é avanço sequencial (válido), não retorno."""
        assert can_transition(State.TODO, State.DEV)


# ---------------------------------------------------------------------------
# transition_state — invariante "1 estado por vez" (issue #107)
# ---------------------------------------------------------------------------

class TestTransitionState:
    def test_todo_para_dev_remove_todo_e_adiciona_dev(self) -> None:
        resultado = transition_state({"crewflow:todo"}, State.DEV)
        assert "crewflow:dev" in resultado
        assert "crewflow:todo" not in resultado

    def test_dev_para_review_remove_dev_e_adiciona_review(self) -> None:
        resultado = transition_state({"crewflow:dev"}, State.REVIEW)
        assert "crewflow:review" in resultado
        assert "crewflow:dev" not in resultado

    def test_dois_estados_colapsam_para_exatamente_um(self) -> None:
        """O bug da #107: entrada com todo E review termina com 1 estado."""
        entrada = {"crewflow:todo", "crewflow:review"}
        resultado = transition_state(entrada, State.QA)
        assert len(resultado & STATE_VALUES) == 1
        assert "crewflow:qa" in resultado
        assert "crewflow:todo" not in resultado
        assert "crewflow:review" not in resultado

    def test_preserva_modificadores(self) -> None:
        entrada = {
            "crewflow:todo",
            "crewflow:running",
            "crewflow:reviewed",
            "crewflow:changes-requested",
            "crewflow:blocked",
        }
        resultado = transition_state(entrada, State.DEV)
        assert "crewflow:running" in resultado
        assert "crewflow:reviewed" in resultado
        assert "crewflow:changes-requested" in resultado
        assert "crewflow:blocked" in resultado
        assert "crewflow:dev" in resultado
        assert "crewflow:todo" not in resultado

    def test_preserva_tipo_e_prioridade(self) -> None:
        entrada = {"crewflow:todo", "crewflow:feature", "crewflow:p2"}
        resultado = transition_state(entrada, State.DEV)
        assert "crewflow:feature" in resultado
        assert "crewflow:p2" in resultado
        assert "crewflow:dev" in resultado

    def test_preserva_labels_estrangeiras(self) -> None:
        entrada = {"crewflow:todo", "phase-1", "documentation"}
        resultado = transition_state(entrada, State.DEV)
        assert "phase-1" in resultado
        assert "documentation" in resultado

    def test_idempotente_aplicado_duas_vezes(self) -> None:
        entrada = {"crewflow:dev", "crewflow:feature", "phase-1"}
        uma = transition_state(entrada, State.REVIEW)
        duas = transition_state(uma, State.REVIEW)
        assert uma == duas

    def test_estado_ja_presente_produz_mesmo_conjunto(self) -> None:
        entrada = {"crewflow:review", "crewflow:running"}
        resultado = transition_state(entrada, State.REVIEW)
        assert resultado == entrada

    def test_exatamente_um_estado_no_resultado(self) -> None:
        entrada = {"crewflow:spec", "crewflow:feature", "phase-1"}
        for alvo in State:
            resultado = transition_state(entrada, alvo)
            assert len(resultado & STATE_VALUES) == 1
            assert alvo.value in resultado

    def test_aceita_lista_como_entrada(self) -> None:
        """deployment passa list[str]."""
        entrada = ["crewflow:todo", "crewflow:p2"]
        resultado = transition_state(entrada, State.DEV)
        assert isinstance(resultado, set)
        assert "crewflow:dev" in resultado
        assert "crewflow:p2" in resultado
        assert "crewflow:todo" not in resultado

    def test_aceita_frozenset_como_entrada(self) -> None:
        """scanner usa frozenset."""
        entrada = frozenset({"crewflow:todo", "crewflow:blocked"})
        resultado = transition_state(entrada, State.DEV)
        assert isinstance(resultado, set)
        assert "crewflow:dev" in resultado
        assert "crewflow:blocked" in resultado

    def test_retorna_novo_conjunto_sem_mutar_entrada(self) -> None:
        entrada = {"crewflow:todo", "crewflow:feature"}
        transition_state(entrada, State.DEV)
        assert entrada == {"crewflow:todo", "crewflow:feature"}
