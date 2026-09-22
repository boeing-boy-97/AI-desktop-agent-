"""Unified exception hierarchy for NOVA.

Every layer raises these typed exceptions; the API layer maps them to HTTP
responses and the agent layer maps them to recovery decisions.
"""
from __future__ import annotations


class NovaError(Exception):
    """Base class for all NOVA-raised errors."""

    code: str = "NOVA_ERROR"

    def __init__(self, message: str, *, code: str | None = None,
                 details: dict | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.code = code or self.__class__.code
        self.details = details or {}

    def to_dict(self) -> dict:
        out: dict = {"code": self.code, "message": self.message}
        if self.details:
            out["details"] = self.details
        return out


class ConfigError(NovaError):
    code = "CONFIG_ERROR"


class DatabaseError(NovaError):
    code = "DATABASE_ERROR"


class AuthenticationError(NovaError):
    code = "AUTH_ERROR"


class PermissionDenied(NovaError):
    code = "PERMISSION_DENIED"

    def __init__(self, message: str, *, tool: str | None = None,
                 level: str | None = None, details: dict | None = None) -> None:
        d = dict(details or {})
        if tool:
            d["tool"] = tool
        if level:
            d["level"] = level
        super().__init__(message, details=d)


class ConfirmationRequired(NovaError):
    """Raised when a tool needs user confirmation before execution."""

    code = "CONFIRMATION_REQUIRED"

    def __init__(self, message: str, *, tool: str, task_id: str | None = None,
                 question: str | None = None, details: dict | None = None) -> None:
        d = dict(details or {})
        d["tool"] = tool
        if question:
            d["question"] = question
        self.tool = tool
        self.question = question or message
        self.task_id = task_id
        super().__init__(message, details=d)


class ToolError(NovaError):
    code = "TOOL_ERROR"


class ToolNotFound(ToolError):
    code = "TOOL_NOT_FOUND"


class ToolValidationError(ToolError):
    code = "TOOL_INVALID_ARGS"


class ToolTimeout(NovaError):
    code = "TOOL_TIMEOUT"


class EmergencyStop(NovaError):
    code = "EMERGENCY_STOP"


class TaskCancelled(NovaError):
    code = "TASK_CANCELLED"


class ActionFailed(NovaError):
    """An individual step failed after retries."""

    code = "ACTION_FAILED"


class ExecutionBlocked(NovaError):
    """The execution layer refused to run a command."""

    code = "EXECUTION_BLOCKED"


class NotAvailable(NovaError):
    """A platform capability is genuinely unavailable (documented limitation)."""

    code = "NOT_AVAILABLE"


class ProviderError(NovaError):
    code = "PROVIDER_ERROR"


class VoiceError(NovaError):
    code = "VOICE_ERROR"


class SafetyError(NovaError):
    code = "SAFETY_ERROR"


class VerificationError(NovaError):
    code = "VERIFICATION_ERROR"
