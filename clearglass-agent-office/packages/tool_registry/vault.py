"""Secret references.

Agents and tool configs name secrets by reference (``vault:social/linkedin``),
never by value. The MVP vault resolves a reference to an environment variable
(``OFFICE_SECRET_SOCIAL_LINKEDIN``) at the connector boundary only:

- ``resolve`` refuses a tool that does not own the reference;
- nothing returned by ``describe`` or ``handle`` contains a value;
- no code path places a resolved value in agent context, memory, outputs, or
  the audit ledger (the ledger also redacts credential-shaped strings).

Production should back this interface with a managed secret store; see
docs/THREAT_MODEL.md.
"""

from __future__ import annotations

import os
import re
import secrets
from collections.abc import Mapping

from agent_core.models import Tool

_REF = re.compile(r"^vault:[a-z0-9][a-z0-9_/-]*$")


class VaultError(PermissionError):
    pass


def env_name(ref: str) -> str:
    if not _REF.match(ref):
        raise VaultError("malformed secret reference")
    return "OFFICE_SECRET_" + re.sub(r"[^A-Z0-9]", "_", ref.removeprefix("vault:").upper())


class SecretVault:
    def __init__(self, env: Mapping[str, str] | None = None) -> None:
        self._env = env if env is not None else os.environ

    def configured(self, ref: str) -> bool:
        return bool(self._env.get(env_name(ref)))

    def describe(self, tools: list[Tool]) -> list[dict[str, object]]:
        refs = sorted({t.secret_ref for t in tools if t.secret_ref})
        return [
            {"ref": r, "configured": self.configured(r), "owners": sorted(t.id for t in tools if t.secret_ref == r)}
            for r in refs
        ]

    def resolve(self, ref: str, tool: Tool) -> str:
        """Connector-boundary only. Never call this from agent or skill code."""
        if tool.secret_ref != ref:
            raise VaultError(f"tool {tool.id} does not own {ref}")
        value = self._env.get(env_name(ref))
        if not value:
            raise VaultError(f"{ref} is not configured")
        return value

    def handle(self, ref: str) -> dict[str, object]:
        """An opaque, value-free handle returned by an approved secrets.access action."""
        return {
            "ref": ref,
            "handle": f"cred_{secrets.token_hex(8)}",
            "value_exposed": False,
            "configured": self.configured(ref),
        }
