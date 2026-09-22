"""NOVA tool plugin system.

Central pieces:
    * PermissionLevel             — low/medium/high risk ranking
    * Tool / ToolContext / ToolResult — interfaces every tool implements
    * ToolRegistry                — discovers & registers tools
    * register_builtin_tools      — wires all plugin modules to a registry
"""
from __future__ import annotations

import importlib
import inspect
import pkgutil
from collections.abc import Callable
from dataclasses import dataclass
from dataclasses import field as dc_field
from typing import Any

from core.exceptions import ToolNotFound
from tools.base import PermissionLevel, Tool, ToolContext, ToolDefinition, ToolResult

__all__ = [
    "PermissionLevel",
    "Tool",
    "ToolContext",
    "ToolDefinition",
    "ToolRegistry",
    "ToolResult",
    "build_tool_context",
    "register_builtin_tools",
]

_BUILTIN_MODULES = [
    "tools.computer",
    "tools.filesystem",
    "tools.process_ctl",
    "tools.browser",
    "tools.windows",
    "tools.vscode",
    "tools.whatsapp",
    "tools.downloads",
    "tools.alias",
    "tools.memory_tools",
    "tools.web_tools",
    "tools.introspection",
    "tools.core_control",
]


@dataclass
class RegisteredTool:
    definition: ToolDefinition
    factory: Callable[[ToolContext], Tool]
    _instance: Tool | None = dc_field(default=None, repr=False)

    def instantiate(self, ctx: ToolContext) -> Tool:
        if self._instance is None:
            self._instance = self.factory(ctx)
        return self._instance


class ToolRegistry:
    """Discover, register and instantiate tools. Thread-safe enough for one loop."""

    def __init__(self, ctx: ToolContext | None = None) -> None:
        self.ctx = ctx
        self._registry: dict[str, RegisteredTool] = {}
        self._instances: dict[str, Tool] = {}
        self._categories: dict[str, list[str]] = {}
        self._load_started = False

    # -- registration ---------------------------------------------------
    def register(self, tool_cls: type[Tool], ctx: ToolContext | None = None) -> None:
        ctx = ctx or self.ctx
        if ctx is None:
            raise RuntimeError("ToolRegistry needs a ToolContext to instantiate tools")
        if not (inspect.isclass(tool_cls) and issubclass(tool_cls, Tool)):
            raise TypeError(f"{tool_cls!r} is not a Tool subclass")
        name = tool_cls.name
        reg = RegisteredTool(definition=None, factory=lambda c, t=tool_cls: t(c))
        # build definition lazily from a throw-away instance so properties work
        probe = tool_cls(ctx)
        reg.definition = probe.to_definition()
        if not name or " " in name:
            raise ValueError(f"Tool {tool_cls.__name__} has invalid name {name!r}")
        self._registry[name] = reg
        self._categories.setdefault(probe.category, []).append(name)

    def register_module(self, module_name: str, ctx: ToolContext | None = None) -> int:
        module = importlib.import_module(module_name)
        count = 0
        for _, cls in inspect.getmembers(module, inspect.isclass):
            if cls is Tool or not issubclass(cls, Tool):
                continue
            if cls.__module__ != module.__name__:
                continue
            if cls.__dict__.get("_abstract", False):
                continue
            self.register(cls, ctx)
            count += 1
        return count

    def discover(self, ctx: ToolContext | None = None) -> None:
        """Auto-discover tools inside the ``tools`` package namespace."""
        import tools as tools_pkg
        seen = set()
        for modinfo in pkgutil.walk_packages(tools_pkg.__path__, prefix="tools."):
            if modinfo.name in seen:
                continue
            seen.add(modinfo.name)
            try:
                self.register_module(modinfo.name, ctx)
            except Exception:  # skip broken optional plugin modules
                self._load_started = True
                continue
        self._load_started = True

    # -- lookup ---------------------------------------------------------
    def has(self, name: str) -> bool:
        return name in self._registry

    def get(self, name: str, ctx: ToolContext | None = None) -> Tool:
        reg = self._registry.get(name)
        if reg is None:
            raise ToolNotFound(f"Unknown tool: {name}")
        ctx = ctx or self.ctx
        if ctx is None:
            raise RuntimeError("ToolRegistry has no ToolContext")
        if name not in self._instances:
            self._instances[name] = reg.factory(ctx)
        return self._instances[name]

    def definition(self, name: str) -> ToolDefinition:
        reg = self._registry.get(name)
        if reg is None:
            raise ToolNotFound(f"Unknown tool: {name}")
        return reg.definition

    def definitions(self) -> list[ToolDefinition]:
        return [r.definition for r in self._registry.values()]

    def names(self) -> list[str]:
        return sorted(self._registry.keys())

    def by_category(self) -> dict[str, list[str]]:
        return {k: sorted(v) for k, v in self._categories.items()}

    def as_catalog(self) -> list[dict]:
        return [{
            "name": d.name,
            "description": d.description,
            "permission_level": d.permission_level,
            "category": d.category,
            "requires_confirmation": d.requires_confirmation,
            "input_schema": (d.input_model.model_json_schema() if d.input_model else {}),
        } for d in sorted(self.definitions(), key=lambda d: d.name)]


def build_tool_context(
    settings: Any,
    event_bus: Any = None,
    observer: Any = None,
    confirmations: Any = None,
    session_factory: Any = None,
    logger: Any = None,
) -> ToolContext:
    return ToolContext(settings=settings, event_bus=event_bus, observer=observer,
                       confirmations=confirmations, session_factory=session_factory,
                       logger=logger)


def register_builtin_tools(registry: ToolRegistry, ctx: ToolContext) -> None:
    """Register every first-party tool module into ``registry``."""
    for module_name in _BUILTIN_MODULES:
        registry.register_module(module_name, ctx)
