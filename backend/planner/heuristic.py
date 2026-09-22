"""Deterministic offline planner.

Covers the demo commands (spec §42) and the common natural-language forms
(spec §43) so NOVA works without a configured cloud model. Produces safe,
verifiable plans using direct tools) — no hallucination, no unsafe shell.
"""
from __future__ import annotations

import re
from typing import ClassVar

from planner.planner import Planner, PlanStep, TaskPlan


class HeuristicPlanner(Planner):
    def __init__(self, *args, session: object | None = None, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.session = session

    async def plan(self, command: str, *, mode: str = "smart",
                   context: list[dict] | None = None,
                   session: object | None = None) -> TaskPlan:
        c = command.strip()
        low = c.lower()

        # --- explicit workflow/macro invocation (spec §19, §20) -------------
        wf_steps = await self._workflow_steps(low, c)
        if wf_steps is not None:
            return TaskPlan(goal=f"run workflow: {c}", steps=wf_steps,
                            mode=mode, source="workflow")

        # --- interruption words (V2 §8/§31) ---------------------------------
        # phrase-based on purpose: bare "resume"/"pause" appear in ordinary
        # sentences ("find my resume") and must not be hijacked
        if any(p in low for p in ("resume the task", "resume task", "resume it",
                                  "resume the paused", "unpause")):
            return TaskPlan(goal="resume the paused task",
                            steps=[PlanStep(0, "core.resume", {}, "resume")],
                            mode=mode, source="heuristic")
        if any(p in low for p in ("pause the task", "pause task", "pause it",
                                  "pause the current", "pause everything")):
            return TaskPlan(goal="pause the active task",
                            steps=[PlanStep(0, "core.pause", {}, "pause")],
                            mode=mode, source="heuristic")
        # word-boundary match, and never hijack commands that contain a real
        # path ("delete /tmp/on-cancel.txt" is a file operation, not a stop)
        if not re.search(r"(?:^|[\s'\"])(?:/|[A-Za-z]:[\\/])\S", c) and any(
                re.search(rf"\b{re.escape(w)}\b", low)
                for w in ("stop everything", "stop", "cancel", "never mind",
                          "abort", "kill all")):
            return TaskPlan(goal="cancel all tasks",
                            steps=[PlanStep(0, "core.cancel", {}, "interrupt")],
                            mode=mode, source="heuristic")

        # --- undo / rollback (V2 §13) ---------------------------------------
        # anchored on purpose: paths containing "undo" must not trigger it
        if low.startswith("undo"):
            return TaskPlan(goal="undo NOVA's last filesystem changes",
                            steps=[PlanStep(0, "undo.last", {}, "rollback")],
                            mode=mode, source="heuristic")

        # --- developer / introspection commands (V2 §59) ---------------------
        dev = self._developer_plan(low, mode)
        if dev is not None:
            return dev

        # --- session coreference (V2 §16): resolve pronouns from context ----
        sess = getattr(self, "session", session)
        if sess is not None and hasattr(sess, "apply_coreference"):
            resolved = sess.apply_coreference(c)
            if resolved != c:
                c, low = resolved, resolved.lower()

        steps: list[PlanStep] = []
        # ------------------------------------------------------------------
        # browser / search
        # ------------------------------------------------------------------
        if self._has(low, "search", "latest", "news") and self._has(low, "web", "google", "news", "for"):
            q = self._query_after(low, "for") or c
            steps.append(PlanStep(0, "web.search", {"query": q}, "search the web"))
        elif self._has(low, "open", "browser", "chrome") and self._has(low, "website", "site", "url", "http"):
            steps.append(PlanStep(0, "computer.launch_app", {"command": "chrome"}, ""))
        elif self._has(low, "take a screenshot") or self._has(low, "screenshot"):
            steps.append(PlanStep(0, "computer.screenshot", {}, "capture screen"))
        elif (self._has(low, "open") and self._has(low, "chrome", "browser")) or \
                low.strip().startswith("chrome"):
            steps.append(PlanStep(0, "computer.launch_app", {"command": "chrome"}, "launch Chrome"))
        # ------------------------------------------------------------------
        # VS Code / project build
        # ------------------------------------------------------------------
        elif self._has(low, "vscode", "vs code", "visual studio code"):
            steps.append(PlanStep(0, "vscode.open", {"path": self._maybe_project(c)}, "open VS Code"))
        elif self._has(low, "create a folder") or self._has(low, "make a folder") or \
                self._has(low, "new folder") or self._has(low, "create folder"):
            name = self._extract_quoted(c) or self._last_token_after(c, "called", "named") or "New Folder"
            steps.append(PlanStep(0, "filesystem.create_folder",
                                  {"path": name}, "create folder"))
        elif self._has(low, "create a file") or self._has(low, "write a file") or \
                (self._has(low, "create") and self._has(low, "file")):
            path, content = self._parse_file_request(c)
            steps.append(PlanStep(0, "filesystem.write_file",
                                  {"path": path, "content": content},
                                  "create file"))
        elif self._has(low, "build", "create", "make") and self._is_project_request(low):
            steps = self._build_plan(c)
        elif self._has(low, "open my college project") or \
                (self._has(low, "college project") and not self._is_explicit_path_command(low, c)):
            steps.append(PlanStep(0, "memory.recall", {"key": "college_projects"}, "recall path"))
            steps.append(PlanStep(1, "filesystem.list", {"path": "@college_projects"}, "open"))
        # ------------------------------------------------------------------
        # WhatsApp
        # ------------------------------------------------------------------
        elif self._has(low, "whatsapp"):
            contact = self._extract_contact(low)
            if self._has(low, "send") and self._has(low, "photo", "image", "media", "latest"):
                steps.append(PlanStep(0, "whatsapp.open", {"contact": contact}, "open WhatsApp"))
                steps.append(PlanStep(1, "whatsapp.find_media", {"contact": contact}, "find media"))
                steps.append(PlanStep(2, "whatsapp.download_media", {"contact": contact}, "download media"))
            elif self._has(low, "download", "save", "photo", "image", "media"):
                steps.append(PlanStep(0, "whatsapp.open", {"contact": contact}, "open chat"))
                steps.append(PlanStep(1, "whatsapp.download_media", {"contact": contact}, "download media"))
            elif self._has(low, "open") or self._has(low, "chat"):
                if contact:
                    steps.append(PlanStep(0, "whatsapp.open_chat", {"contact": contact}, "open chat"))
                else:
                    steps.append(PlanStep(0, "whatsapp.open", {}, "open WhatsApp"))
            else:
                steps.append(PlanStep(0, "whatsapp.open", {}, "open WhatsApp"))
        # ------------------------------------------------------------------
        # file operations
        # ------------------------------------------------------------------
        elif self._has(low, "delete", "remove", "trash"):
            paths = self._parse_path_list(c)
            if not paths:
                paths = [self._extract_quoted(c) or self._last_token_after(c, "file", "folder") or "unknown"]
            steps.append(PlanStep(0, "filesystem.delete", {"paths": paths, "use_recycle_bin": True},
                                  "delete (recycle bin)"))
        elif self._has(low, "rename") and self._has(low, " to "):
            src, dst = self._parse_from_to(c)
            if src and dst:
                steps.append(PlanStep(0, "filesystem.rename", {"source": src, "destination": dst}, "rename"))
        elif (self._has(low, "move") and self._has(low, " to ")) or self._has(low, "move all"):
            src, dst = self._parse_from_to(c)
            steps.append(PlanStep(0, "filesystem.move",
                                  {"source": src or "~/Downloads/*", "destination": dst or "~"},
                                  "move"))
        elif self._has(low, "copy") and self._has(low, " to "):
            src, dst = self._parse_from_to(c)
            if src and dst:
                steps.append(PlanStep(0, "filesystem.copy", {"source": src, "destination": dst}, "copy"))
        elif self._has(low, "move all pdf", "pdfs") and self._has(low, "downloads"):
            steps.append(PlanStep(0, "filesystem.organize", {"path": "~/Downloads"}, "organize"))
        elif self._has(low, "find", "locate") and self._has(low, "file", "resume", "pdf", "document"):
            q = self._query_after(low, "file") or "resume"
            steps.append(PlanStep(0, "filesystem.search", {"query": q, "start_dir": "~/"}, "search files"))
        elif self._has(low, "open my resume"):
            steps.append(PlanStep(0, "filesystem.search", {"query": "resume", "start_dir": "~/Documents"}, "find resume"))
        elif self._has(low, "largest files") or self._has(low, "biggest files"):
            steps.append(PlanStep(0, "filesystem.largest", {"path": "~/Downloads"}, "largest files"))
        elif self._has(low, "find my downloads") or self._has(low, "open downloads"):
            steps.append(PlanStep(0, "filesystem.list", {"path": "~/Downloads"}, "list Downloads"))
        # ------------------------------------------------------------------
        # run project / dev server
        # ------------------------------------------------------------------
        elif self._has(low, "run it") or self._has(low, "run the project") or self._has(low, "start the react"):
            steps.append(PlanStep(0, "shell.run", {"command": "npm run dev"}, "start dev server"))
        elif re.search(r"\brun\b", low) and self._has(low, "project"):
            steps.append(PlanStep(0, "shell.run", {"command": "npm start"}, "run project"))
        # ------------------------------------------------------------------
        # explicit shell command (V2 §22): run the command "X" / run command X
        # ------------------------------------------------------------------
        elif re.search(r"\brun\b", low) and (self._has(low, "command", "shell")
                                             or self._extract_quoted(c)):
            quoted = self._extract_quoted(c)
            if not quoted:
                m = re.search(r"\b(?:command|shell command)\s+[\"']?(.+?)[\"']?$",
                              c, re.IGNORECASE)
                quoted = (m.group(1).strip() if m else "").strip("\"'")
            if quoted:
                steps.append(PlanStep(0, "shell.run", {"command": quoted},
                                      "run the requested command"))
        # ------------------------------------------------------------------
        # generic "open X" → launch application
        # ------------------------------------------------------------------
        elif self._has(low, "open") or self._has(low, "launch") or self._has(low, "start"):
            app = self._app_to_launch(low)
            if app:
                steps.append(PlanStep(0, "computer.launch_app", {"command": app}, f"launch {app}"))
        # ------------------------------------------------------------------
        # conversation fallbacks (§44 conversational memory)
        # ------------------------------------------------------------------
        elif context and len(context) >= 1 and self._has(low, "latest", "photo", "image", "run", "download"):
            # refer back to previous step's contact/project
            last = context[-1]
            if last.get("name") in ("chat", "contact") and last.get("value"):
                steps.append(PlanStep(0, "whatsapp.download_media",
                                      {"contact": str(last["value"])}, "download latest from context"))
            elif last.get("name") == "project" and last.get("value"):
                steps.append(PlanStep(0, "shell.run", {"command": "npm run dev",
                                                       "cwd": str(last["value"])}, "rerun project"))

        if not steps and low.strip() in ("pause", "hold on"):
            steps = [PlanStep(0, "core.pause", {}, "bare pause keyword (§8)")]
        if not steps and low.strip() in ("resume", "continue"):
            steps = [PlanStep(0, "core.resume", {}, "bare resume keyword (§8)")]

        if not steps:
            # final fallback: echo-safe plan (still a real plan, and informative)
            steps = [
                PlanStep(0, "shell.run",
                         {"command": f"echo 'NOVA received: {c[:120].replace(chr(39), '')}'"},
                         "acknowledge command"),
            ]

        # renumber
        for i, s in enumerate(steps):
            s.seq = i
        return TaskPlan(goal=c, steps=steps, mode=mode, source="heuristic")

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _has(low: str, *needles: str) -> bool:
        return any(n in low for n in needles)

    def _is_explicit_path_command(self, low: str, c: str) -> bool:
        """True when the command already names a real filesystem path or uses a
        mutation verb — in which case a memory-placeholder shortcut must NOT
        hijack it (e.g. 'delete /…/College Projects/report.txt')."""
        if self._parse_path_list(c):
            return True
        return self._has(low, "delete", "remove", "trash", "move", "rename", "copy")

    @staticmethod
    def _query_after(low: str, marker: str) -> str:
        idx = low.find(marker)
        if idx >= 0:
            rest = low[idx + len(marker):].strip(" :,-")
            return rest[:120]
        return ""

    @staticmethod
    def _extract_quoted(text: str) -> str | None:
        m = re.search(r"['\"]([^'\"]{1,80})['\"]", text)
        return m.group(1) if m else None

    @staticmethod
    def _parse_file_request(text: str) -> tuple[str, str]:
        quoted = HeuristicPlanner._extract_quoted(text)
        low = text.lower()
        content = ""
        if " with content " in low:
            idx = low.find(" with content ")
            content = text[idx + len(" with content "):].strip().strip("'\"")
            path_part = text[:idx]
        elif " containing " in low:
            idx = low.find(" containing ")
            content = text[idx + len(" containing "):].strip().strip("'\"")
            path_part = text[:idx]
        else:
            path_part = text
        path = ""
        if quoted and quoted in path_part:
            path = quoted
        else:
            m = re.search(r"\bcalled\s+(.{1,200})", path_part, re.IGNORECASE)
            if m:
                path = m.group(1).strip().strip("'\"")
        if not path:
            path = "untitled.txt"
        return path[:300], content

    @staticmethod
    def _last_token_after(text: str, *markers: str) -> str:
        low = text.lower()
        best = ""
        for mk in markers:
            idx = low.rfind(mk)
            if idx >= 0:
                tail = text[idx + len(mk):].strip(" :,-")
                if tail:
                    best = tail
        return best[:80]

    _CONTACT_WORDS: ClassVar[set[str]] = {"rahul", "priya", "mom", "dad", "boss", "john", "sarika", "amit"}

    def _extract_contact(self, low: str) -> str:
        for word in self._CONTACT_WORDS:
            if word in low:
                return word
        # last capitalized word after "to/with/from"
        m = re.search(r"\b(?:to|with|from|chat with)\s+([A-Za-z]{2,20})(?:\s|$)", low)
        if m:
            return m.group(1)
        return ""

    _APPS: ClassVar[dict[str, str]] = {
        "notepad": "notepad", "calculator": "calc", "calc": "calc",
        "explorer": "explorer", "file explorer": "explorer",
        "terminal": "wt", "powershell": "powershell", "cmd": "cmd",
        "chrome": "chrome", "edge": "msedge", "firefox": "firefox",
        "spotify": "spotify", "word": "winword", "excel": "excel",
        "settings": "ms-settings:", "whatsapp": "whatsapp", "vscode": "code",
    }

    def _app_to_launch(self, low: str) -> str | None:
        for name, cmd in self._APPS.items():
            if name in low:
                return cmd
        m = re.search(r"\b(?:open|launch|start)\s+([a-z0-9 .]{2,30})", low)
        if m:
            candidate = m.group(1).strip()
            if candidate in self._APPS:
                return self._APPS[candidate]
            return candidate
        return None

    @staticmethod
    def _is_project_request(low: str) -> bool:
        return any(k in low for k in ("project", "website", "app", "site", "react",
                                      "dashboard", "portfolio", "chatbot", "blog"))

    def _build_plan(self, c: str) -> list[PlanStep]:
        name = self._extract_quoted(c) or "NovaProject"
        slug = re.sub(r"[^A-Za-z0-9]+", "-", name).strip("-") or "nova-project"
        project_dir = f"C:/NovaProjects/{slug}"
        return [
            PlanStep(0, "filesystem.create_folder", {"path": project_dir}, "create project dir"),
            PlanStep(1, "filesystem.write_file",
                     {"path": f"{project_dir}/package.json",
                      "content": _package_json(slug)}, "package.json"),
            PlanStep(2, "filesystem.write_file",
                     {"path": f"{project_dir}/index.html", "content": _index_html(name)},
                     "landing page"),
            PlanStep(3, "filesystem.write_file",
                     {"path": f"{project_dir}/src/main.js", "content": _main_js()}, "app entry"),
            PlanStep(4, "shell.run", {"command": "npm install", "cwd": project_dir},
                     "install deps"),
            PlanStep(5, "shell.run", {"command": "npm run build", "cwd": project_dir},
                     "build project"),
            PlanStep(6, "vscode.open", {"path": project_dir}, "open in VS Code"),
            PlanStep(7, "computer.launch_app", {"command": "chrome"}, "open browser"),
        ]

    async def _workflow_steps(self, low: str,
                              original: str | None = None) -> list[PlanStep] | None:
        """Look up stored workflows/aliases whose triggers match the command.

        §35: step arguments may contain ``{name}`` variables. Values are
        extracted from the spoken command ("from Rahul", "to Desktop",
        "called X", "in chrome"); anything unresolvable raises a clear error
        instead of running with literal placeholders. Extraction uses the
        ORIGINAL command so names/paths keep their capitalisation.
        """
        source = original or low
        if not self.registry.ctx or not getattr(self.registry.ctx, "session_factory", None):
            return None
        from database.service import list_workflows
        from workflows.engine import (MissingWorkflowVariable, render_variables,
                                      required_variables)
        try:
            with self.registry.ctx.session_factory() as s:
                rows = list_workflows(s)
        except Exception:
            return None
        for row in rows:
            if not row.triggers:
                continue
            for trig in row.triggers:
                if not trig or trig not in low:
                    continue
                raw_steps = [r for r in (row.steps or [])
                             if isinstance(r, dict) and r.get("tool")]
                needed: set[str] = set()
                for raw in raw_steps:
                    needed |= required_variables(raw.get("arguments") or {})
                variables = self._extract_variables(source, needed) if needed else {}
                rendered = [render_variables(r.get("arguments") or {}, variables)
                            for r in raw_steps]
                missing = sorted(required_variables(rendered))
                if missing:
                    raise MissingWorkflowVariable(
                        f"Workflow '{row.name}' needs: {', '.join(missing)}. "
                        f"Say them in the command (e.g. 'from Rahul to Desktop') "
                        f"or edit the workflow in Settings → Workflows.")
                return [PlanStep(i, raw["tool"], args, raw.get("rationale", ""))
                        for i, (raw, args)
                        in enumerate(zip(raw_steps, rendered, strict=True))]
        return None

    @staticmethod
    def _extract_variables(text: str, needed: set[str]) -> dict[str, str]:
        """Best-effort extraction of workflow variables from the command.
        *text* is the ORIGINAL command so values keep their capitalisation."""
        low = text
        import re as _re
        vals: dict[str, str] = {}
        cue_map = (
            ("contact", r"\bfrom\s+(.+?)(?:\s+\b(?:to|into|called)\b\s|$)"),
            ("destination", r"\b(?:to|into)\s+(.+?)(?:\s+\b(?:and|then|from|called)\b\s|$)"),
            ("folder", r"\b(?:to|into)\s+(.+?)(?:\s+\b(?:and|then|from|called)\b\s|$)"),
            ("name", r"\bcalled\s+(.+?)(?:\s+\b(?:and|then|with|from|to|into)\b\s|$)"),
            ("project", r"\bcalled\s+(.+?)(?:\s+\b(?:and|then|with|from|to|into)\b\s|$)"),
        )
        for var, pattern in cue_map:
            if var in needed and var not in vals:
                m = _re.search(pattern, low, _re.IGNORECASE)
                if m:
                    vals[var] = m.group(1).strip().strip(".,!?")
        if "browser" in needed and "browser" not in vals:
            for b in ("chrome", "edge", "firefox", "brave"):
                if b in low.lower():
                    vals["browser"] = b
                    break
        # quoted values fill any single remaining gap
        still = needed - set(vals)
        if len(still) == 1:
            m = _re.search(r"['\"]([^'\"]+)['\"]", low)
            if m:
                vals[next(iter(still))] = m.group(1)
        return vals

    @staticmethod
    def _parse_from_to(text: str) -> tuple[str, str]:
        """Split 'move <A> to <B>' style commands into (source, destination)."""
        low = text.lower()
        for marker in (" to ", " into "):
            idx = low.find(marker)
            if idx >= 0:
                head = text[:idx]
                tail = text[idx + len(marker):].strip()
                # strip leading verb
                m = re.search(r"\b(?:move|copy|rename)\s+(.{1,300})", head, re.IGNORECASE)
                src = (m.group(1).strip() if m else head.strip()).strip("'\"")
                return src[:300] or "", tail[:300]
        return text, ""

    @staticmethod
    def _parse_path_list(text: str) -> list[str]:
        """Extract path-like tokens from a delete request.

        Spaces inside a path are preserved: a path begins with '/' or a drive
        letter and runs to the next comma/semicolon. Conjunctions split multi-path
        requests ("delete /a and /b").
        """
        quoted = re.findall(r"['\"]([^'\"]+)['\"]", text)
        if quoted:
            return quoted[:40]
        paths: list[str] = []
        for m in re.finditer(r"(?:/|[A-Za-z]:[\\/])[^,;]*", text):
            for part in re.split(r"\s+(?:and|or)\s+", m.group(0)):
                part = part.strip()
                # drop a trailing sentence period (but keep real extensions)
                if part.endswith(".") and part.count(".") > 1:
                    part = part[:-1]
                if part:
                    paths.append(part)
        return paths[:40]

    def _maybe_project(self, c: str) -> str:
        low = c.lower()
        quoted = self._extract_quoted(c)
        if quoted:
            return quoted
        explicit = self._parse_path_list(c)
        if explicit:
            return explicit[0]
        if "college" in low:
            return "@college_projects"
        return "."

    # ------------------------------------------------------------------
    def _developer_plan(self, low: str, mode: str) -> TaskPlan | None:
        """Introspection / developer voice commands (V2 §58/§59)."""
        table: tuple[tuple[tuple[str, ...], str, str, str], ...] = (
            (("show current plan", "show the plan", "show plan", "what is the plan",
              "what's the plan"),
             "introspection.plan", "show the current plan", "show current plan"),
            (("show current task", "show task", "what are you doing",
              "what is running"),
             "introspection.task", "show the current task", "show current task"),
            (("show last error", "last error", "show errors"),
             "introspection.last_error", "show the most recent error", "show last error"),
            (("show logs", "show the logs", "show events"),
             "introspection.logs", "show recent agent events", "show logs"),
            (("list tools", "list available tools", "what tools"),
             "introspection.tools", "list registered tools", "list tools"),
            (("list permissions", "show permissions"),
             "introspection.permissions", "show permission policy", "list permissions"),
            (("run diagnostics", "run a diagnostic", "full diagnostic",
              "run a full nova diagnostic", "diagnose"),
             "introspection.diagnostics", "run self diagnostics", "run diagnostics"),
        )
        for phrases, tool, rationale, goal in table:
            if any(p in low for p in phrases):
                return TaskPlan(goal=goal,
                                steps=[PlanStep(0, tool, {}, rationale)],
                                mode=mode, source="heuristic")
        if self._has(low, "clear memory") and self._has(low, "clear"):
            return TaskPlan(goal="clear all stored memories",
                            steps=[PlanStep(0, "memory.clear", {}, "clear memory")],
                            mode=mode, source="heuristic")
        if self._has(low, "show memory") or self._has(low, "what do you remember"):
            return TaskPlan(goal="show stored memories",
                            steps=[PlanStep(0, "memory.list", {}, "list memory")],
                            mode=mode, source="heuristic")
        return None


# ---------------------------------------------------------------------------
# project file templates used by build mode
# ---------------------------------------------------------------------------
def _package_json(slug: str) -> str:
    import json
    return json.dumps({
        "name": slug, "version": "1.0.0", "private": True, "type": "module",
        "scripts": {"dev": "vite", "build": "vite build", "preview": "vite preview"},
        "dependencies": {"react": "^18.3.1", "react-dom": "^18.3.1"},
        "devDependencies": {"@vitejs/plugin-react": "^4.3.1", "vite": "^5.4.0"},
    }, indent=2)


def _index_html(name: str) -> str:
    return f"""<!doctype html>
<html lang="en">
  <head><meta charset="UTF-8" /><meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>{name}</title></head>
  <body>
    <div id="app"></div>
    <script type="module" src="/src/main.js"></script>
  </body>
</html>
"""


def _main_js() -> str:
    return """import { createRoot } from "react-dom/client";
import React from "react";

function App() {
  return (
    <main style={{ fontFamily: "system-ui", padding: 48 }}>
      <h1>Hello from NOVA 👋</h1>
      <p>This project was generated by the NOVA build agent.</p>
    </main>
  );
}

createRoot(document.getElementById("app")).render(<App />);
"""
