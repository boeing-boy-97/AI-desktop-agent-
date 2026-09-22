"""Memory package — re-exports the conversational/persistent memory context.

The implementation lives in ``agent/memory.py``; this package keeps the
spec'd module layout discoverable.
"""
from agent.memory import MemoryContext

__all__ = ["MemoryContext"]
