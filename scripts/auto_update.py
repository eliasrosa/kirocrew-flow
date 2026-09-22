#!/usr/bin/env python3
"""KiroCrew Flow — cron de auto-update do App.

Mantém a instalação do App sincronizada com ``origin/main``: puxa as
alterações mais recentes e reexecuta ``install-cron.sh`` para reinstalar os
scripts de cron em ``~/.kiro/crew/crons/``.

Por que ``__file__`` em vez de um template ``{app_dir}``?
    O gateway do Kiro Crew não oferece suporte verificável a variáveis de
    template (ex.: ``{app_dir}``) no campo ``command``/``script`` dos crons
    declarados no ``app.json`` — não há nada neste repositório que consuma
    esse placeholder (o Makefile fixa ``APP_DIR`` de forma estática e nenhum
    componente expande ``{app_dir}``). Para obter o diretório do App instalado
    de forma robusta, este script se autolocaliza via
    ``pathlib.Path(__file__).resolve().parent.parent`` — a raiz do repo é o
    diretório-pai de ``scripts/``. Assim o cron funciona onde quer que o App
    tenha sido instalado, sem depender de expansão de template do gateway.

O ``run(ctx)`` nunca levanta exceção: uma atualização que falha jamais pode
derrubar o runtime de crons. Erros são reportados via ``ctx.notify`` quando
disponível, ou impressos como fallback.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

# Raiz do App/repo: diretório-pai de scripts/ (autolocalização via __file__,
# já que {app_dir} não é suportado pelo gateway — ver docstring do módulo).
_APP_ROOT = Path(__file__).resolve().parent.parent


def _report(ctx: object, message: str) -> None:
    """Reporta ``message`` via ctx.notify se existir, senão imprime."""
    notify = getattr(ctx, "notify", None)
    if callable(notify):
        try:
            notify(message)
            return
        except Exception:  # notify não pode derrubar o cron
            pass
    print(message)


def run(ctx: object) -> None:
    """Entrypoint do cron ``flow-auto-update``.

    Puxa ``origin/main`` (rebase) e reexecuta ``scripts/install-cron.sh`` a
    partir da raiz autolocalizada do App. Silencioso em caso de sucesso;
    reporta falhas sem nunca levantar exceção.
    """
    steps: list[list[str]] = [
        ["git", "pull", "--rebase", "origin", "main"],
        ["./scripts/install-cron.sh"],
    ]
    for cmd in steps:
        try:
            subprocess.run(
                cmd,
                cwd=_APP_ROOT,
                check=True,
                capture_output=True,
                text=True,
            )
        except subprocess.CalledProcessError as exc:
            _report(
                ctx,
                f"flow-auto-update: comando {cmd!r} falhou "
                f"(rc={exc.returncode}): {exc.stderr or exc.stdout}",
            )
            return
        except OSError as exc:
            _report(ctx, f"flow-auto-update: erro ao executar {cmd!r}: {exc}")
            return
