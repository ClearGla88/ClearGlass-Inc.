#!/usr/bin/env python3
"""ClearGlass 50/30/20 content planning agent.

Produces drafts only. It never publishes content or performs network activity.
"""
from __future__ import annotations

import argparse
import json
import re
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

PILLARS = ("clarity_breakdown", "founder_reality", "product_demo")
ALLOCATION = (5, 3, 2)


@dataclass(frozen=True)
class Draft:
    number: int
    pillar: str
    title: str
    hook: str
    script: list[str]
    shot: str
    cta: str
    evidence: list[str]
    status: str = "DRAFT_REQUIRES_HUMAN_APPROVAL"


@dataclass(frozen=True)
class PaidAction:
    reel_id: str
    decision: str
    budget_cad_per_day: int
    reason: str
    status: str = "RECOMMENDATION_REQUIRES_HUMAN_APPROVAL"


def _valid_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme == "https" and bool(parsed.netloc)


def validate_seed(seed: dict) -> None:
    required = {"opacity_issue", "security_consequence", "founder_truth", "product", "feature", "pain", "demo", "sources"}
    missing = sorted(required - seed.keys())
    if missing:
        raise ValueError("Missing seed fields: " + ", ".join(missing))
    if not isinstance(seed["sources"], list) or not seed["sources"]:
        raise ValueError("At least one public source is required for Clarity Breakdowns")
    if any(not _valid_url(item) for item in seed["sources"]):
        raise ValueError("Every source must be a valid HTTPS URL")
    for key in required - {"sources"}:
        if not isinstance(seed[key], str) or not seed[key].strip():
            raise ValueError(f"{key} must be a non-empty string")


def _clean(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def build_plan(seed: dict) -> list[Draft]:
    validate_seed(seed)
    content_keys = {"opacity_issue", "security_consequence", "founder_truth", "product", "feature", "pain", "demo"}
    s = {key: _clean(seed[key]) for key in content_keys}
    s["sources"] = [_clean(item) for item in seed["sources"]]
    drafts: list[Draft] = []
    for index in range(ALLOCATION[0]):
        drafts.append(Draft(
            len(drafts) + 1, PILLARS[0], f"Clarity Breakdown {index + 1}",
            f"If the public cannot see {s['opacity_issue']}, defenders cannot measure the risk.",
            [f"Public problem: {s['opacity_issue']}.", f"Security consequence: {s['security_consequence']}.",
             "Show the primary-source evidence on screen. Separate verified fact from analysis.",
             "Close: transparency is a security control, not decoration."],
            "Direct-to-camera; insert source screenshot and highlight the exact supporting line.",
            "Ask one precise accountability question.", s["sources"]))
    for index in range(ALLOCATION[1]):
        drafts.append(Draft(
            len(drafts) + 1, PILLARS[1], f"Founder Reality {index + 1}",
            "Building security infrastructure is less glamorous than the finished dashboard.",
            [s["founder_truth"], "Name the decision, constraint, or mistake plainly.",
             "State what changed today and what ships next."],
            "Raw phone video at desk, parked car, or walking; one take; natural sound; no beauty filter.",
            "Invite operators to compare notes.", []))
    for index in range(ALLOCATION[2]):
        drafts.append(Draft(
            len(drafts) + 1, PILLARS[2], f"{s['product']} in 30 Seconds {index + 1}",
            f"Still fighting {s['pain']}?",
            [f"Pain (0-7s): {s['pain']}.", f"Feature (7-15s): {s['feature']}.",
             f"Demo (15-25s): {s['demo']}.", "Close (25-30s): show the measurable operator outcome; do not invent results."],
            "Screen recording with cursor emphasis, large captions, and a visible 30-second timer.",
            f"Request a {s['product']} walkthrough.", []))
    return drafts


def evaluate_paid(performance: list[dict]) -> list[PaidAction]:
    """Turn Reel telemetry into bounded recommendations, never ad-platform writes."""
    actions: list[PaidAction] = []
    required = {"reel_id", "hours_since_publish", "completion_rate", "hook_retention", "spend_cad"}
    for row in performance:
        missing = sorted(required - row.keys())
        if missing:
            raise ValueError("Missing performance fields: " + ", ".join(missing))
        reel_id = _clean(str(row["reel_id"]))
        hours = float(row["hours_since_publish"])
        completion = float(row["completion_rate"])
        hook = float(row["hook_retention"])
        spend = float(row["spend_cad"])
        if not reel_id or hours < 0 or spend < 0 or not 0 <= completion <= 1 or not 0 <= hook <= 1:
            raise ValueError("Performance values are outside allowed ranges")
        if spend >= 5 and hook < .30:
            actions.append(PaidAction(reel_id, "PAUSE", 0, "Hook retention is below 30% after at least CAD 5 spend."))
        elif completion > .50 and hours <= 6 and spend == 0:
            actions.append(PaidAction(reel_id, "SEED", 10, "Organic completion exceeded 50% within six hours."))
        elif spend > 0 and hook >= .30:
            actions.append(PaidAction(reel_id, "SCALE_CAP", 20, "Paid hook retention is at least 30%; cap proposed spend at CAD 20/day."))
        else:
            actions.append(PaidAction(reel_id, "HOLD_ORGANIC", 0, "The Reel has not met a paid promotion gate."))
    return actions


def render_markdown(drafts: list[Draft], paid: list[PaidAction], generated: str) -> str:
    lines = ["# ClearGlass Content Brief", "", f"Generated: {generated}", "", "Allocation: 5 Clarity Breakdowns / 3 Founder Reality / 2 Product Demos", "",
             "> Drafts only. Verify every factual claim against the linked primary source. Human approval is mandatory before publication.", ""]
    for item in drafts:
        lines += [f"## {item.number}. {item.title}", "", f"**Pillar:** `{item.pillar}`  ", f"**Status:** `{item.status}`  ",
                  f"**Hook:** {item.hook}", "", "**Script**", ""]
        lines += [f"{i}. {line}" for i, line in enumerate(item.script, 1)]
        lines += ["", f"**Shot:** {item.shot}", "", f"**CTA:** {item.cta}", ""]
        if item.evidence:
            lines += ["**Evidence**", ""] + [f"- {url}" for url in item.evidence] + [""]
    lines += ["## Phase 3: Paid Domination", "", "**Operating rule:** boost measured winners, not production value. All spend changes remain recommendations until a human approves them in Meta Ads Manager.", "",
              "### Campaign 1: Seeding", "", "Publish five Reels organically. A Reel may receive a CAD 10/day Engagement test with Advantage+ Audience and Advantage+ Placements only when organic completion exceeds 50% within six hours.", "",
              "### Campaign 2: Profile Domination", "", "Retarget consented three-second video viewers with a Feed carousel: Why clarity is the product; Artemis; Founder story. CTA: Follow Profile.", "",
              "### Campaign 3: Lead Magnet", "", "Offer “Compliant vs Secure: 7-Gap Audit for Canadian SMBs.” Collect only the minimum email data with clear consent and a privacy notice. Any Facebook invitation must comply with that consent.", "",
              "### Measurement decisions", ""]
    if paid:
        lines += [f"- `{item.reel_id}`: **{item.decision}** at CAD {item.budget_cad_per_day}/day — {item.reason} `{item.status}`" for item in paid]
    else:
        lines += ["- No Reel telemetry supplied. No budget recommendation generated."]
    lines += ["", "### Data and budget controls", "", "- Meta Pixel must remain disabled until a valid Pixel ID and analytics/advertising consent are available.",
              "- Never commit, log, or pass customer emails to this agent. Upload a lawfully collected, consented list directly through Meta's secured interface after privacy review.",
              "- Never claim universal CPA improvement. Record ClearGlass baseline, test window, spend, placements, and result before drawing a conclusion.",
              "- A recommendation cannot create, pause, scale, or publish an ad. Human approval is mandatory.", ""]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a governed ClearGlass 50/30/20 content brief")
    parser.add_argument("--seed", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("content-brief.md"))
    parser.add_argument("--json-output", type=Path)
    args = parser.parse_args()
    seed = json.loads(args.seed.read_text(encoding="utf-8"))
    drafts = build_plan(seed)
    paid = evaluate_paid(seed.get("paid_performance", []))
    args.output.write_text(render_markdown(drafts, paid, date.today().isoformat()) + "\n", encoding="utf-8")
    if args.json_output:
        payload = {"organic_drafts": [asdict(item) for item in drafts], "paid_recommendations": [asdict(item) for item in paid]}
        args.json_output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
