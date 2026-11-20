"""Tool registry and connectors.

A tool is a named capability with a declared action list, a connector type, a
risk ceiling, and an optional secret reference. Agents never call handlers
directly: the governed executor (agent_core.governance) resolves the tool
through the policy engine and then calls ``ToolRegistry.execute``.

Connectors:
- ``internal`` - runs a registered handler in-process.
- ``dry_run``  - records exactly what would have been sent and returns a receipt
                 bound to the approved payload. No network call is made.
- ``live``     - reserved. No live adapter ships in the MVP; registering one is a
                 reviewed change (docs/THREAT_MODEL.md, "Connector activation").
"""

from __future__ import annotations

import json
import secrets
from collections.abc import Callable
from pathlib import Path
from typing import Any

from agent_core.models import TIER_ORDER, Tool

Handler = Callable[[dict[str, Any]], dict[str, Any]]

CONNECTORS = ("internal", "dry_run", "live")


class ToolError(RuntimeError):
    pass


def load_tools(path: str | Path) -> list[Tool]:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    tools: list[Tool] = []
    seen: set[str] = set()
    for entry in raw.get("tools", []):
        tool = Tool(
            id=entry["id"],
            name=entry["name"],
            description=entry.get("description", ""),
            connector=entry.get("connector", "internal"),
            actions=list(entry.get("actions", [])),
            external=bool(entry.get("external", False)),
            sandbox_only=bool(entry.get("sandbox_only", False)),
            risk_ceiling=entry.get("risk_ceiling", "low"),
            secret_ref=entry.get("secret_ref"),
        )
        if tool.id in seen:
            raise ToolError(f"duplicate tool id {tool.id}")
        if tool.connector not in CONNECTORS:
            raise ToolError(f"{tool.id}: unknown connector {tool.connector!r}")
        if tool.risk_ceiling not in TIER_ORDER:
            raise ToolError(f"{tool.id}: unknown risk ceiling {tool.risk_ceiling!r}")
        if tool.connector == "live":
            raise ToolError(f"{tool.id}: live connectors require a reviewed adapter; none is registered")
        seen.add(tool.id)
        tools.append(tool)
    return tools


class ToolRegistry:
    def __init__(self, tools: list[Tool]) -> None:
        self.tools: dict[str, Tool] = {t.id: t for t in tools}
        self._handlers: dict[str, Handler] = {}

    def register(self, action_type: str, handler: Handler) -> None:
        self._handlers[action_type] = handler

    def has_handler(self, action_type: str) -> bool:
        return action_type in self._handlers

    def get(self, tool_id: str) -> Tool:
        try:
            return self.tools[tool_id]
        except KeyError as exc:
            raise ToolError(f"unknown tool {tool_id}") from exc

    def execute(self, tool_id: str, action_type: str, ctx: dict[str, Any]) -> dict[str, Any]:
        tool = self.get(tool_id)
        if action_type not in tool.actions:
            raise ToolError(f"tool {tool_id} does not declare {action_type}")
        handler = self._handlers.get(action_type)
        if handler is not None:
            return handler(ctx)
        if tool.connector == "dry_run":
            return dry_run_receipt(tool, action_type, ctx)
        raise ToolError(f"no handler for {action_type} on internal tool {tool_id}")


def dry_run_receipt(tool: Tool, action_type: str, ctx: dict[str, Any]) -> dict[str, Any]:
    """What a live connector would have done, recorded without doing it."""
    params = ctx.get("params", {})
    receipt = {
        "receipt_id": f"rcpt_{secrets.token_hex(6)}",
        "mode": "dry_run",
        "connector": tool.id,
        "action_type": action_type,
        "action_digest": ctx.get("approved_digest"),
        "approval_id": ctx.get("approval_id"),
        "recorded_at": ctx.get("now"),
        "note": "DRY RUN: no external system was contacted. A reviewed live adapter is required for real execution.",
    }
    if tool.secret_ref:
        # The secret is referenced by name only; its value never enters agent context.
        receipt["credential"] = {"ref": tool.secret_ref, "value_exposed": False}
    summary = f"Dry-run {action_type} via {tool.name}"
    return {
        "summary": summary,
        "artifact": {"would_execute": {"action_type": action_type, "params": params}},
        "receipt": receipt,
    }
