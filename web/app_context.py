"""Shared application context — single module-level instance.

Eliminates bidirectional dependency between main.py and web/app.py:
both modules import `ctx` from here; main.py populates it at startup.
"""

from __future__ import annotations

from typing import Any


class AppContext:
    """Holds all runtime singletons previously scattered as module globals."""

    def __init__(self):
        # Injected from main.py
        self.coordinator: Any = None
        self.config: dict = {}
        self.notifiers: list = []
        self.scheduler: Any = None

        # Lazily initialized within web/app.py
        self.vector_store: Any = None
        self.hybrid_searcher: Any = None
        self.alert_store: Any = None
        self.story_watch_store: Any = None
        self.chat_agent: Any = None
        self.track_store: Any = None
        self.memory_manager: Any = None

        # Dashboard state
        self.dashboard_token: str | None = None
        self.last_run_time: Any = None
        self.report_last_result: Any = None

        # Finalized flag — set after main.py finishes setup, before serving
        self._ready = False

    @property
    def ready(self) -> bool:
        return self._ready

    def mark_ready(self):
        self._ready = True


ctx = AppContext()
