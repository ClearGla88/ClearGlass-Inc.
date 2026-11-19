"""Asset identity resolution.

An IP address is an observation, not an identity. Resolution returns RESOLVED
only when exactly one inventoried asset holds the address under a binding that
is current for the event's time, and the address is not a shared (NAT, proxy,
VPN) range or an authorized scanner. Everything else is a reason not to act.
"""

from __future__ import annotations

import ipaddress
from dataclasses import dataclass
from datetime import datetime

from .models import Asset, Inventory

RESOLVED = "RESOLVED"
AMBIGUOUS = "AMBIGUOUS"
UNKNOWN = "UNKNOWN"
STALE = "STALE"
SHARED_ADDRESS = "SHARED_ADDRESS"
AUTHORIZED_SCANNER = "AUTHORIZED_SCANNER"
CONFLICT = "CONFLICT"
UNVERIFIED = "UNVERIFIED"
SENSOR_REF = "SENSOR_REF"


@dataclass(frozen=True)
class Identity:
    status: str
    asset_id: str | None
    reason: str

    @property
    def verified(self) -> bool:
        return self.status == RESOLVED and self.asset_id is not None


class AssetRegistry:
    def __init__(self, inventory: Inventory) -> None:
        self.inventory = inventory
        self._by_id: dict[str, Asset] = {a.asset_id: a for a in inventory.assets}

    @property
    def version(self) -> str:
        return self.inventory.inventory_version

    def get(self, asset_id: str) -> Asset | None:
        return self._by_id.get(asset_id)

    def all(self) -> list[Asset]:
        return list(self._by_id.values())

    def resolve_ip(self, ip: str, at: datetime) -> Identity:
        addr = ipaddress.ip_address(ip)
        for scanner in self.inventory.authorized_scanners:
            if addr in scanner.cidr:
                return Identity(AUTHORIZED_SCANNER, None, f"{ip} is an authorized scanner ({scanner.owner})")
        for net in self.inventory.shared_address_ranges:
            if addr in net:
                return Identity(SHARED_ADDRESS, None, f"{ip} is in shared range {net}; many hosts can appear as it")
        holders: dict[str, list] = {}
        for asset in self._by_id.values():
            for b in asset.ip_bindings:
                if b.ip == addr:
                    holders.setdefault(asset.asset_id, []).append(b)
        if not holders:
            return Identity(UNKNOWN, None, f"{ip} is not bound to any inventoried asset")
        if len(holders) > 1:
            return Identity(AMBIGUOUS, None, f"{ip} is bound to several assets: {sorted(holders)}")
        asset_id, bindings = next(iter(holders.items()))
        max_age = self.inventory.dhcp_binding_max_age_seconds
        for b in bindings:
            if b.kind == "static":
                return Identity(RESOLVED, asset_id, f"{ip} is a static binding of {asset_id}")
            age = abs((at - b.observed_at).total_seconds())
            if age <= max_age:
                return Identity(RESOLVED, asset_id, f"{ip} was leased to {asset_id} within {int(age)}s of the event")
        return Identity(STALE, None, f"{ip}'s dhcp binding to {asset_id} is older than {max_age}s at event time")

    def verify_asserted(self, asset_id: str, src_ip: str | None, at: datetime) -> Identity:
        if self.get(asset_id) is None:
            return Identity(UNKNOWN, None, f"asserted asset {asset_id} is not in the inventory")
        if src_ip is not None:
            by_ip = self.resolve_ip(src_ip, at)
            if by_ip.status == RESOLVED and by_ip.asset_id != asset_id:
                return Identity(
                    CONFLICT, None, f"sensor asserted {asset_id} but {src_ip} resolves to {by_ip.asset_id}"
                )
        return Identity(RESOLVED, asset_id, f"{asset_id} asserted by an authenticated identity-asserting sensor")
