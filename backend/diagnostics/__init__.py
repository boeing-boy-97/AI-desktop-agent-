"""Diagnostics package: runtime checks + self-repair loop (spec §36, §38)."""
from diagnostics.checks import CheckResult, run_diagnostics
from diagnostics.self_repair import SelfRepair

__all__ = ["CheckResult", "SelfRepair", "run_diagnostics"]
