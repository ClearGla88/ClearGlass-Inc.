"""Editable content for the ClearGlass Inc. homepage.

Every word, link and optional detail on the homepage comes from this file.
Edit it, then run ``python3 website/build.py`` to regenerate ``index.html``.

Content rules (enforced in part by ``tests/test_homepage.py``):

* The copy below describes service areas and a proposed way of working. It is
  marketing copy, not a record of completed work. Do not add clients,
  testimonials, certifications, partnerships, awards, metrics, guarantees or
  government affiliation unless you can point to the evidence.
* Optional fields (people, contact email, form endpoint, social and legal
  links, articles) default to empty. Empty means "not shown": the page states
  honestly that the item is not available yet instead of inventing it.

stdlib only, so the build runs on a bare CI runner.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Link:
    label: str
    href: str


@dataclass(frozen=True)
class Capability:
    id: str
    icon: str  # key into components.ICONS
    title: str
    summary: str
    points: tuple[str, ...]


@dataclass(frozen=True)
class ProcessStep:
    number: str
    title: str
    summary: str
    output: str


@dataclass(frozen=True)
class Article:
    """A published article. Add one only when the page at ``href`` exists."""

    title: str
    summary: str
    href: str
    published: str  # ISO date, e.g. "2026-12-01"
    topic: str


@dataclass(frozen=True)
class Person:
    """A leadership profile. Shown in About only when at least one exists."""

    name: str
    role: str
    bio: str


@dataclass(frozen=True)
class Contact:
    # A confirmed, working inbox. None hides every email link on the page.
    email: str | None = None
    # A form-handling endpoint that accepts a POST (for example a Formspree
    # form URL). None renders the form switched off, with an explanation.
    form_endpoint: str | None = None


@dataclass(frozen=True)
class HeroImage:
    # (path, width in px) pairs, all WebP, same aspect ratio as width/height.
    webp_sources: tuple[tuple[str, int], ...]
    fallback: str
    width: int
    height: int
    alt: str


@dataclass(frozen=True)
class SiteConfig:
    name: str
    url: str  # production origin; must match CNAME
    tagline: str
    utility_label: str
    eyebrow: str
    headline: tuple[str, ...]
    headline_brand: str  # visible first line of the <h1>
    supporting: str
    primary_cta: Link
    secondary_cta: Link
    nav: tuple[Link, ...]
    header_cta: Link
    capabilities_intro: str
    capabilities: tuple[Capability, ...]
    process_intro: str
    process: tuple[ProcessStep, ...]
    insights_intro: str
    articles: tuple[Article, ...]
    about: tuple[str, ...]
    principles: tuple[tuple[str, str], ...]
    location: str | None
    people: tuple[Person, ...]
    contact_intro: str
    contact: Contact
    socials: tuple[Link, ...]
    legal: tuple[Link, ...]
    # Existing public pages linked from the homepage footer, for visitors and
    # crawlers. build.py fails if one is missing or is not a canonical sitemap URL.
    explore: tuple[Link, ...]
    hero_image: HeroImage
    monogram: str
    og_image: str
    meta_title: str
    alternate_name: str | None  # JSON-LD WebSite.alternateName
    meta_description: str
    theme_color: str
    # Old homepage anchors that other pages still link to, mapped to the
    # section that now covers them, so those links keep landing somewhere.
    anchor_aliases: dict[str, tuple[str, ...]] = field(default_factory=dict)


SUPPORTING = (
    "Software architecture, AI automation, and cybersecurity-focused systems "
    "designed for clarity, control, and accountable operations."
)

SITE = SiteConfig(
    name="ClearGlass Inc.",
    url="https://www.clearglassinc.com",
    tagline="See Through Everything.",
    utility_label="CLEARGLASS / SYSTEMS & INTELLIGENCE",
    eyebrow="SOFTWARE ARCHITECTURE • AI AUTOMATION • CYBERSECURITY",
    headline=("Governed AI.", "Engineered Trust."),
    headline_brand="ClearGlass Inc.",
    supporting=SUPPORTING,
    primary_cta=Link("Explore Capabilities", "#capabilities"),
    secondary_cta=Link("Discuss a Project", "#contact"),
    nav=(
        Link("Capabilities", "#capabilities"),
        Link("Approach", "#approach"),
        Link("Insights", "#insights"),
        Link("About", "#about"),
        Link("Contact", "#contact"),
    ),
    header_cta=Link("Discuss a Project", "#contact"),
    capabilities_intro=(
        "Four connected service areas. Each one starts from the systems and "
        "data an organization already runs."
    ),
    capabilities=(
        Capability(
            id="architecture",
            icon="layers",
            title="Software & Systems Architecture",
            summary=(
                "System design for software that has to stay understandable as "
                "it grows: service boundaries, data flows, integration points, "
                "and the documentation that keeps them maintainable."
            ),
            points=(
                "Architecture reviews and target-state designs",
                "Integration and data-flow mapping",
                "Technical documentation and decision records",
            ),
        ),
        Capability(
            id="automation",
            icon="nodes",
            title="AI Automation & Integration",
            summary=(
                "Automation that fits into existing work, with defined inputs, "
                "human approval where decisions carry risk, and a record of "
                "what each automated step did."
            ),
            points=(
                "Workflow automation design",
                "Model and tool integration",
                "Human approval points for higher-risk steps",
            ),
        ),
        Capability(
            id="security",
            icon="shield",
            title="Cybersecurity & Digital Risk",
            summary=(
                "Security work scoped to the systems and data an organization "
                "actually runs: understanding exposure, prioritizing fixes, "
                "and planning for incidents."
            ),
            points=(
                "Risk and exposure assessments",
                "Hardening and configuration review",
                "Incident-readiness planning",
            ),
        ),
        Capability(
            id="governance",
            icon="ledger",
            title="Governance & Technical Operations",
            summary=(
                "Operating controls for technology teams: who can approve what, "
                "how changes are recorded, and how systems are looked after "
                "once they are live."
            ),
            points=(
                "Approval and change-control design",
                "Audit trails and operational records",
                "Runbooks and maintenance routines",
            ),
        ),
    ),
    process_intro=(
        "A proposed engagement process. Each phase ends with something you can "
        "review before the next one begins."
    ),
    process=(
        ProcessStep(
            "01",
            "Discover",
            "Understand the current systems, constraints, data and "
            "decision-makers before proposing anything.",
            "A written summary of scope, constraints and open questions.",
        ),
        ProcessStep(
            "02",
            "Architect",
            "Design the target state and the path to it, with trade-offs and "
            "risks stated plainly.",
            "An architecture and delivery plan for your review and approval.",
        ),
        ProcessStep(
            "03",
            "Implement",
            "Build in small, reviewable increments, with approval gates on "
            "changes that carry risk.",
            "Working increments, each with its documentation.",
        ),
        ProcessStep(
            "04",
            "Validate",
            "Test the result against the agreed requirements and record what "
            "was checked, and what was not.",
            "Validation notes and a handover record.",
        ),
    ),
    insights_intro="Notes on governed AI, system architecture and digital risk.",
    articles=(),
    about=(
        "ClearGlass Inc. designs and builds software, automation and "
        "security-focused systems. The work rests on one idea: a system should "
        "be clear enough that the people responsible for it can see what it "
        "does, approve what matters, and check what happened.",
        "Engagements are scoped to the problem at hand and documented as they "
        "go, so decisions, trade-offs and limits are on record rather than "
        "implied.",
    ),
    principles=(
        ("Show the work", "Decisions and trade-offs are written down."),
        ("Approve what matters", "People sign off on changes that carry risk."),
        ("State the limits", "What was not checked is reported with what was."),
    ),
    # Shown in About. Taken from the owner's own brand imagery ("ONTARIO").
    location="Ontario, Canada",
    people=(),
    contact_intro=(
        "Describe the system, the problem or the decision you are working on."
    ),
    contact=Contact(email=None, form_endpoint=None),
    socials=(),
    legal=(),
    # Chosen 2026-11-21 from sitemap pages that pass the homepage claim checks
    # (tests/test_homepage.py FORBIDDEN). Passing is not a fact-check: review
    # each page before relying on it, and edit this list freely.
    explore=(
        Link("Pricing and engagements", "pricing.html"),
        Link("SMB Cyber Trust Kit", "smb-cyber-trust-kit.html"),
        Link("Environmental cyber-risk", "environmental-cyber-risk.html"),
        Link("Business email on your own domain", "workspace-email.html"),
    ),
    hero_image=HeroImage(
        webp_sources=(
            ("assets/site/img/ontario-skyline-640.webp", 640),
            ("assets/site/img/ontario-skyline-1024.webp", 1024),
            ("assets/site/img/ontario-skyline-1536.webp", 1536),
        ),
        fallback="assets/site/img/ontario-skyline-1024.jpg",
        width=1536,
        height=1024,
        alt=(
            "Stylized illustration of the Toronto waterfront at dusk: the CN "
            "Tower and skyline lit in blue and violet, two hovering craft "
            "casting light beams, and the word ONTARIO over the water."
        ),
    ),
    monogram="assets/site/img/monogram.svg",
    og_image="assets/site/img/og-card.png",
    # Owner-supplied search title and description (2026-11-21).
    meta_title="ClearGlass Inc. | AI Automation, Secure Software & Strategic Operations",
    alternate_name="ClearGlass",
    meta_description=(
        "ClearGlass Inc. builds secure software, AI automation, cybersecurity, "
        "and strategic operations systems."
    ),
    theme_color="#09080c",
    anchor_aliases={
        "capabilities": ("services", "products"),
        "about": ("vision", "founder"),
    },
)
