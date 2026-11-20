"""Message templates and execution tickets for the Revenue Floor.

Templates only. No model rewrites outbound customer copy: every sentence comes
from the approved offer, the Revenue settings, or a fixed line written here.
Free text from a lead (their stated need, a reply) never enters a message, so an
instruction hidden in an inbound email cannot travel back out.

A ticket is what the office hands a person after an approved action is released:
the exact fields to enter in the connector, in order, and what to record
afterwards. The office itself never calls the provider.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from revenue_ops.rules import UNSUBSCRIBE_LINE, invoice_total_cents, money_text, tax_cents

BRAND_LINE = "CLEARGLASS: See Through Everything"


def split_name(name: str) -> tuple[str, str | None]:
    parts = name.split()
    return (parts[0], " ".join(parts[1:]) or None) if parts else (name, None)


def identity_block(settings: dict[str, Any]) -> str:
    lines = [settings["business_name"], settings["mailing_address"], settings["email"]]
    if settings.get("website"):
        lines.append(settings["website"])
    return "\n".join(lines)


def required_text(settings: dict[str, Any] | None) -> dict[str, str]:
    """What CASL s.6(2) needs in every commercial message: who sent it, how to reach them, how to stop."""
    s = settings or {}
    return {
        "business name": s.get("business_name", ""),
        "mailing address": s.get("mailing_address", ""),
        "contact email": s.get("email", ""),
        "unsubscribe line": UNSUBSCRIBE_LINE,
    }


def tax_percent_text(basis_points: int) -> str:
    whole, part = divmod(basis_points, 100)
    return f"{whole}" if not part else f"{whole}.{part:02d}".rstrip("0")


def fee_line(offer: dict[str, Any]) -> str:
    d = offer["decision"]
    price, cur, bp = offer["price_cents"], offer["currency"], d["tax_basis_points"]
    line = f"The fee is {money_text(price, cur)}, one time"
    if bp:
        line += (
            f", plus {tax_percent_text(bp)}% sales tax ({money_text(tax_cents(price, bp), cur)}),"
            f" for a total of {money_text(invoice_total_cents(price, bp), cur)}"
        )
    return line + "."


def opening(opp: dict[str, Any]) -> str:
    basis = opp["consent"]["basis"]
    if opp["source"] in ("inbound_email", "calendly_booking") or basis == "implied_inquiry":
        return "Thank you for reaching out to ClearGlass."
    if basis == "implied_purchase" or opp["source"] == "existing_customer":
        return "Thank you for working with ClearGlass."
    return "Thank you for agreeing to hear from ClearGlass."


def _signature(settings: dict[str, Any]) -> list[str]:
    return ["", identity_block(settings), "", UNSUBSCRIBE_LINE, "", BRAND_LINE]


def outreach_email(opp: dict[str, Any], offer: dict[str, Any], settings: dict[str, Any]) -> dict[str, str]:
    first, _ = split_name(opp["contact"]["name"])
    lines = [
        f"Hello {first},",
        "",
        opening(opp),
        "",
        f"We offer a {offer['name']}. {offer['summary']} It covers:",
        "",
        *[f"- {item}" for item in offer["scope"]],
        "",
        fee_line(offer),
        "We start only after you confirm in writing which systems we may review."
        if offer["assessment"]
        else "We start once you confirm the scope in writing.",
        "",
    ]
    if settings.get("booking_url"):
        lines.append(f"If you would like to talk it through first, you can book a time here: {settings['booking_url']}")
    else:
        lines.append("If you would like to go ahead, or have questions, reply to this email.")
    lines += _signature(settings)
    return {"subject": f"{offer['name']} for {opp['contact']['organization']}", "body": "\n".join(lines)}


def proposal_sections(opp: dict[str, Any], offer: dict[str, Any]) -> dict[str, Any]:
    """The Proposal Agent's document, as structured sections. The proposal email is built from these."""
    d = offer["decision"]
    due = "on receipt" if d["payment_due_days"] == 0 else f"{d['payment_due_days']} days after the invoice date"
    return {
        "title": f"Proposal: {offer['name']} for {opp['contact']['organization']}",
        "client": opp["contact"]["organization"],
        "scope": list(offer["scope"]),
        "not_included": list(d["exclusions"]),
        "fee": fee_line(offer),
        "timing": f"Delivered within {d['turnaround_business_days']} business days after the work is authorized.",
        "before_we_start": list(offer["fulfillment_requirements"]),
        "payment": f"We send an invoice through PayPal once you accept. Payment is due {due}.",
        "terms": f"This engagement follows: {d['terms_ref']}",
        "reference": opp["id"],
    }


def proposal_email(
    opp: dict[str, Any], offer: dict[str, Any], settings: dict[str, Any], sections: dict[str, Any]
) -> dict[str, str]:
    first, _ = split_name(opp["contact"]["name"])
    lines = [
        f"Hello {first},",
        "",
        f"Here is our proposal for the {offer['name']} for {sections['client']}.",
        "",
        "Scope",
        *[f"- {item}" for item in sections["scope"]],
        "",
        "Not included",
        *[f"- {item}" for item in sections["not_included"]],
        "",
        "Fee",
        sections["fee"],
        "",
        "Timing",
        sections["timing"],
        "",
        "Before we start",
        *[f"- {item}" for item in sections["before_we_start"]],
        "",
        "Payment",
        sections["payment"],
        "",
        "Terms",
        sections["terms"],
        "",
        "To accept, reply to this email and say so.",
        "",
        f"Reference: {sections['reference']}",
        *_signature(settings),
    ]
    return {"subject": sections["title"], "body": "\n".join(lines)}


def invoice_fields(opp: dict[str, Any], offer: dict[str, Any], settings: dict[str, Any], today: date) -> dict[str, Any]:
    """The body of PayPal's create_invoice form, using only the field names its schema declares."""
    d = offer["decision"]
    given, surname = split_name(opp["contact"]["name"])
    fields: dict[str, Any] = {
        "business_name": settings["business_name"],
        "business_email": settings["email"],
        "recipient_email": opp["contact"]["email"],
        "recipient_given_name": given,
        "product_name": offer["name"],
        "amount_value": offer["price_cents"] / 100,
        "amount_currency_code": offer["currency"],
        "due_date": (today + timedelta(days=d["payment_due_days"])).isoformat(),
        "note_from_seller": f"Reference {opp['id']}. {offer['name']} as accepted. {settings['business_name']},"
        f" {settings['email']}.",
    }
    if surname:
        fields["recipient_surname"] = surname
    if d["tax_basis_points"]:
        fields["tax"] = tax_percent_text(d["tax_basis_points"])
    return fields


def allowed_figures(opp: dict[str, Any], offer: dict[str, Any], settings: dict[str, Any] | None) -> list[str]:
    """Every source a number in an outbound message may legitimately come from."""
    d = offer.get("decision") or {}
    price, cur = offer["price_cents"], offer["currency"]
    bp = d.get("tax_basis_points", 0)
    out = [
        *offer["scope"],
        offer["name"],
        offer["summary"],
        *offer["fulfillment_requirements"],
        *d.get("exclusions", []),
        str(d.get("terms_ref", "")),
        money_text(price, cur),
        money_text(tax_cents(price, bp), cur),
        money_text(invoice_total_cents(price, bp), cur),
        tax_percent_text(bp),
        str(d.get("turnaround_business_days", "")),
        str(d.get("payment_due_days", "")),
        opp["id"],
        opp["contact"]["name"],
        opp["contact"]["organization"],
        opp["contact"]["email"],
    ]
    if settings:
        out += [settings["business_name"], settings["mailing_address"], settings["email"]]
    return out


def allowed_urls(settings: dict[str, Any] | None, offer: dict[str, Any] | None = None) -> list[str]:
    s = settings or {}
    urls = [s.get("website") or "", s.get("booking_url") or ""]
    terms = ((offer or {}).get("decision") or {}).get("terms_ref", "")
    if isinstance(terms, str) and terms.startswith("https://"):
        urls.append(terms)
    return [u for u in urls if u]


def ticket(
    kind: str,
    params: dict[str, Any],
    *,
    approval_id: str,
    payload_digest: str,
    office_receipt: str | None,
    released_by: str,
    released_at: str,
) -> dict[str, Any]:
    """Exact execution instructions for a released action. Nothing in it has been sent."""
    base = {
        "kind": kind,
        "approval_id": approval_id,
        "payload_digest": payload_digest,
        "office_receipt": office_receipt,
        "released_by": released_by,
        "released_at": released_at,
        "rehearsal": bool(params.get("rehearsal")),
        "warning": "Execute exactly as shown. Any change to a field needs a new approval.",
    }
    if params.get("rehearsal"):
        base["warning"] += " REHEARSAL: the recipient is a test address; money recorded here never counts."
    if kind in ("outreach_email", "proposal_email"):
        fields = {"to": list(params["recipients"]), "subject": params["subject"], "body": params["body"]}
        if params["connector"] == "gmail":
            step = {"connector": "gmail", "tool": "send_message", "fields": fields}
        else:
            step = {
                "connector": "microsoft_365",
                "tool": "Outlook: new message",
                "fields": fields,
                "note": "The Microsoft 365 connector is not connected. Send from Outlook itself.",
            }
        return {
            **base,
            "connector": params["connector"],
            "steps": [step],
            "record": "Record the message id the mailbox returns. Then verify it against the sent message.",
        }
    if kind == "invoice":
        return {
            **base,
            "connector": "paypal",
            "steps": [
                {
                    "connector": "paypal",
                    "tool": "create_invoice",
                    "fields": params["paypal_fields"],
                    "note": "Opens a PayPal form. Check every field against this ticket before you submit it.",
                },
                {
                    "connector": "paypal",
                    "tool": "send_invoice",
                    "fields": {},
                    "note": "Opens a PayPal form for the invoice just created. It does not return the invoice id.",
                },
                {
                    "connector": "paypal",
                    "tool": "list_invoices",
                    "fields": {"status": ["SENT"], "page_size": 10},
                    "note": f"Find the invoice whose note carries reference {params['opportunity_id']}.",
                },
            ],
            "record": "Record that invoice's id. Then verify its status, total, currency and recipient.",
        }
    raise ValueError(f"no ticket format for {kind!r}")
