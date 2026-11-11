# Runbook: from plan to corporation

> **Status notice.** ClearGlass Institute is a proposed organization. It is not yet incorporated and is not a registered charity. Files in this folder are working drafts and templates, not legal advice. Signed originals belong in the minute book, not in this repository.

Work the steps in order. Each step has an owner. HUMAN means only a person can do it: it involves a signature, a payment, a legal filing, or a decision about someone's rights. PREPARED means the paper is in this folder and a person still has to act on it.

After each step, record it in `data/status.json` (date, and where the evidence is kept), run `render`, and commit. `STATUS.md` then shows the current state.

## Stage 0. Decide before spending money

Three questions can each force a change to the articles. Answer them first. One paid hour with a charity lawyer can cover all three.

| # | Question | Why it matters | Owner |
|---|---|---|---|
| 0.1 | What is the Institute's income tax status while it is unregistered, given charitable purposes? | An unregistered body with exclusively charitable purposes may not qualify for the non-profit exemption [L-23] | HUMAN, with lawyer or CPA |
| 0.2 | Can the name ClearGlass Institute be registered? | Institute is restricted for educational bodies [L-09]; ClearGlass may need consent from ClearGlass Inc. [L-10] | HUMAN, with search house or lawyer |
| 0.3 | What dissolution clause works under ONCA and for the CRA? | ONCA limits who receives the property, by type of corporation [L-19] | HUMAN, with lawyer |

Record as: `milestones.tax_and_name_opinion`.

Questions to bring are listed at the end of `articles/ARTICLES_DRAFT.md`, `governance/BYLAW_NO_1_DRAFT.md` and `governance/CONFLICT_AND_RELATED_PARTY_POLICY.md`.

## Stage 1. People

| # | Step | Owner | Paper |
|---|---|---|---|
| 1.1 | Confirm three directors. Each is an individual, 18 or older, not bankrupt [L-01] [L-02] | HUMAN | none |
| 1.2 | At least one director with no stake in ClearGlass Inc.; two is better | HUMAN | conflict policy |
| 1.3 | Each director signs a consent to act [L-03] | HUMAN | PREPARED: `governance/DIRECTOR_CONSENT_TEMPLATE.md` |

Record as: `gates.three_director_consents`.

The blunt point: this stage is the real bottleneck. Everything else in the kit is paperwork one person can finish in a week. Two other adults willing to carry a director's legal duties are not paperwork. Start here.

## Stage 2. Name and filing

| # | Step | Owner | Paper |
|---|---|---|---|
| 2.1 | Order an Ontario-biased NUANS report for the name settled in 0.2, or decide on a number name [L-08] [L-11] | HUMAN | none |
| 2.2 | Get written consent from ClearGlass Inc. if 0.2 found it is needed [L-10] | HUMAN | none |
| 2.3 | Complete the articles from the fill-in sheet | PREPARED | `articles/ARTICLES_DRAFT.md` |
| 2.4 | File the articles and pay the fee [L-07]. The report must be under 90 days old on the filing date [L-08] | HUMAN | none |
| 2.5 | Receive the certificate. Note the corporation number and date | HUMAN | none |

Record as: `milestones.name_search_report`, `milestones.articles_filed`, then `gates.certificate_of_incorporation` together with `entity.corporation_number` and `entity.incorporation_date`.

Once the date is recorded, `STATUS.md` shows the real deadlines.

## Stage 3. First 60 days after the certificate

The 60-day clock covers two things: the initial return [L-12] and passing by-laws before the default ones apply [L-18].

| # | Step | Owner | Paper |
|---|---|---|---|
| 3.1 | Hold the directors' organizational meeting, then the members' meeting | HUMAN | PREPARED: `governance/ORGANIZATIONAL_RESOLUTIONS_DRAFT.md` |
| 3.2 | Adopt by-laws and have members confirm them [L-17] | HUMAN | PREPARED: `governance/BYLAW_NO_1_DRAFT.md` |
| 3.3 | Adopt the conflict policy | HUMAN | PREPARED: `governance/CONFLICT_AND_RELATED_PARTY_POLICY.md` |
| 3.4 | Open the minute book and registers | HUMAN | PREPARED: `governance/MINUTE_BOOK_INDEX.md` |
| 3.5 | File the initial return [L-12] | HUMAN | none |
| 3.6 | Choose the financial year end and record it in `entity.financial_year_end` | HUMAN | resolutions, item 4 |

Record as: `gates.bylaws_adopted_in_minutes`, `milestones.minute_book_opened`, `milestones.initial_return_filed`.

## Stage 4. Money

| # | Step | Owner | Paper |
|---|---|---|---|
| 4.1 | Confirm the business number, or register for one [L-26] | HUMAN | none |
| 4.2 | Open the bank account in the Institute's name with two signing officers | HUMAN | resolutions, item 7 |
| 4.3 | Put no ClearGlass Inc. money in without a minuted donation, sponsorship or loan agreement | HUMAN | conflict policy, 4.1 |

Record as: `gates.cra_business_number`, `gates.institute_bank_account`.

## Stage 5. Public presence

| # | Step | Owner | Paper |
|---|---|---|---|
| 5.1 | Register a domain for the Institute that is not a ClearGlass Inc. domain | HUMAN | none |
| 5.2 | Create a code host organization for the Institute and move this folder to it | HUMAN | `README.md`, "Moving out" |
| 5.3 | Publish the public page on that domain | PREPARED | `site/index.html` |
| 5.4 | Set `public_site.live` and `public_site.url` | HUMAN | none |

Record as: `milestones.separate_domain_and_code_host`, then `gates.public_charity_disclaimer`.

The checker refuses a public site URL on the ClearGlass Inc. domain.

## Stage 6. First work

| # | Step | Owner | Paper |
|---|---|---|---|
| 6.1 | Write the first public brief: cited, dated, author named | HUMAN author; an agent may draft | PREPARED: `programs/BRIEF_TEMPLATE.md` |
| 6.2 | Second person checks every source before it is published | HUMAN | program plan, publishing rules |

Record as: `milestones.first_public_brief_published`.

## Stage 7. Ninety days in

- Board calendar and filing reminders set (`operations/COMPLIANCE_CALENDAR.md`)
- One workshop outline
- Decision memo to the board: stay a non-profit, or apply for charitable registration [L-21]

## What an agent may and may not do here

| May | May not |
|---|---|
| Draft and correct the documents in this folder | File anything with a registry or the CRA |
| Keep the source register current | Sign, pay, open accounts, or accept terms |
| Update `data/status.json` when a person reports a step done and says where the evidence is | Record a step as done on its own inference |
| Run the checker and fix what it finds | Contact directors, funders, regulators, or the public |
| Draft a brief for a named human author to review | Publish under the Institute's name |
