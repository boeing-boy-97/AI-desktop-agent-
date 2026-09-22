"""Workflow engine — sequential/parallel multi-step execution (spec §20,
§34-35).

A workflow is a named list of tool steps with optional conditions, retries
and delays. Steps run sequentially by default; steps marked ``parallel: true``
are fanned out with asyncio.gather. Cancellation is honoured between steps.

Variables (§35): step arguments may reference ``{name}`` placeholders which
are substituted from the ``variables`` mapping at run time. Missing variables
raise ``MissingWorkflowVariable`` with an actionable message — a workflow is
NEVER silently run with unresolved placeholders.
"""
from __future__ import annotations

import asyncio
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from core.exceptions import NovaError, TaskCancelled

_VAR_RE = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")


class MissingWorkflowVariable(NovaError):
    code = "WORKFLOW_VARIABLE"


def render_variables(obj: Any, variables: dict) -> Any:
    """Recursively substitute ``{name}`` tokens in strings/dicts/lists.
    Unknown tokens are left as-is so callers can detect them."""
    if isinstance(obj, str):
        return _VAR_RE.sub(lambda m: str(variables.get(m.group(1), m.group(0))), obj)
    if isinstance(obj, dict):
        return {k: render_variables(v, variables) for k, v in obj.items()}
    if isinstance(obj, list):
        return [render_variables(v, variables) for v in obj]
    return obj


def required_variables(obj: Any) -> set[str]:
    """All ``{name}`` tokens still present in *obj* after rendering."""
    found: set[str] = set()

    def walk(o: Any) -> None:
        if isinstance(o, str):
            found.update(_VAR_RE.findall(o))
        elif isinstance(o, dict):
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    walk(obj)
    return found


@dataclass
class WorkflowStep:
    tool: str
    arguments: dict = field(default_factory=dict)
    parallel: bool = False
    condition: str | None = None     # "success" | "failed" | "always"
    timeout: float = 60.0
    retries: int = 0
    delay: float = 0.0
    label: str = ""

    def as_dict(self) -> dict:
        return {"tool": self.tool, "arguments": self.arguments,
                "parallel": self.parallel, "condition": self.condition,
                "timeout": self.timeout, "retries": self.retries,
                "delay": self.delay, "label": self.label}


@dataclass
class Workflow:
    name: str
    steps: list[WorkflowStep]
    triggers: list[str] = field(default_factory=list)
    enabled: bool = True

    def as_dict(self) -> dict:
        return {"name": self.name, "triggers": self.triggers, "enabled": self.enabled,
                "steps": [s.as_dict() for s in self.steps]}


class StepRunner:
    """Callable that executes one step (tool name + args) → ToolResult."""

    def __init__(self, run_fn: Callable) -> None:
        self.run_fn = run_fn

    async def __call__(self, step: WorkflowStep, ctx: dict) -> Any:
        result = await self.run_fn(step.tool, step.arguments, ctx)
        return result


class WorkflowEngine:
    """Executes workflows with sequencing, parallelism (when safe), retries
    and cancellation."""

    def __init__(self, registry, executor=None, event_bus=None) -> None:
        self.registry = registry
        self.executor = executor
        self.event_bus = event_bus

    # ------------------------------------------------------------------
    async def run(self, workflow: Workflow, *,
                  task_id: str = "",
                  variables: dict | None = None,
                  cancel_check: Callable[[], bool] | None = None,
                  run_fn: Callable | None = None) -> dict:
        if run_fn is None:
            run_fn = self._default_run
        variables = dict(variables or {})
        results: list[dict] = []
        ctx: dict = {"task_id": task_id}

        idx = 0
        while idx < len(workflow.steps):
            batch: list[WorkflowStep] = [workflow.steps[idx]]
            if workflow.steps[idx].parallel:
                while idx + 1 < len(workflow.steps) and workflow.steps[idx + 1].parallel:
                    batch.append(workflow.steps[idx + 1])
                    idx += 1
            if cancel_check and cancel_check():
                raise TaskCancelled("workflow cancelled")

            # §35 — substitute {name} variables; refuse to run with gaps
            rendered: list[WorkflowStep] = []
            for s in batch:
                args = render_variables(s.arguments, variables)
                missing = sorted(required_variables(args))
                if missing:
                    raise MissingWorkflowVariable(
                        f"Workflow '{workflow.name}' needs variable(s) "
                        f"{', '.join('{' + m + '}' for m in missing)} — "
                        f"provide them, e.g. edit the workflow or supply the values.")
                rendered.append(WorkflowStep(
                    tool=s.tool, arguments=args, parallel=s.parallel,
                    condition=s.condition, timeout=s.timeout, retries=s.retries,
                    delay=s.delay, label=s.label))

            # §34 — conditions gate a batch on the previous step's outcome
            cond = rendered[0].condition
            if cond and cond not in ("always",):
                prev_ok = bool(ctx.get("success", True))
                if (cond == "success" and not prev_ok) or (cond == "failed" and prev_ok):
                    results.append({"tool": rendered[0].tool,
                                    "label": rendered[0].label,
                                    "result": {"skipped": True, "condition": cond}})
                    idx += 1
                    continue

            if len(rendered) > 1:
                outs = await asyncio.gather(*[run_fn(s, ctx) for s in rendered])
            else:
                outs = [await self._with_retries(rendered[0], ctx, run_fn)]

            for step, out in zip(rendered, outs, strict=True):
                results.append({"tool": step.tool, "label": step.label,
                                "result": out.as_dict() if hasattr(out, "as_dict") else str(out)})
                ctx["last"] = step.tool
                ctx["last_result"] = out
                ctx["success"] = getattr(out, "success", True)
            idx += 1
        return {"results": results, "success": ctx.get("success", True)}

    async def _with_retries(self, step: WorkflowStep, ctx: dict, run_fn) -> Any:
        if step.delay > 0:
            await asyncio.sleep(step.delay)
        attempts = 0
        last = None
        while attempts <= step.retries:
            try:
                return await asyncio.wait_for(run_fn(step, ctx), timeout=step.timeout)
            except asyncio.TimeoutError:
                last = NovaError(f"{step.tool} timed out")
            except Exception as exc:
                last = exc
            attempts += 1
        if isinstance(last, NovaError):
            raise last
        from core.exceptions import ActionFailed
        raise ActionFailed(f"{step.tool} failed after {attempts} retries: {last}")

    async def _default_run(self, step: WorkflowStep, ctx: dict) -> Any:
        if self.executor is None:
            raise NovaError("no executor attached to workflow engine")
        from planner.planner import PlanStep
        return await self.executor.execute_step(
            PlanStep(0, step.tool, step.arguments), task_id=ctx.get("task_id", ""),
            step_index=0, attempt_context={})

    # ------------------------------------------------------------------
    @staticmethod
    def parse(data: dict) -> Workflow:
        steps = []
        for raw in data.get("steps", []):
            if not isinstance(raw, dict):
                continue
            steps.append(WorkflowStep(
                tool=str(raw.get("tool", "")),
                arguments=raw.get("arguments") or {},
                parallel=bool(raw.get("parallel", False)),
                condition=raw.get("condition"),
                timeout=float(raw.get("timeout", 60.0)),
                retries=int(raw.get("retries", 0)),
                delay=float(raw.get("delay", 0.0)),
                label=str(raw.get("label", "")),
            ))
        return Workflow(name=str(data.get("name", "unnamed")), steps=steps,
                        triggers=list(data.get("triggers", [])),
                        enabled=bool(data.get("enabled", True)))
