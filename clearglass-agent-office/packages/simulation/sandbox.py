"""Simulation Chamber: seeded what-if models over operator-stated assumptions.

Isolation: this module imports nothing from the office runtime, the tool
registry, or any connector. A scenario is a pure function of its assumptions,
its options, and a seed, so a run cannot reach production systems and the same
inputs always give the same outputs.

Honesty: each result carries the disclaimer below. The numbers follow only from
the ranges the operator typed in; they are not forecasts and they are never
shown as observed data.

Ranges are given as {"low": a, "mode": b, "high": c} (triangular; ``mode``
optional, defaults to the midpoint) or as a plain number (fixed).
"""

from __future__ import annotations

import random
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

DISCLAIMER = (
    "Model output from the assumptions listed. Not a forecast and not observed data. "
    "Change an assumption and the result changes with it."
)
MAX_RUNS = 20000


class SimulationError(ValueError):
    pass


def draw(rng: random.Random, spec: Any, name: str) -> float:
    if isinstance(spec, (int, float)) and not isinstance(spec, bool):
        return float(spec)
    if not isinstance(spec, dict) or "low" not in spec or "high" not in spec:
        raise SimulationError(f"assumption '{name}' must be a number or {{low, high[, mode]}}")
    low, high = float(spec["low"]), float(spec["high"])
    if low > high:
        raise SimulationError(f"assumption '{name}': low > high")
    mode = float(spec.get("mode", (low + high) / 2))
    if not low <= mode <= high:
        raise SimulationError(f"assumption '{name}': mode outside [low, high]")
    return rng.triangular(low, high, mode)


def quantile(sorted_values: list[float], q: float) -> float:
    if not sorted_values:
        return 0.0
    idx = (len(sorted_values) - 1) * q
    lo, hi = int(idx), min(int(idx) + 1, len(sorted_values) - 1)
    return sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * (idx - lo)


@dataclass(frozen=True)
class Scenario:
    name: str
    description: str
    objective: str
    direction: str  # "maximize" | "minimize"
    metrics: tuple[str, ...]
    sample: Callable[[random.Random, dict[str, Any], dict[str, Any]], dict[str, float]]
    example: dict[str, Any]


def _pricing(rng: random.Random, a: dict[str, Any], o: dict[str, Any]) -> dict[str, float]:
    leads = draw(rng, a["monthly_qualified_leads"], "monthly_qualified_leads")
    base_conv = draw(rng, a["conversion_at_reference_price"], "conversion_at_reference_price")
    elasticity = draw(rng, a["price_elasticity"], "price_elasticity")
    ref = float(a["reference_price"])
    price = float(o["price"])
    conv = max(0.0, min(1.0, base_conv * (price / ref) ** elasticity))
    clients = leads * conv
    return {"new_clients": clients, "monthly_revenue": clients * price}


def _campaign(rng: random.Random, a: dict[str, Any], o: dict[str, Any]) -> dict[str, float]:
    budget = float(o["budget"])
    cpl = max(1e-9, draw(rng, o["cost_per_lead"], "cost_per_lead"))
    close = draw(rng, a["lead_to_client_rate"], "lead_to_client_rate")
    value = draw(rng, a["client_first_year_value"], "client_first_year_value")
    leads = budget / cpl
    clients = leads * close
    return {
        "leads": leads,
        "clients": clients,
        "return_on_spend": (clients * value - budget) / budget if budget else 0.0,
    }


def _incident(rng: random.Random, a: dict[str, Any], o: dict[str, Any]) -> dict[str, float]:
    # Red team: the adversary's dwell before detection depends on the playbook's detection.
    detect = draw(rng, o["detect_hours"], "detect_hours")
    contain = draw(rng, o["contain_hours"], "contain_hours")
    success = draw(rng, o["containment_success"], "containment_success")
    cost_per_hour = draw(rng, a["impact_cost_per_hour"], "impact_cost_per_hour")
    escalation = draw(rng, a["escalation_hours_if_failed"], "escalation_hours_if_failed")
    hours = detect + contain + (0.0 if rng.random() < success else escalation)
    return {"hours_to_contain": hours, "impact_cost": hours * cost_per_hour}


def _rollout(rng: random.Random, a: dict[str, Any], o: dict[str, Any]) -> dict[str, float]:
    fail = draw(rng, a["change_failure_probability"], "change_failure_probability")
    users = float(a["active_users"])
    exposed = float(o["exposed_fraction"])
    detect = draw(rng, o["detect_minutes"], "detect_minutes")
    rollback = draw(rng, o["rollback_minutes"], "rollback_minutes")
    failed = rng.random() < fail
    impact = users * exposed * (detect + rollback) if failed else 0.0
    return {"user_minutes_impacted": impact, "failed": 1.0 if failed else 0.0}


SCENARIOS: dict[str, Scenario] = {
    "pricing": Scenario(
        "pricing",
        "Compare monthly advisory price points under demand uncertainty.",
        "monthly_revenue",
        "maximize",
        ("new_clients", "monthly_revenue"),
        _pricing,
        {
            "assumptions": {
                "reference_price": 1500,
                "monthly_qualified_leads": {"low": 4, "mode": 8, "high": 14},
                "conversion_at_reference_price": {"low": 0.10, "mode": 0.20, "high": 0.30},
                "price_elasticity": {"low": -1.6, "mode": -1.0, "high": -0.5},
            },
            "options": [
                {"name": "Hold at $1,500/mo", "price": 1500},
                {"name": "Raise to $1,900/mo", "price": 1900},
                {"name": "Entry tier at $950/mo", "price": 950},
            ],
        },
    ),
    "campaign": Scenario(
        "campaign",
        "Compare campaign budgets and channels by return on spend.",
        "return_on_spend",
        "maximize",
        ("leads", "clients", "return_on_spend"),
        _campaign,
        {
            "assumptions": {
                "lead_to_client_rate": {"low": 0.03, "mode": 0.08, "high": 0.15},
                "client_first_year_value": {"low": 6000, "mode": 12000, "high": 20000},
            },
            "options": [
                {
                    "name": "LinkedIn organic + events",
                    "budget": 600,
                    "cost_per_lead": {"low": 40, "mode": 90, "high": 200},
                },
                {"name": "Paid search, local", "budget": 1500, "cost_per_lead": {"low": 60, "mode": 140, "high": 300}},
            ],
        },
    ),
    "incident": Scenario(
        "incident",
        "Red team vs blue team tabletop: compare response playbooks by time to contain.",
        "impact_cost",
        "minimize",
        ("hours_to_contain", "impact_cost"),
        _incident,
        {
            "assumptions": {
                "impact_cost_per_hour": {"low": 200, "mode": 600, "high": 2500},
                "escalation_hours_if_failed": {"low": 12, "mode": 24, "high": 72},
            },
            "options": [
                {
                    "name": "Ad-hoc response",
                    "detect_hours": {"low": 4, "mode": 24, "high": 96},
                    "contain_hours": {"low": 2, "mode": 8, "high": 24},
                    "containment_success": {"low": 0.4, "mode": 0.6, "high": 0.8},
                },
                {
                    "name": "Written playbook + drills",
                    "detect_hours": {"low": 1, "mode": 4, "high": 24},
                    "contain_hours": {"low": 1, "mode": 3, "high": 8},
                    "containment_success": {"low": 0.7, "mode": 0.85, "high": 0.95},
                },
            ],
        },
    ),
    "rollout": Scenario(
        "rollout",
        "Compare deployment strategies by user impact when a change fails.",
        "user_minutes_impacted",
        "minimize",
        ("user_minutes_impacted", "failed"),
        _rollout,
        {
            "assumptions": {
                "change_failure_probability": {"low": 0.02, "mode": 0.08, "high": 0.2},
                "active_users": 400,
            },
            "options": [
                {
                    "name": "Big-bang",
                    "exposed_fraction": 1.0,
                    "detect_minutes": {"low": 5, "mode": 20, "high": 60},
                    "rollback_minutes": {"low": 10, "mode": 20, "high": 45},
                },
                {
                    "name": "Canary 10%",
                    "exposed_fraction": 0.1,
                    "detect_minutes": {"low": 2, "mode": 8, "high": 20},
                    "rollback_minutes": {"low": 2, "mode": 5, "high": 10},
                },
            ],
        },
    ),
}


def run_scenario(
    scenario_type: str,
    assumptions: dict[str, Any],
    options: list[dict[str, Any]],
    *,
    seed: int = 7,
    runs: int = 2000,
) -> dict[str, Any]:
    scenario = SCENARIOS.get(scenario_type)
    if scenario is None:
        raise SimulationError(f"unknown scenario '{scenario_type}'; choose from {sorted(SCENARIOS)}")
    if not options or len(options) > 6:
        raise SimulationError("provide 1 to 6 options")
    if not 100 <= runs <= MAX_RUNS:
        raise SimulationError(f"runs must be between 100 and {MAX_RUNS}")
    results: dict[str, Any] = {}
    for idx, option in enumerate(options):
        name = str(option.get("name") or f"Option {idx + 1}")
        rng = random.Random(f"{seed}:{scenario_type}:{idx}")
        samples: dict[str, list[float]] = {m: [] for m in scenario.metrics}
        try:
            for _ in range(runs):
                for metric, value in scenario.sample(rng, assumptions, option).items():
                    samples[metric].append(value)
        except KeyError as exc:
            raise SimulationError(f"missing assumption or option field {exc}") from exc
        summary = {}
        for metric, values in samples.items():
            values.sort()
            summary[metric] = {
                "p10": round(quantile(values, 0.10), 2),
                "p50": round(quantile(values, 0.50), 2),
                "p90": round(quantile(values, 0.90), 2),
                "mean": round(sum(values) / len(values), 2),
            }
        results[name] = summary

    obj, maximize = scenario.objective, scenario.direction == "maximize"

    def key(name: str) -> tuple[float, float]:
        s = results[name][obj]
        # Primary: median. Tie-break on the downside (p10 when maximizing, p90 when minimizing).
        return (s["p50"], s["p10"]) if maximize else (-s["p50"], -s["p90"])

    best = max(results, key=key)
    downside = "p10" if maximize else "p90"
    recommendation = {
        "option": best,
        "objective": obj,
        "direction": scenario.direction,
        "rationale": (
            f"Best median {obj} ({results[best][obj]['p50']}) under the stated assumptions; "
            f"downside {downside} is {results[best][obj][downside]}."
        ),
        "conditions": "Holds only if the assumption ranges are right. Re-run when you have observed data.",
    }
    return {
        "scenario": scenario_type,
        "description": scenario.description,
        "results": results,
        "recommendation": recommendation,
        "seed": seed,
        "runs": runs,
        "disclaimer": DISCLAIMER,
    }


def after_action_report(sim: dict[str, Any], title: str) -> dict[str, Any]:
    rec = sim["recommendation"]
    lines = [f"Scenario: {sim['description']}", f"Runs per option: {sim['runs']} (seed {sim['seed']})"]
    for name, metrics in sim["results"].items():
        obj = metrics[rec["objective"]]
        lines.append(f"- {name}: {rec['objective']} p10 {obj['p10']} / p50 {obj['p50']} / p90 {obj['p90']}")
    return {
        "title": f"After-action report: {title}",
        "summary": lines,
        "decision": f"Recommend '{rec['option']}'. {rec['rationale']}",
        "conditions": rec["conditions"],
        "disclaimer": sim["disclaimer"],
    }
