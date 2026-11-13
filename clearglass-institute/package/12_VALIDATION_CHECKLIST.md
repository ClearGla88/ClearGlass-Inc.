# 12. Validation checklist: go / no-go

> **Status notice.** ClearGlass Institute is a proposed organization. It has not been incorporated. ClearGlass Institute is not currently a registered charity with the Canada Revenue Agency. Donations are not eligible for official charitable tax receipts. Documents in this folder are drafts and templates, not legal advice. Signed originals belong in the minute book, not in this repository.

**The rule.** ClearGlass Institute may describe itself as an operating not-for-profit corporation only when all ten conditions below are true. Until then it is a plan, or after the certificate a corporation still being organized, and every document and page says so.

**Current result:** see `STATUS.md`, which is generated from `data/status.json`. This page states the conditions; it does not record their state.

---

## The ten conditions

| # | Condition | What counts as evidence | Record key |
|---|---|---|---|
| 1 | Ontario certificate of incorporation received | The certificate, showing the Ontario Corporation Number and date | `gates.certificate_of_incorporation` |
| 2 | Articles filed and retained | A copy of the articles as filed, with the registry receipt, in the minute book | `gates.articles_filed` |
| 3 | Three director consents on file | Three signed consents, each dated before or within 10 days after the director took office [L-03] | `gates.three_director_consents` |
| 4 | By-laws adopted | The directors' resolution making By-law No. 1 and the members' resolution confirming it [L-17] | `gates.bylaws_adopted` |
| 5 | Organizational minutes signed | Signed minutes of the first directors' meeting and the members' meeting or signed resolution, including the election of directors [L-31] | `gates.organizational_minutes_signed` |
| 6 | CRA Business Number obtained | The CRA's confirmation of the number | `gates.cra_business_number` |
| 7 | Bank account opened in the Institute's legal name | Account-opening documents naming ClearGlass Institute and two signing officers | `gates.institute_bank_account` |
| 8 | Public "not a registered charity" disclaimer live | The public page, live on the Institute's own domain, carrying the required disclaimer word for word | `gates.public_charity_disclaimer`, with `public_site` |
| 9 | Conflict-of-interest policy adopted | The board resolution adopting the policy, and each director's signed disclosure | `gates.conflict_policy_adopted` |
| 10 | Annual-return calendar created | The compliance calendar with the year end recorded and reminders set | `gates.annual_return_calendar` |

## Decision

| Result | Meaning | What the Institute may say |
|---|---|---|
| **NO-GO** before condition 1 | No corporation exists | "ClearGlass Institute is a proposed organization. It has not been incorporated." |
| **NO-GO** after condition 1, with any other condition open | A corporation exists and is being organized | That it was incorporated in Ontario on the date shown, with its corporation number, and that it is still being organized |
| **GO**, all ten recorded | The Institute is organized and may operate | That it is an operating Ontario not-for-profit corporation |

At every stage, until the Canada Revenue Agency registers it: "ClearGlass Institute is not currently a registered charity with the Canada Revenue Agency. Donations are not eligible for official charitable tax receipts."

## How a condition is recorded

1. A person completes the step and files the evidence in the minute book.
2. That person, or someone they instruct, sets the condition to met in `data/status.json`, with the date and a short pointer to where the evidence is kept (for example "minute book, tab 1"). The evidence itself, and any name, address or account detail, stays out of the repository.
3. Run `python3 clearglass-institute/tools/institute_kit.py render`, then `check`.
4. Every status notice, `STATUS.md` and the public page update together.

The checker refuses a condition recorded without a date and evidence, and refuses one recorded before the step it depends on: the certificate needs filed articles; by-laws, minutes, the policy, the business number and the calendar need the certificate; the bank account needs the certificate and the signed minutes; the disclaimer needs a live site on a domain that is not ClearGlass Inc.'s.

## What GO does not mean

- It does not make the Institute a registered charity. That needs a separate application to the CRA and its approval [L-20] [L-21].
- It does not settle the questions in `13_OPEN_QUESTIONS.md`. Several of them should be answered before condition 2.
- It does not mean any program has been delivered. Program results are recorded separately and reported only from records the Institute holds.

## Also tracked, outside the ten

Written legal and tax advice; the name search report; the initial return, due within 60 days of incorporation [L-12]; the minute book and registers [L-36]; a domain and code host separate from ClearGlass Inc.; and the first published brief. Their state is in `STATUS.md`.
