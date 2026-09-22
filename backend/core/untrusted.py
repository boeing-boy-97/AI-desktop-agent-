"""Untrusted-content firewall (V2 §44/§45).

NOVA must distinguish USER INSTRUCTION from EXTERNAL CONTENT.  Anything that
arrived from the world — webpages, downloaded files, OCR text, clipboard,
message bodies, tool output — is *external content*.  External content may be
displayed, summarised and quoted, but it must never become an authorized
command on its own.

Structural guarantees enforced across the codebase:

1. ``planner.plan(...)`` only ever receives the user's own transcript/text.
   Tool results and web extractions are passed as *data* to specific tools,
   never re-fed to the planner as instructions.
2. Functions here scrub external text before it is shown or stored, so
   embedded directives ("ignore previous instructions…") are demoted to
   inert quoted text.
3. Tests (``tests/unit/test_untrusted.py``) pin all of this.
"""
from __future__ import annotations

import re

_MAX_EXTERNAL_LEN = 4000

# phrases that try to seize control of the agent
_DIRECTIVE_PATTERNS = (
    re.compile(r"ignore\s+(all\s+)?(previous|prior|above)\s+(instructions?|prompts?|rules?)", re.I),
    re.compile(r"disregard\s+(all\s+)?(previous|prior|your)\s+(instructions?|rules?|training)", re.I),
    re.compile(r"you\s+must\s+(now\s+)?(run|execute|delete|send|install)", re.I),
    re.compile(r"(run|execute)\s+(powershell|cmd|shell|terminal)\b", re.I),
    re.compile(r"system\s*:\s*", re.I),
    re.compile(r"new\s+instructions?\s*:", re.I),
    re.compile(r"act\s+as\s+(if\s+)?(an?\s+)?(unrestricted|root|admin)", re.I),
)


def is_external(text: str | None) -> bool:
    """True when *text* contains directive-injection markers."""
    if not text:
        return False
    return any(p.search(text) for p in _DIRECTIVE_PATTERNS)


def sanitize_external(text: str, source: str = "external") -> str:
    """Neutralise external text so it can be safely displayed or remembered.

    * truncates to a sane length
    * tags detected directives so downstream components (and the user) can
      see that the content tried to issue commands
    """
    if not text:
        return ""
    clipped = text[:_MAX_EXTERNAL_LEN]
    flagged = [p.pattern for p in _DIRECTIVE_PATTERNS if p.search(clipped)]
    clean = clipped
    for p in _DIRECTIVE_PATTERNS:
        clean = p.sub("[blocked directive]", clean)
    if flagged:
        clean = (f"[{source} content — embedded instructions blocked] " + clean)
    return clean


def as_data(value: str, source: str = "external") -> dict:
    """Wrap external text so tools receive it explicitly as DATA.

    Tools must pass this envelope — never the raw string — anywhere the
    content could be re-interpreted as a command.
    """
    return {"untrusted": True, "source": source,
            "flagged": is_external(value),
            "text": sanitize_external(value, source)}
