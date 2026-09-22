"""Runtime container — wires every subsystem together (spec §2, §13).

:class:`Runtime` owns:
    * Settings + Database (SQLite via SQLAlchemy)
    * EventBus                (real-time agent.listening/executing/... )
    * ScreenObserver          (screenshots/OCR/active window)
    * AI / STT / TTS / Browser providers
    * ToolRegistry            (85+ tools, plugin discovery)
    * PermissionManager       (allow/ask/deny + confirmations)
    * EmergencyStop latch
    * Planner / Executor / Verifier / MemoryContext
    * TaskStore + TaskManager (state machine + single-flight execution)
    * WorkflowEngine
    * Diagnostics + SelfRepair

Tests construct isolated instances using ``for_testing=True`` with an in-memory
SQLite database and the mock AI provider so every layer runs offline.
"""
from __future__ import annotations

import time

from agent.executor import Executor
from agent.memory import MemoryContext
from agent.session import SessionContext
from agent.task_manager import TaskManager
from agent.task_store import TaskStore
from agent.undo import UndoJournal
from agent.verifier import Verifier
from core.config import Settings
from core.locks import ResourceLocks
from core.logging_config import EventLogger
from core.startup_check import run_startup_checks, summarise
from database.service import SettingsService
from database.session import Database
from events import EventBus
from observer import ScreenObserver
from permissions import ConfirmationStore, EmergencyStop, PermissionManager
from planner import create_planner
from providers.ai import AIProvider, create_ai_provider
from providers.browser import create_browser_engine
from providers.stt import create_stt_provider
from providers.tts import create_tts_provider
from tools import ToolRegistry, build_tool_context, register_builtin_tools
from workflows import WorkflowEngine


class Runtime:
    """The assembled NOVA backend. One instance per process."""

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        db_url: str | None = None,
        for_testing: bool = False,
        force_heuristic: bool = False,
    ) -> None:
        self.for_testing = for_testing
        self.settings = settings or Settings()
        if for_testing:
            self.settings.load({
                "ai.provider": "mock",
                "voice.tts_provider": "none",
                "voice.stt_provider": "mock",
                "browser.engine": "mock",
                "permissions.default_mode": "ask",
                "storage.data_dir": "/tmp/nova-test-data",
            })
            if not db_url:
                # isolate tests from the user's real NOVA database
                db_url = "sqlite://"
        if db_url:
            self.settings.load({"database.url": db_url})

        # database (+ additive migrations so upgrades never lose data, V2 §67)
        self.database = Database(url=self.settings.get_str("database.url", "") or None)
        self.database.create_all()
        self.migrations_applied = self.database.apply_migrations()
        self.settings_service = SettingsService(self.database, self.settings)
        try:
            self.settings_service.load()
        except Exception:
            pass

        # event bus + logger
        self.event_bus = EventBus()
        self.logger = EventLogger("nova")

        # observer
        self.observer = ScreenObserver(self.settings, self.event_bus)

        # providers
        self.ai: AIProvider = create_ai_provider(self.settings)
        self.stt = create_stt_provider(self.settings)
        self.tts = create_tts_provider(self.settings)
        self.browser = create_browser_engine(self.settings)

        # permissions + emergency
        self.confirmation_store = ConfirmationStore()
        self.permissions = PermissionManager(
            self.settings, session_factory=self.database.session_factory,
            store=self.confirmation_store)
        self.emergency = EmergencyStop()

        # tools
        self.tool_context = build_tool_context(
            self.settings, event_bus=self.event_bus, observer=self.observer,
            confirmations=self.confirmation_store,
            session_factory=self.database.session_factory, logger=self.logger)
        self.registry = ToolRegistry(self.tool_context)
        register_builtin_tools(self.registry, self.tool_context)

        # memory + session context
        self.memory = MemoryContext(session_factory=self.database.session_factory)
        self.session = SessionContext()

        # undo journal + resource locks (V2 §13/§30) — persisted under data dir
        journal_path = None
        try:
            journal_path = self.settings.data_dir / "undo_journal.json"
        except Exception:
            journal_path = None
        self.undo_journal = UndoJournal(journal_path)
        self.locks = ResourceLocks()

        # expose V2 services to tools (DI through the shared ToolContext)
        self.tool_context.undo_journal = self.undo_journal
        self.tool_context.locks = self.locks
        self.tool_context.runtime = self

        # planner / executor / verifier
        self.planner = create_planner(self.settings, self.registry, self.ai,
                                      self.memory, force_heuristic=force_heuristic,
                                      session=self.session)
        self.store = TaskStore(session_factory=self.database.session_factory)
        # tasks left in-flight by a previous process can never finish —
        # mark them failed so history/dashboard never show phantom 'executing' rows
        if self.database.session_factory is not None:
            from database.service import reap_interrupted_tasks
            with self.database.session_factory() as s:
                reap_interrupted_tasks(s)
        self.executor = Executor(self.registry, self.permissions, self.settings,
                                 self.event_bus, observer=self.observer)
        self.verifier = Verifier(self.observer, self.settings)
        self.workflows = WorkflowEngine(self.registry, self.executor, self.event_bus)

        # task manager
        self.tasks = TaskManager(
            planner=self.planner, executor=self.executor, store=self.store,
            permissions=self.permissions, emergency=self.emergency,
            event_bus=self.event_bus, memory=self.memory, verifier=self.verifier,
            tts=self.tts, settings=self.settings, logger=self.logger,
            undo_journal=self.undo_journal, session=self.session)

        # observation: before/after change detection (V2 §10/§11)
        from observer.changes import ChangeDetector
        self.changes = ChangeDetector(self.observer)

        # startup configuration validation (V2 §66) — never raises
        self.startup_checks = run_startup_checks(self.settings)
        self.startup_summary = summarise(self.startup_checks)

        # update checker (V2 §54) — report-only; never installs silently
        from core.updater import UpdateChecker
        self.updater = UpdateChecker(self.settings)

        self.started = time.time()

    # ------------------------------------------------------------------
    @property
    def state(self) -> str:
        return self.tasks.state

    def uptime(self) -> float:
        return time.time() - self.started

    def status(self) -> dict:
        import platform
        import sys
        return {
            "state": self.state,
            "active_task": self.tasks.active_task,
            "queued": len(self.tasks.queue),
            "queued_tasks": self.tasks.queue,
            "uptime_seconds": round(time.time() - self.started, 1),
            "version": "2.0.0",
            "platform": platform.system(),
            "python": sys.version.split()[0],
            "ai_provider": self.settings.get_str("ai.provider", "openai"),
            "stt_provider": self.settings.get_str("voice.stt_provider", "faster-whisper"),
            "tts_provider": self.settings.get_str("voice.tts_provider", "pyttsx3"),
            "emergency_active": self.emergency.active,
            "tool_count": len(self.registry.names()),
            "startup_ok": self.startup_summary["ok"],
            "startup_errors": len(self.startup_summary["errors"]),
        }

    # ------------------------------------------------------------------
    def diagnostics(self) -> dict:
        from diagnostics.checks import run_diagnostics
        return run_diagnostics(self)

    def self_repair(self) -> dict:
        from diagnostics.self_repair import SelfRepair
        return SelfRepair(self).run()

    # ------------------------------------------------------------------
    async def execute(self, command: str, *, mode: str = "smart",
                      session_id: str | None = None) -> str:
        return await self.tasks.execute(command, mode=mode, session_id=session_id)

    async def wait(self, task_id: str, timeout: float = 180.0) -> dict:
        return await self.tasks.wait(task_id, timeout)

    def shutdown(self) -> None:
        try:
            self.tts.close()
        except Exception:
            pass


# Backend singletons (constructed once per process by main.py / app factory)
_runtime_singleton: Runtime | None = None


def get_runtime(**kwargs) -> Runtime:
    """Return the process-wide runtime (creating it on first use)."""
    global _runtime_singleton
    if _runtime_singleton is None:
        _runtime_singleton = Runtime(**kwargs)
    return _runtime_singleton


def reset_runtime() -> None:
    global _runtime_singleton
    _runtime_singleton = None
