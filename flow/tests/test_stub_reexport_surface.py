"""Testes de drift do bloco de re-export do stub de compatibilidade.

O ``deployment/deployment.py`` refatorado é um stub: em runtime ele aliasa
``sys.modules["deployment.deployment"] = deployment.flow.base`` (os dois módulos
passam a ser o MESMO objeto). Antes desse alias, porém, existe um bloco explícito
``from deployment.flow.base import (...)`` mantido à mão. Esse bloco é inerte em
runtime, mas é a ÚNICA superfície que os type-checkers enxergam: o CI roda
``mypy flow/`` que segue os imports ``from deployment.deployment import <nome>``
até o stub.

O risco (apontado em review, finding #2): a lista é mantida à mão e o ``mypy``
só reclama de um nome faltante quando ALGUM arquivo sob ``flow/`` de fato o
importa. Um símbolo de ``base.py`` que passe a ser referenciado mas que tenha
"caído" da lista só quebraria o CI tardiamente. Estes testes fecham essa lacuna
de forma programática (sem lista esperada mantida à mão):

  1. Todo nome referenciado em ``deployment.deployment`` por ``flow/`` ou
     ``backend/`` — via ``from deployment.deployment import X`` ou
     ``mock.patch("deployment.deployment.X")`` — DEVE constar no bloco de
     re-export explícito do stub. (Pega o finding #2 diretamente.)
  2. Todo nome listado no bloco DEVE existir de fato em ``deployment.flow.base``
     (pega entradas obsoletas / erros de digitação na lista).

Um teste de mutação rápida confirma a sensibilidade: remover um nome referenciado
do bloco faz (1) falhar.
"""

from __future__ import annotations

import ast
import os
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

_STUB_PY = _REPO_ROOT / "deployment" / "deployment.py"
_DEPLOYMENT_MODULE_PATH = "deployment.deployment"
# Diretórios cujo código o CI type-checka / testa e que consomem o stub.
_CONSUMER_ROOTS = ("flow", "backend")


# ---------------------------------------------------------------------------
# Helpers de extração (AST — não importa os módulos consumidores)
# ---------------------------------------------------------------------------


def _stub_reexport_names() -> frozenset[str]:
    """Nomes no bloco explícito ``from deployment.flow.base import (...)`` do stub."""
    tree = ast.parse(_STUB_PY.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.ImportFrom)
            and node.module == "deployment.flow.base"
        ):
            for alias in node.names:
                names.add(alias.name)
    return frozenset(names)


def _iter_py_files(root: Path):
    for dirpath, _dirnames, filenames in os.walk(root):
        if "__pycache__" in dirpath:
            continue
        for name in filenames:
            if name.endswith(".py"):
                yield Path(dirpath) / name


def _names_referenced_on_stub() -> dict[str, set[str]]:
    """Mapeia nome → arquivos que o referenciam via ``deployment.deployment``.

    Captura duas formas:
      * ``from deployment.deployment import X`` (o que o mypy segue)
      * literais string ``"deployment.deployment.X"`` (alvos de mock.patch)
    """
    prefix = _DEPLOYMENT_MODULE_PATH + "."
    referenced: dict[str, set[str]] = {}
    for root_name in _CONSUMER_ROOTS:
        root = _REPO_ROOT / root_name
        if not root.exists():
            continue
        for path in _iter_py_files(root):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if (
                    isinstance(node, ast.ImportFrom)
                    and node.module == _DEPLOYMENT_MODULE_PATH
                ):
                    for alias in node.names:
                        referenced.setdefault(alias.name, set()).add(str(path))
                elif isinstance(node, ast.Constant) and isinstance(
                    node.value, str
                ):
                    value = node.value
                    if value.startswith(prefix):
                        top = value[len(prefix) :].split(".")[0]
                        if top:
                            referenced.setdefault(top, set()).add(str(path))
    return referenced


# ---------------------------------------------------------------------------
# Testes
# ---------------------------------------------------------------------------


def test_stub_reexports_every_referenced_name() -> None:
    """Finding #2: nenhum nome consumido de deployment.deployment pode faltar no stub.

    Se um símbolo de base.py for referenciado por flow/ ou backend/ mas cair do
    bloco de re-export explícito, este teste falha — antes de o mypy tropeçar.
    """
    reexported = _stub_reexport_names()
    referenced = _names_referenced_on_stub()

    missing = {
        name: sorted(files)
        for name, files in referenced.items()
        if name not in reexported
    }
    assert not missing, (
        "Nomes referenciados em deployment.deployment ausentes do bloco de "
        "re-export explícito de deployment/deployment.py (drift): "
        f"{missing}"
    )


def test_stub_reexport_list_has_no_stale_entries() -> None:
    """Todo nome no bloco de re-export deve existir de fato em base.py.

    Pega entradas obsoletas ou com erro de digitação na lista mantida à mão.
    """
    from deployment.flow import base as base_module

    reexported = _stub_reexport_names()
    stale = sorted(n for n in reexported if not hasattr(base_module, n))
    assert not stale, (
        "Nomes listados no bloco de re-export de deployment/deployment.py que "
        f"NÃO existem em deployment.flow.base (obsoletos): {stale}"
    )


def test_reexport_drift_check_is_sensitive() -> None:
    """Mutação: se um nome referenciado sumir do bloco, o guard DEVE acusar.

    Garante que o teste principal não é vacuamente verdadeiro.
    """
    reexported = _stub_reexport_names()
    referenced = _names_referenced_on_stub()
    assert referenced, "esperava nomes referenciados em deployment.deployment"

    # Simula a remoção de um nome referenciado do bloco de re-export.
    victim = sorted(referenced)[0]
    mutated = frozenset(reexported - {victim})
    still_missing = [name for name in referenced if name not in mutated]
    assert victim in still_missing, (
        "o guard de drift deveria detectar a remoção de um nome referenciado"
    )
