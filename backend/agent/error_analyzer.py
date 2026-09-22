"""Code error analyzer (V2 §23).

Parses compiler / runtime / build / test output into structured errors so the
recovery loop can reason about *what* broke instead of blindly re-running.

    analyze("module.js(12,5): error TS2304: Cannot find name 'foo'")
    -> ParsedError(kind="compiler", file="module.js", line=12, column=5,
                   code="TS2304", message="Cannot find name 'foo'", ...)

Deliberately heuristic and dependency-free: this runs offline and on Windows
and Linux alike.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, asdict

# (regex, kind) — order matters, first match wins
_PATTERNS: tuple[tuple[str, str], ...] = (
    # TypeScript / MSBuild style:  file(line,col): error CODE: message
    (r"^(?P<file>[^\s(]+)\((?P<line>\d+),(?P<col>\d+)\):\s*"
     r"(?:error\s+)?(?P<code>[A-Z]+\d+):\s*(?P<msg>.+)$", "compiler"),
    # GCC / eslint style:  file:line:col: message
    (r"^(?P<file>[^\s:]+):(?P<line>\d+):(?P<col>\d+):\s*"
     r"(?:error:?|fatal error:?)?\s*(?P<msg>.+)$", "compiler"),
    # Python tracebacks: File "x.py", line N
    (r'^\s*File "(?P<file>[^"]+)", line (?P<line>\d+)', "runtime"),
    # Node: /path/file.js:12
    (r"^(?P<file>[^\s:]+\.(?:js|mjs|cjs|ts|jsx|tsx)):(?P<line>\d+)", "runtime"),
    # npm: npm ERR! ...
    (r"^npm ERR!?\s+(?P<msg>.+)$", "package_manager"),
    # pytest: FAILED tests/test_x.py::test_y
    (r"^FAILED\s+(?P<file>\S+?)(?:::(?P<msg>\S+))?$", "test"),
)

_ERROR_HINTS = ("error", "failed", "cannot", "could not", "no such",
                "not found", "traceback", "exception")


@dataclass
class ParsedError:
    kind: str                 # compiler | runtime | package_manager | test | generic
    file: str | None = None
    line: int | None = None
    column: int | None = None
    code: str | None = None
    message: str = ""
    confidence: float = 0.0   # 0..1 heuristic confidence

    def as_dict(self) -> dict:
        return asdict(self)

    @property
    def likely_cause(self) -> str:
        msg = self.message.lower()
        if "cannot find module" in msg or "module not found" in msg or "no module named" in msg:
            return "missing dependency or wrong import path — install the package or fix the import"
        if "enoent" in msg or "no such file" in msg:
            return "referenced file does not exist — check the path or create it first"
        if "eaddrinuse" in msg or "address already in use" in msg:
            return "port already in use — stop the other process or pick another port"
        if "permission" in msg or "eacces" in msg:
            return "insufficient permissions — run with appropriate rights or change target"
        if "syntax" in msg:
            return "syntax error — fix the highlighted line"
        if self.kind == "package_manager":
            return "package manager failure — check network/registry and package name"
        if self.kind == "test":
            return "test failure — inspect assertion output and repair the code under test"
        return "see message for details"

    @property
    def proposed_fix(self) -> str:
        cause = self.likely_cause
        if "install the package" in cause and self.message:
            m = re.search(r"(?:module|package|named)\s+'([^']+)'", self.message)
            if m:
                return f"install the missing dependency (e.g. 'npm install {m.group(1)}' or 'pip install {m.group(1)}'), then rerun"
        if self.file and self.line:
            return f"open {self.file} at line {self.line} and repair the reported problem, then rerun"
        return "repair the reported problem and rerun the failing command"


def analyze(output: str, max_errors: int = 10) -> list[ParsedError]:
    """Extract structured errors from command/build/test output."""
    results: list[ParsedError] = []
    if not output:
        return results
    for raw_line in output.splitlines():
        line = raw_line.rstrip()
        if not line:
            continue
        for pattern, kind in _PATTERNS:
            m = re.match(pattern, line)
            if not m:
                continue
            groups = m.groupdict()
            err = ParsedError(
                kind=kind,
                file=groups.get("file"),
                line=int(groups["line"]) if groups.get("line") else None,
                column=int(groups["col"]) if groups.get("col") else None,
                code=groups.get("code"),
                message=(groups.get("msg") or line).strip(),
                confidence=0.85 if groups.get("line") else 0.6,
            )
            results.append(err)
            break
        if len(results) >= max_errors:
            break

    # fallback: surface obvious error lines even without a location
    if not results:
        for raw_line in output.splitlines():
            low = raw_line.lower()
            if any(h in low for h in _ERROR_HINTS):
                results.append(ParsedError(kind="generic",
                                           message=raw_line.strip()[:300],
                                           confidence=0.3))
                if len(results) >= max_errors:
                    break
    return results


def to_report(output: str) -> dict:
    """Convenience wrapper used by tools/diagnostics."""
    errors = analyze(output)
    return {
        "error_count": len(errors),
        "errors": [e.as_dict() for e in errors],
        "primary": errors[0].as_dict() if errors else None,
    }
