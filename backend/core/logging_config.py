"""Structured logging.

Emits human-readable key=value log lines to a rotating file plus the console.
Sensitive values (API keys, tokens, passwords) are redacted at the formatter
level so they can never reach a log file by accident.
"""
from __future__ import annotations

import logging
import logging.handlers
import re
import sys
from pathlib import Path

_SENSITIVE_PATTERNS = [
    re.compile(r"(api[_-]?key\s*[=:]\s*)(\S+)", re.IGNORECASE),
    re.compile(r"(authorization\s*[=:]\s*)(\S+)", re.IGNORECASE),
    re.compile(r"(bearer\s+)([A-Za-z0-9._\-]+)", re.IGNORECASE),
    re.compile(r"(password\s*[=:]\s*)(\S+)", re.IGNORECASE),
    re.compile(r"(sk-[A-Za-z0-9_\-]{6,})", re.IGNORECASE),
]


class RedactingFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        msg = super().format(record)
        for pat in _SENSITIVE_PATTERNS:
            msg = pat.sub(lambda m: m.group(1) + "***REDACTED***", msg)
        return msg


class EventLogger:
    """Small structured helper used by the agent/tools for trace events."""

    def __init__(self, name: str = "nova") -> None:
        self._logger = logging.getLogger(name)

    def event(self, event: str, **fields) -> None:
        pairs = " ".join(f"{k}={_clean(v)}" for k, v in fields.items() if v is not None)
        self._logger.info(f"[{event}] {pairs}".strip())

    def debug(self, msg: str, **fields) -> None:
        self._logger.debug(msg, extra=_clean_fields(fields))

    def info(self, msg: str, **fields) -> None:
        self._logger.info(msg, extra=_clean_fields(fields))

    def warning(self, msg: str, **fields) -> None:
        self._logger.warning(msg, extra=_clean_fields(fields))

    def error(self, msg: str, **fields) -> None:
        self._logger.error(msg, extra=_clean_fields(fields))


def _clean(value) -> str:
    text = str(value)
    if len(text) > 200:
        text = text[:200] + "…"
    return text


def _clean_fields(fields: dict) -> dict:
    return {k: _clean(v) for k, v in fields.items()}


def setup_logging(
    level: str | int = "INFO",
    log_dir: Path | None = None,
) -> None:
    """Configure the root logger once at process start."""
    if isinstance(level, str):
        level = getattr(logging, level.upper(), logging.INFO)

    root = logging.getLogger()
    for handler in list(root.handlers):
        root.removeHandler(handler)

    fmt = "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"
    formatter = RedactingFormatter(fmt, datefmt="%Y-%m-%d %H:%M:%S")

    console = logging.StreamHandler(sys.stderr)
    console.setFormatter(formatter)
    root.addHandler(console)

    if log_dir is not None:
        try:
            log_dir = Path(log_dir)
            log_dir.mkdir(parents=True, exist_ok=True)
            file_handler = logging.handlers.RotatingFileHandler(
                log_dir / "nova.log",
                maxBytes=5 * 1024 * 1024,
                backupCount=5,
                encoding="utf-8",
            )
            file_handler.setFormatter(formatter)
            root.addHandler(file_handler)
        except Exception:  # pragma: no cover - logging must never crash the app
            root.warning("Could not open log file in %s", log_dir)

    root.setLevel(level)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("faster_whisper").setLevel(logging.WARNING)
