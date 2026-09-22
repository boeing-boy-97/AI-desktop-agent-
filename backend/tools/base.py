"""Tool abstractions: permission levels, tool definition, tool classes, context."""
from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import Any, ClassVar

from core.exceptions import ToolValidationError
from core.utils import utcnow
from pydantic import ValidationError


class PermissionLevel:
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"

    RANK: ClassVar[dict[str, int]] = {LOW: 0, MEDIUM: 1, HIGH: 2}

    @classmethod
    def meets(cls, required: str, granted: str) -> bool:
        return cls.RANK.get(required, 0) <= cls.RANK.get(granted, 0)


@dataclass
class ToolDefinition:
    """Static metadata describing a tool (registry entry)."""
    name: str
    description: str
    permission_level: str
    category: str
    input_model: type | None = None
    requires_confirmation: bool = False
    confirm_message_tpl: str | None = None
    timeout: float = 30.0
    verify_after: bool = True
    risky_keywords: tuple[str, ...] = ()


@dataclass
class ToolResult:
    """Standardised result envelope for every tool execution."""
    success: bool
    output: Any = None
    data: dict = field(default_factory=dict)
    error: str | None = None
    error_code: str | None = None
    message: str | None = None
    duration_ms: int | None = None

    def as_dict(self) -> dict:
        return {
            "success": self.success,
            "output": self.output,
            "data": self.data or {},
            "error": self.error,
            "error_code": self.error_code,
            "message": self.message,
            "duration_ms": self.duration_ms,
        }

    @classmethod
    def ok(cls, output: Any = None, message: str = "", data: dict | None = None,
           duration_ms: int | None = None) -> ToolResult:
        merged = dict(data or {})
        if isinstance(output, dict):
            merged = {**output, **merged}
        return cls(True, output=output, message=message, data=merged,
                   duration_ms=duration_ms)

    @classmethod
    def fail(cls, error: str, error_code: str = "TOOL_ERROR",
             data: dict | None = None) -> ToolResult:
        return cls(False, error=error, error_code=error_code, data=data or {})


@dataclass
class ToolContext:
    """Runtime services handed to tools (dependency injection)."""
    settings: Any  # Settings
    event_bus: Any = None  # EventBus
    observer: Any = None   # ScreenObserver
    registry: Any = None   # ToolRegistry
    confirmations: Any = None  # ConfirmationStore
    session_factory: Any = None  # SQLAlchemy sessionmaker (None in unit tests)
    logger: Any = None      # EventLogger
    undo_journal: Any = None  # agent.undo.UndoJournal (V2 §13)
    locks: Any = None         # core.locks.ResourceLocks (V2 §30)
    runtime: Any = None       # Runtime back-reference for introspection tools


class Tool(abc.ABC):
    """Base class for every NOVA tool (plugin).

    Subclasses set `name`, `description`, `permission`, `input_model` and
    implement :meth:`run` (async, receives validated ``input_model``).
    """

    name: ClassVar[str]
    description: ClassVar[str]
    permission: ClassVar[str] = PermissionLevel.LOW
    category: ClassVar[str] = "general"
    input_model: ClassVar[type[Any] | None] = None
    requires_confirmation: ClassVar[bool] = False
    confirm_message_tpl: ClassVar[str] = "Allow {tool} to proceed?"
    timeout: ClassVar[float] = 30.0
    verify_after: ClassVar[bool] = True

    def __init__(self, ctx: ToolContext) -> None:
        self.ctx = ctx

    # -- public API used by the executor -------------------------------
    def to_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name=self.name,
            description=self.description,
            permission_level=self.permission,
            category=self.category,
            input_model=self.input_model,
            requires_confirmation=self.requires_confirmation,
            confirm_message_tpl=self.confirm_message_tpl,
            timeout=self.timeout,
            verify_after=self.verify_after,
        )

    async def execute(self, arguments: dict, task_id: str | None = None) -> ToolResult:
        """Validate arguments and dispatch to :meth:`run`, returning ToolResult."""
        parsed = self._validate(arguments)
        started = utcnow()
        try:
            output = await self.run(parsed, task_id=task_id)
            if isinstance(output, ToolResult):
                result = output
            else:
                result = ToolResult.ok(output)
        except ToolValidationError as exc:
            result = ToolResult.fail(str(exc), error_code="TOOL_INVALID_ARGS")
        except Exception as exc:
            result = ToolResult.fail(f"{type(exc).__name__}: {exc}",
                                     error_code=getattr(exc, "code", "TOOL_ERROR"))
        result.duration_ms = int((utcnow() - started).total_seconds() * 1000)
        if not result.message:
            result.message = _summarise(result)
        return result

    def _validate(self, arguments: dict) -> Any:
        if self.input_model is None:
            return arguments
        try:
            return self.input_model(**arguments)
        except ValidationError as exc:
            raise ToolValidationError(
                f"Invalid arguments for tool '{self.name}': {_errors_text(exc)}",
                details={"tool": self.name, "errors": exc.errors()}) from exc

    async def verify(self, arguments: dict, task_id: str | None = None) -> ToolResult:
        """Optional post-execution verification hook (default: no-op pass)."""
        return ToolResult.ok(True, message="verified")

    def summarize_confirmation(self, arguments: dict, task_id: str | None = None) -> str | None:
        """Optional human detail appended to a confirmation prompt.

        Tools that act on user-visible/irreversible state (e.g. deletion)
        override this so the confirmation shows *what* is about to happen.
        Return ``None`` to keep the default prompt.
        """
        return None

    # -- subclasses implement this ------------------------------------
    @abc.abstractmethod
    async def run(self, args: Any, task_id: str | None = None) -> ToolResult:
        raise NotImplementedError


def _errors_text(exc: ValidationError) -> str:
    parts = []
    for e in exc.errors()[:8]:
        loc = ".".join(str(x) for x in e.get("loc", []))
        parts.append(f"{loc or '(root)'}: {e.get('msg', 'invalid')}")
    return "; ".join(parts)


def _summarise(result: ToolResult) -> str:
    if not result.success:
        return result.error or "Failed"
    if result.output and isinstance(result.output, str):
        return result.output[:200]
    return "OK"


def format_tool_result(result: ToolResult, max_len: int = 1000) -> str:
    """Compact string form of a ToolResult used in LLM observations."""
    if not result.success:
        return f"ERROR ({result.error_code}): {result.error}"
    parts = []
    if result.message and result.message != "OK":
        parts.append(str(result.message))
    if result.output is not None:
        parts.append(str(result.output))
    if result.data:
        parts.append(_fmt_dict(result.data))
    text = " | ".join(p for p in parts if p)
    return (text or "OK")[:max_len]


def _fmt_dict(data: dict, limit: int = 300) -> str:
    try:
        from core.utils import json_dumps
        return json_dumps(data)[:limit]
    except Exception:
        return str(data)[:limit]
