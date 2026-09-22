"""TaskManager — orchestrates the full agent loop (V2 §4/§5/§30/§31).

State machine:
    IDLE → LISTENING → UNDERSTANDING → PLANNING → EXECUTING →
    (WAITING_CONFIRMATION | PAUSED | OBSERVING) → VERIFYING →
    (RECOVERING) → SPEAKING → COMPLETED | FAILED | CANCELLED

Single-flight execution with a FIFO queue: at most one task controls the
computer (mouse/keyboard/screen) at any time.  Additional tasks are stored
with status ``queued`` and start in submission order when the active task
finishes.  Cancellation, pause/resume and the global emergency stop are
checked between every step.  Confirmations hold the task until the API/UI
resolves them.
"""
from __future__ import annotations

import asyncio
import re
import time
from typing import Any

from agent.executor import Executor
from agent.recovery import classify_failure
from agent.state_machine import InvalidTransition, StateMachine
from agent.task_store import TaskStore
from core.exceptions import (
    ConfirmationRequired,
    EmergencyStop,
    TaskCancelled,
)
from permissions import PermissionManager
from permissions import EmergencyStop as StopLatch
from planner.planner import TaskPlan

# re-exported for backwards compatibility (tests, API)
from agent.state_machine import VALID_STATES  # noqa: F401

RUNNING_STATUSES = {"understanding", "planning", "executing",
                    "waiting_confirmation", "verifying", "paused"}

# Voice interrupt commands (§8: STOP / CANCEL / ABORT).  These must NEVER
# wait behind the task they are meant to kill, so execute() handles them on
# a fast path.  Guarded so ordinary work requests are never hijacked:
#   * commands containing a real path are file operations, not interrupts
#   * commands that START with a task verb ("open stop-motion.txt") are work
_INTERRUPT_RE = re.compile(
    r"\b(stop everything|stop|cancel|abort|kill all|never mind)\b")
_PATH_RE = re.compile(r"(?:^|[\s'\"])(?:/|[A-Za-z]:[\\/])\S")
_TASK_VERB_RE = re.compile(
    r"^(please\s+)?(open|launch|start|create|make|new|delete|remove|move|"
    r"copy|rename|find|locate|download|upload|send|run|build|write|read|"
    r"search|show|list|install|set|take)\b")


def is_interrupt_command(command: str) -> bool:
    low = command.strip().lower()
    if _PATH_RE.search(command):
        return False
    if _TASK_VERB_RE.match(low):
        return False
    return bool(_INTERRUPT_RE.search(low))


class TaskManager:
    def __init__(
        self,
        planner: Any,
        executor: Executor,
        store: TaskStore,
        permissions: PermissionManager,
        emergency: StopLatch,
        event_bus: Any = None,
        memory: Any = None,
        verifier: Any = None,
        tts: Any = None,
        settings: Any = None,
        logger: Any = None,
        undo_journal: Any = None,
        session: Any = None,
    ) -> None:
        self.planner = planner
        self.executor = executor
        self.store = store
        self.permissions = permissions
        self.emergency = emergency
        self.event_bus = event_bus
        self.memory = memory
        self.verifier = verifier
        self.tts = tts
        self.settings = settings
        self.logger = logger
        self.undo_journal = undo_journal
        self.session = session
        self.fsm = StateMachine(on_transition=self._on_transition)
        self._active_task: str | None = None
        self._queue: list[str] = []
        self._cancel_flags: dict[str, asyncio.Event] = {}
        self._pause_flags: dict[str, asyncio.Event] = {}  # set == running
        self._interrupt_counts: dict[str, int] = {}
        self._pending_confirmations: dict[str, dict] = {}
        self._background_tasks: set[asyncio.Future] = set()
        self.started = time.time()

    # ------------------------------------------------------------------
    # state helpers
    # ------------------------------------------------------------------
    @property
    def state(self) -> str:
        return self.fsm.state

    @property
    def active_task(self) -> str | None:
        return self._active_task

    @property
    def queue(self) -> list[str]:
        return list(self._queue)

    def state_history(self, limit: int = 50) -> list[dict]:
        return self.fsm.history(limit)

    def _on_transition(self, previous: str, target: str, data: dict) -> None:
        if self.event_bus:
            payload = dict(data or {})
            payload.update({"from": previous, "to": target})
            self.event_bus.emit(f"agent.{target.lower()}", payload)
            self.event_bus.emit("agent.state_changed", payload)

    def _set_state(self, state: str, **data) -> None:
        try:
            self.fsm.transition(state, **data)
        except InvalidTransition as exc:
            # never let a bookkeeping bug kill a task: report loudly, then
            # force the state so the runtime stays observable (§57).
            if self.logger:
                self.logger.error("invalid state transition blocked",
                                  from_state=exc.current, to_state=exc.requested)
            self._emit("agent.invalid_transition",
                       from_state=exc.current, to_state=exc.requested)
            self.fsm.force(state, reason=str(exc))

    def _emit(self, event: str, **data) -> None:
        if self.event_bus:
            self.event_bus.emit(event, data)

    # ------------------------------------------------------------------
    # confirmation / cancel / pause gates
    # ------------------------------------------------------------------
    def resolve_confirmation(self, task_id: str, approved: bool) -> bool:
        """Called by API when the user answers a confirmation prompt."""
        ev = self._pending_confirmations.get(task_id)
        if ev is None:
            return False
        ev["approved"] = approved
        if ev.get("waiter") and not ev["waiter"].done():
            ev["waiter"].set_result(approved)
        return True

    def cancel(self, task_id: str, reason: str = "user_cancel") -> bool:
        rec = self.store.get(task_id)
        if not rec:
            return False
        status = rec.get("status")
        if status == "queued":
            # drop it from the queue without ever starting it
            if task_id in self._queue:
                self._queue.remove(task_id)
            self.store.update(task_id, status="cancelled", error=reason,
                              finished_at=_now())
            self._cancel_flags.pop(task_id, None)
            self._emit("agent.cancelled", task_id=task_id, reason=reason)
            return True
        self.store.update(task_id, status="cancelled", error=reason)
        flag = self._cancel_flags.get(task_id)
        if flag:
            flag.set()
        pause = self._pause_flags.get(task_id)
        if pause:
            pause.set()  # unblock a paused task so it can exit
        # a task parked on a confirmation must be woken up too — otherwise it
        # holds the single-flight gate until the 300s confirmation timeout
        if task_id in self._pending_confirmations:
            self.resolve_confirmation(task_id, approved=False)
        if self._active_task == task_id:
            self._emit("agent.cancelled", task_id=task_id, reason=reason)
        return True

    def cancel_active(self, reason: str = "user_cancel") -> bool:
        if self._active_task:
            return self.cancel(self._active_task, reason)
        return False

    def cancel_all(self, reason: str = "user_cancel") -> int:
        """Cancel the active task and every queued task (V2 §75)."""
        cancelled = 0
        for tid in list(self._queue):
            if self.cancel(tid, reason):
                cancelled += 1
        if self._active_task and self.cancel(self._active_task, reason):
            cancelled += 1
        return cancelled

    def pause(self, task_id: str) -> bool:
        """Pause *task_id* before its next step (V2 §31)."""
        if task_id != self._active_task:
            return False
        rec = self.store.get(task_id)
        if not rec or rec.get("status") not in RUNNING_STATUSES:
            return False
        ev = self._pause_flags.get(task_id)
        if ev is None or ev.is_set() is False:
            return False  # already paused
        ev.clear()
        self.store.update(task_id, status="paused")
        self._emit("agent.paused", task_id=task_id)
        return True

    def resume(self, task_id: str) -> bool:
        if task_id != self._active_task:
            return False
        ev = self._pause_flags.get(task_id)
        if ev is None or ev.is_set():
            return False
        ev.set()
        self.store.update(task_id, status="executing")
        self._emit("agent.resumed", task_id=task_id)
        return True

    # ------------------------------------------------------------------
    def emergency_stop(self) -> None:
        self.emergency.pull()
        self.fsm.force("CANCELLED", reason="emergency_stop")
        self.cancel_all("emergency_stop")
        self._emit("agent.emergency_stop")

    def release_emergency(self) -> None:
        self.emergency.release()
        self.fsm.reset()

    # ------------------------------------------------------------------
    # main entry point
    # ------------------------------------------------------------------
    async def execute(self, command: str, *, mode: str = "smart",
                      session_id: str | None = None) -> str:
        """Create a task and start it, or queue it when another task holds
        the computer. Returns the task id immediately."""
        if self.emergency.active:
            raise EmergencyStop("Emergency stop active; reset before new tasks.")

        # fast path for voice interrupts (§8/§75): an interrupt must cancel
        # the busy task immediately instead of queueing behind it
        interrupted = 0
        if is_interrupt_command(command):
            interrupted = self.cancel_all("user_interrupt")

        task_id = self.store.create(command, mode)
        flag = asyncio.Event()
        self._cancel_flags[task_id] = flag
        if is_interrupt_command(command):
            # remember how many tasks the fast path already cancelled so the
            # interrupt task reports the truthful total (§75, no fake claims)
            self._interrupt_counts[task_id] = interrupted
        self._emit("agent.listening", task_id=task_id, command=command)

        if self._active_task is not None or self._queue:
            # single-flight gate: the computer is busy -> FIFO queue (§30)
            self._queue.append(task_id)
            self.store.update(task_id, status="queued")
            self._emit("agent.queued", task_id=task_id,
                       position=len(self._queue))
            return task_id

        # claim the gate synchronously: _run() starts on a future loop
        # iteration, so the busy flag must exist before execute() returns
        self._active_task = task_id
        self._spawn(task_id, command, mode, flag)
        return task_id

    def _spawn(self, task_id: str, command: str, mode: str,
               flag: asyncio.Event) -> None:
        t = asyncio.create_task(self._run(task_id, command, mode, flag))
        # keep a strong reference so the task is never GC'd mid-flight
        self._background_tasks.add(t)
        t.add_done_callback(self._background_tasks.discard)

    def _start_next_queued(self) -> None:
        while self._queue:
            tid = self._queue.pop(0)
            rec = self.store.get(tid)
            flag = self._cancel_flags.get(tid)
            if not rec or not flag:
                continue
            if rec.get("status") != "queued":
                continue  # cancelled while waiting
            command = rec.get("command") or ""
            mode = rec.get("mode") or "smart"
            self._active_task = tid  # synchronous re-claim of the gate
            self._spawn(tid, command, mode, flag)
            return

    async def wait(self, task_id: str, timeout: float = 180.0) -> dict:
        started = time.monotonic()
        while time.monotonic() - started < timeout:
            rec = self.store.get(task_id)
            if rec and rec.get("status") in ("completed", "failed", "cancelled"):
                return rec
            await asyncio.sleep(0.05)
        rec = self.store.get(task_id) or {}
        rec["status"] = rec.get("status", "timeout")
        return rec

    # ------------------------------------------------------------------
    async def _run(self, task_id: str, command: str, mode: str,
                   cancel_flag: asyncio.Event) -> None:
        pause_flag = asyncio.Event()
        pause_flag.set()  # starts un-paused
        self._pause_flags[task_id] = pause_flag
        try:
            self._active_task = task_id
            self.store.update(task_id, status="understanding", started_at=_now())
            self.fsm.force("IDLE", reason="task-start")  # normalise after terminal
            self._set_state("UNDERSTANDING", task_id=task_id)

            # 1. plan
            self._set_state("PLANNING", task_id=task_id)
            self._emit("agent.planning", task_id=task_id)
            plan: TaskPlan = await self.planner.plan(
                command, mode=mode,
                context=(self.memory.conversational_context()
                         if self.memory else None),
                session=self.session)
            self.store.update(task_id, goal=plan.goal,
                              plan=plan.as_dict(), status="executing")
            for i, step in enumerate(plan.steps):
                self.store.add_step(task_id, i, step.tool, step.arguments)

            n = len(plan.steps)
            self._emit("agent.executing", task_id=task_id, steps=n)
            max_retries = self.settings.get_int("automation.max_retries", 2) if self.settings else 2
            repaired = 0
            files: list[str] = []
            apps: list[str] = []
            step_failures: list[str] = []
            last_message: str | None = None

            for idx, step in enumerate(plan.steps):
                await self._gate(task_id, cancel_flag, pause_flag)
                self._set_state("EXECUTING", task_id=task_id, step=idx)

                result = None
                attempt = 0
                while attempt <= max_retries:
                    try:
                        result = await self.executor.execute_step(
                            step, task_id=task_id, step_index=idx,
                            attempt_context={"attempts": attempt})
                        break
                    except ConfirmationRequired as creq:
                        approved = await self._await_confirmation(task_id, creq)
                        if not approved:
                            raise TaskCancelled(f"declined: {creq.tool}") from None
                        # remember the approval only when policy allows it
                        definition = self.executor.registry.get(creq.tool).to_definition()
                        self.permissions.remember_approval(definition)
                    except TaskCancelled:
                        raise
                    except Exception as exc:
                        result = ToolResultLike(str(exc), getattr(exc, "code", "TOOL_ERROR"))
                    attempt += 1
                    if result and not result.success and attempt <= max_retries:
                        failure = classify_failure(step.tool, result.error or "",
                                                   result.data if hasattr(result, "data") else {})
                        self._set_state("RECOVERING", task_id=task_id, step=idx)
                        self._emit("agent.recovering", task_id=task_id, step=idx,
                                   attempt=attempt, kind=failure.kind,
                                   strategy=failure.strategy)
                        repaired += 1
                        await asyncio.sleep(0.4)

                if result is None:
                    result = ToolResultLike("no result", "EXECUTOR_ERROR")
                self.store.update_step(task_id, idx, status="completed" if result.success else "failed",
                                       output=(result.data or {}), error=result.error or "",
                                       attempts=attempt, duration_ms=result.duration_ms or 0)
                if not result.success:
                    step_failures.append(f"{step.tool}: {result.error or 'failed'}")
                if getattr(result, "message", None):
                    last_message = result.message
                if result.data and isinstance(result.data, dict):
                    p = result.data.get("path") or result.data.get("saved_to")
                    if p:
                        files.append(str(p))
                    if result.data.get("opened") or result.data.get("launched"):
                        apps.append(step.tool)

            # 2. verify phase
            await self._gate(task_id, cancel_flag, pause_flag)
            self._set_state("VERIFYING", task_id=task_id)
            self._emit("agent.verifying", task_id=task_id)
            changes = self._collect_changes(task_id)
            summary = self._summarise(plan, files, apps, repaired, changes,
                                      last_message)
            already = self._interrupt_counts.pop(task_id, None)
            if already:
                # the fast path did the real cancellation before this task ran;
                # report the truthful total instead of core.cancel's "0".
                summary = (f"Cancelled {already} task(s). Everything stopped.")
            if step_failures:
                # a task whose steps failed is NOT 'completed' — the stored
                # result must never claim success (V2 §61)
                err = "; ".join(step_failures[:5])
                summary = f"Failed: {err}"
                self.store.update(task_id, status="failed",
                                  result=summary, error=err,
                                  files_changed=files or None, apps_used=apps or None,
                                  errors_repaired=repaired, changes=changes or None,
                                  finished_at=_now())
                self._set_state("FAILED", task_id=task_id)
                self._emit("agent.failed", task_id=task_id, error=err)
                await self._speak(f"I couldn't finish that. {err[:160]}")
            else:
                self.store.update(task_id, status="completed", result=summary,
                                  files_changed=files or None, apps_used=apps or None,
                                  errors_repaired=repaired, changes=changes or None,
                                  finished_at=_now())
                self._set_state("SPEAKING", task_id=task_id)
                self._emit("agent.completed", task_id=task_id, result=summary)
                await self._speak(summary)
            self._update_session(plan)

        except (TaskCancelled, asyncio.CancelledError):
            self.store.update(task_id, status="cancelled", finished_at=_now())
            self.fsm.force("CANCELLED", reason="cancelled")
            self._emit("agent.cancelled", task_id=task_id)
        except EmergencyStop as exc:
            self.store.update(task_id, status="cancelled", error=str(exc), finished_at=_now())
            self.fsm.force("CANCELLED", reason="emergency_stop")
        except Exception as exc:
            self.store.update(task_id, status="failed", error=f"{type(exc).__name__}: {exc}",
                              finished_at=_now())
            self.fsm.force("FAILED", reason=str(exc))
            self._emit("agent.failed", task_id=task_id, error=str(exc))
            if self.logger:
                self.logger.error("task failed", task_id=task_id, error=str(exc))
        finally:
            self._active_task = None
            self._cancel_flags.pop(task_id, None)
            self._pause_flags.pop(task_id, None)
            self._pending_confirmations.pop(task_id, None)
            self.permissions.store.consume(task_id)  # safety net for all exit paths
            self.fsm.reset()
            self._start_next_queued()

    async def _gate(self, task_id: str, cancel_flag: asyncio.Event,
                    pause_flag: asyncio.Event) -> None:
        """Cancellation + pause checkpoint evaluated before every step."""
        if cancel_flag.is_set():
            raise TaskCancelled("cancelled by user")
        if self.emergency.active:
            raise EmergencyStop("emergency stop triggered")
        if not pause_flag.is_set():
            self._set_state("PAUSED", task_id=task_id)
            self._emit("agent.paused", task_id=task_id)
            await pause_flag.wait()
            if cancel_flag.is_set():
                raise TaskCancelled("cancelled while paused")
            if self.emergency.active:
                raise EmergencyStop("emergency stop triggered")

    # ------------------------------------------------------------------
    def _collect_changes(self, task_id: str) -> dict:
        """Aggregate the undo-journal entries for this task (§47)."""
        if not self.undo_journal:
            return {}
        entries = self.undo_journal.entries_for(task_id)
        if not entries:
            return {}
        stats = {"created": 0, "modified": 0, "deleted": 0, "moved": 0,
                 "files": []}
        for e in entries:
            op = e.get("op")
            if op == "create":
                stats["created"] += 1
            elif op == "modify":
                stats["modified"] += 1
            elif op == "delete":
                stats["deleted"] += 1
            elif op in ("move", "rename"):
                stats["moved"] += 1
            p = e.get("path")
            if p and p not in stats["files"]:
                stats["files"].append(p)
        return stats

    def _update_session(self, plan: TaskPlan) -> None:
        if not self.session:
            return
        for step in plan.steps:
            args = step.arguments or {}
            if step.tool.startswith("computer.launch") or step.tool == "windows.open_app":
                app = args.get("app") or args.get("name")
                if app:
                    self.session.set("current_app", str(app))
            if step.tool.startswith("filesystem.") or step.tool.startswith("downloads."):
                p = args.get("path") or args.get("destination") or args.get("target")
                if p:
                    self.session.set("current_file", str(p))
            if step.tool.startswith("browser."):
                url = args.get("url")
                if url:
                    self.session.set("current_site", str(url))
            if step.tool.startswith("whatsapp."):
                contact = args.get("contact") or args.get("name")
                if contact:
                    self.session.set("selected_contact", str(contact))

    # ------------------------------------------------------------------
    async def _await_confirmation(self, task_id: str, creq: ConfirmationRequired) -> bool:
        self._set_state("WAITING_CONFIRMATION", task_id=task_id, tool=creq.tool)
        self.store.update(task_id, status="waiting_confirmation")
        self._emit("agent.waiting_confirmation", task_id=task_id, tool=creq.tool,
                   question=creq.question)
        waiter: asyncio.Future = asyncio.get_running_loop().create_future()
        self._pending_confirmations[task_id] = {"waiter": waiter, "approved": False}
        self._emit("agent.confirmation_requested", task_id=task_id, tool=creq.tool,
                   question=creq.question)
        try:
            approved = await asyncio.wait_for(waiter, timeout=300.0)
        except asyncio.TimeoutError:
            approved = False
        finally:
            # always drop the store entry so /api/confirmations never shows
            # stale prompts for a decision that has already been made
            self.permissions.store.consume(task_id)
        self.store.update(task_id, status="executing")
        self._set_state("EXECUTING", task_id=task_id)
        return bool(approved)

    # ------------------------------------------------------------------
    async def _speak(self, text: str) -> None:
        if not self.tts:
            return
        short = _shorten(text)
        try:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, self.tts.speak, short)
        except Exception:
            pass

    def _summarise(self, plan: TaskPlan, files: list[str], apps: list[str],
                   repaired: int, changes: dict | None = None,
                   last_message: str | None = None) -> str:
        n = len(plan.steps)
        # single-step tasks speak the tool's own message — that is the
        # useful, specific sentence the user asked for (V2 §57)
        if n == 1 and last_message:
            summary = last_message
            if repaired:
                summary += f" (recovered from {repaired} error" \
                           f"{'s' if repaired != 1 else ''})"
            return summary
        parts = [f"Completed {n} action{'s' if n != 1 else ''}."]
        if changes:
            bits = [f"{changes[k]} {v}" for k, v in
                    (("created", "created"), ("modified", "modified"),
                     ("deleted", "deleted"), ("moved", "moved"))
                    if changes.get(k)]
            if bits:
                parts.append("Files: " + ", ".join(bits) + ".")
        elif files:
            parts.append(f"Saved {len(files)} file{'s' if len(files) != 1 else ''} "
                         f"(first: {files[0]}).")
        if repaired:
            parts.append(f"Recovered from {repaired} error{'s' if repaired != 1 else ''}.")
        if len(parts) == 1:
            parts.append("Done.")
        return " ".join(parts)


# ---------------------------------------------------------------------------
def _now() -> str | None:
    from core.utils import iso_now
    return iso_now()


def _shorten(text: str, limit: int = 240) -> str:
    if len(text) <= limit:
        return text
    clipped = text[: limit - 1]
    idx = clipped.rfind(". ")
    if idx > limit // 2:
        clipped = clipped[: idx + 1]
    return clipped + "…"


class ToolResultLike:
    """Minimal duck-type of ToolResult used when errors escape a tool boundary."""

    def __init__(self, error: str, code: str) -> None:
        self.success = False
        self.error = error
        self.error_code = code
        self.data: dict = {}
        self.output = None
        self.message = error
        self.duration_ms = 0

    def as_dict(self) -> dict:
        return {"success": False, "error": self.error, "error_code": self.error_code}
