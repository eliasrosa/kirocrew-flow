"""Hooks de ciclo de vida do app kirocrew-flow (in-gateway)."""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

_LOOP_TASKS: list[asyncio.Task] = []  # type: ignore[type-arg]


def on_startup() -> None:
    """Invocado quando o app é habilitado. Inicia os loops asyncio de polling."""
    app_root = Path(__file__).parent.parent
    if str(app_root) not in sys.path:
        sys.path.insert(0, str(app_root))

    try:
        from backend.server import _run_stage_loop
        from deployment.deployment import (
            _STAGE_CONFLITO,
            _STAGE_DEV,
            _STAGE_MERGE,
            _STAGE_REVIEWER,
        )

        loop = asyncio.get_event_loop()
        _LOOP_TASKS.extend(
            [
                loop.create_task(
                    _run_stage_loop(
                        _STAGE_DEV,
                        int(os.environ.get("CREWFLOW_DEV_INTERVAL", "300")),
                    )
                ),
                loop.create_task(
                    _run_stage_loop(
                        _STAGE_REVIEWER,
                        int(os.environ.get("CREWFLOW_REVIEWER_INTERVAL", "180")),
                    )
                ),
                loop.create_task(
                    _run_stage_loop(
                        _STAGE_MERGE,
                        int(os.environ.get("CREWFLOW_MERGE_INTERVAL", "120")),
                    )
                ),
                loop.create_task(
                    _run_stage_loop(
                        _STAGE_CONFLITO,
                        int(os.environ.get("CREWFLOW_CONFLITO_INTERVAL", "300")),
                    )
                ),
            ]
        )
        print("[kirocrew-flow] on_startup: 4 loops asyncio iniciados", flush=True)
    except Exception as exc:
        print(f"[kirocrew-flow] on_startup error: {exc}", flush=True)


def on_shutdown() -> None:
    """Invocado quando o app é desabilitado. Cancela os loops asyncio."""
    for task in _LOOP_TASKS:
        task.cancel()
    _LOOP_TASKS.clear()
    print("[kirocrew-flow] on_shutdown: loops cancelados", flush=True)
