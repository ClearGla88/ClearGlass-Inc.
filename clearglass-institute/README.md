# ClearGlass Institute founding package

> **Status notice.** ClearGlass Institute is a proposed organization. It has not been incorporated. ClearGlass Institute is not currently a registered charity with the Canada Revenue Agency. Donations are not eligible for official charitable tax receipts. Documents in this folder are drafts and templates, not legal advice. Signed originals belong in the minute book, not in this repository.

An execution-ready package for incorporating ClearGlass Institute as an Ontario not-for-profit corporation, and a checker that stops these files from claiming more than has happened.

Current state: [`STATUS.md`](STATUS.md). How far each legal rule was verified: [`LEGAL_VERIFICATION.md`](LEGAL_VERIFICATION.md). What is still open: [`package/13_OPEN_QUESTIONS.md`](package/13_OPEN_QUESTIONS.md).

## The package, in order

| # | Document | What it is |
|---|---|---|
| 1 | [`package/01_EXECUTIVE_BRIEF.md`](package/01_EXECUTIVE_BRIEF.md) | One-page brief: why, for whom, why separate, the 14-day plan, what is true today |
| 2 | [`articles/ARTICLES_DRAFT.md`](articles/ARTICLES_DRAFT.md) | Articles of incorporation fill-in sheet. **Not updated in this pass.** It predates the statute read; see section A of document 13 |
| 3 | [`package/03_BYLAWS.md`](package/03_BYLAWS.md) | By-law No. 1, first draft, with drafting notes tied to the Act |
| 4 | [`package/04_CONFLICT_AND_RELATED_PARTY_POLICY.md`](package/04_CONFLICT_AND_RELATED_PARTY_POLICY.md) | One-page policy covering every dealing with ClearGlass Inc. |
| 5 | [`package/05_FOUNDING_BOARD_PACKAGE.md`](package/05_FOUNDING_BOARD_PACKAGE.md) | Consent, disclosure, notice, agenda, resolutions, minutes, registers, compliance calendar |
| 6 | [`package/06_BANKING_AND_FINANCIAL_CONTROLS.md`](package/06_BANKING_AND_FINANCIAL_CONTROLS.md) | Banking resolutions, $500 dual authorization, expense and prohibited-transaction policies, budget and bookkeeping |
| 7 | [`package/07_PUBLIC_LAUNCH_PAGE_COPY.md`](package/07_PUBLIC_LAUNCH_PAGE_COPY.md) | Copy for the public page; built as [`site/index.html`](site/index.html) |
| 8 | [`package/08_FIRST_PUBLIC_BRIEF_OUTLINE.md`](package/08_FIRST_PUBLIC_BRIEF_OUTLINE.md) | Outline, standards and checklists for the first public brief |
| 9 | [`package/09_14_DAY_EXECUTION_PLAN.md`](package/09_14_DAY_EXECUTION_PLAN.md) | Each step with owner, dates, dependency, evidence, risk and escalation |
| 10 | [`package/10_90_DAY_OPERATING_PLAN.md`](package/10_90_DAY_OPERATING_PLAN.md) | Twelve measurable outcomes |
| 11 | [`package/11_RISK_AND_COMPLIANCE_REGISTER.md`](package/11_RISK_AND_COMPLIANCE_REGISTER.md) | Twenty risks with mitigation, owner, monitoring and evidence |
| 12 | [`package/12_VALIDATION_CHECKLIST.md`](package/12_VALIDATION_CHECKLIST.md) | The ten go/no-go conditions |
| 13 | [`package/13_OPEN_QUESTIONS.md`](package/13_OPEN_QUESTIONS.md) | Legal, tax and founder decisions still to be made |

Supporting files: `data/status.json` (the record of what has happened), `data/legal_claims.json` (the source register), `tools/institute_kit.py` (the checker and generator, Python standard library only), `tests/test_institute_kit.py`.

## Open items

Unresolved points are tagged in the text: `[CONFIRM]` for a fact to check, `[LEGAL REVIEW]` for a lawyer or tax adviser, `[DECISION REQUIRED]` for the founders or the board. `STATUS.md` counts them per document. Square-bracketed capitals such as `[FULL LEGAL NAME]` are blanks to fill in.

## Keeping it current

```bash
python3 clearglass-institute/tools/institute_kit.py status     # the ten conditions
python3 clearglass-institute/tools/institute_kit.py check      # fails on any unsupported claim or stale file
python3 clearglass-institute/tools/institute_kit.py render     # regenerate notices, STATUS.md, LEGAL_VERIFICATION.md, page blocks
python3 clearglass-institute/tools/institute_kit.py calendar --incorporated 2027-01-15 --fye 12-31
python3 -m pytest clearglass-institute/tests -q
```

**When a step is done:** set it to `"met": true` in `data/status.json` with the date and a short pointer to where the evidence is kept (for example "minute book, tab 3"). Update `as_of`. Run `render`, then `check`, then commit.

**When a legal rule is rechecked:** edit its entry in `data/legal_claims.json`, update `checked`, and raise the level only if the provision was read on the official page. Run `render`.

**When writing a document:** cite rules by id, for example `[L-12]`. Keep the one line that starts with `> **Status notice.**`; `render` rewrites it.

## What the checker enforces

- A step cannot be marked done without a date and evidence, or before the steps it depends on.
- The corporation number and incorporation date stay empty until the certificate is recorded.
- Every document carries the current status notice. It has three states: proposed, incorporated and being organized, and operating. "Operating" appears only when all ten conditions are recorded.
- The public page must carry the two required disclaimers word for word.
- The public page cannot state or imply that the Institute is incorporated, is operating, is a charity, has partners, or has reached anyone, unless the record supports it. This is a pattern scan. It catches drift; it does not replace reading the page.
- The public site's address cannot be on the ClearGlass Inc. domain.
- Every rule id cited in a document exists in the source register. A confirmed rule needs a source; an unverified rule needs a named action.
- Evidence text cannot contain an email address, phone number or postal code.
- `check` warns when a rule was last checked more than 180 days ago. `check --strict` turns warnings into failures.

The tests run in the repository's Baseline CI, so a change that breaks any of this fails the build.

## What the statute read changed

The first version of this folder was drafted from search extracts. The Ontario Act and regulations and the federal Income Tax Act were then read in full text, and the package was corrected:

| Earlier draft | Now | Rule |
|---|---|---|
| Non-profit now, charity later | With educational purposes the Institute may be a charitable corporation under Ontario law from day one. Decide Path A or B before filing | [L-29] [L-30] |
| A numbered name if the search fails | Not available on incorporation | [L-11] |
| First directors simply continue | Directors must be elected at the first members' meeting | [L-31] |
| Remaining property to "qualified donees" | The Act names a narrower group for a charitable corporation | [L-19] |
| Sources disagreed on a six-month deadline for the annual meeting | The financial statements put before it cannot be more than six months old, which has the same effect | [L-16] |
| Annual return "within six months" as a statutory figure | The Act says "prescribed time"; the regulation ties it to the tax return deadline | [L-13] |
| A conflicted three-person board might lack a quorum | The remaining directors are deemed a quorum; if all are conflicted, the members decide | [L-32] |

## Privacy

This repository is public. Signed documents, directors' names and addresses, bank details and CRA letters never go in it. Record that a document exists and where it is kept, nothing more.

## Why this sits in the ClearGlass Inc. repository, and moving out

The plan says the Institute's code host and domain must be separate from ClearGlass Inc. They are not yet: no separate organization exists. This folder is written to be lifted out whole. It imports nothing from the rest of the repository and nothing else imports it.

Two consequences until it moves:

- The repository's Pages build publishes this folder, including the draft page, under the ClearGlass Inc. domain. The page is marked `noindex`, says the Institute is proposed and has not been incorporated, and nothing links to it.
- `public_site.live` stays false. The checker will not accept a ClearGlass Inc. address as the Institute's site.

To move: create the Institute's own organization and repository, copy this folder to its root, add a workflow that runs `check` and `pytest`, point the Institute's domain at `site/`, remove the folder and its three references from this repository (`pyproject.toml` test path, `README.md` status table, `CLAUDE.md` note), and record `milestones.separate_domain_and_code_host`.

## Not legal advice

These are working drafts prepared without a lawyer. Section A of document 13 lists what must go to one before anything is filed.
