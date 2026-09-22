"""Planner package."""
from planner.heuristic import HeuristicPlanner
from planner.planner import IntelligentPlanner, Planner, PlanStep, TaskPlan


def create_planner(settings, registry, ai_provider, memory_context=None,
                   force_heuristic: bool = False, session=None) -> Planner:
    if force_heuristic or not ai_provider:
        return HeuristicPlanner(settings, registry, ai_provider, memory_context,
                                session=session)
    name = settings.get_str("ai.provider", "openai").lower()
    if name in ("mock", "demo", "heuristic"):
        return HeuristicPlanner(settings, registry, ai_provider, memory_context,
                                session=session)
    return IntelligentPlanner(settings, registry, ai_provider, memory_context)


__all__ = [
    "HeuristicPlanner",
    "IntelligentPlanner",
    "PlanStep",
    "Planner",
    "TaskPlan",
    "create_planner",
]
