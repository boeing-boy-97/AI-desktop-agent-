"""Miscellaneous helpers shared across NOVA modules."""
from __future__ import annotations

import dataclasses
import json
import pathlib
import re
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso_now() -> str:
    return utcnow().isoformat()


def local_now() -> datetime:
    return datetime.now().astimezone()


def new_id(prefix: str = "") -> str:
    raw = uuid.uuid4().hex[:12]
    return f"{prefix}-{raw}" if prefix else raw


def json_dumps(obj: Any, pretty: bool = False) -> str:
    if pretty:
        return json.dumps(obj, ensure_ascii=False, indent=2, default=_json_default)
    return json.dumps(obj, ensure_ascii=False, default=_json_default)


def _json_default(obj: Any) -> Any:
    if dataclasses.is_dataclass(obj):
        return dataclasses.asdict(obj)
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, pathlib.Path):
        return str(obj)
    raise TypeError(f"Not serialisable: {type(obj)}")


def clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def truncate(text: str, limit: int = 400) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


_CAMEL_SPLIT = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")


def to_snake(name: str) -> str:
    return _CAMEL_SPLIT.sub("_", name).lower()


_ALIASES = {"control": "ctrl", "cmd": "ctrl", "win": "meta", "super": "meta"}


def parse_hotkey(value: str) -> list[str]:
    """Normalise ``ctrl+alt+space`` into a sorted token list."""
    if not value:
        return []
    tokens = [t.strip().lower() for t in value.split("+") if t.strip()]
    return sorted({_ALIASES.get(t, t) for t in tokens})


def human_bytes(num: float) -> str:
    num = float(num)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(num) < 1024.0 or unit == "TB":
            return f"{num:.1f} {unit}" if unit != "B" else f"{int(num)} B"
        num /= 1024.0
    return f"{num:.1f} TB"


def extract_code_fences(text: str) -> list[str]:
    """Return code blocks extracted from a markdown string."""
    blocks = re.findall(r"```[a-zA-Z0-9+_\-]*\n(.*?)```", text, re.DOTALL)
    if not blocks:
        blocks = re.findall(r"```([^`]*)```", text, re.DOTALL)
    return [b.strip("\n") for b in blocks]


def robust_json_parse(text: str, fallback: dict | None = None) -> dict:
    """Parse JSON that might be wrapped in markdown fences or prose."""
    fallback = fallback or {}
    candidate = text.strip()
    if candidate.startswith("```"):
        blocks = extract_code_fences(candidate)
        candidate = (blocks[0] if blocks else candidate).strip()
    try:
        data = json.loads(candidate)
        return data if isinstance(data, dict) else {"result": data}
    except Exception:
        start = candidate.find("{")
        end = candidate.rfind("}")
        if start >= 0 and end > start:
            try:
                data = json.loads(candidate[start : end + 1])
                return data if isinstance(data, dict) else {"result": data}
            except Exception:
                pass
    return fallback
