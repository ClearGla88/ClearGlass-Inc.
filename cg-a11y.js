/* ClearGlass · shared accessibility contract.
   ────────────────────────────────────────────────────────────────────────────
   The site runs two navigation systems: nav.js (the glass top bar) and
   control-surface.js (the command cluster, which deliberately sets
   __cgNavLoaded to supersede nav.js on ~35 pages). Both are legitimate, but the
   keyboard contract must not depend on which one a page happens to load, so the
   guarantees every page owes a keyboard or screen-reader user live here:

     1. a bypass link ("Skip to main content") as the first tab stop, resolved
        to a real target even on pages authored without <main>, and
     2. aria-current="page" on the active destination in whatever nav exists.

   Everything is idempotent and additive: on a nav.js page the skip link is
   already present and this module leaves it alone. Load order does not matter —
   the nav is often injected after this script runs, so active-route marking is
   retried through a MutationObserver with a bounded lifetime.

   Drop in with <script defer src="/cg-a11y.js"></script>. No dependencies. */
(function () {
  "use strict";
  if (window.__cgA11y) return;
  window.__cgA11y = true;

  var here = (location.pathname.split("/").pop() || "index.html").toLowerCase();

  /* ── skip-link target ───────────────────────────────────────────────────
     39 of the older pages were authored without <main>, leaving the bypass link
     with nothing to aim at. We resolve a target for it, but deliberately do NOT
     invent a landmark: the outermost block holding the <h1> is often just the
     hero (`<header class="hero">`), and labelling a partial region role="main"
     would mislead landmark navigation more than the missing role does. Those
     pages are tracked in DESIGN_SYSTEM_AUDIT.md as a markup follow-up; the
     bypass link below satisfies WCAG 2.4.1 in the meantime. */
  var CHROME = "nav, [role='banner'], [role='navigation'], .cg-topnav, .cg-mobile, " +
               "#cg-global-nav, #cg-mobile-nav, .cgcs-bar, .cgcs-menu";

  function skipTarget() {
    var existing = document.querySelector("main, [role='main']");
    if (existing) return existing;

    var h1 = document.querySelector("h1");
    if (!h1) return null;

    // Prefer the outermost block still inside <body> so the jump clears the
    // whole chrome, but never hand back the chrome itself.
    var node = h1;
    while (node.parentElement && node.parentElement !== document.body) {
      node = node.parentElement;
    }
    if (node.matches(CHROME) || node.closest(CHROME)) return h1;
    return node;
  }

  function installSkipLink() {
    if (document.querySelector(".cg-skip")) return; // nav.js already placed one
    var target = skipTarget();
    if (!target) return;
    if (!target.id) target.id = "cg-main";
    if (!target.hasAttribute("tabindex")) target.setAttribute("tabindex", "-1");

    var style = document.createElement("style");
    style.textContent =
      ".cg-skip{position:fixed;top:8px;left:50%;transform:translate(-50%,-160%);" +
      "z-index:2147483600;padding:12px 20px;border-radius:14px;background:#0a0c10;" +
      "color:#fff;font-family:Urbanist,Inter,system-ui,sans-serif;font-size:15px;" +
      "font-weight:700;text-decoration:none;border:1px solid rgba(205,146,255,.82);" +
      "box-shadow:0 16px 44px rgba(0,0,0,.4);transition:transform .18s cubic-bezier(.4,0,.2,1)}" +
      ".cg-skip:focus{transform:translate(-50%,0)}" +
      ".cg-skip:focus-visible{outline:3px solid #fff;outline-offset:2px}" +
      "@media(prefers-reduced-motion:reduce){.cg-skip{transition:none}}";
    document.head.appendChild(style);

    var link = document.createElement("a");
    link.className = "cg-skip";
    link.href = "#" + target.id;
    link.textContent = "Skip to main content";
    // Some browsers scroll on a hash jump but leave focus behind, so the next
    // Tab would walk back into the nav. Move focus explicitly.
    link.addEventListener("click", function () {
      window.setTimeout(function () { target.focus(); }, 0);
    });
    document.body.insertBefore(link, document.body.firstChild);
  }

  /* ── active route ────────────────────────────────────────────────────── */
  function markActiveRoute() {
    // Both navigation systems, by their own container names: nav.js renders
    // #cg-global-nav / #cg-mobile-nav, control-surface.js renders .cgcs-*.
    var navs = document.querySelectorAll(
      "#cg-global-nav, #cg-mobile-nav, .cg-topnav, .cgcs-menu, .cgcs-bar, .cgcs-dr, " +
      "nav[aria-label='Primary navigation']"
    );
    var marked = false;
    Array.prototype.forEach.call(navs, function (scope) {
      if (scope.querySelector("a[aria-current='page']")) { marked = true; return; }
      var matches = [];
      Array.prototype.forEach.call(scope.querySelectorAll("a[href]"), function (a) {
        var url;
        try { url = new URL(a.href, location.href); } catch (e) { return; }
        if (url.host !== location.host) {
          a.setAttribute("rel", "noopener noreferrer");
          a.setAttribute("data-cg-external", "true");
          return;
        }
        var file = (url.pathname.split("/").pop() || "index.html").toLowerCase();
        if (file === here && (!url.hash || url.hash === location.hash)) matches.push(a);
      });
      // Catalogs repeat destinations; only the first copy carries the state so
      // the page is not announced as "current" several times over.
      if (matches.length) { matches[0].setAttribute("aria-current", "page"); marked = true; }
    });
    return marked;
  }

  function start() {
    installSkipLink();
    if (markActiveRoute()) return;

    // Both nav systems inject asynchronously. Watch for them, but give up after
    // a few seconds so a page without a nav does not keep an observer alive.
    var observer = new MutationObserver(function () {
      installSkipLink();
      if (markActiveRoute()) observer.disconnect();
    });
    observer.observe(document.body, { childList: true, subtree: true });
    window.setTimeout(function () { observer.disconnect(); }, 6000);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", start);
  } else {
    start();
  }
})();
