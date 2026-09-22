"""MemoryContext — conversational + persistent memory used by planner/executor.

* persistent facts ("college_projects" → D:\\College\\Projects) via DB
* rollout of '@key' placeholders in tool arguments to remembered values
* a short conversational window for follow-up commands (spec §44)
* immediate resolution returned by ``relevant()``
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class MemoryContext:
    session_factory: Any = None          # SQLAlchemy sessionmaker (None in tests)
    conversation: list[dict] = field(default_factory=list)  # short-term window
    cache: dict = field(default_factory=dict)

    MAX_CONVERSATION = 8

    # -- persistent facts ------------------------------------------------
    def _load_facts(self) -> dict[str, dict]:
        if self.session_factory is None:
            return {}
        from database.service import list_memory
        try:
            with self.session_factory() as s:
                rows = list_memory(s)
            return {r.key: {"value": r.value, "category": r.category} for r in rows}
        except Exception:
            return {}

    def facts(self) -> dict[str, dict]:
        self.cache = self._load_facts()
        return dict(self.cache)

    def remember(self, key: str, value: str, category: str = "general") -> None:
        if self.session_factory is None:
            self.cache[key] = {"value": value, "category": category}
            return
        from database.service import set_memory
        with self.session_factory() as s:
            set_memory(s, key, value, category)
        self.cache[key] = {"value": value, "category": category}

    def recall(self, key: str) -> str | None:
        facts = self.facts()
        row = facts.get(key)
        default = self.cache.get(key, {}).get("value")
        return (row or {}).get("value", default)

    def forget(self, key: str) -> bool:
        if self.session_factory is None:
            return self.cache.pop(key, None) is not None
        from database.service import delete_memory
        with self.session_factory() as s:
            ok = delete_memory(s, key)
        self.cache.pop(key, None)
        return ok

    # -- reasoning helpers -----------------------------------------------
    def relevant(self, text: str, limit: int = 5) -> dict[str, dict]:
        """Return facts whose key is mentioned in the text (or all if few)."""
        facts = self.facts()
        low = text.lower()
        hits = {k: v for k, v in facts.items()
                if k.lower() in low or self._loose(k, text)}
        if not hits and len(facts) <= limit:
            hits = facts
        return dict(list(hits.items())[:limit])

    @staticmethod
    def _loose(key: str, text: str) -> bool:
        words = key.lower().replace("_", " ").split()
        return any(w in text.lower() for w in words if len(w) > 3)

    def resolve(self, arguments: dict) -> dict:
        """Replace '@key' string values in tool args with remembered values."""
        out = dict(arguments)
        for k, v in out.items():
            if isinstance(v, str) and v.startswith("@"):
                key = v[1:]
                val = self.recall(key)
                if val is not None:
                    out[k] = val
        return out

    # -- conversational window (§44) ------------------------------------
    def push_conversation(self, name: str, value: str) -> None:
        self.conversation.append({"name": name, "value": value})
        if len(self.conversation) > self.MAX_CONVERSATION:
            self.conversation = self.conversation[-self.MAX_CONVERSATION:]

    def conversational_context(self) -> list[dict]:
        return list(self.conversation)

    def describe(self) -> dict:
        return {"facts": {k: v["value"] for k, v in self.facts().items()},
                "conversation": self.conversation}
