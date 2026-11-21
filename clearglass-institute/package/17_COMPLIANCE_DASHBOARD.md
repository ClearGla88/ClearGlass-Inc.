# 17. Compliance dashboard

> **Status notice.** ClearGlass Institute is a proposed organization. It has not been incorporated. ClearGlass Institute is not currently a registered charity with the Canada Revenue Agency. Donations are not eligible for official charitable tax receipts. Documents in this folder are drafts and templates, not legal advice. Signed originals belong in the minute book, not in this repository.

Phase 12 of the owner's prompt of 2026-11-15. One table of every recurring or one-time obligation known to this package, with who owns it.

**Dates.** No corporation exists, so every due date is counted from an event: incorporation (I), the financial year end (FYE), or a trigger. To turn them into calendar dates once the certificate is issued, run:

```bash
python3 clearglass-institute/tools/institute_kit.py calendar --incorporated YYYY-MM-DD --fye MM-DD
```

**Status.** Every row reads "Not started" because no corporation exists. The record of what has happened is `data/status.json`, not this table. When a row is done, record the evidence there and in the minute book; this table is not edited to say "done".

**Risk if missed.** Only consequences stated in a rule in the register are given. Anything else is marked [CONFIRM].

---

## A. Corporate (Ontario)

| Requirement | Authority | Due | Status | Risk if missed | Documentation | Responsible officer |
|---|---|---|---|---|---|---|
| Initial return [L-12] | Ontario Business Registry | I + 60 days | Not started | [CONFIRM] | Filing confirmation, minute book | Secretary |
| Pass the Institute's own by-law [L-18] | Board | I + 60 days | Not started | The Ministry's standard by-laws apply by default [L-18] | Signed resolution | Chair |
| Notice of change [L-14] | Ontario Business Registry | Change + 15 days | Not started | [CONFIRM] | Filing confirmation | Secretary |
| First members' meeting; elect directors [L-15] [L-31] | Members | Within I + 18 months | Not started | First directors' terms end at that meeting; directors must be elected there [L-31] | Notice, minutes | Secretary |
| Annual meeting with statements not more than six months old [L-15] [L-16] | Members | Within 15 months of the last, and FYE + 6 months | Not started | Statements put before the meeting would be too old [L-16] | Notice, minutes, approved statements | Secretary, Treasurer |
| Auditor, review engagement, or the permitted resolution [L-06] [L-28] | Members | Each annual meeting | Not started | [CONFIRM] | Members' resolution | Treasurer |
| Ontario annual return [L-13] | Ontario Business Registry | With the tax return deadline | Not started | [CONFIRM] | Filing confirmation | Secretary |
| Registers and minutes kept current [L-36] | Act | Continuous | Not started | [CONFIRM] | Minute book | Secretary |

## B. Tax (federal)

| Requirement | Authority | Due | Status | Risk if missed | Documentation | Responsible officer |
|---|---|---|---|---|---|---|
| Business number confirmed [L-26] | CRA | I + 7 days (target) | Not started | [CONFIRM] | Confirmation letter | Treasurer |
| Corporate income tax return [L-25] | CRA | FYE + 6 months | Not started | [CONFIRM] | Return and confirmation | Treasurer |
| Non-profit information return, if its tests are met [L-24] | CRA | FYE + 6 months | Not started | [CONFIRM] | Return and confirmation | Treasurer |
| Charity information returns, after registration [L-46] | CRA | FYE + 6 months | Not triggered | [CONFIRM] | Returns and confirmation | Treasurer |
| No tax receipt before registration [L-20] | CRA | Standing rule | Not started | A receipt the Institute is not entitled to issue (risk 3) | Copy of each acknowledgement | Treasurer |
| GST/HST small-supplier check [L-47] | CRA | Each calendar quarter, once any fee is charged | Not triggered | [CONFIRM] | Quarterly revenue worksheet | Treasurer |
| Payroll remittances | CRA | From the first pay date | Not triggered | [CONFIRM] | Remittance records | Treasurer |

## C. Charity designation and money from ClearGlass Inc.

| Requirement | Authority | Due | Status | Risk if missed | Documentation | Responsible officer |
|---|---|---|---|---|---|---|
| Majority of directors at arm's length with the founder and ClearGlass Inc. [L-44] [L-45] | Board, members | Each election | Not started | Private foundation designation (doc 14.3) | Register of directors; annual disclosures | Chair |
| Share of contributions from the founder and ClearGlass Inc. | Board | Quarterly | Not started | Private foundation designation (doc 14.3) | Contribution ledger | Treasurer |
| Every ClearGlass Inc. dealing approved under doc 4 [L-32] | Board | Before each dealing | Not started | Undisclosed related-party dealing (risk 11) | Checklist, minutes, register | Treasurer |

## D. People, messages and data

| Requirement | Authority | Due | Status | Risk if missed | Documentation | Responsible officer |
|---|---|---|---|---|---|---|
| Accessibility policies and training [L-49] | Ontario | Before the first employee starts | Not triggered | [CONFIRM] | Policy; training record | Chair |
| Worker status checked [L-50] | Ontario | Before each volunteer, intern or contractor starts | Not triggered | A person treated as a non-employee who is one (risk 24) | Signed agreement | Chair |
| Consent records for promotional messages [L-48] | Anti-spam law | Before the first such message | Not triggered | Messages sent without the consent the law requires (risk 25) | Consent log; unsubscribe log | Secretary |
| Privacy notice; deletion on schedule [L-51] | Doc 18.1 | Before first collection; then quarterly | Not triggered | Risk 16 | Record of what is held and when it is deleted | Secretary |
| Annual conflict disclosures | Doc 4 | Each year, and on joining | Not started | Risk 11 | Signed disclosures | Secretary |

## E. Internal reviews

| Requirement | Authority | Due | Status | Risk if missed | Documentation | Responsible officer |
|---|---|---|---|---|---|---|
| Risk register review | Doc 11 | Quarterly | Not started | Risks drift unmanaged | Minutes | Chair |
| Account access review (risk 21) | Doc 11 | Quarterly | Not started | Former officers keep access | Access review record | Secretary, Treasurer |
| Backup restore test (risk 21) | Doc 11 | Yearly | Not started | Records cannot be recovered | Restore test record | Secretary |
| Legal register rechecked | `LEGAL_VERIFICATION.md` | Every 180 days; `check` warns | Not started | Reliance on stale rules (risk 20) | Updated `data/legal_claims.json` | Secretary |
| Package check passes | `tools/institute_kit.py check` | Every change | Running | A document claims more than the record shows | CI result | Secretary |
