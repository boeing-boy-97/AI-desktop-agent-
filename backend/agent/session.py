"""Session context model (V2 §16/§17).

Structured, time-limited conversational state: what the user is currently
working on (application, file, site, contact, project) plus recent artifacts.
Entries expire automatically so stale context never leaks into later,
unrelated tasks.  The planner uses :meth:`resolve_coreference` to map
pronouns/demonstratives ("it", "that file", "he") onto this state, so users
never have to repeat themselves.
"""
from __future__ import annotations

import re
import time
from typing import Any

DEFAULT_TTL_SECONDS = 15 * 60.0
MAX_ARTIFACTS = 12

# coreference cues -> session keys, in priority order
_COREF: tuple[tuple[tuple[str, ...], tuple[str, ...]], ...] = (
    (("he", "him", "his", "she", "her"), ("selected_contact",)),
    (("that photo", "the photo", "that image", "the image", "that file",
      "the file", "it", "that"), ("selected_artifact", "current_file")),
    (("that folder", "the folder"), ("current_folder", "current_file")),
    (("that chat", "the chat"), ("selected_contact",)),
    (("this project", "the project", "my project"), ("current_project",)),
    (("that site", "the site", "that page", "the page", "that website"),
     ("current_site",)),
)


class SessionContext:
    def __init__(self, ttl_seconds: float = DEFAULT_TTL_SECONDS) -> None:
        self.ttl = ttl_seconds
        self._data: dict[str, dict[str, Any]] = {}

    # ------------------------------------------------------------------
    def set(self, key: str, value: Any, ttl: float | None = None) -> None:
        self._data[key] = {"value": value, "at": time.time(),
                           "ttl": ttl if ttl is not None else self.ttl}

    def get(self, key: str) -> Any | None:
        self.expire()
        entry = self._data.get(key)
        return entry["value"] if entry else None

    def expire(self) -> None:
        now = time.time()
        dead = [k for k, e in self._data.items() if now - e["at"] > e["ttl"]]
        for k in dead:
            del self._data[k]

    def clear(self) -> None:
        self._data.clear()

    def add_artifact(self, kind: str, ref: str) -> None:
        """Track a concrete artifact (photo/file/download) the user may
        refer back to ("download it", "move that")."""
        arts = self.get("artifacts") or []
        arts.append({"kind": kind, "ref": ref, "at": time.time()})
        self.set("artifacts", arts[-MAX_ARTIFACTS:])
        self.set("selected_artifact", ref)

    # ------------------------------------------------------------------
    def resolve_coreference(self, text: str) -> dict[str, Any]:
        """Map pronouns/demonstratives in *text* to concrete session values.

        Returns a dict of substitutions the planner can apply, e.g.
        {"it": "/home/u/photo.jpg", "he": "Rahul"}.
        """
        self.expire()
        words = set(text.lower().replace(",", " ").replace(".", " ").split())
        resolved: dict[str, Any] = {}
        for cues, keys in _COREF:
            cue = next((c for c in cues if c in words), None)
            if cue is None:
                continue
            for key in keys:
                value = self.get(key)
                if value:
                    resolved[cue] = value
                    break
            else:
                # fall back to the newest artifact for object pronouns
                if cue in ("it", "that", "that file", "that photo"):
                    arts = self.get("artifacts") or []
                    if arts:
                        resolved[cue] = arts[-1]["ref"]
        return resolved

    def apply_coreference(self, text: str) -> str:
        """Rewrite *text* replacing resolved pronouns with their referents.

        Whole-word matching only — "Split it" must not corrupt "Split".
        """
        for cue, value in sorted(self.resolve_coreference(text).items(),
                                 key=lambda kv: -len(kv[0])):
            if not isinstance(value, str):
                continue
            pattern = r"(?<!\w)" + re.escape(cue) + r"(?!\w)"
            text = re.sub(pattern, value.replace("\\", "\\\\"), text,
                          count=1, flags=re.IGNORECASE)
        return text

    # ------------------------------------------------------------------
    def snapshot(self) -> dict[str, Any]:
        self.expire()
        return {k: e["value"] for k, e in self._data.items()}

    def describe(self) -> dict[str, Any]:
        snap = self.snapshot()
        return {"entries": snap, "count": len(snap), "ttl_seconds": self.ttl}
