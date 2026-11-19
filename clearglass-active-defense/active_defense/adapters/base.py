"""The isolation adapter contract. See docs/INTEGRATION_CONTRACT.md.

An adapter touches only the rules it created, identified by the action's
idempotency key. It never flushes a rule set or replaces unrelated policy.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

ISOLATION_STEPS: tuple[str, ...] = (
    "deny_inbound_except_management",
    "deny_outbound_except_management",
    "tag_quarantined",
)


@dataclass(frozen=True)
class AdapterResult:
    status: str  # "applied" | "partial" | "error"
    applied_steps: tuple[str, ...] = ()
    detail: str = ""
    extra: dict = field(default_factory=dict)


class IsolationAdapter(Protocol):
    name: str

    def apply_isolation(self, asset_id: str, key: str, steps: list[str], preserve: list[str]) -> AdapterResult: ...

    def release_isolation(self, asset_id: str, key: str) -> AdapterResult: ...

    def state(self, asset_id: str, key: str) -> set[str]: ...

    def verify_isolation(self, asset_id: str, key: str, steps: list[str], preserve: list[str]) -> tuple[bool, str]: ...

    def verify_released(self, asset_id: str, key: str) -> tuple[bool, str]: ...


class UnimplementedAdapter:
    """Placeholder for EDR, firewall, SIEM and ticketing integrations. Every call
    refuses. Configuration validation rejects any adapter other than "mock", so
    this class exists to make the gap explicit in code, not to be selected."""

    def __init__(self, category: str) -> None:
        self.name = f"unimplemented-{category}"

    def _refuse(self, *_args, **_kwargs):
        raise NotImplementedError(f"{self.name}: no vendor adapter is implemented or tested in this build")

    apply_isolation = release_isolation = state = verify_isolation = verify_released = _refuse
