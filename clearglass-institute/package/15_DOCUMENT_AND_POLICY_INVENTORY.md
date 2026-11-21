# 15. Document and policy inventory

> **Status notice.** ClearGlass Institute is a proposed organization. It has not been incorporated. ClearGlass Institute is not currently a registered charity with the Canada Revenue Agency. Donations are not eligible for official charitable tax receipts. Documents in this folder are drafts and templates, not legal advice. Signed originals belong in the minute book, not in this repository.

Every document named in phases 2, 4, 6, 8 and 11 of the owner's prompt of 2026-11-15, with where it stands. For each one the inventory says whether the law requires it, or whether it is a control the Institute chooses. A document the law does not require is written only when the Institute has the activity it governs. A three-person body with no staff that adopts thirty policies on day one will not follow them, and a policy it does not follow is worse than none.

## How to read the tables

**Basis.** "Required" cites the rule that makes it so. "Recommended control" means good practice, not a legal duty. "Funder or bank" means a third party may ask for it.

**When.** The tier at which the document must be adopted:

| Tier | Trigger |
|---|---|
| T0 | Before the articles are filed |
| T1 | At the organizational meeting |
| T2 | Before the first public activity, the first personal information collected, or the first money received |
| T3 | Before the first volunteer, contractor or employee starts |
| T4 | Before the application for charitable registration, or the first grant program |
| T5 | Only when the activity it governs exists. Not drafted until then |

**Stands.** "Drafted" names the document that holds it. "Not drafted" is an open item.

---

## A. Formation (phase 2)

| Document | Purpose | Basis | When | Stands |
|---|---|---|---|---|
| Articles of incorporation | Creates the corporation; sets name and purposes | Required [L-07] [L-43] | T0 | Drafted: `articles/ARTICLES_DRAFT.md` |
| Name search report | Supports the proposed name | Required [L-08] | T0 | Not obtained |
| Registered office | Address in the articles | Required [L-43] | T0 | Municipality chosen; address [CONFIRM] (doc 13, A11) |
| Director consents | Makes each director's election effective | Required [L-03] | T0 | Drafted: doc 5.2 |
| Officer appointments | Names the officers | Directors' power [L-38] | T1 | Drafted: doc 5.6 |
| Corporation number | Issued with the certificate | Required | T0 | None. `data/status.json` keeps it empty until issued |
| Business number | Federal tax account | [L-26] | T1 | Not obtained; may be automatic (doc 13, B12) |
| Initial return | First filing after incorporation | Required within 60 days [L-12] | T1 | Not filed |
| Minute book and registers | Statutory records | Required [L-36] | T1 | Templates drafted: doc 5.8, 5.9 |
| Corporate seal | Not drafted. No rule requiring one was found in the sources read for this package | Not required on the sources read. [CONFIRM] whether the chosen bank asks for one | T5 | Not needed |
| Share restrictions | None. A corporation under the Ontario Act has no share capital [L-43] | Not applicable | none | Not needed |

## B. Governance (phase 4)

| Document | Purpose | Required sections | Basis | When | Stands |
|---|---|---|---|---|---|
| By-law No. 1 | Membership, meetings, directors, officers, finance | Members, notice, quorum, directors, officers, signing, financial year, amendment | Required in practice: if none is passed within 60 days the standard by-laws apply [L-18] | T1 | Drafted: doc 3 |
| Conflict-of-interest and related-party policy | Governs every dealing with ClearGlass Inc. | Who is covered, disclosure, withdrawal, approval, register | The statutory duty is in [L-32]; the policy goes further | T1 | Drafted: doc 4 |
| Record retention and destruction | What is kept, where, for how long, and who may destroy it | Record classes, retention periods, storage, destruction approval, litigation hold | Records the Act requires are in [L-36]; periods are a control. Accounting period [CONFIRM] (doc 13, D6) | T1 | Not drafted |
| Code of conduct, including ethics | Standards for directors, officers, volunteers and staff | Honesty, confidentiality, respect, use of the Institute's name, gifts, reporting concerns | Recommended control. Directors' statutory duties are in [L-39] | T2 | Not drafted |
| Whistleblower policy | Safe route to report wrongdoing | What may be reported, to whom (a director with no interest in ClearGlass Inc.), no retaliation, records | Recommended control | T3 | Not drafted |
| Director orientation note (the prompt's "director handbook") | What a new director must read | Articles, by-law, policies, duties [L-39], conflict rules [L-32], compliance calendar, risk register | Recommended control | T1 | Not drafted. One page; no separate handbook |
| Governance charter | Not drafted. The by-law, doc 4 and the board calendar cover the same ground | Recommended control | T5 | Not needed at this size |
| Committee charters | Only once the board creates a committee | Recommended control | T5 | Not needed: no committees planned |

## C. Financial (phases 4 and 6)

| Document | Purpose | Basis | When | Stands |
|---|---|---|---|---|
| Bank-account opening resolution | Opens the account in the Institute's name | Bank requirement | T1 | Drafted: doc 6.1 |
| Signing-authority resolution (signing authority matrix) | Two signatures over $500 | Recommended control; bank requirement | T1 | Drafted: doc 6.2 |
| Expense-approval policy | Who approves what | Recommended control | T1 | Drafted: doc 6.3 |
| Prohibited transactions policy | Payments that are never made | Recommended control; charity law on paying directors [L-30] | T1 | Drafted: doc 6.4 |
| Related-party approval checklist | Every ClearGlass Inc. dealing | [L-32]; doc 4 | T1 | Drafted: doc 6.5 |
| Annual budget | Spending plan | Recommended control | T1 | Template drafted: doc 6.6 |
| Bookkeeping checklist and chart of accounts | Monthly records | Records [L-36]; chart of accounts is a control | T1 | Checklist drafted: doc 6.7. Chart of accounts not drafted; [CONFIRM] with the accountant, who should set it up to match the accounting standard chosen (doc 13, D11) |
| Donation (gift acceptance) policy | Which gifts are accepted, and how they are acknowledged | No receipts before registration [L-20]; rest is a control | T2 | Drafted: doc 18.2 |
| Contribution tracking | Separates founder and ClearGlass Inc. money from all other money | Charity designation tests [L-44] [L-45] | T2 | Not drafted. A separate ledger class; see doc 14.3 |
| Procurement policy, including vendor risk | Quotes, conflicts and security checks before buying | Recommended control | T2 | Not drafted. Short: two quotes above [LIMIT]; no ClearGlass Inc. supplier without doc 4; security questions for any service that will hold personal information |
| Grant management policy | Application, acceptance, restricted funds, reporting | Recommended control; risk 22 | T4 | Not drafted |
| Investment policy | How reserves are invested | [LEGAL REVIEW] Charities Accounting Act and investment rules (doc 13, B8) | T5 | Not needed until there are reserves |
| Audit readiness checklist | Records the reviewer or auditor will ask for | Audit or review engagement [L-06] | T4 | Not drafted |
| Internal controls policy | Not separate. Docs 6.2 to 6.7 are the internal controls | Recommended control | none | Drafted in doc 6 |

## D. Security and privacy (phase 4)

| Document | Purpose | Basis | When | Stands |
|---|---|---|---|---|
| Privacy policy and public privacy notice | What personal information is collected, why, how long, who sees it | Which law applies is open [L-51] (doc 13, C6). The policy is a control in any case | T2 | Drafted: doc 18.1 |
| Information security policy (the prompt's cybersecurity policy) | Accounts, devices, backups | Recommended control. For an organization that teaches digital safety, the credibility risk is high (risk 21) | T2 | Not drafted. Risk 21 already lists its content |
| Access control | Who holds which account; removal on change | Recommended control | T2 | Rules drafted in doc 6.2 paragraph 6 and risk 21; no standalone policy needed |
| Incident response plan | What happens when an account is taken over or data is exposed | Recommended control; risk 21 | T2 | Not drafted. One page: contain, preserve evidence, inform the Chair, decide on notices with counsel |
| Data governance | Not separate. Folded into the privacy policy and the retention policy | Recommended control | none | Covered by doc 18.1 and the retention policy |
| Vendor risk | Not separate. Folded into procurement | Recommended control | none | See section C |

## E. AI governance (phase 4)

| Document | Purpose | Basis | When | Stands |
|---|---|---|---|---|
| AI use and transparency policy | Covers acceptable use, risk check before use, disclosure and human responsibility in one document | Recommended control; risk 19; doc 8 standards | T2 | Drafted: doc 18.3 |
| Model governance standard | Not drafted. The Institute does not train or deploy models | Not applicable | T5 | Only if the Institute builds or hosts a model |
| Responsible AI framework | Not separate. Doc 18.3 and doc 8 hold it | Recommended control | none | Covered |

## F. People (phase 8)

| Document | Purpose | Basis | When | Stands |
|---|---|---|---|---|
| Director commitment letter (the prompt's "director agreement") | Time, confidentiality, conflict disclosure, no pay | Directors are not paid as directors [L-30]; consent [L-03]. A letter, not a contract for services | T1 | Not drafted. See doc 16.2 |
| Volunteer agreement | Role, supervision, confidentiality, licence of work | Volunteer status [L-50]; ownership of work (doc 13, C10) | T3 | Not drafted. Contents in doc 16.2 |
| Contractor agreement | Deliverables, fees, assignment or licence of work, confidentiality, conflict declaration | Contractor status [L-50]; doc 13, C10 | T3 | Not drafted. Contents in doc 16.2 |
| Hiring checklist | Steps before a first employee starts | Employment rules [L-49] [L-50]; payroll and other registrations [CONFIRM] (doc 16.1) | T3 | Drafted: doc 16.2 |
| Accessibility policies and training record | Required once the Institute has an employee in Ontario | [L-49] | T3 | Not drafted |

## G. Count

Filings and numbers (name search, registered office address, corporation number, business number, initial return) are tracked in `data/status.json` and doc 17, not counted here.

| Drafted or covered | Not drafted, needed by T3 | Not needed yet (T4, T5 or not applicable) |
|---|---|---|
| 22 | 13 | 8 |

The thirteen to write, by tier:

- **T1:** record retention; director orientation note; director commitment letter; chart of accounts (with the accountant).
- **T2:** code of conduct; information security policy; incident response plan; procurement; contribution tracking.
- **T3:** volunteer agreement; contractor agreement; accessibility policies; whistleblower policy.

[DECISION REQUIRED] the board confirms the order at its first meeting.
