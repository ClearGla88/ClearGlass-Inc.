/* ClearGlass · platform layer — progressive enhancement with real, shipping
   browser technology. Drop in with <script defer src="platform.js"></script>.

     1) PWA: registers the service worker (offline shell + fast repeat visits)
        and injects the web-app manifest link where a page lacks it, making the
        site installable.
     2) Instant navigation: injects a Speculation Rules script so Chromium
        prefetches (and prerenders on hover) same-origin pages — typical
        click→render drops to near-zero. Other engines ignore it harmlessly.
     3) Cross-document View Transitions: opts the site into smooth page-to-page
        fades (Chromium 126+), disabled under prefers-reduced-motion.

   Everything is feature-detected; on unsupported browsers this file is inert. */
(function () {
  "use strict";
  if (window.__cgPlatform) return;
  window.__cgPlatform = true;

  var platformBase = (document.currentScript && document.currentScript.src) || location.href;
  function platformAsset(name) {
    try { return new URL(name, platformBase).href; }
    catch (e) { return name; }
  }

  /* The homepage already owns its navigation, Artemis instrumentation,
     Sentinel surface and unified assistant fixture. Do not mount additional
     global fixed-control runtimes there: FX adds fixed scroll controls and
     AEGIS-OMEGA adds fixed telemetry plus a second full-screen command layer.
     Those systems remain available everywhere else. The canonical check keeps
     this isolation correct on custom-domain and GitHub Pages preview routes. */
  var normalizedPath = (location.pathname || "/").replace(/\/+$/, "") || "/";
  var canonical = document.querySelector('link[rel="canonical"]');
  var canonicalHref = canonical ? canonical.href : "";
  var isHomepage = normalizedPath === "/" ||
    /\/index\.html$/i.test(normalizedPath) ||
    canonicalHref === "https://www.clearglassinc.com/";
  if (isHomepage) {
    document.documentElement.setAttribute("data-cg-home-runtime", "stabilized");
  }

  /* Homepage cinematic fail-static gate.
     Do not merely ask the motion runtime to reduce itself on constrained
     touch-first devices: WebKit can still pay the DOM/GPU initialization cost
     before that downgrade takes effect. Claim the cinematic runtime here,
     before either platform.js or future-buttons.js can mount it, while loading
     the stylesheet so its cg-low-power rules also stop decorative CSS motion.
     This is capability-based rather than user-agent based and also honours
     reduced-motion and Save-Data. */
  var staticCinematicHomepage = false;
  if (isHomepage) {
    var touchFirstSmall = false;
    var saveData = false;
    var reducedMotion = false;
    try {
      touchFirstSmall = window.matchMedia("(hover: none) and (pointer: coarse)").matches &&
        window.innerWidth <= 820;
    } catch (e) {}
    try { saveData = !!(navigator.connection && navigator.connection.saveData); } catch (e) {}
    try { reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches; } catch (e) {}

    staticCinematicHomepage = touchFirstSmall || saveData || reducedMotion;
    if (staticCinematicHomepage) {
      document.documentElement.classList.add("cg-low-power", "cg-motion-reduced");
      document.documentElement.setAttribute("data-cg-performance", "reduced");
      document.documentElement.setAttribute("data-cg-motion-level", "minimal");
      document.documentElement.setAttribute("data-cg-cinematic-motion", "static-capability");
      /* future-buttons.js uses this same ownership flag before loading the
         cinematic script, so one early claim protects both loader paths. */
      window.__cgCinematicMotion = true;
    }
  }

  /* Global navigation search: additive, non-fixed progressive enhancement.
     The runtime attaches only when an existing primary nav is present, indexes
     same-origin public pages lazily, and fails closed without changing routes. */
  if (!document.querySelector('script[data-cg-global-nav-search="true"]')) {
    var navSearch = document.createElement("script");
    navSearch.src = platformAsset("global-nav-search.js");
    navSearch.defer = true;
    navSearch.setAttribute("data-cg-global-nav-search", "true");
    navSearch.addEventListener("error", function () {
      document.documentElement.setAttribute("data-cg-nav-search", "degraded");
    }, { once: true });
    document.body.appendChild(navSearch);
  }

  /* Homepage editorial showcase: intentionally content-only and non-fixed.
     It reads the existing Insights post index, mounts before the timeline,
     and fails closed so editorial enhancement can never destabilize the page. */
  if (isHomepage && !document.querySelector('script[data-cg-home-insights="true"]')) {
    var homeInsights = document.createElement("script");
    homeInsights.src = platformAsset("homepage-insights.js");
    homeInsights.async = true;
    homeInsights.setAttribute("data-cg-home-insights", "true");
    homeInsights.addEventListener("error", function () {
      document.documentElement.setAttribute("data-cg-home-insights", "degraded");
    }, { once: true });
    document.body.appendChild(homeInsights);
  }

  /* The Sentinel dialog exists in homepage markup with aria-modal="true" even
     while its parent shell is hidden. The unified assistant intentionally hides
     whenever a real modal is active, so synchronize aria-modal with the shell's
     actual hidden state. This prevents a hidden dialog from suppressing the
     bottom-right control station and avoids stale overlay state on open/close. */
  if (isHomepage) {
    var sentinelShell = document.getElementById("sentinelShell");
    var sentinelDialog = sentinelShell && sentinelShell.querySelector('[role="dialog"]');
    if (sentinelShell && sentinelDialog) {
      var syncSentinelModalState = function () {
        var open = !sentinelShell.hidden;
        sentinelDialog.setAttribute("aria-modal", String(open));
        sentinelShell.setAttribute("aria-hidden", String(!open));
      };
      syncSentinelModalState();
      if ("MutationObserver" in window) {
        new MutationObserver(syncSentinelModalState).observe(sentinelShell, {
          attributes: true,
          attributeFilter: ["hidden"]
        });
      }
    }
  }

  /* ── 1) PWA: manifest link + service worker ─────────────────────────────── */
  if (!document.querySelector('link[rel="manifest"]')) {
    var mf = document.createElement("link");
    mf.rel = "manifest";
    mf.href = "manifest.webmanifest";
    document.head.appendChild(mf);
  }
  if (!document.querySelector('meta[name="theme-color"]')) {
    var tc = document.createElement("meta");
    tc.name = "theme-color";
    tc.content = "#0b0f1e";
    document.head.appendChild(tc);
  }
  function addLink(sel, attrs) {
    if (document.querySelector(sel)) return;
    var l = document.createElement("link");
    Object.keys(attrs).forEach(function (k) { l.setAttribute(k, attrs[k]); });
    document.head.appendChild(l);
  }
  addLink('link[rel="icon"][type="image/svg+xml"]', { rel: "icon", type: "image/svg+xml", href: "icon.svg" });
  addLink('link[rel="apple-touch-icon"]', { rel: "apple-touch-icon", href: "logo.png" });

  /* ── advanced motion layer (fx.css + fx.js) — progressive enhancement ─────
     The homepage intentionally skips this layer because its fixed top/bottom
     buttons duplicate the unified control station and can stack during boot. */
  if (!isHomepage) {
    addLink('link[href="fx.css"]', { rel: "stylesheet", href: "fx.css" });
    if (!document.querySelector('script[src="fx.js"]')) {
      var fx = document.createElement("script");
      fx.src = "fx.js"; fx.defer = true;
      document.body.appendChild(fx);
    }
  }

  /* ── cinematic system: purpose-driven hero + motion hierarchy ─────────────
     Desktop-capable devices keep the cinematic runtime. Constrained homepage
     devices remain static before the script is mounted, eliminating the WebKit
     renderer/GPU initialization path that can terminate the page process. */
  addLink('link[href="/assets/css/cinematic-motion.css"]', {
    rel: "stylesheet",
    href: "/assets/css/cinematic-motion.css"
  });
  if (!staticCinematicHomepage && !document.querySelector('script[src="/assets/js/cinematic-motion.js"]')) {
    var cinematic = document.createElement("script");
    cinematic.src = "/assets/js/cinematic-motion.js";
    cinematic.defer = true;
    document.body.appendChild(cinematic);
  }

  /* ── AEGIS-OMEGA control plane: fault-contained progressive enhancement ──
     Skip on the homepage: it appends a second fixed telemetry rail and a
     second full-screen command-palette surface. Those are redundant with the
     homepage's existing Sentinel/unified assistant controls. */
  if (!isHomepage) {
    var omegaCss = platformAsset("aegis-omega.css");
    var omegaJs = platformAsset("aegis-omega.js");
    addLink('link[data-cg-aegis-omega="true"]', {
      rel: "stylesheet",
      href: omegaCss,
      "data-cg-aegis-omega": "true"
    });
    if (!document.querySelector('script[data-cg-aegis-omega="true"]')) {
      var omega = document.createElement("script");
      omega.src = omegaJs;
      omega.defer = true;
      omega.setAttribute("data-cg-aegis-omega", "true");
      omega.addEventListener("error", function () {
        document.documentElement.setAttribute("data-aegis-omega", "degraded");
      }, { once: true });
      document.body.appendChild(omega);
    }
  }

  if ("serviceWorker" in navigator) {
    window.addEventListener("load", function () {
      navigator.serviceWorker.register("sw.js").catch(function () {});
    });
  }

  /* ── 2) instant navigation: Speculation Rules (Chromium) ────────────────── */
  try {
    if (HTMLScriptElement.supports && HTMLScriptElement.supports("speculationrules")) {
      var rules = document.createElement("script");
      rules.type = "speculationrules";
      rules.textContent = JSON.stringify({
        prefetch: [{ where: { href_matches: "/*" }, eagerness: "moderate" }],
        prerender: [{ where: { href_matches: "/*" }, eagerness: "moderate" }]
      });
      document.head.appendChild(rules);
    }
  } catch (e) {}

  /* ── 3) cross-document view transitions (motion-pref aware) ─────────────── */
  try {
    var reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (!reduce) {
      var st = document.createElement("style");
      st.textContent = "@view-transition{navigation:auto}" +
        "::view-transition-old(root),::view-transition-new(root){animation-duration:.22s}";
      document.head.appendChild(st);
    }
  } catch (e) {}

  /* ── 4) founder profile link ─────────────────────────────────────────────── */
  var founderActions = document.querySelector("#founder .founder-actions");
  if (founderActions && !founderActions.querySelector('a[data-founder-linkedin]')) {
    var linkedin = document.createElement("a");
    linkedin.href = "https://www.linkedin.com/in/desmondotieno?utm_source=share_via&utm_content=profile&utm_medium=member_ios";
    linkedin.className = "btn btn-glass";
    linkedin.target = "_blank";
    linkedin.rel = "noopener noreferrer me";
    linkedin.setAttribute("data-founder-linkedin", "true");
    linkedin.setAttribute("aria-label", "View Desmond Otieno Odhiambo on LinkedIn");
    linkedin.textContent = "LinkedIn Profile ↗";
    founderActions.appendChild(linkedin);
  }

  /* ── 5) pricing catalogue parity for newly published strategic offers ───── */
  var plans = document.querySelector("#plans.grid");
  if (plans && !plans.querySelector('[data-sku="critical-minerals-compliance"]')) {
    var critical = document.createElement("article");
    critical.className = "plan feat";
    critical.setAttribute("data-reveal", "");
    critical.setAttribute("data-tilt", "5");
    critical.setAttribute("data-sku", "critical-minerals-compliance");
    critical.innerHTML =
      '<span class="tag">Strategic operations · new</span>' +
      '<h3>Critical Minerals Compliance Strategy</h3>' +
      '<div class="blurb">Compliance-first civilian strategy for critical minerals, strategic materials and lawful dual-use supply chains.</div>' +
      '<div class="price">CAD&nbsp;$1,499<span class="u">one-time</span></div>' +
      '<ul class="feats">' +
        '<li><span class="ck">✓</span> Classification, sanctions and licensing triage</li>' +
        '<li><span class="ck">✓</span> Provenance and traceability architecture</li>' +
        '<li><span class="ck">✓</span> Risk register and mitigation ownership</li>' +
        '<li><span class="ck">✓</span> Ranked go/no-go opportunity matrix</li>' +
      '</ul>' +
      '<div class="cta"><a class="cg-btn cg-btn--primary cg-btn--block" href="https://book.stripe.com/fZu3cwcfWb1jgKoeCw4Ni08" rel="noopener">Secure checkout →</a>' +
      '<div class="paynote">🔒 Stripe · encrypted card payment</div></div>';
    plans.appendChild(critical);
  }

  /* Restore the explicit payment-safety promise if a compact storefront build
     omitted the older trust copy. This is customer-facing, not a hidden check. */
  if (/\/store(?:\.html)?$/.test(location.pathname) && !document.querySelector("[data-payment-safety]")) {
    var main = document.querySelector("main");
    if (main) {
      var safety = document.createElement("p");
      safety.setAttribute("data-payment-safety", "true");
      safety.className = "note";
      safety.textContent = "Nothing is auto-charged or auto-sent. Payments occur only when you explicitly choose and complete a checkout, e-Transfer, or approved invoice.";
      main.appendChild(safety);
    }
  }
})();