"""Reusable homepage components, rendered to static HTML.

Each function takes typed values from ``site_config`` and returns an HTML
string. All text passes through ``e()`` (HTML escaping), so content edits
in the config cannot break the markup or inject script.

stdlib only.
"""

from __future__ import annotations

import json
from datetime import date
from html import escape

from site_config import (
    Article,
    Capability,
    Contact,
    Link,
    Person,
    ProcessStep,
    SiteConfig,
)


def e(text: str) -> str:
    return escape(text, quote=True)


# Original 24x24 stroke icons (no third-party icon set).
ICONS: dict[str, str] = {
    "layers": '<path d="M12 3 3 7.5l9 4.5 9-4.5z"/><path d="m3 12 9 4.5 9-4.5"/>'
    '<path d="m3 16.5 9 4.5 9-4.5"/>',
    "nodes": '<circle cx="6" cy="6" r="2.5"/><circle cx="18" cy="6" r="2.5"/>'
    '<circle cx="12" cy="18" r="2.5"/><path d="M8.5 6h7M7.2 8.3l3.6 7.4M16.8 8.3l-3.6 7.4"/>',
    "shield": '<path d="M12 3 19 6v5.2c0 4.4-2.9 8.1-7 9.8-4.1-1.7-7-5.4-7-9.8V6z"/>'
    '<path d="m9 12 2 2 4-4.2"/>',
    "ledger": '<rect x="5" y="3.5" width="14" height="17" rx="2"/>'
    '<path d="M9 8h6M9 12h6M9 16h3"/>',
    "arrow": '<path d="M5 12h14M13 6l6 6-6 6"/>',
    "chevron": '<path d="m6 9 6 6 6-6"/>',
    "menu": '<path d="M4 7h16M4 12h16M4 17h16"/>',
    "close": '<path d="M6 6l12 12M18 6 6 18"/>',
    "lock": '<rect x="5" y="10.5" width="14" height="10" rx="2"/><path d="M8 10.5V7.5a4 4 0 0 1 8 0v3"/>',
}


def icon(name: str, cls: str = "icon") -> str:
    return (
        f'<svg class="{cls}" viewBox="0 0 24 24" width="24" height="24" aria-hidden="true" '
        'focusable="false" fill="none" stroke="currentColor" stroke-width="1.6" '
        f'stroke-linecap="round" stroke-linejoin="round">{ICONS[name]}</svg>'
    )


def button(link: Link, variant: str = "primary", with_arrow: bool = False, extra: str = "") -> str:
    arrow = icon("arrow", "icon icon--sm") if with_arrow else ""
    cls = f"btn btn--{variant}" + (f" {extra}" if extra else "")
    return f'<a class="{cls}" href="{e(link.href)}"><span>{e(link.label)}</span>{arrow}</a>'


def section_head(kicker: str, title: str, title_id: str, intro: str | None = None) -> str:
    intro_html = f'<p class="section-head__intro">{e(intro)}</p>' if intro else ""
    return (
        '<div class="section-head">'
        f'<p class="kicker">{e(kicker)}</p>'
        f'<h2 id="{title_id}" class="section-title">{e(title)}</h2>'
        f"{intro_html}</div>"
    )


def anchor_aliases(site: SiteConfig, section_id: str) -> str:
    return "".join(
        f'<span id="{e(alias)}" class="anchor-alias" aria-hidden="true"></span>'
        for alias in site.anchor_aliases.get(section_id, ())
    )


# ---------------------------------------------------------------- chrome --

def utility_strip(site: SiteConfig) -> str:
    return (
        '<div class="utility">'
        '<div class="container utility__inner">'
        f'<p class="utility__label">{e(site.utility_label)}</p>'
        f'<p class="utility__tagline">{e(site.tagline)}</p>'
        "</div></div>"
    )


def mobile_navigation(site: SiteConfig) -> str:
    items = "".join(f'<li><a href="{e(n.href)}">{e(n.label)}</a></li>' for n in site.nav)
    return (
        '<div id="mobile-nav" class="mobile-nav" data-mobile-nav>'
        '<nav class="mobile-nav__panel" aria-label="Main">'
        f'<ul class="mobile-nav__list" role="list">{items}</ul>'
        f'{button(site.header_cta, "primary", with_arrow=True, extra="mobile-nav__cta")}'
        "</nav></div>"
    )


def site_header(site: SiteConfig) -> str:
    links = "".join(f'<li><a href="{e(n.href)}">{e(n.label)}</a></li>' for n in site.nav)
    return (
        '<header class="site-header" data-header>'
        '<div class="container">'
        '<div class="site-header__bar">'
        '<a class="brand" href="#top">'
        f'<img class="brand__mark" src="{e(site.monogram)}" width="40" height="40" alt="">'
        '<span class="brand__word">ClearGlass<span class="brand__inc">Inc.</span></span>'
        "</a>"
        '<nav class="site-nav" aria-label="Main">'
        f'<ul class="site-nav__list" role="list">{links}</ul>'
        "</nav>"
        f'{button(site.header_cta, "primary", extra="btn--sm header-cta")}'
        '<button class="menu-toggle" type="button" aria-expanded="false" '
        'aria-controls="mobile-nav" data-menu-toggle>'
        f'<span class="menu-toggle__icon menu-toggle__icon--open">{icon("menu")}</span>'
        f'<span class="menu-toggle__icon menu-toggle__icon--close">{icon("close")}</span>'
        '<span class="visually-hidden" data-menu-label>Open menu</span>'
        "</button>"
        "</div>"
        f"{mobile_navigation(site)}"
        "</div></header>"
    )


# ------------------------------------------------------------------ hero --

RADAR_SVG = (
    '<svg class="radar" viewBox="0 0 48 48" width="48" height="48" aria-hidden="true" focusable="false">'
    "<defs>"
    '<radialGradient id="radar-bg" cx=".5" cy=".5" r=".5">'
    '<stop offset="0" stop-color="#123038"/><stop offset="1" stop-color="#071216"/></radialGradient>'
    '<linearGradient id="radar-sweep" x1="0" y1="0" x2="1" y2="0">'
    '<stop offset="0" stop-color="#7ceeff" stop-opacity="0"/>'
    '<stop offset="1" stop-color="#7ceeff" stop-opacity=".55"/></linearGradient>'
    "</defs>"
    '<circle cx="24" cy="24" r="22.5" fill="url(#radar-bg)" stroke="#7ceeff" stroke-opacity=".55"/>'
    '<circle cx="24" cy="24" r="15" fill="none" stroke="#7ceeff" stroke-opacity=".28"/>'
    '<circle cx="24" cy="24" r="7.5" fill="none" stroke="#7ceeff" stroke-opacity=".28"/>'
    '<path d="M24 2v44M2 24h44" stroke="#7ceeff" stroke-opacity=".16"/>'
    '<g class="radar__sweep"><path d="M24 24V1.5A22.5 22.5 0 0 1 39.9 8.1z" fill="url(#radar-sweep)"/></g>'
    '<circle class="radar__blip" cx="31.5" cy="15" r="1.8" fill="#7ceeff"/>'
    '<circle cx="24" cy="24" r="2.2" fill="#7ceeff"/>'
    "</svg>"
)


def sentinel_core() -> str:
    """Radar-style status pill. A design demonstration, not a live monitor."""
    return (
        '<details class="sentinel" data-sentinel>'
        '<summary class="sentinel__bar">'
        f'<span class="sentinel__radar">{RADAR_SVG}</span>'
        '<span class="sentinel__text">'
        '<span class="sentinel__title">Sentinel Core</span>'
        '<span class="sentinel__status"><span class="sentinel__dot" aria-hidden="true"></span>'
        "Interface demo</span>"
        "</span>"
        f'<span class="sentinel__chevron">{icon("chevron")}</span>'
        "</summary>"
        '<div class="sentinel__panel">'
        "<p>Sentinel Core is a design demonstration of a status interface. It is not "
        "connected to any system, monitors nothing, and shows no live data.</p>"
        '<dl class="sentinel__readout">'
        "<div><dt>Mode</dt><dd>Demonstration</dd></div>"
        "<div><dt>Data source</dt><dd>None</dd></div>"
        "<div><dt>Monitoring</dt><dd>Not active</dd></div>"
        "</dl></div></details>"
    )


def brand_medallion(site: SiteConfig, size: int = 132) -> str:
    return (
        '<div class="medallion" aria-hidden="true">'
        f'<img src="{e(site.monogram)}" width="{size}" height="{size}" alt="" decoding="async">'
        "</div>"
    )


def hero_picture(site: SiteConfig) -> str:
    img = site.hero_image
    srcset = ", ".join(f"{e(path)} {width}w" for path, width in img.webp_sources)
    sizes = "(min-width: 1024px) 52vw, (min-width: 768px) 88vw, 100vw"
    return (
        "<picture>"
        f'<source type="image/webp" srcset="{srcset}" sizes="{sizes}">'
        f'<img class="hero__img" src="{e(img.fallback)}" width="{img.width}" height="{img.height}" '
        f'alt="{e(img.alt)}" fetchpriority="high" decoding="async">'
        "</picture>"
    )


def hero_section(site: SiteConfig) -> str:
    first, *rest = site.headline
    rest_html = "".join(f' <span class="hero__title-accent">{e(line)}</span>' for line in rest)
    return (
        '<section class="hero" aria-labelledby="hero-title">'
        '<div class="container hero__grid">'
        '<div class="hero__copy">'
        f'<p class="eyebrow">{e(site.eyebrow)}</p>'
        f'<h1 id="hero-title" class="hero__title"><span class="hero__brand">{e(site.headline_brand)}</span> '
        f'<span>{e(first)}</span>{rest_html}</h1>'
        f'<p class="hero__lede">{e(site.supporting)}</p>'
        '<div class="hero__actions">'
        f'{button(site.primary_cta, "primary", with_arrow=True)}'
        f'{button(site.secondary_cta, "ghost")}'
        "</div></div>"
        '<div class="hero__visual">'
        '<div class="hero__frame">'
        f"{hero_picture(site)}"
        '<span class="hero__scan" aria-hidden="true"></span>'
        "</div>"
        f"{brand_medallion(site)}"
        "</div>"
        f'<div class="hero__sentinel">{sentinel_core()}</div>'
        "</div></section>"
    )


# -------------------------------------------------------------- sections --

def capability_card(cap: Capability) -> str:
    points = "".join(f"<li>{e(p)}</li>" for p in cap.points)
    return (
        f'<article class="card capability" aria-labelledby="cap-{e(cap.id)}">'
        f'<span class="capability__icon">{icon(cap.icon)}</span>'
        f'<h3 id="cap-{e(cap.id)}" class="card__title">{e(cap.title)}</h3>'
        f'<p class="card__text">{e(cap.summary)}</p>'
        f'<ul class="ticks" role="list">{points}</ul>'
        "</article>"
    )


def capabilities_section(site: SiteConfig) -> str:
    cards = "".join(capability_card(c) for c in site.capabilities)
    return (
        '<section id="capabilities" class="section" aria-labelledby="capabilities-title">'
        f'{anchor_aliases(site, "capabilities")}'
        '<div class="container">'
        f'{section_head("Capabilities", "What ClearGlass works on", "capabilities-title", site.capabilities_intro)}'
        f'<div class="capabilities">{cards}</div>'
        "</div></section>"
    )


def process_step(step: ProcessStep) -> str:
    return (
        '<li class="process__step">'
        f'<span class="process__num" aria-hidden="true">{e(step.number)}</span>'
        f'<h3 class="card__title">{e(step.title)}</h3>'
        f'<p class="card__text">{e(step.summary)}</p>'
        f'<p class="process__output"><span class="label">Output</span>{e(step.output)}</p>'
        "</li>"
    )


def process_section(site: SiteConfig) -> str:
    steps = "".join(process_step(s) for s in site.process)
    return (
        '<section id="approach" class="section section--tinted" aria-labelledby="approach-title">'
        '<div class="container">'
        f'{section_head("Approach", "How an engagement runs", "approach-title", site.process_intro)}'
        f'<ol class="process">{steps}</ol>'
        "</div></section>"
    )


def article_card(article: Article) -> str:
    published = date.fromisoformat(article.published)
    label = f"{published:%B} {published.day}, {published.year}"
    return (
        '<article class="card article-card">'
        f'<p class="article-card__meta"><span>{e(article.topic)}</span>'
        f'<time datetime="{published.isoformat()}">{label}</time></p>'
        f'<h3 class="card__title"><a class="article-card__link" href="{e(article.href)}">'
        f"{e(article.title)}</a></h3>"
        f'<p class="card__text">{e(article.summary)}</p>'
        "</article>"
    )


def insights_section(site: SiteConfig) -> str:
    if site.articles:
        body = '<div class="articles">' + "".join(article_card(a) for a in site.articles) + "</div>"
    else:
        body = (
            '<div class="empty-state">'
            f'<img class="empty-state__mark" src="{e(site.monogram)}" width="56" height="56" alt="">'
            '<p class="empty-state__title">No articles published yet</p>'
            '<p class="empty-state__text">Articles will be listed here once they are '
            "written and reviewed.</p></div>"
        )
    return (
        '<section id="insights" class="section" aria-labelledby="insights-title">'
        '<div class="container">'
        f'{section_head("Insights", "Insights", "insights-title", site.insights_intro)}'
        f"{body}</div></section>"
    )


def people_list(people: tuple[Person, ...]) -> str:
    if not people:
        return ""
    items = "".join(
        '<li class="person">'
        f'<p class="person__name">{e(p.name)}</p>'
        f'<p class="person__role">{e(p.role)}</p>'
        f'<p class="card__text">{e(p.bio)}</p></li>'
        for p in people
    )
    return f'<h3 class="subhead">Leadership</h3><ul class="people" role="list">{items}</ul>'


def about_section(site: SiteConfig) -> str:
    paragraphs = "".join(f'<p class="prose">{e(p)}</p>' for p in site.about)
    location = (
        f'<p class="about__location"><span class="label">Based in</span>{e(site.location)}</p>'
        if site.location
        else ""
    )
    principles = "".join(
        f"<li><p class=\"principle__title\">{e(t)}</p><p class=\"card__text\">{e(d)}</p></li>"
        for t, d in site.principles
    )
    return (
        '<section id="about" class="section section--tinted" aria-labelledby="about-title">'
        f'{anchor_aliases(site, "about")}'
        '<div class="container about">'
        '<div class="about__text">'
        f'{section_head("About", "About ClearGlass Inc.", "about-title")}'
        f"{paragraphs}{location}{people_list(site.people)}"
        "</div>"
        '<aside class="card about__principles" aria-labelledby="principles-title">'
        '<h3 id="principles-title" class="card__title">Working principles</h3>'
        f'<ul class="principles" role="list">{principles}</ul>'
        f'<p class="about__tagline">{e(site.tagline)}</p>'
        "</aside></div></section>"
    )


def _field(field_id: str, label: str, control: str, hint: str = "") -> str:
    hint_html = f'<span class="field__hint">{e(hint)}</span>' if hint else ""
    return (
        f'<div class="field"><label class="field__label" for="{field_id}">{e(label)}{hint_html}</label>'
        f"{control}</div>"
    )


def contact_form(contact: Contact) -> str:
    configured = bool(contact.form_endpoint)
    fields = (
        _field("cf-name", "Name", '<input id="cf-name" name="name" type="text" autocomplete="name" required>')
        + _field(
            "cf-email",
            "Email",
            '<input id="cf-email" name="email" type="email" autocomplete="email" required>',
        )
        + _field(
            "cf-org",
            "Organization",
            '<input id="cf-org" name="organization" type="text" autocomplete="organization">',
            "Optional",
        )
        + _field(
            "cf-message",
            "Project details",
            '<textarea id="cf-message" name="message" rows="5" required></textarea>',
        )
    )
    if configured:
        honeypot = (
            '<div class="visually-hidden" aria-hidden="true"><label>Leave this field empty'
            '<input type="text" name="_gotcha" tabindex="-1" autocomplete="off"></label></div>'
        )
        endpoint = e(contact.form_endpoint or "")
        return (
            f'<form class="card contact-form" action="{endpoint}" method="post" '
            f'data-contact-form data-endpoint="{endpoint}">'
            '<fieldset class="contact-form__fields"><legend class="visually-hidden">Project enquiry</legend>'
            f"{fields}{honeypot}"
            '<button class="btn btn--primary" type="submit"><span>Send enquiry</span></button>'
            "</fieldset>"
            '<p class="form-status" role="status" aria-live="polite" data-form-status></p>'
            "</form>"
        )
    return (
        '<form class="card contact-form contact-form--off" aria-describedby="contact-notice" data-contact-form>'
        '<div id="contact-notice" class="notice">'
        f'{icon("lock", "icon notice__icon")}'
        "<p><strong>Online submission is not set up yet.</strong> This form is switched off, "
        "so nothing typed here can be sent.</p></div>"
        '<fieldset class="contact-form__fields" disabled><legend class="visually-hidden">Project enquiry</legend>'
        f"{fields}"
        '<button class="btn btn--primary" type="submit"><span>Send enquiry</span></button>'
        "</fieldset></form>"
    )


def contact_section(site: SiteConfig) -> str:
    if site.contact.email:
        email = e(site.contact.email)
        direct = (
            '<p class="contact__direct"><span class="label">Email</span>'
            f'<a href="mailto:{email}">{email}</a></p>'
        )
    else:
        direct = (
            '<p class="contact__direct contact__direct--pending">A direct contact address '
            "will be published here once it is confirmed.</p>"
        )
    return (
        '<section id="contact" class="section" aria-labelledby="contact-title">'
        '<div class="container contact">'
        '<div class="contact__intro">'
        f'{section_head("Contact", "Discuss a project", "contact-title", site.contact_intro)}'
        f"{direct}</div>"
        f"{contact_form(site.contact)}"
        "</div></section>"
    )


def site_footer(site: SiteConfig, year: int) -> str:
    nav = "".join(f'<li><a href="{e(n.href)}">{e(n.label)}</a></li>' for n in site.nav)
    extra = ""
    for label, links in (("Explore", site.explore), ("Social", site.socials), ("Legal", site.legal)):
        if links:
            items = "".join(f'<li><a href="{e(lk.href)}">{e(lk.label)}</a></li>' for lk in links)
            extra += f'<nav class="footer__nav footer__nav--extra" aria-label="{label}"><ul role="list">{items}</ul></nav>'
    return (
        '<footer class="site-footer">'
        '<div class="container footer__grid">'
        '<div class="footer__brand">'
        f'<img src="{e(site.monogram)}" width="44" height="44" alt="" decoding="async">'
        f'<div><p class="footer__name">{e(site.name)}</p>'
        f'<p class="footer__tagline">{e(site.tagline)}</p></div></div>'
        f'<nav class="footer__nav" aria-label="Footer"><ul role="list">{nav}</ul></nav>'
        f"{extra}</div>"
        '<div class="container footer__base">'
        f'<p>&copy; <span data-year>{year}</span> {e(site.name)} All rights reserved.</p>'
        '<a href="#top">Back to top</a>'
        "</div></footer>"
    )


# -------------------------------------------------------------- document --

def head(site: SiteConfig) -> str:
    url = site.url.rstrip("/") + "/"
    og_image = url + site.og_image
    hero = site.hero_image
    srcset = ", ".join(f"{path} {width}w" for path, width in hero.webp_sources)
    website_id, org_id, page_id = url + "#website", url + "#organization", url + "#webpage"
    website = {"@type": "WebSite", "@id": website_id, "name": site.name, "url": url,
               "inLanguage": "en-CA", "publisher": {"@id": org_id}}
    if site.alternate_name:
        website["alternateName"] = site.alternate_name
    graph = {
        "@context": "https://schema.org",
        "@graph": [
            website,
            {
                "@type": "Organization",
                "@id": org_id,
                "name": site.name,
                "url": url,
                # The monogram shown in the header, footer and hero (512x512 PNG).
                "logo": {"@type": "ImageObject", "url": url + "assets/site/img/icon-512.png",
                         "width": 512, "height": 512},
                "slogan": site.tagline,
            },
            {
                "@type": "WebPage",
                "@id": page_id,
                "url": url,
                "name": site.meta_title,
                "description": site.meta_description,
                "inLanguage": "en-CA",
                "isPartOf": {"@id": website_id},
                "about": {"@id": org_id},
            },
        ],
    }
    # "</" cannot appear inside a <script> element; escape it in the JSON text.
    jsonld = json.dumps(graph, ensure_ascii=False).replace("</", "<\\/")
    fonts = (
        "assets/site/fonts/cormorant-garamond-latin-500-normal.woff2",
        "assets/site/fonts/urbanist-latin-wght-normal.woff2",
    )
    preload_fonts = "".join(
        f'<link rel="preload" href="{f}" as="font" type="font/woff2" crossorigin>' for f in fonts
    )
    return (
        "<head>"
        '<meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">'
        f"<title>{e(site.meta_title)}</title>"
        f'<meta name="description" content="{e(site.meta_description)}">'
        f'<link rel="canonical" href="{e(url)}">'
        f'<meta name="theme-color" content="{e(site.theme_color)}">'
        '<meta name="color-scheme" content="dark">'
        f'<link rel="icon" href="{e(site.monogram)}" type="image/svg+xml">'
        '<link rel="icon" href="assets/site/img/icon-32.png" sizes="32x32" type="image/png">'
        '<link rel="apple-touch-icon" href="assets/site/img/icon-180.png">'
        '<link rel="sitemap" type="application/xml" href="sitemap.xml">'
        '<meta property="og:type" content="website">'
        f'<meta property="og:site_name" content="{e(site.name)}">'
        f'<meta property="og:title" content="{e(site.meta_title)}">'
        f'<meta property="og:description" content="{e(site.meta_description)}">'
        f'<meta property="og:url" content="{e(url)}">'
        f'<meta property="og:image" content="{e(og_image)}">'
        '<meta property="og:image:width" content="1200">'
        '<meta property="og:image:height" content="630">'
        f'<meta property="og:image:alt" content="{e(site.name)} — {e(" ".join(site.headline))}">'
        '<meta property="og:locale" content="en_CA">'
        '<meta name="twitter:card" content="summary_large_image">'
        f'<meta name="twitter:title" content="{e(site.meta_title)}">'
        f'<meta name="twitter:description" content="{e(site.meta_description)}">'
        f'<meta name="twitter:image" content="{e(og_image)}">'
        f"{preload_fonts}"
        f'<link rel="preload" as="image" type="image/webp" imagesrcset="{e(srcset)}" '
        'imagesizes="(min-width: 1024px) 52vw, (min-width: 768px) 88vw, 100vw" fetchpriority="high">'
        '<link rel="stylesheet" href="assets/site/css/clearglass.css">'
        "<script>document.documentElement.classList.replace('no-js','js')</script>"
        '<script defer src="assets/site/js/clearglass.js"></script>'
        f'<script type="application/ld+json">{jsonld}</script>'
        "</head>"
    )


def page(site: SiteConfig, year: int) -> str:
    return (
        "<!DOCTYPE html>\n"
        "<!-- Generated by website/build.py from website/site_config.py. "
        "Do not edit by hand: edit the config and rebuild. -->\n"
        '<html lang="en-CA" class="no-js">'
        f"{head(site)}"
        '<body id="top">'
        '<a class="skip-link" href="#main">Skip to main content</a>'
        '<div class="backdrop" aria-hidden="true"></div>'
        f"{utility_strip(site)}"
        f"{site_header(site)}"
        '<main id="main" tabindex="-1">'
        f"{hero_section(site)}"
        f"{capabilities_section(site)}"
        f"{process_section(site)}"
        f"{insights_section(site)}"
        f"{about_section(site)}"
        f"{contact_section(site)}"
        "</main>"
        f"{site_footer(site, year)}"
        "</body></html>\n"
    )
