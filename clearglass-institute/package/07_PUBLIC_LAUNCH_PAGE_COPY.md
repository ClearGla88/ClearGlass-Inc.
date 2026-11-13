# 7. Public launch page copy

> **Status notice.** ClearGlass Institute is a proposed organization. It has not been incorporated. ClearGlass Institute is not currently a registered charity with the Canada Revenue Agency. Donations are not eligible for official charitable tax receipts. Documents in this folder are drafts and templates, not legal advice. Signed originals belong in the minute book, not in this repository.

Copy for the Institute's single public page. The built page is `site/index.html`. It is not live: the plan puts it on the Institute's own domain, and that domain does not exist yet. [DECISION REQUIRED] the domain.

Two lines on the page are generated from `data/status.json` and cannot be edited by hand: the legal status notice, and the formation checklist. The checker also refuses the page if either required disclaimer is missing or altered, or if any sentence states or implies incorporation, operation, charitable registration, partners or reach that the record does not support.

---

## Page title

ClearGlass Institute — Clarity in the Public Interest

## Meta description

ClearGlass Institute is a proposed Ontario not-for-profit for public education in digital safety, AI literacy and cybersecurity awareness.

[CONFIRM] at launch: replace "a proposed" once the certificate of incorporation is recorded.

## Legal status notice (generated)

Shown directly under the title. The wording follows the record:

| Record | Notice |
|---|---|
| No certificate | ClearGlass Institute is a proposed organization. It has not been incorporated. ClearGlass Institute is not currently a registered charity with the Canada Revenue Agency. Donations are not eligible for official charitable tax receipts. It does not accept donations, payments or memberships. |
| Certificate recorded, checklist incomplete | States the incorporation date and Ontario Corporation Number, says the Institute is still being organized, then the charity disclaimer. |
| All ten go/no-go conditions recorded | States that the Institute is an operating Ontario not-for-profit corporation, with its Ontario Corporation Number, then the charity disclaimer. |

## Mission

To advance public education in digital safety, AI literacy, cybersecurity awareness, digital-investigations literacy, information integrity, and transparent systems knowledge, so that people and communities can understand digital risk and reduce it.

## Vision

A public that can evaluate AI, cybersecurity and information systems for itself, without having to rely on what vendors say about them.

## What the Institute does

The Institute's work is public education. It has three programs:

- **Public briefs.** Short, plain-language explainers on topics such as phishing, AI model risk, data exposure, and the ethics of open-source research. Free to read. Every factual claim is sourced.
- **Open educational frameworks.** Guides and methodology cards on defensive security practice and responsible use of AI tools, published for anyone to use.
- **Workshops and public briefings.** Learning sessions for students, community organizations and small organizations. A session is announced only after its host has agreed in writing.

Program status: the first brief is in preparation. Nothing has been published yet.

[CONFIRM] at launch: update the program status line so it is true on the day the page goes live.

## What the Institute does not do

- It does not sell products or services.
- It does not test, assess or advise on any organization's systems.
- It does not recommend vendors or products, and it accepts no payment to do so.
- It does not refer anyone to ClearGlass Inc. or collect contact details for it.
- It does not issue official charitable tax receipts.

## Public-interest education focus

Everything the Institute publishes is written for people who are not specialists: students, community groups, small organizations and the general public in Canada. The material explains how to recognize and reduce a risk. It does not give instructions for causing harm. It is free, it carries its sources, and it shows when it was last reviewed.

## First program: Public AI & Cyber Literacy Briefs

The first brief is "AI Systems, Digital Risk, and Public Safety: A Practical Literacy Brief". It explains in plain language what AI systems do, where they fail, what that means for personal and community safety, and what a reader can do about it. Each brief names its author and the person who checked its sources, and gives its publication and review dates.

## Contact

[CONFIRM] a contact email address on the Institute's own domain. Until the domain exists, the page reads:

Contact details will be posted here when the Institute has its own domain.

Do not use a personal email address or a ClearGlass Inc. address on this page.

## Disclaimers (required wording)

These two paragraphs appear on the page exactly as written.

> ClearGlass Institute is not currently a registered charity with the Canada Revenue Agency. Donations are not eligible for official charitable tax receipts.

> ClearGlass Institute is a separate not-for-profit initiative from ClearGlass Inc. ClearGlass Inc. is a separate commercial entity.

The first is part of the generated legal status notice and is repeated in the footer. The second appears under its own heading and in the footer.

## Footer

ClearGlass Institute is not currently a registered charity with the Canada Revenue Agency. Donations are not eligible for official charitable tax receipts.

ClearGlass Institute is a separate not-for-profit initiative from ClearGlass Inc. ClearGlass Inc. is a separate commercial entity.

---

## Notes for whoever publishes the page

1. The page carries `noindex` until `public_site.live` is recorded.
2. The checker will not accept a public site address on the ClearGlass Inc. domain.
3. No organization is named on the page unless it is listed in `named_partners` in `data/status.json` with the date and location of its written agreement.
4. No figure for people reached, briefs published or workshops delivered appears unless it can be counted from records the Institute holds.
5. The page asks for nothing: no donation button, no sign-up form, no membership offer. [DECISION REQUIRED] whether and when to add a way to give, and the wording that goes with it. Any such wording must repeat the first disclaimer next to the request.
6. Words to keep off the page unless they become accurate and are supported by the record: "registered charity" (other than in the disclaimer), "tax receipt" (other than in the disclaimer), "CRA-approved", "government partner", "official".
