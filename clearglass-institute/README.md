# ClearGlass Institute founding kit

> **Status notice.** ClearGlass Institute is a proposed organization. It is not yet incorporated and is not a registered charity. Files in this folder are working drafts and templates, not legal advice. Signed originals belong in the minute book, not in this repository.

Everything needed to take ClearGlass Institute from an idea to an Ontario not-for-profit corporation, and a checker that stops these files from claiming more than has happened.

Current state: [`STATUS.md`](STATUS.md). How far each legal rule was verified: [`LEGAL_VERIFICATION.md`](LEGAL_VERIFICATION.md).

## Read in this order

1. [`FOUNDING_KIT.md`](FOUNDING_KIT.md): the plan, with the corrections made to the first draft listed at the end.
2. [`operations/RUNBOOK.md`](operations/RUNBOOK.md): the steps, in order, with who has to do each one.
3. [`LEGAL_VERIFICATION.md`](LEGAL_VERIFICATION.md): what is confirmed and what is not.

## What is here

| Path | What it is |
|---|---|
| `FOUNDING_KIT.md` | The founding plan |
| `STATUS.md` | Generated. The six tests and where things stand |
| `LEGAL_VERIFICATION.md` | Generated. Every legal rule relied on, with sources and verification level |
| `articles/ARTICLES_DRAFT.md` | Fill-in sheet for the articles of incorporation |
| `governance/BYLAW_NO_1_DRAFT.md` | Draft general by-law |
| `governance/CONFLICT_AND_RELATED_PARTY_POLICY.md` | Draft policy for conflicts and all dealings with ClearGlass Inc. |
| `governance/ORGANIZATIONAL_RESOLUTIONS_DRAFT.md` | First meeting agenda, founding and banking resolutions |
| `governance/DIRECTOR_CONSENT_TEMPLATE.md` | Blank consent to act as a director |
| `governance/MINUTE_BOOK_INDEX.md` | What the minute book holds, and what may be written in this repository |
| `operations/RUNBOOK.md` | Step-by-step execution |
| `operations/COMPLIANCE_CALENDAR.md` | Recurring obligations |
| `programs/PROGRAM_PLAN.md` | The three programs and the publishing rules |
| `programs/BRIEF_TEMPLATE.md` | Template for a public brief |
| `site/index.html` | Draft public page |
| `data/status.json` | The record of what has actually happened |
| `data/legal_claims.json` | The source register |
| `tools/institute_kit.py` | The checker and generator (Python standard library only) |
| `tests/test_institute_kit.py` | Tests for the checker |

## Keeping it current

```bash
python3 clearglass-institute/tools/institute_kit.py status     # the six tests
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
- Every document carries the current status notice. When the record changes, every notice changes with it.
- The public page cannot state or imply that the Institute is incorporated, is a charity, has partners, or has reached anyone, unless the record supports it. This is a pattern scan. It catches drift; it does not replace reading the page.
- The public site's address cannot be on the ClearGlass Inc. domain.
- Every rule id cited in a document exists in the source register. A confirmed rule needs a source; an unverified rule needs a named action.
- Evidence text cannot contain an email address, phone number or postal code.
- `check` warns when a rule was last checked more than 180 days ago. `check --strict` turns warnings into failures.

The tests run in the repository's Baseline CI, so a change that breaks any of this fails the build.

## Privacy

This repository is public. Signed documents, directors' names and addresses, bank details and CRA letters never go in it. Record that a document exists and where it is kept, nothing more. See `governance/MINUTE_BOOK_INDEX.md`.

## Why this sits in the ClearGlass Inc. repository, and moving out

The plan says the Institute's code host and domain must be separate from ClearGlass Inc. They are not yet: no separate organization exists. This folder is written to be lifted out whole. It imports nothing from the rest of the repository and nothing else imports it.

Two consequences until it moves:

- The repository's Pages build publishes this folder, including the draft page, under the ClearGlass Inc. domain. The page is marked `noindex`, says the Institute is proposed and not incorporated, and nothing links to it.
- `public_site.live` stays false. The checker will not accept a ClearGlass Inc. address as the Institute's site.

To move: create the Institute's own organization and repository, copy this folder to its root, add a workflow that runs the two commands `check` and `pytest`, point the Institute's domain at `site/`, remove the folder and its three references from this repository (`pyproject.toml` test path, `README.md` status table, `CLAUDE.md` note), and record `milestones.separate_domain_and_code_host`.

## Not legal advice

These are working drafts prepared without a lawyer. Three points must go to one before anything is filed: tax status while unregistered, whether the name can be registered, and the dissolution clause. They are stage 0 of the runbook.
