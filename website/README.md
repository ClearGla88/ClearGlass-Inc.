# ClearGlass Inc. homepage

The homepage (`index.html` at the repository root) is a static page generated
from one typed content file. GitHub Pages serves it directly, so there is no
framework, bundler, server or API key involved.

```
website/
  site_config.py           all copy, links and optional details (edit this)
  components.py            reusable components: SiteHeader, MobileNavigation,
                           SentinelCore, HeroSection, BrandMedallion,
                           CapabilityCard, ProcessSection, InsightsSection,
                           AboutSection, ContactSection, SiteFooter
  build.py                 renders index.html; --check fails if it is stale
  render_brand_images.mjs  optional: re-renders icons and the social card
assets/site/
  css/clearglass.css       design tokens and all component styles
  js/clearglass.js         mobile menu, form submission, sticky header, year
  fonts/                   self-hosted fonts and their SIL OFL 1.1 licences
  img/                     skyline (WebP + JPEG), monogram.svg, icons, og-card.png
tests/test_homepage.py     contract tests (run by Baseline CI's pytest job)
tests/browser/homepage-audit.mjs   browser audit at six widths (run manually)
```

## Requirements

- Python 3.10 or later (standard library only) to build.
- Optional: Node 20+ with Playwright and Chromium, for the browser audit and
  for re-rendering the icon and social-card PNGs.

## Develop

```bash
python3 website/build.py                      # regenerate index.html
python3 -m http.server 8765 --bind 127.0.0.1  # from the repository root
# open http://127.0.0.1:8765/
```

Edit `website/site_config.py` (content) or `assets/site/css/clearglass.css`
(styling), rebuild, and reload. Never edit `index.html` by hand; the next
build overwrites it, and `tests/test_homepage.py` fails while it is stale.

## Check

```bash
python3 website/build.py --check              # index.html matches the config
python3 -m pytest tests/test_homepage.py -q   # contract tests
python3 tools/repo_hygiene.py                 # repository hygiene gate
python3 tools/validate_seo.py                 # robots.txt, sitemaps, homepage indexing tags

# Browser audit (server running as above). AXE is optional: point it at
# axe-core's axe.min.js to add automated WCAG A/AA rules.
AXE=/path/to/axe.min.js node tests/browser/homepage-audit.mjs /tmp/shots
```

The audit loads the page at 320, 375, 390, 768, 1024 and 1440 px and fails on:
horizontal scrolling, elements past the viewport edge, clipped text, controls
smaller than 24 px, the header covering the headline or a section heading,
broken anchors, heading-level skips, and images without `alt` or dimensions.
It also drives the mobile menu by keyboard (focus moves in, Tab stays inside,
Escape closes and returns focus), toggles Sentinel Core with Enter and Space,
confirms reduced motion stops all animation, and loads the page with
JavaScript off. Pass a directory to save screenshots.

## Deploy

Merging to `main` deploys through the existing
`.github/workflows/jekyll-gh-pages.yml`. Nothing else needs configuring. The
canonical URL comes from `site.url`, which `build.py` requires to match
`CNAME` (`www.clearglassinc.com`).

## Configuration

Everything below lives in `website/site_config.py`. Empty values are
deliberate: the page says an item is not available yet instead of
inventing one.

| Setting | Default | Effect |
|---|---|---|
| `contact.form_endpoint` | `None` | Form is shown switched off, with a notice that submission is not set up. Set an `https://` endpoint that accepts a POST (for example a Formspree form URL) to enable it. |
| `contact.email` | `None` | No email link anywhere. Set a confirmed, working inbox to show it in Contact. |
| `people` | empty | No leadership block. Add `Person(name, role, bio)` entries to show one in About. |
| `articles` | empty | Insights shows "No articles published yet". Add `Article(...)` only when the page at `href` exists; `build.py` refuses a local link to a missing file. |
| `socials`, `legal` | empty | No social or legal links in the footer. Add `Link(label, href)` entries once the destinations exist. |
| `explore` | 4 existing pages | Footer links to other public pages. `build.py` refuses a page that is missing or is not a canonical URL in `sitemap.xml`. |
| `location` | `"Ontario, Canada"` | The "Based in" line in About. Set to `None` to hide it. |
| `hero_image` | supplied skyline | Swap the files and `alt` text to replace the hero picture. Keep the 3:2 ratio or update `width`/`height`. |

### Enabling the contact form

1. Create a form with a form-handling service and copy its POST URL.
2. Set `contact=Contact(email=..., form_endpoint="https://...")` and rebuild.
3. If the site is ever served by a host that applies `_headers`, make sure the
   endpoint's host is listed in that file's `form-action` directive
   (Formspree and FormSubmit already are). GitHub Pages ignores `_headers`.
4. Send a real test message and confirm it arrives.

`assets/site/js/clearglass.js` reports success only on a 2xx response from
the endpoint, and an error otherwise. Without JavaScript, the browser posts
the form to the endpoint directly. Spam protection is a hidden `_gotcha`
field (Formspree's honeypot name).

### Re-rendering brand images

```bash
node website/render_brand_images.mjs   # from the repository root
```

This writes `icon-32.png`, `icon-180.png`, `icon-512.png` and `og-card.png`
from `monogram.svg` and the bundled fonts. Run it after changing the monogram
or the headline.

## Content rules

- The copy describes service areas and a proposed way of working. It is not a
  record of completed work.
- Do not add clients, testimonials, certifications, partnerships, awards,
  metrics, guarantees or government affiliation without evidence. Several of
  these are gated by `tests/test_homepage.py`.
- Sentinel Core is a labelled interface demonstration. It is not connected to
  anything; keep the wording that says so.
- The monogram is an original geometric mark. Do not replace it with an
  official seal or government-style insignia.

## Assets and licences

- Skyline: the owner-supplied image `20260203_224147843_iOS.png`, resized to
  WebP (640, 1024, 1536 px) and a 1024 px JPEG fallback.
- Fonts: Cormorant Garamond, Urbanist and IBM Plex Mono from Fontsource
  5.2.6, SIL Open Font License 1.1 (licence files in `assets/site/fonts/`).
- Monogram, icons and social card: original to this repository.
