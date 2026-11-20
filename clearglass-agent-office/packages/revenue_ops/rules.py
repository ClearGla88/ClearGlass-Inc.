"""Pure rules for the Revenue Floor.

Stages, field schemas, consent, outbound content, qualification, and the
classification of payment-provider records. Nothing here writes, sends, or reads
the network, and nothing imports the office runtime, so every rule can be tested
on its own and the desk, the API, and the tests share one definition.

Two facts shape the money rules:

- An invoice is not a payment, a pending transaction is not a settled one, and a
  payment is not revenue or profit. Each is its own category.
- Money is called received only on a provider record whose status says so.
  PayPal's ``MARKED_AS_PAID`` is a seller's own note, not a processor record, so
  it stays "reported, not verified".

The status vocabularies below are the ones the connected PayPal tools declare in
their schemas (checked 2026-11-19). An unknown status fails closed.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from audit_ledger.canonical import digest, find_secrets


class RuleError(ValueError):
    """Input that a rule refuses. The message says what to change."""


# -- stages --------------------------------------------------------------------------------------

STAGES = (
    "new",
    "qualified",
    "disqualified",
    "contacted",
    "engaged",
    "proposal_sent",
    "accepted",
    "invoiced",
    "paid",
    "in_fulfillment",
    "lost",
)
OPEN_STAGES = frozenset({"new", "qualified", "contacted", "engaged", "proposal_sent", "accepted", "invoiced", "paid"})

# event -> (stages it moves from, target stage, stages where it is recorded without moving)
TRANSITIONS: dict[str, tuple[frozenset[str], str, frozenset[str]]] = {
    "qualified": (frozenset({"new", "disqualified"}), "qualified", frozenset({"qualified"})),
    "disqualified": (frozenset({"new", "disqualified"}), "disqualified", frozenset()),
    "outreach_sent": (frozenset({"qualified"}), "contacted", frozenset({"contacted", "engaged"})),
    # A client can write or book before the lead is qualified, or after it closed: the fact is
    # recorded, and the stage moves only from qualified or contacted.
    "customer_engaged": (
        frozenset({"qualified", "contacted"}),
        "engaged",
        frozenset(
            {
                "new",
                "disqualified",
                "engaged",
                "proposal_sent",
                "accepted",
                "invoiced",
                "paid",
                "in_fulfillment",
                "lost",
            }
        ),
    ),
    "proposal_sent": (frozenset({"contacted", "engaged"}), "proposal_sent", frozenset()),
    "terms_accepted": (frozenset({"proposal_sent"}), "accepted", frozenset()),
    "invoice_sent": (frozenset({"accepted"}), "invoiced", frozenset()),
    "paid": (frozenset({"invoiced"}), "paid", frozenset({"paid", "in_fulfillment"})),
    "handoff": (frozenset({"paid"}), "in_fulfillment", frozenset()),
    "lost": (OPEN_STAGES, "lost", frozenset()),
}


def next_stage(current: str, event: str) -> str:
    """The stage after ``event``. Raises RuleError when the event cannot happen in ``current``."""
    if event not in TRANSITIONS:
        raise RuleError(f"unknown stage event {event!r}")
    movable, target, unchanged = TRANSITIONS[event]
    if current in movable:
        return target
    if current in unchanged:
        return current
    raise RuleError(f"'{event}' cannot happen while the opportunity is {current}")


# -- field schemas -------------------------------------------------------------------------------

EMAIL = re.compile(r"^[A-Za-z0-9._%+'-]{1,64}@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,63}$")
HTTPS_URL = re.compile(r"^https://[A-Za-z0-9.-]+(?::\d{2,5})?(?:/[^\s<>\"']*)?$")
RESERVED_DOMAINS = ("example.com", "example.net", "example.org")
RESERVED_SUFFIXES = (".test", ".example", ".invalid", ".localhost")


def normalize_email(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip().lower()
    return value if len(value) <= 254 and EMAIL.match(value) else None


def is_reserved_test_address(email: str) -> bool:
    """RFC 2606 / RFC 6761 names that can never reach a real person."""
    domain = email.rsplit("@", 1)[-1].lower()
    return domain in RESERVED_DOMAINS or any(domain.endswith(s) for s in RESERVED_SUFFIXES)


@dataclass(frozen=True)
class Field:
    kind: str  # str | text | email | url | int | bool | date | datetime | enum | str_list | email_list
    required: bool = False
    lo: int | None = None
    hi: int | None = None
    choices: tuple[str, ...] = ()


def _parse_date(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError:
        return None


def parse_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        dt = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        return None  # a timestamp without a zone is ambiguous; refuse it
    return dt


def _check(name: str, spec: Field, value: Any) -> tuple[Any, str]:
    """Return (clean value, problem). Problem is empty when the value is acceptable."""
    k = spec.kind
    if k in ("str", "text"):
        if not isinstance(value, str) or not value.strip():
            return None, f"{name} must be text"
        value = value.strip() if k == "str" else value.strip("\n ")
        if k == "str" and ("\n" in value or "\r" in value):
            return None, f"{name} must be one line"
        if spec.lo is not None and len(value) < spec.lo:
            return None, f"{name} must be at least {spec.lo} characters"
        if spec.hi is not None and len(value) > spec.hi:
            return None, f"{name} must be at most {spec.hi} characters"
        return value, ""
    if k == "email":
        clean = normalize_email(value)
        return (clean, "") if clean else (None, f"{name} must be a valid email address")
    if k == "url":
        if not isinstance(value, str) or len(value) > 300 or not HTTPS_URL.match(value.strip()):
            return None, f"{name} must be an https:// link"
        return value.strip(), ""
    if k == "int":
        if not isinstance(value, int) or isinstance(value, bool):
            return None, f"{name} must be a whole number"
        if (spec.lo is not None and value < spec.lo) or (spec.hi is not None and value > spec.hi):
            return None, f"{name} must be between {spec.lo} and {spec.hi}"
        return value, ""
    if k == "bool":
        return (value, "") if isinstance(value, bool) else (None, f"{name} must be true or false")
    if k == "date":
        clean = _parse_date(value)
        return (clean, "") if clean else (None, f"{name} must be a date (YYYY-MM-DD)")
    if k == "datetime":
        dt = parse_datetime(value)
        return (dt.isoformat(timespec="seconds"), "") if dt else (None, f"{name} must be an ISO 8601 time with a zone")
    if k == "enum":
        return (value, "") if value in spec.choices else (None, f"{name} must be one of {list(spec.choices)}")
    if k in ("str_list", "email_list"):
        if not isinstance(value, list):
            return None, f"{name} must be a list"
        if (spec.lo is not None and len(value) < spec.lo) or (spec.hi is not None and len(value) > spec.hi):
            return None, f"{name} must have between {spec.lo} and {spec.hi} items"
        out = []
        for i, item in enumerate(value):
            inner = Field("email") if k == "email_list" else Field("str", True, 3, 200)
            clean, problem = _check(f"{name}[{i}]", inner, item)
            if problem:
                return None, problem
            out.append(clean)
        if len(set(out)) != len(out):
            return None, f"{name} has duplicates"
        return out, ""
    raise RuleError(f"unknown field kind {k!r}")


def validate_fields(raw: Any, schema: dict[str, Field], what: str) -> dict[str, Any]:
    """Strict validation: unknown fields are refused, never ignored. Raises RuleError listing every problem."""
    if not isinstance(raw, dict):
        raise RuleError(f"{what} must be an object")
    problems = [f"unknown field {k!r}" for k in sorted(set(raw) - set(schema))]
    clean: dict[str, Any] = {}
    for name, spec in schema.items():
        if name not in raw or raw[name] is None or raw[name] == "":
            if spec.required:
                problems.append(f"{name} is required")
            continue
        value, problem = _check(name, spec, raw[name])
        if problem:
            problems.append(problem)
        else:
            clean[name] = value
    if problems:
        raise RuleError(f"{what}: " + "; ".join(problems))
    return clean


def lead_schema(sources: Iterable[str], bases: Iterable[str]) -> dict[str, Field]:
    return {
        "contact_name": Field("str", True, 2, 120),
        "contact_email": Field("email", True),
        "contact_role": Field("str", False, 2, 120),
        "organization": Field("str", True, 2, 160),
        "region": Field("str", False, 2, 60),
        "city": Field("str", False, 2, 60),
        "sector": Field("str", False, 2, 60),
        "employees": Field("int", False, 1, 1_000_000),
        "stated_need": Field("text", False, 1, 2000),
        "source": Field("enum", True, choices=tuple(sources)),
        "source_ref": Field("str", True, 2, 300),
        "consent_basis": Field("enum", True, choices=tuple(bases)),
        "consent_evidence": Field("str", False, 3, 300),
        "consent_date": Field("date"),
        "rehearsal": Field("bool"),
    }


SETTINGS_SCHEMA: dict[str, Field] = {
    "business_name": Field("str", True, 2, 120),
    "mailing_address": Field("str", True, 10, 300),
    "email": Field("email", True),
    "website": Field("url"),
    "booking_url": Field("url"),
    "email_connector": Field("enum", True, choices=("gmail", "microsoft_365")),
    "own_payer_emails": Field("email_list", False, 0, 10),
    "rehearsal_recipients": Field("email_list", False, 0, 10),
}

OFFER_DECISION_SCHEMA: dict[str, Field] = {
    "exclusions": Field("str_list", True, 1, 20),
    "delivery_capacity_per_week": Field("int", True, 1, 50),
    "turnaround_business_days": Field("int", True, 1, 60),
    "payment_due_days": Field("int", True, 0, 60),
    "tax_basis_points": Field("int", True, 0, 2500),
    "terms_ref": Field("str", True, 3, 300),
}

# -- injection and credentials -----------------------------------------------------------------


def instruction_markers(text: str, markers: Iterable[str]) -> list[str]:
    low = " ".join(text.lower().split())
    return sorted({m for m in markers if m in low})


def credential_rules(value: Any) -> list[str]:
    """Credential-shaped content anywhere in ``value``: the rule ids, never the values."""
    return find_secrets(str(value))


# -- consent (CASL) ------------------------------------------------------------------------------

PURPOSES = ("outreach_email", "proposal_email", "invoice")


def consent_problem(
    consent: dict[str, Any],
    purpose: str,
    *,
    bases: dict[str, dict[str, Any]],
    today: date,
    quote_requested: bool = False,
    terms_accepted: bool = False,
) -> str:
    """Empty when a message for ``purpose`` may be sent on this consent record; else the reason.

    CASL s.6(6) lifts the consent requirement (s.6(1)(a)), and only that requirement, for a
    message that solely gives a quote the recipient asked for (6(6)(a)) or completes a
    transaction the recipient already agreed to (6(6)(b)). The form rules of s.6(2) still apply.
    """
    if purpose not in PURPOSES:
        return f"unknown message purpose {purpose!r}"
    basis = consent.get("basis")
    spec = bases.get(str(basis))
    if spec is None:
        return f"unknown consent basis {basis!r}"
    if purpose == "proposal_email" and quote_requested:
        return ""
    if purpose == "invoice" and terms_accepted:
        return ""
    if not spec.get("allows_first_contact"):
        return f"no consent on record for this message ({spec['law']})"
    if not consent.get("evidence"):
        return "the consent record has no evidence reference"
    on = consent.get("date")
    if not on:
        return "the consent record has no date"
    age = (today - date.fromisoformat(on)).days
    if age < 0:
        return "the consent date is in the future"
    limit = spec.get("max_age_days")
    if limit is not None and age > limit:
        return f"{spec['label'].lower()} has lapsed: {age} days since {on} ({spec['law']})"
    return ""


# -- outbound content ------------------------------------------------------------------------------

URL = re.compile(r"https?://[^\s<>\"')]+")
DIGIT_RUN = re.compile(r"\d+")
UNSUBSCRIBE_LINE = 'To stop receiving email from us, reply "unsubscribe".'


def digit_runs(text: str) -> set[str]:
    return {run.lstrip("0") or "0" for run in DIGIT_RUN.findall(text)}


def _has_phrase(text: str, phrase: str) -> bool:
    return re.search(r"(?<![a-z0-9])" + re.escape(phrase.lower()) + r"(?![a-z0-9])", text) is not None


def content_problems(
    subject: str,
    body: str,
    *,
    allowed_figures: Iterable[str],
    allowed_urls: Iterable[str],
    prohibited: Iterable[str],
    required_text: dict[str, str] | None = None,
) -> list[str]:
    """Check outbound copy against the claim boundary. Empty list means it passes.

    - Every number must come from ``allowed_figures`` (offer facts, settings, dates, references).
    - Every link must be one of ``allowed_urls``.
    - No prohibited phrase (guarantees, false urgency, unverifiable social proof).
    - Every ``required_text`` value must appear verbatim (CASL s.6(2) identification,
      contact information, and an unsubscribe mechanism).
    - No credential-shaped string.
    """
    problems: list[str] = []
    text = f"{subject}\n{body}"
    urls = {u.rstrip(".,;:") for u in allowed_urls if u}
    for found in URL.findall(text):
        if found.rstrip(".,;:") not in urls:
            problems.append(f"link not in the Revenue settings: {found}")
    without_links = URL.sub(" ", text)
    allowed: set[str] = set()
    for source in allowed_figures:
        allowed |= digit_runs(str(source))
    unknown = sorted(digit_runs(without_links) - allowed, key=lambda s: (len(s), s))
    if unknown:
        problems.append(
            "figures that are not in the approved offer, the settings or the references: " + ", ".join(unknown)
        )
    low = " ".join(without_links.lower().split())
    for phrase in prohibited:
        if _has_phrase(low, phrase):
            problems.append(f"prohibited phrase: {phrase!r}")
    for label, value in (required_text or {}).items():
        if not value:
            problems.append(f"{label} is not set in the Revenue settings (CASL s.6(2))")
        elif value not in body:
            problems.append(f"{label} is missing from the message (CASL s.6(2))")
    hits = credential_rules(text)
    if hits:
        problems.append(f"credential-shaped text ({', '.join(hits)})")
    return problems


# -- qualification ---------------------------------------------------------------------------------

Check = Callable[[dict[str, Any], dict[str, Any]], bool | None]


def _slug(value: Any) -> str:
    return "-".join(str(value).strip().lower().replace("_", " ").split())


def _region(f: dict[str, Any], icp: dict[str, Any]) -> bool | None:
    if not f.get("region"):
        return None
    return _slug(f["region"]) in {_slug(r) for r in icp.get("regions", [])}


def _sector(f: dict[str, Any], icp: dict[str, Any]) -> bool | None:
    if not f.get("sector"):
        return None
    return _slug(f["sector"]) in {_slug(s) for s in icp.get("sectors", [])}


def _size(f: dict[str, Any], icp: dict[str, Any]) -> bool | None:
    emp = f.get("employees")
    if not isinstance(emp, int):
        return None
    lo, hi = (icp.get("employee_range") or [1, 10**9])[:2]
    return lo <= emp <= hi


CHECKS: dict[str, Check] = {
    "contact_email_valid": lambda f, icp: (
        bool(normalize_email(f.get("contact_email"))) if f.get("contact_email") else None
    ),
    "organization_named": lambda f, icp: bool(str(f.get("organization") or "").strip()) or None,
    "region_in_icp": _region,
    "sector_in_icp": _sector,
    "employees_in_range": _size,
    "stated_need_present": lambda f, icp: True if f.get("stated_need_present") else None,
    "contact_role_present": lambda f, icp: True if f.get("contact_role") else None,
    "source_ref_present": lambda f, icp: True if f.get("source_ref") else None,
}


def qualify(
    facts: dict[str, Any], criteria: list[dict[str, Any]], threshold: int, icp: dict[str, Any]
) -> dict[str, Any]:
    """Score ``facts`` with a transparent rubric. Missing evidence is reported, never assumed."""
    rubric: list[dict[str, Any]] = []
    missing: list[str] = []
    failed_required: list[str] = []
    missing_required: list[str] = []
    score = 0
    for c in criteria:
        result = CHECKS[c["check"]](facts, icp)
        if result is None:
            state, points = "missing", 0
            missing.append(c["label"])
            if c.get("required"):
                missing_required.append(c["label"])
        elif result:
            state, points = "met", int(c.get("points", 0))
        else:
            state, points = "not met", 0
            if c.get("required"):
                failed_required.append(c["label"])
        score += points
        rubric.append(
            {
                "id": c["id"],
                "label": c["label"],
                "result": state,
                "points": points,
                "required": c.get("required", False),
            }
        )
    if failed_required:
        outcome = "disqualified"
        why = "required criteria not met: " + "; ".join(failed_required)
    elif missing_required:
        outcome = "needs_evidence"
        why = "required evidence missing: " + "; ".join(missing_required)
    elif score >= threshold:
        outcome = "qualified"
        why = f"score {score} meets the threshold of {threshold}"
    else:
        outcome = "below_threshold"
        why = f"score {score} is below the threshold of {threshold}"
    return {
        "outcome": outcome,
        "score": score,
        "threshold": threshold,
        "why": why,
        "rubric": rubric,
        "missing_evidence": missing,
    }


# -- offers ------------------------------------------------------------------------------------------

PUBLISHED_OFFER_KEYS = (
    "sku",
    "name",
    "summary",
    "scope",
    "price_cents",
    "currency",
    "price_type",
    "published_at",
    "assessment",
    "fulfillment_requirements",
)


def offer_content(published: dict[str, Any], decision: dict[str, Any] | None) -> dict[str, Any]:
    """The full offer an approval binds to: published facts plus the owner's decisions."""
    return {**{k: published[k] for k in PUBLISHED_OFFER_KEYS}, "decision": decision}


def offer_digest(content: dict[str, Any]) -> str:
    return digest(content)


def tax_cents(price_cents: int, basis_points: int) -> int:
    return (price_cents * basis_points + 5000) // 10000  # half up


def invoice_total_cents(price_cents: int, basis_points: int) -> int:
    return price_cents + tax_cents(price_cents, basis_points)


def money_text(cents: int, currency: str) -> str:
    return f"{currency} {cents // 100:,}.{cents % 100:02d}"


# -- provider records ---------------------------------------------------------------------------------

# kind, verification. "provider_record" counts; "unverified" never does.
PAYPAL_INVOICE_PAYMENT_STATUS: dict[str, tuple[str, str]] = {
    "PAID": ("payment_received", "provider_record"),
    "PARTIALLY_PAID": ("payment_received", "provider_record"),
    "PAYMENT_PENDING": ("payment_pending", "provider_record"),
    "MARKED_AS_PAID": ("payment_reported", "unverified"),
    "REFUNDED": ("refund", "provider_record"),
    "CANCELLED": ("invoice_cancelled", "provider_record"),
}
PAYPAL_INVOICE_OPEN_STATUS = frozenset({"DRAFT", "SENT", "SCHEDULED", "UNPAID"})
PAYPAL_TRANSACTION_STATUS: dict[str, tuple[str, str]] = {
    "S": ("payment_received", "provider_record"),
    "P": ("payment_pending", "provider_record"),
    "V": ("refund", "provider_record"),
    "D": ("payment_failed", "provider_record"),
}
PAYPAL_DISPUTE_STATUS: dict[str, tuple[str, str]] = {
    "OPEN": ("dispute_opened", "provider_record"),
    "UNDER_REVIEW": ("dispute_opened", "provider_record"),
    "APPEALED": ("dispute_opened", "provider_record"),
    "RESOLVED": ("dispute_closed", "provider_record"),
    "APPEALED_RESOLVED": ("dispute_closed", "provider_record"),
}

PAYMENT_RECORD_SCHEMA: dict[str, Field] = {
    "provider": Field("enum", True, choices=("paypal",)),
    "record_type": Field("enum", True, choices=("invoice", "transaction", "dispute")),
    "external_ref": Field("str", True, 4, 80),
    "status": Field("str", True, 1, 40),
    "gross_amount_cents": Field("int", True, 0, 100_000_000),
    "currency": Field("enum", True, choices=("CAD", "USD")),
    "occurred_at": Field("datetime", True),
    "invoice_ref": Field("str", False, 4, 80),
    "payer_email": Field("email"),
    "fee_cents": Field("int", False, 0, 10_000_000),
}


def classify_payment_record(record: dict[str, Any]) -> tuple[str, str]:
    """(money event kind, verification) for a normalized provider record. Unknown statuses fail closed."""
    status = str(record["status"]).strip().upper()
    rtype = record["record_type"]
    table = {
        "invoice": PAYPAL_INVOICE_PAYMENT_STATUS,
        "transaction": PAYPAL_TRANSACTION_STATUS,
        "dispute": PAYPAL_DISPUTE_STATUS,
    }[rtype]
    if rtype == "invoice" and status in PAYPAL_INVOICE_OPEN_STATUS:
        raise RuleError(f"invoice status {status} is not a payment; use the invoice's verification step instead")
    if status not in table:
        raise RuleError(f"unknown PayPal {rtype} status {status!r}; check the provider's record before adding it")
    return table[status]


def raw_record_consistent(raw: Any, record: dict[str, Any]) -> str:
    """The raw provider record must carry the reference and status the normalized record claims."""
    if not isinstance(raw, dict) or not raw:
        return "raw_record (the provider's record as the connector returned it) is required"
    text = str(raw)
    if str(record["external_ref"]) not in text:
        return "raw_record does not contain external_ref"
    if str(record["status"]) not in text:
        return "raw_record does not contain status"
    return ""


EMAIL_RECEIPT_SCHEMA: dict[str, Field] = {
    "message_id": Field("str", True, 4, 200),
    "to": Field("email_list", True, 1, 10),
    "subject": Field("str", True, 1, 300),
    "sent_at": Field("datetime", True),
}

INVOICE_RECEIPT_SCHEMA: dict[str, Field] = {
    "invoice_id": Field("str", True, 4, 80),
    "status": Field("enum", True, choices=("SENT", "UNPAID", "SCHEDULED", "PAYMENT_PENDING", "PARTIALLY_PAID", "PAID")),
    "total_cents": Field("int", True, 1, 100_000_000),
    "currency": Field("enum", True, choices=("CAD", "USD")),
    "recipient_email": Field("email", True),
}
