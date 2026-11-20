/* ClearGlass · Cinematic motion runtime (v1.0)
   Mounted by platform.js. Reveals opt-in .cg-reveal / [data-cg-reveal]
   elements as they enter the viewport (styles in cinematic-motion.css).

   Content is never hidden unless this script is running and motion is
   allowed: html.cg-reveal-ready is only set when IntersectionObserver
   exists, the page is not in platform.js's low-power mode, and the visitor
   has not asked for reduced motion. Elements added later can be registered
   with window.cgReveal(element). */
(function () {
  "use strict";
  if (window.__cgCinematicMotionRuntime) return;
  window.__cgCinematicMotionRuntime = true;

  var root = document.documentElement;
  var SELECTOR = ".cg-reveal, [data-cg-reveal]";

  function reduced() {
    try { if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return true; } catch (e) {}
    return root.classList.contains("cg-low-power") || root.classList.contains("cg-motion-reduced");
  }

  function revealAll() {
    var els = document.querySelectorAll(SELECTOR);
    for (var i = 0; i < els.length; i++) els[i].classList.add("is-revealed");
  }

  function start() {
    var els = document.querySelectorAll(SELECTOR);
    if (!els.length) { window.cgReveal = function () {}; return; }
    if (reduced() || !("IntersectionObserver" in window)) {
      revealAll();
      window.cgReveal = function (el) { if (el) el.classList.add("is-revealed"); };
      return;
    }

    var io = new IntersectionObserver(function (entries) {
      var batch = 0;
      entries.forEach(function (entry) {
        if (!entry.isIntersecting) return;
        var el = entry.target;
        // Stagger elements that arrive in the same frame, capped at 300ms.
        el.style.setProperty("--cg-reveal-delay", Math.min(batch * 60, 300) + "ms");
        batch++;
        el.classList.add("is-revealed");
        io.unobserve(el);
      });
    }, { rootMargin: "0px 0px -6% 0px", threshold: 0.08 });

    window.cgReveal = function (el) { if (el && !el.classList.contains("is-revealed")) io.observe(el); };
    for (var i = 0; i < els.length; i++) io.observe(els[i]);
    root.classList.add("cg-reveal-ready");
    window.addEventListener("beforeprint", revealAll);
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start);
  else start();
})();
