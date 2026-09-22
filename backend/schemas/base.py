"""Base ToolInput + shared building blocks for tool argument schemas."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class ToolInput(BaseModel):
    """Every tool declares one concrete subclass — its JSON input schema."""

    @classmethod
    def describe(cls) -> str:
        """Human+LLM readable summary of the schema."""
        fields = []
        for name, fobj in cls.model_fields.items():
            ann = getattr(fobj.annotation, "__name__", str(fobj.annotation))
            desc = fobj.description or ""
            default = fobj.default
            required = fobj.is_required()
            fields.append(
                f"    {name} ({ann}{'' if required else f', default={default}'}): {desc}")
        return "\n".join(fields)

    def serialise(self) -> dict:
        return self.model_dump(exclude_none=True)


def json_type(annotation: Any) -> str:
    origin = getattr(annotation, "__origin__", None)
    if origin is list or origin is set:
        return "array"
    if origin is dict:
        return "object"
    name = getattr(annotation, "__name__", "").lower()
    if name in {"str", "string"}:
        return "string"
    if name in {"int", "integer"}:
        return "integer"
    if name in {"float"}:
        return "number"
    if name in {"bool"}:
        return "boolean"
    return "string"
