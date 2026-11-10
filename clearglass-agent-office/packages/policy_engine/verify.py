"""Step 8 of the pipeline: check a tool's output against the action's verify rule.

A failed verification fails the task. It never silently passes an output that
is missing citations, a rollback plan, or a receipt bound to the approval.
"""

from __future__ import annotations

from typing import Any


def _items(artifact: dict[str, Any]) -> list[dict[str, Any]]:
    for key in ("findings", "items", "records", "notes"):
        value = artifact.get(key)
        if isinstance(value, list):
            return [v for v in value if isinstance(v, dict)]
    return []


def verify_output(rule: str, output: dict[str, Any] | None, *, approved_digest: str | None = None) -> tuple[bool, str]:
    if not isinstance(output, dict):
        return False, "tool returned no output"
    artifact = output.get("artifact")

    if rule == "artifact":
        if artifact in (None, "", {}, []):
            return False, "empty artifact"
        return True, "artifact present"

    if rule == "citations":
        if not isinstance(artifact, dict):
            return False, "artifact missing"
        items = _items(artifact)
        if not items:
            return False, "no items to verify"
        uncited = [i for i in items if not i.get("source") and not i.get("unverified")]
        if uncited:
            return False, f"{len(uncited)} item(s) have neither a source nor an 'unverified' flag"
        cited = sum(1 for i in items if i.get("source"))
        return True, f"{cited}/{len(items)} items cite a source; the rest are flagged unverified"

    if rule == "rollback_plan":
        if not isinstance(artifact, dict) or not artifact.get("rollback"):
            return False, "plan has no rollback steps"
        return True, f"{len(artifact['rollback'])} rollback step(s)"

    if rule == "tests_passed":
        if not isinstance(artifact, dict) or "passed" not in artifact:
            return False, "no test-run result"
        if artifact.get("passed") is not True:
            return False, f"suite '{artifact.get('suite')}' failed (exit code {artifact.get('returncode')})"
        return True, f"suite '{artifact.get('suite')}' passed in {artifact.get('duration_s')}s"

    if rule == "receipt":
        receipt = output.get("receipt")
        if not isinstance(receipt, dict):
            return False, "no receipt from connector"
        if approved_digest and receipt.get("action_digest") != approved_digest:
            return False, "receipt is not bound to the approved payload"
        mode = receipt.get("mode")
        if mode not in ("dry_run", "live"):
            return False, f"unknown receipt mode {mode!r}"
        return True, f"{mode} receipt {receipt.get('receipt_id')}"

    return False, f"unknown verify rule {rule!r} (fails closed)"
