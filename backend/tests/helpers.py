"""Test helpers."""
from __future__ import annotations


async def invoke(runtime, tool_name: str, arguments=None):
    tool = runtime.registry.get(tool_name)
    return await tool.execute(arguments or {})
