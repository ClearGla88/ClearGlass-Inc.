"""Typed, strict models for events, configuration, inventory, rules and playbooks.

Every model forbids unknown fields. A typo in a configuration file is a startup
failure, not a silently ignored setting.
"""

from __future__ import annotations

import ipaddress
from typing import Annotated, Literal

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    IPvAnyAddress,
    IPvAnyNetwork,
    StrictBool,
    StrictInt,
    StrictStr,
    StringConstraints,
    field_validator,
    model_validator,
)

Identifier = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,79}$")]
EventId = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{7,79}$")]
AttrKey = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]{0,47}$")]
ShortText = Annotated[StrictStr, StringConstraints(max_length=1024)]
ListItem = Annotated[StrictStr, StringConstraints(max_length=128)]
AttrValue = ShortText | StrictInt | StrictBool | Annotated[list[ListItem], Field(max_length=16)]

Category = Literal[
    "honeypot.http.request",
    "tripwire.tcp.connect",
    "honeyfile.access",
    "honeyfile.modify",
    "honeytoken.use",
    "endpoint.alert",
    "network.flow",
    "sensor.health",
]
Severity = Literal["info", "low", "medium", "high", "critical"]
Environment = Literal["lab", "staging", "production"]
Criticality = Literal["low", "medium", "high", "critical"]
ProtectedClass = Literal["identity", "network_control", "response_platform", "backup", "safety_ot"]
SignalName = Literal[
    "decoy_interaction",
    "honeytoken_use",
    "endpoint_compromise_indicator",
    "ransomware_indicator",
    "lateral_movement_indicator",
    "sensor_integrity",
]
Mode = Literal["observe", "recommend", "enforce"]
Role = Literal["analyst", "approver", "admin"]

SEVERITY_RANK: dict[str, int] = {"info": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}
CRITICALITY_RANK: dict[str, int] = {"low": 0, "medium": 1, "high": 2, "critical": 3}
PROTECTED_CLASSES: tuple[str, ...] = ("identity", "network_control", "response_platform", "backup", "safety_ot")

# Deception signals. Code, not configuration, enforces that these alone never
# authorize containment: see policy.evaluate_isolation.
DECOY_SIGNALS: frozenset[str] = frozenset({"decoy_interaction", "honeytoken_use"})

# Whose identity an event is about. "source" is the address that touched a decoy;
# "sensor_host" is the host a decoy file lives on; "asserted_asset" is the asset an
# identity-asserting sensor (such as an EDR agent) reports on.
CATEGORY_SUBJECT: dict[str, str] = {
    "honeypot.http.request": "source",
    "tripwire.tcp.connect": "source",
    "honeytoken.use": "source",
    "network.flow": "source",
    "honeyfile.access": "sensor_host",
    "honeyfile.modify": "sensor_host",
    "endpoint.alert": "asserted_asset",
    "sensor.health": "sensor_ref",
}


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


# --------------------------------------------------------------------------- events


class EventIn(Strict):
    """The normalized event a sensor submits. Server-side fields (ingestion time,
    authentication result, verified asset, rule and case IDs) are never accepted
    from a sensor; the server derives them."""

    schema_version: Literal["1.0"]
    event_id: EventId
    occurred_at: AwareDatetime
    sensor_id: Identifier
    category: Category
    severity: Severity
    environment: Environment
    authorization_scope: Identifier
    src_ip: IPvAnyAddress | None = None
    src_port: int | None = Field(default=None, ge=0, le=65535)
    dst_ip: IPvAnyAddress | None = None
    dst_port: int | None = Field(default=None, ge=0, le=65535)
    asset_id: Identifier | None = None
    attributes: dict[AttrKey, AttrValue] = Field(default_factory=dict, max_length=32)


# --------------------------------------------------------------------------- inventory


class IpBinding(Strict):
    ip: IPvAnyAddress
    kind: Literal["static", "dhcp"]
    observed_at: AwareDatetime | None = None

    @model_validator(mode="after")
    def _dhcp_needs_time(self) -> IpBinding:
        if self.kind == "dhcp" and self.observed_at is None:
            raise ValueError("a dhcp binding needs observed_at")
        return self


class Asset(Strict):
    asset_id: Identifier
    hostname: Annotated[str, StringConstraints(min_length=1, max_length=253)]
    owner: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    environment: Environment
    criticality: Criticality
    protected_class: ProtectedClass | None = None
    authorized_for_containment: bool
    adapter: Literal["mock", "none"]
    ip_bindings: list[IpBinding] = Field(default_factory=list)
    management_paths: list[Annotated[str, StringConstraints(pattern=r"^[0-9a-fA-F:.]+/\d{1,3}:\d{1,5}$")]] = Field(
        default_factory=list
    )
    dependents: list[Identifier] = Field(default_factory=list)

    @model_validator(mode="after")
    def _containment_rules(self) -> Asset:
        if self.protected_class is not None and self.authorized_for_containment:
            raise ValueError(f"{self.asset_id}: a protected asset cannot be authorized for containment")
        if self.authorized_for_containment:
            if self.adapter == "none":
                raise ValueError(f"{self.asset_id}: containment needs an adapter")
            if not self.management_paths:
                raise ValueError(f"{self.asset_id}: containment needs at least one preserved management path")
        for path in self.management_paths:
            net, _, port = path.rpartition(":")
            ipaddress.ip_network(net, strict=False)
            if not 0 < int(port) <= 65535:
                raise ValueError(f"{self.asset_id}: bad management path port in {path}")
        return self


class AuthorizedScanner(Strict):
    cidr: IPvAnyNetwork
    owner: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    note: Annotated[str, StringConstraints(max_length=500)] = ""


class Inventory(Strict):
    schema_version: Literal[1]
    inventory_version: Identifier
    dhcp_binding_max_age_seconds: int = Field(default=3600, ge=60, le=7 * 86400)
    shared_address_ranges: list[IPvAnyNetwork] = Field(default_factory=list)
    authorized_scanners: list[AuthorizedScanner] = Field(default_factory=list)
    assets: list[Asset] = Field(min_length=1)

    @model_validator(mode="after")
    def _unique(self) -> Inventory:
        ids = [a.asset_id for a in self.assets]
        if len(ids) != len(set(ids)):
            raise ValueError("asset_id values must be unique")
        known = set(ids)
        for a in self.assets:
            missing = [d for d in a.dependents if d not in known]
            if missing:
                raise ValueError(f"{a.asset_id}: unknown dependents {missing}")
        return self


# --------------------------------------------------------------------------- rules


class RuleMatch(Strict):
    category: Category
    attributes: dict[AttrKey, list[StrictStr | StrictInt | StrictBool]] = Field(default_factory=dict)
    derived: dict[Literal["honeytoken_match"], list[StrictBool]] = Field(default_factory=dict)


class DetectionRule(Strict):
    id: Identifier
    version: int = Field(ge=1)
    description: Annotated[str, StringConstraints(min_length=1, max_length=500)]
    match: RuleMatch
    signal: SignalName


class CorrelationRule(Strict):
    id: Identifier
    version: int = Field(ge=1)
    description: Annotated[str, StringConstraints(min_length=1, max_length=500)]
    all_of: list[SignalName] = Field(min_length=1)
    any_of: list[SignalName] = Field(default_factory=list)
    min_distinct_sensors: int = Field(ge=1, le=10)
    window_seconds: int = Field(ge=60, le=7 * 86400)
    requires_verified_asset: bool = True
    playbook: Identifier


class RuleSet(Strict):
    schema_version: Literal[1]
    ruleset_version: Identifier
    rules: list[DetectionRule] = Field(min_length=1)
    correlations: list[CorrelationRule] = Field(default_factory=list)
    signal_playbooks: dict[SignalName, Identifier]

    @model_validator(mode="after")
    def _unique(self) -> RuleSet:
        ids = [r.id for r in self.rules] + [c.id for c in self.correlations]
        if len(ids) != len(set(ids)):
            raise ValueError("rule and correlation ids must be unique")
        return self


# --------------------------------------------------------------------------- playbooks

ActionType = Literal[
    "record_alert",
    "notify",
    "escalate",
    "preserve_evidence",
    "scope_assets",
    "propose_isolation",
    "propose_release",
    "cancel_pending",
    "distrust_sensor",
]
PreconditionName = Literal[
    "no_emergency_stop",
    "circuit_closed",
    "identity_verified",
    "asset_in_inventory",
    "environment_in_scope",
    "not_protected",
    "asset_authorized_for_containment",
    "adapter_available",
    "evidence_corroborated",
    "sensor_trusted",
    "not_already_contained",
    "within_rate_limits",
]
MANDATORY_CONTAINMENT_PRECONDITIONS: tuple[str, ...] = (
    "no_emergency_stop",
    "circuit_closed",
    "identity_verified",
    "asset_in_inventory",
    "environment_in_scope",
    "not_protected",
    "asset_authorized_for_containment",
    "adapter_available",
    "evidence_corroborated",
    "sensor_trusted",
    "not_already_contained",
    "within_rate_limits",
)


class PlaybookTrigger(Strict):
    kind: Literal["signal", "correlation", "operator"]
    ref: Identifier


class RequiredEvidence(Strict):
    all_of: list[SignalName] = Field(default_factory=list)
    any_of: list[SignalName] = Field(default_factory=list)
    min_distinct_sensors: int = Field(default=1, ge=1, le=10)


class ApprovalRequirement(Strict):
    required: bool
    approver_role: Literal["approver"] = "approver"
    ttl_seconds: int | None = Field(default=None, ge=60, le=86400)
    distinct_from_requester: bool = True


class PlaybookAction(Strict):
    id: Identifier
    type: ActionType
    timeout_seconds: int = Field(default=30, ge=1, le=600)
    description: Annotated[str, StringConstraints(min_length=1, max_length=500)]


class RetryPolicy(Strict):
    max_attempts: int = Field(ge=1, le=5)
    backoff_seconds: int = Field(ge=0, le=3600)


class FailurePaths(Strict):
    on_timeout: Annotated[str, StringConstraints(min_length=1, max_length=300)]
    on_partial: Annotated[str, StringConstraints(min_length=1, max_length=300)]
    on_error: Annotated[str, StringConstraints(min_length=1, max_length=300)]


class RecoveryCriterion(Strict):
    id: Identifier
    description: Annotated[str, StringConstraints(min_length=1, max_length=300)]


Line = Annotated[str, StringConstraints(min_length=1, max_length=300)]


class Playbook(Strict):
    id: Identifier
    version: int = Field(ge=1)
    owner: Annotated[str, StringConstraints(min_length=1, max_length=120)]
    purpose: Annotated[str, StringConstraints(min_length=1, max_length=600)]
    trigger: PlaybookTrigger
    required_evidence: RequiredEvidence
    preconditions: list[PreconditionName] = Field(default_factory=list)
    authorization_scope: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    asset_exclusions: list[ProtectedClass] = Field(default_factory=list)
    approval: ApprovalRequirement
    actions: list[PlaybookAction] = Field(min_length=1)
    retry: RetryPolicy
    idempotency_key_fields: list[Identifier] = Field(min_length=1)
    verification: list[Line] = Field(min_length=1)
    failure_paths: FailurePaths
    escalation: list[Line] = Field(min_length=1)
    compensating_actions: list[Line] = Field(default_factory=list)
    recovery_criteria: list[RecoveryCriterion] = Field(default_factory=list)
    evidence_requirements: list[Line] = Field(min_length=1)
    notifications: list[Line] = Field(default_factory=list)

    @property
    def action_types(self) -> set[str]:
        return {a.type for a in self.actions}

    @model_validator(mode="after")
    def _containment_safeguards(self) -> Playbook:
        ids = [a.id for a in self.actions]
        if len(ids) != len(set(ids)):
            raise ValueError(f"{self.id}: action ids must be unique")
        if self.action_types & {"propose_isolation", "propose_release"}:
            if not self.approval.required:
                raise ValueError(f"{self.id}: a containment playbook must require approval")
            missing_ex = set(PROTECTED_CLASSES) - set(self.asset_exclusions)
            if missing_ex:
                raise ValueError(f"{self.id}: containment playbook must exclude {sorted(missing_ex)}")
            if not self.compensating_actions:
                raise ValueError(f"{self.id}: containment playbook needs compensating actions")
        if "propose_isolation" in self.action_types:
            missing = set(MANDATORY_CONTAINMENT_PRECONDITIONS) - set(self.preconditions)
            if missing:
                raise ValueError(f"{self.id}: isolation playbook must list preconditions {sorted(missing)}")
            if not self.recovery_criteria:
                raise ValueError(f"{self.id}: isolation playbook needs recovery criteria")
            if not (self.required_evidence.all_of or self.required_evidence.any_of):
                raise ValueError(f"{self.id}: isolation playbook needs required evidence")
        return self


# --------------------------------------------------------------------------- configuration


class SensorConfig(Strict):
    id: Identifier
    kind: Literal[
        "http_honeypot", "tcp_tripwire", "honeyfile", "honeytoken_detector", "edr_mock", "flow_monitor",
        "integrity_monitor",
    ]
    key_env: Annotated[str, StringConstraints(pattern=r"^[A-Z][A-Z0-9_]{2,63}$")] | None = None
    key_file: str | None = None
    asserts_asset_identity: bool = False
    host_asset_id: Identifier | None = None
    allowed_categories: list[Category] = Field(min_length=1)

    @model_validator(mode="after")
    def _one_key_source(self) -> SensorConfig:
        if (self.key_env is None) == (self.key_file is None):
            raise ValueError(f"sensor {self.id}: set exactly one of key_env or key_file")
        if self.kind == "honeyfile" and self.host_asset_id is None:
            raise ValueError(f"sensor {self.id}: a honeyfile sensor needs host_asset_id")
        if self.asserts_asset_identity and self.kind != "edr_mock":
            raise ValueError(f"sensor {self.id}: only an endpoint sensor may assert asset identity")
        if "sensor.health" in self.allowed_categories and self.kind != "integrity_monitor":
            raise ValueError(f"sensor {self.id}: only an integrity monitor may report sensor health")
        if "endpoint.alert" in self.allowed_categories and self.kind != "edr_mock":
            raise ValueError(f"sensor {self.id}: only an endpoint sensor may report endpoint alerts")
        return self


class PrincipalConfig(Strict):
    principal: Identifier
    role: Role
    token_sha256: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")] | None = None
    token_file: str | None = None
    token_env: Annotated[str, StringConstraints(pattern=r"^[A-Z][A-Z0-9_]{2,63}$")] | None = None

    @model_validator(mode="after")
    def _one_source(self) -> PrincipalConfig:
        if sum(x is not None for x in (self.token_sha256, self.token_file, self.token_env)) != 1:
            raise ValueError(f"principal {self.principal}: set exactly one of token_sha256, token_file, token_env")
        return self


class IngestConfig(Strict):
    max_body_bytes: int = Field(default=65536, ge=1024, le=1048576)
    clock_skew_seconds: int = Field(default=300, ge=5, le=3600)
    max_event_age_seconds: int = Field(default=86400, ge=60, le=30 * 86400)
    nonce_ttl_seconds: int = Field(default=900, ge=60, le=86400)
    signature_failure_burst: int = Field(default=5, ge=2, le=1000)
    signature_failure_window_seconds: int = Field(default=300, ge=60, le=86400)


class ResponseConfig(Strict):
    adapter: str = "mock"
    approval_ttl_seconds: int = Field(default=3600, ge=60, le=86400)
    execute_within_seconds: int = Field(default=900, ge=60, le=86400)
    max_isolations_per_case: int = Field(default=1, ge=1, le=5)
    max_concurrent_isolations: int = Field(default=1, ge=1, le=50)
    max_actions_per_hour: int = Field(default=3, ge=1, le=100)
    adapter_timeout_seconds: float = Field(default=10.0, gt=0, le=300)
    max_attempts: int = Field(default=3, ge=1, le=5)
    retry_backoff_seconds: int = Field(default=30, ge=0, le=3600)
    lease_seconds: int = Field(default=120, ge=5, le=3600)
    circuit_breaker_threshold: int = Field(default=3, ge=1, le=20)
    review_deadline_hours: int = Field(default=24, ge=1, le=720)
    enforce_acknowledged: bool = False
    enforce_preauthorized_playbooks: list[Identifier] = Field(default_factory=list)
    enforce_max_criticality: Literal["low", "medium"] = "low"

    @field_validator("adapter")
    @classmethod
    def _only_mock(cls, value: str) -> str:
        if value != "mock":
            raise ValueError(
                f"adapter {value!r} is not implemented in this build; only the mock adapter exists "
                "(see docs/INTEGRATION_CONTRACT.md)"
            )
        return value


class EvidenceConfig(Strict):
    retention_days: int = Field(default=90, ge=1, le=3650)
    max_artifact_bytes: int = Field(default=65536, ge=1024, le=1048576)


class DefenseConfig(Strict):
    schema_version: Literal[1]
    environment: Environment
    mode: Mode = "observe"
    policy_version: Identifier
    authorization_scope: Identifier
    database: str
    state_dir: str
    assets_file: str
    rules_file: str
    playbooks_dir: str
    ingest: IngestConfig = IngestConfig()
    response: ResponseConfig = ResponseConfig()
    evidence: EvidenceConfig = EvidenceConfig()
    sensors: list[SensorConfig] = Field(min_length=1)
    principals: list[PrincipalConfig] = Field(default_factory=list)

    @model_validator(mode="after")
    def _checks(self) -> DefenseConfig:
        sids = [s.id for s in self.sensors]
        if len(sids) != len(set(sids)):
            raise ValueError("sensor ids must be unique")
        pids = [p.principal for p in self.principals]
        if len(pids) != len(set(pids)):
            raise ValueError("principal names must be unique")
        if self.ingest.nonce_ttl_seconds < 2 * self.ingest.clock_skew_seconds:
            raise ValueError("ingest.nonce_ttl_seconds must be at least twice clock_skew_seconds, or replays slip through")
        if self.mode == "enforce":
            if not self.response.enforce_acknowledged:
                raise ValueError("mode 'enforce' needs response.enforce_acknowledged: true")
            if not self.response.enforce_preauthorized_playbooks:
                raise ValueError("mode 'enforce' needs at least one preauthorized playbook")
        elif self.response.enforce_preauthorized_playbooks:
            raise ValueError("enforce_preauthorized_playbooks is only valid in mode 'enforce'")
        return self
