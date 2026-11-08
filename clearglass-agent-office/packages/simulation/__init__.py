"""Sandboxed, seeded what-if simulations. No imports from the office runtime or connectors."""

from simulation.sandbox import (
    DISCLAIMER,
    SCENARIOS,
    Scenario,
    SimulationError,
    after_action_report,
    run_scenario,
)

__all__ = ["DISCLAIMER", "SCENARIOS", "Scenario", "SimulationError", "after_action_report", "run_scenario"]
