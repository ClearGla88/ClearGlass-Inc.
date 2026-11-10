"""Internal tool handlers ("skills").

Each handler takes the execution context built by the governed executor and
returns ``{"summary": str, "artifact": ..., optional "messages", "report",
"decision"}``. Handlers only run after the policy engine has allowed the
action, and they only see the parameters they were given plus read-only office
state.

Ground rules every handler follows:
- Build outputs from inputs and recorded state only. No invented facts,
  numbers, names, or results.
- Keep the source of every item; mark anything without one as unverified.
- A model rewrite (optional provider) is rejected if it introduces digits
  that were not in the template draft, a cheap guard against invented figures.

Actions without a handler here (``code.commit_branch``, ``data.update_internal``)
fail with a clear error instead of pretending to work.
External and critical actions route to the dry-run connector.
"""

from __future__ import annotations

import json
import re
from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

from agent_core.models import Simulation
from agent_core.util import parse_iso
from audit_ledger.canonical import find_secrets
from simulation.sandbox import after_action_report, run_scenario

if TYPE_CHECKING:
    from agent_core.office import Office

Ctx = dict[str, Any]
_DIGITS = re.compile(r"\d+(?:[.,]\d+)?")


def _office(ctx: Ctx) -> Office:
    return ctx["office"]


def _rewrite(ctx: Ctx, draft: str, purpose: str) -> tuple[str, str]:
    """Optionally improve a draft with the configured provider. Returns (text, provenance)."""
    office = _office(ctx)
    provider = office.provider
    improved = provider.rewrite(draft, purpose)
    if not improved:
        return draft, provider.name if provider.name == "offline-template" else f"{provider.name} (kept template)"
    new_numbers = set(_DIGITS.findall(improved)) - set(_DIGITS.findall(draft))
    if new_numbers or find_secrets(improved):
        return draft, f"{provider.name} (rewrite rejected: introduced unverified figures)"
    return improved, provider.name


# -- documents ------------------------------------------------------------------


def docs_draft(ctx: Ctx) -> dict[str, Any]:
    p = ctx["params"]
    title = str(p.get("title") or "Untitled draft")
    sections: dict[str, Any] = {k: v for k, v in p.items() if k not in ("title",)}
    lines = [f"# {title}"]
    for key, value in sections.items():
        lines.append(f"\n## {key.replace('_', ' ').capitalize()}")
        if isinstance(value, list):
            lines.extend(f"- {item}" for item in value)
        else:
            lines.append(str(value))
    body, provenance = _rewrite(ctx, "\n".join(lines), "internal design note")
    return {
        "summary": f"Drafted '{title}'",
        "artifact": {"title": title, "body": body, **sections, "provenance": provenance, "status": "draft"},
    }


def code_draft_patch(ctx: Ctx) -> dict[str, Any]:
    p = ctx["params"]
    files = [f for f in p.get("files", []) if isinstance(f, dict) and f.get("path")]
    outline = "\n".join(f"--- a/{f['path']}\n+++ b/{f['path']}\n@@ {f.get('change', '')}" for f in files)
    return {
        "summary": f"Patch draft: {p.get('summary', '')} ({len(files)} files)",
        "artifact": {
            "summary": p.get("summary", ""),
            "files": files,
            "diff_outline": outline,
            "tests_included": any("test" in f["path"] for f in files),
            "design_ref": p.get("design_ref"),
            "status": "draft: not committed, not merged",
        },
    }


def tests_plan(ctx: Ctx) -> dict[str, Any]:
    criteria = [str(c) for c in ctx["params"].get("acceptance_criteria", [])]
    cases = []
    for i, criterion in enumerate(criteria, start=1):
        low = criterion.lower()
        negative = any(w in low for w in ("503", "fail", "unreachable", "never", "not "))
        perf = "ms" in low or "under" in low
        cases.append(
            {
                "id": f"TC-{i:02d}",
                "criterion": criterion,
                "type": "performance" if perf else ("negative" if negative else "positive"),
                "expected": criterion,
                "source": f"acceptance_criteria[{i - 1}]",
            }
        )
    return {
        "summary": f"{len(cases)} test cases from {len(criteria)} acceptance criteria",
        "artifact": {"cases": cases, "coverage": f"{len(cases)}/{len(criteria)} criteria mapped"},
    }


def code_review(ctx: Ctx) -> dict[str, Any]:
    p = ctx["params"]
    patch = p.get("patch") or {}
    plan = p.get("test_plan") or {}
    findings = []

    def add(check: str, ok: bool, severity: str, detail: str) -> None:
        findings.append(
            {
                "check": check,
                "result": "pass" if ok else "fail",
                "severity": "none" if ok else severity,
                "detail": detail,
                "source": "patch draft",
            }
        )

    files = patch.get("files", [])
    add("has_changes", bool(files), "high", f"{len(files)} file(s) in the patch")
    add(
        "tests_included",
        bool(patch.get("tests_included")),
        "high",
        "patch touches a test file" if patch.get("tests_included") else "no test file in the patch",
    )
    cases = plan.get("cases", [])
    add("criteria_covered", bool(cases), "medium", plan.get("coverage", "no test plan"))
    secrets_hit = find_secrets(json.dumps(patch))
    add(
        "no_secrets",
        not secrets_hit,
        "critical",
        "no credential-shaped strings" if not secrets_hit else f"credential-shaped content: {', '.join(secrets_hit)}",
    )
    sensitive = [f["path"] for f in files if f["path"].startswith((".github/", "config/policy"))]
    add(
        "no_governance_paths",
        not sensitive,
        "high",
        "no CI or policy files touched" if not sensitive else f"touches {', '.join(sensitive)}: needs operator review",
    )
    failed = [f for f in findings if f["result"] == "fail"]
    verdict = "approve" if not failed else "changes_requested"
    return {
        "summary": f"Review verdict: {verdict} ({len(findings) - len(failed)}/{len(findings)} checks passed)",
        "artifact": {"verdict": verdict, "findings": findings},
        "decision": {
            "kind": "agent",
            "summary": f"Code review: {verdict}",
            "rationale": "; ".join(f"{f['check']}={f['result']}" for f in findings),
            "outcome": verdict,
        },
    }


def tests_run_sandbox(ctx: Ctx) -> dict[str, Any]:
    """Run one allow-listed suite. The task id of a passing run is deploy evidence."""
    suite = str(ctx["params"].get("suite", ""))
    result = {**_office(ctx).sandbox.run(suite), "run_id": ctx.get("task_id")}
    verdict = "passed" if result["passed"] else f"failed (exit {result['returncode']})"
    return {"summary": f"Sandbox suite '{suite}' {verdict} in {result['duration_s']}s", "artifact": result}


def deploy_plan(ctx: Ctx) -> dict[str, Any]:
    p = ctx["params"]
    env = p.get("target_environment", "staging")
    strategy = p.get("strategy", "canary")
    verdict = p.get("review")
    ready = verdict == "approve"
    steps = [
        "Build the release artifact from the reviewed commit; record its digest",
        "Deploy to staging; run the readiness and smoke checks",
        f"{strategy.capitalize()} to {env}: 10% of traffic for 30 minutes"
        if strategy == "canary"
        else f"Deploy to {env}",
        "Watch error rate, latency, and /ready for the canary window",
        f"Promote to 100% of {env}",
    ]
    rollback = [
        "Shift traffic back to the previous release (one command, no rebuild)",
        "Confirm /ready and error rate return to baseline",
        "Open an incident record if the rollback was triggered by user impact",
    ]
    verification = [
        "/ready returns 200 on every instance",
        "Error rate within the pre-deploy baseline",
        "Audit chain verifies after the deploy",
    ]
    return {
        "summary": f"Rollout plan for {p.get('change', 'change')} to {env} "
        f"({'ready' if ready else 'blocked by review'})",
        "artifact": {
            "change": p.get("change"),
            "target_environment": env,
            "strategy": strategy,
            "ready": ready,
            "review_verdict": verdict,
            "steps": steps,
            "rollback": rollback,
            "verification": verification,
            "gate": f"deploy.{'production' if env == 'production' else 'staging'} is a separate action: "
            f"{'critical' if env == 'production' else 'high'} tier, operator approval required.",
        },
    }


# -- marketing ------------------------------------------------------------------


def content_draft(ctx: Ctx) -> dict[str, Any]:
    office = _office(ctx)
    brand = office.company().brand_line
    posts_out = []
    for spec in ctx["params"].get("posts", []):
        topic = str(spec.get("topic", "")).strip()
        points = [str(x).strip() for x in spec.get("points", []) if str(x).strip()]
        next_step = str(spec.get("next_step", "")).strip()
        template = "\n".join([topic, "", *[f"- {pt}" for pt in points], "", next_step, "", brand])
        text, provenance = _rewrite(ctx, template, f"LinkedIn post on: {topic}")
        if brand not in text:
            text = f"{text.rstrip()}\n\n{brand}"
        checks = {
            "has_next_step": bool(next_step) and next_step.split()[0].lower() in text.lower(),
            "has_sign_off": brand in text,
            "no_new_figures": not (set(_DIGITS.findall(text)) - set(_DIGITS.findall(template))),
            "plain_length": len(text) <= 1300,
        }
        posts_out.append(
            {
                "topic": topic,
                "text": text,
                "channel": ctx["params"].get("channel", "linkedin"),
                "brand_checks": checks,
                "provenance": provenance,
                "status": "draft",
            }
        )
    passed = sum(all(p["brand_checks"].values()) for p in posts_out)
    return {"summary": f"{len(posts_out)} drafts; {passed} pass every brand check", "artifact": {"posts": posts_out}}


def content_schedule(ctx: Ctx) -> dict[str, Any]:
    p = ctx["params"]
    start = parse_iso(ctx["now"]).date() + timedelta(days=1)
    cadence = max(1, int(p.get("cadence_days", 2)))
    calendar = [
        {
            "date": (start + timedelta(days=i * cadence)).isoformat(),
            "topic": d.get("topic"),
            "channel": d.get("channel", "linkedin"),
            "status": "scheduled draft: publishing needs operator approval",
        }
        for i, d in enumerate(p.get("drafts", []))
    ]
    return {"summary": f"{len(calendar)} entries added to the content calendar", "artifact": {"calendar": calendar}}


# -- revenue --------------------------------------------------------------------


def _safe_dataset(office: Office, rel: str) -> Path:
    base = office.base_dir.resolve()
    path = (base / rel).resolve()
    allowed = [(base / "demo").resolve(), (base / "data").resolve()]
    if not any(path.is_relative_to(a) for a in allowed) or path.suffix != ".json":
        raise PermissionError("dataset must be a .json file under demo/ or data/")
    return path


def leads_research(ctx: Ctx) -> dict[str, Any]:
    office = _office(ctx)
    p = ctx["params"]
    data = json.loads(_safe_dataset(office, str(p.get("dataset", ""))).read_text(encoding="utf-8"))
    source = data.get("source", {})
    if source.get("id") != p.get("source"):
        raise PermissionError(
            f"dataset source {source.get('id')!r} does not match requested source {p.get('source')!r}"
        )
    markers = office.policy.injection_markers
    records, quarantined = [], []
    for item in data.get("prospects", []):
        text = " ".join(str(v) for v in item.values()).lower()
        hits = [m for m in markers if m in " ".join(text.split())]
        entry = {**item, "source": f"{source['id']}#{item.get('id')}", "is_sample": bool(data.get("is_sample"))}
        if hits:
            quarantined.append(
                {
                    "id": item.get("id"),
                    "name": item.get("name"),
                    "markers": hits,
                    "source": entry["source"],
                    "action": "excluded from scoring; flagged for review",
                }
            )
        else:
            records.append(entry)
    messages = []
    if quarantined:
        messages.append(
            {
                "to": "exec.risk-compliance",
                "kind": "escalation",
                "subject": f"{len(quarantined)} prospect record(s) quarantined: instruction-like text",
                "body": "These records contain text that reads like instructions to an agent. They were treated as "
                "data, excluded from scoring, and not acted on: "
                + "; ".join(f"{q['name']} ({', '.join(q['markers'])})" for q in quarantined),
            }
        )
    return {
        "summary": f"{len(records)} records collected from '{source.get('id')}', {len(quarantined)} quarantined",
        "artifact": {
            "source": source,
            "is_sample": bool(data.get("is_sample")),
            "records": records,
            "quarantined": quarantined,
        },
        "messages": messages,
    }


def leads_score(ctx: Ctx) -> dict[str, Any]:
    icp = _office(ctx).company().ideal_customer_profile
    lo, hi = (icp.get("employee_range") or [0, 10**9])[:2]
    scored = []
    for r in ctx["params"].get("records", []):
        points: list[tuple[str, int]] = []
        in_region = r.get("region") in icp.get("regions", [])
        points.append(("region in ICP" if in_region else "region outside ICP", 30 if in_region else -100))
        if r.get("city") in icp.get("preferred_cities", []):
            points.append(("preferred city", 10))
        if r.get("sector") in icp.get("sectors", []):
            points.append(("target sector", 20))
        if r.get("regulated") and icp.get("regulated_bonus"):
            points.append(("regulated sector", 15))
        emp = r.get("employees")
        in_range = isinstance(emp, int) and lo <= emp <= hi
        if isinstance(emp, int):
            points.append(("employees in range", 15) if in_range else ("employees outside range", -20))
        if r.get("has_public_website"):
            points.append(("public website to verify facts", 5))
        if str(r.get("notes", "")).strip():
            points.append(("stated need in notes", 5))
        score = sum(v for _, v in points)
        scored.append(
            {
                "id": r.get("id"),
                "name": r.get("name"),
                "city": r.get("city"),
                "sector": r.get("sector"),
                "score": score,
                "qualified": in_region and in_range and score >= 60,
                "rubric": [{"rule": k, "points": v} for k, v in points],
                "notes": r.get("notes", ""),
                "source": r.get("source"),
                "is_sample": r.get("is_sample", False),
            }
        )
    scored.sort(key=lambda x: (-x["score"], str(x["id"])))
    shortlist = [s for s in scored if s["qualified"]]
    return {
        "summary": f"{len(shortlist)} of {len(scored)} prospects qualified (threshold 60, in region, in size range)",
        "artifact": {
            "threshold": 60,
            "gates": ["region in ICP", f"employees {lo}-{hi}"],
            "scored": scored,
            "shortlist": shortlist,
        },
        "decision": {
            "kind": "agent",
            "summary": f"Qualified {len(shortlist)} prospects",
            "rationale": "Transparent rubric over the ideal customer profile in config/company.json",
            "outcome": ", ".join(s["name"] for s in shortlist) or "none",
        },
    }


def research_summarize(ctx: Ctx) -> dict[str, Any]:
    p = ctx["params"]
    notes = []
    for item in p.get("items", []):
        source = item.get("source")
        facts = [f"{k}: {item[k]}" for k in ("city", "sector") if item.get(k)]
        if item.get("notes"):
            facts.append(f"stated need: {item['notes']}")
        notes.append(
            {
                "title": item.get("name"),
                "facts": facts,
                "score": item.get("score"),
                "open_questions": [
                    "Who owns IT and security decisions?",
                    "Which systems hold client or patient data?",
                    "Is there a current incident response plan?",
                ],
                "source": source,
                "unverified": not bool(source),
                "is_sample": item.get("is_sample", False),
            }
        )
    return {
        "summary": f"{len(notes)} account notes for '{p.get('subject', '')}'",
        "artifact": {
            "subject": p.get("subject"),
            "notes": notes,
            "method": "Facts are copied from the source record only; questions are open, not answered.",
        },
    }


def research_collect(ctx: Ctx) -> dict[str, Any]:
    p = ctx["params"]
    items = [
        {"text": str(s.get("text", "")), "source": s.get("source"), "unverified": not s.get("source")}
        for s in p.get("sources", [])
        if isinstance(s, dict)
    ]
    return {"summary": f"Collected {len(items)} item(s)", "artifact": {"items": items}}


def outreach_draft(ctx: Ctx) -> dict[str, Any]:
    office = _office(ctx)
    drafts = []
    for lead in ctx["params"].get("leads", []):
        body = (
            f"Hello,\n\nI run ClearGlass, a cyber and AI-risk advisory practice in {office.company().region}. "
            f'You mentioned: "{lead.get("notes", "").strip()}". I can walk you through a short, '
            "plain-language review of that one area and what to do first.\n\nWould a 20-minute call next week work?\n\n"
            f"{office.company().brand_line}"
        )
        drafts.append(
            {
                "to": lead.get("name"),
                "body": body,
                "source": lead.get("source"),
                "status": "draft: sending needs operator approval",
            }
        )
    return {"summary": f"{len(drafts)} outreach drafts (not sent)", "artifact": {"drafts": drafts}}


def analysis_run(ctx: Ctx) -> dict[str, Any]:
    values = [v for v in ctx["params"].get("values", []) if isinstance(v, (int, float))]
    stats = {
        "count": len(values),
        "min": min(values, default=None),
        "max": max(values, default=None),
        "mean": round(sum(values) / len(values), 4) if values else None,
    }
    return {"summary": f"Analyzed {len(values)} values", "artifact": stats}


# -- security -------------------------------------------------------------------


def security_audit(ctx: Ctx) -> dict[str, Any]:
    from agent_core.security_audit import run_security_audit

    result = run_security_audit(
        _office(ctx),
        include_control_tests=bool(ctx["params"].get("include_control_tests", True)),
        current_subject=ctx.get("task_id") or str(ctx.get("digest", ""))[:16],
    )
    counts = result["summary"]["by_severity"]
    title = "Security review: agent grants, tools, approval gates"
    return {
        "summary": (
            f"{result['summary']['findings']} findings "
            f"({counts.get('critical', 0)} critical, {counts.get('high', 0)} high); "
            f"{result['summary']['control_tests_passed']}/{result['summary']['control_tests']} control tests passed"
        ),
        "artifact": result,
        "report": {"kind": "security_review", "title": title, "sections": result, "metrics": result["summary"]},
        "messages": [
            {
                "to": "exec.chief-of-staff",
                "kind": "report",
                "subject": title,
                "body": f"Control review complete: {result['summary']['control_tests_passed']}/"
                f"{result['summary']['control_tests']} control tests passed; "
                f"{counts.get('critical', 0)} critical and {counts.get('high', 0)} high findings.",
            }
        ],
    }


def security_incident_draft(ctx: Ctx) -> dict[str, Any]:
    p = ctx["params"]
    fields = [
        "what_happened",
        "when",
        "systems_affected",
        "people_or_data_affected",
        "source_of_report",
        "evidence",
        "containment_status",
        "third_parties",
        "required_human_decision",
    ]
    record = {f: p.get(f, "UNKNOWN: to be confirmed") for f in fields}
    return {
        "summary": f"Incident draft: {record['what_happened']}",
        "artifact": {"incident": record, "status": "draft"},
    }


# -- reports --------------------------------------------------------------------


def briefing_compile(ctx: Ctx) -> dict[str, Any]:
    from agent_core.reports import compile_briefing

    sections = compile_briefing(_office(ctx))
    title = f"Executive briefing: {sections['period']}"
    return {
        "summary": title,
        "artifact": sections,
        "report": {"kind": "briefing", "title": title, "sections": sections, "metrics": sections["kpis"]},
    }


def report_compile(ctx: Ctx) -> dict[str, Any]:
    from agent_core.reports import compile_eod, compile_weekly

    kind = ctx["params"].get("kind", "eod")
    sections = compile_weekly(_office(ctx)) if kind == "weekly" else compile_eod(_office(ctx))
    title = f"{'Weekly performance' if kind == 'weekly' else 'End-of-day operations'} report: {sections['period']}"
    return {
        "summary": title,
        "artifact": sections,
        "report": {"kind": kind, "title": title, "sections": sections, "metrics": sections.get("kpis", {})},
    }


# -- memory, messaging, workflow, simulation ------------------------------------------


def memory_write_task(ctx: Ctx) -> dict[str, Any]:
    p = ctx["params"]
    rec = _office(ctx).memory.write_task(
        ctx["agent"],
        ctx.get("mission_id") or "general",
        str(p.get("title", "note")),
        str(p.get("content", "")),
        str(p.get("source", ctx["agent"].id)),
    )
    return {"summary": f"Task memory {rec.id} written", "artifact": {"memory_id": rec.id}}


def memory_propose(ctx: Ctx) -> dict[str, Any]:
    p = ctx["params"]
    rec = _office(ctx).memory.propose(
        ctx["agent"],
        str(p.get("scope", "company")),
        str(p.get("title", "")),
        str(p.get("content", "")),
        str(p.get("source", "")),
        str(p.get("classification", "internal")),
        list(p.get("tags", [])),
    )
    return {
        "summary": f"Proposed long-term memory {rec.id} (awaiting operator curation)",
        "artifact": {"memory_id": rec.id, "status": rec.status},
    }


def message_internal(ctx: Ctx) -> dict[str, Any]:
    p = ctx["params"]
    msg = _office(ctx).post_message(
        sender=ctx["agent"].id,
        recipient=str(p.get("to", "")),
        kind=str(p.get("kind", "note")),
        subject=str(p.get("subject", "")),
        body=str(p.get("body", "")),
        mission_id=ctx.get("mission_id"),
        task_id=ctx.get("task_id"),
        thread_id=p.get("thread_id"),
    )
    return {"summary": f"Message {msg.id} to {msg.recipient}", "artifact": {"message_id": msg.id}}


def workflow_create(ctx: Ctx) -> dict[str, Any]:
    mission = _office(ctx).create_mission(ctx["params"].get("mission", {}), created_by=ctx["agent"].id)
    return {"summary": f"Created mission {mission.id}", "artifact": {"mission_id": mission.id}}


def simulation_run(ctx: Ctx) -> dict[str, Any]:
    office = _office(ctx)
    p = ctx["params"]
    sim = run_scenario(
        str(p.get("scenario_type")),
        dict(p.get("assumptions", {})),
        list(p.get("options", [])),
        seed=int(p.get("seed", 7)),
        runs=int(p.get("runs", 2000)),
    )
    title = str(p.get("title") or f"{sim['scenario']} scenario")
    record = Simulation(
        id=office.ids("sim"),
        scenario_type=sim["scenario"],
        title=title,
        assumptions=dict(p.get("assumptions", {})),
        options=list(p.get("options", [])),
        seed=sim["seed"],
        runs=sim["runs"],
        results=sim["results"],
        recommendation=sim["recommendation"],
        disclaimer=sim["disclaimer"],
        created_by=ctx["agent"].id,
        created_at=ctx["now"],
    )
    office.store.put(record, ctx["now"])
    aar = after_action_report(sim, title)
    return {
        "summary": f"Simulation {record.id}: recommend '{sim['recommendation']['option']}'",
        "artifact": {"simulation_id": record.id, **sim, "after_action": aar},
    }


def pricing_model(ctx: Ctx) -> dict[str, Any]:
    p = ctx["params"]
    sim = run_scenario(
        "pricing",
        dict(p.get("assumptions", {})),
        list(p.get("options", [])),
        seed=int(p.get("seed", 7)),
        runs=int(p.get("runs", 1000)),
    )
    return {"summary": f"Pricing model: '{sim['recommendation']['option']}' leads on median revenue", "artifact": sim}


HANDLERS: dict[str, Any] = {
    "docs.draft": docs_draft,
    "docs.update": docs_draft,
    "proposal.draft": docs_draft,
    "code.draft_patch": code_draft_patch,
    "code.review": code_review,
    "tests.plan": tests_plan,
    "tests.run_sandbox": tests_run_sandbox,
    "deploy.plan": deploy_plan,
    "content.draft": content_draft,
    "content.schedule": content_schedule,
    "leads.research": leads_research,
    "leads.score": leads_score,
    "research.summarize": research_summarize,
    "research.collect": research_collect,
    "osint.public_research": research_collect,
    "outreach.draft": outreach_draft,
    "analysis.run": analysis_run,
    "pricing.model": pricing_model,
    "security.audit_config": security_audit,
    "security.incident_draft": security_incident_draft,
    "briefing.compile": briefing_compile,
    "report.compile": report_compile,
    "memory.write_task": memory_write_task,
    "memory.propose_long_term": memory_propose,
    "message.internal": message_internal,
    "workflow.create": workflow_create,
    "simulation.run": simulation_run,
}
