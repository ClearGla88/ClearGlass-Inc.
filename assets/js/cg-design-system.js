/* ClearGlass · Neon Glass System runtime (v1.0)
   Companion to /assets/css/cg-design-system.css. Dependency-free, idempotent,
   and safe to load with `defer` on any page.

   1. Hidden-tab pause: sets html[data-cg-hidden] while the tab is in the
      background, which pauses every CSS animation (see the stylesheet).
   2. Broken-image containment: a missing image draws its alt text as loose
      inline text, which spills out of round logo frames. Failed images get
      data-cg-img-missing (hidden visually, alt text still exposed to
      assistive tech). When the image is a ClearGlass brand mark sitting in a
      small, roughly square frame, the frame shows a "CG" monogram instead of
      an empty circle. No substitute image is ever loaded. */
(function () {
  "use strict";
  if (window.__cgDesignSystem) return;
  window.__cgDesignSystem = true;

  var root = document.documentElement;
  var BRAND_MARK = /clearglass-(logo|holographic-seal)/i;

  function syncVisibility() {
    if (document.visibilityState === "hidden") root.setAttribute("data-cg-hidden", "");
    else root.removeAttribute("data-cg-hidden");
  }
  document.addEventListener("visibilitychange", syncVisibility);
  syncVisibility();

  function markFrame(img) {
    var frame = img.parentElement;
    if (frame && frame.tagName === "PICTURE") frame = frame.parentElement;
    if (!frame || frame.hasAttribute("data-cg-mark-fallback")) return;
    var box = frame.getBoundingClientRect();
    var w = box.width, h = box.height;
    // Only monogram a logo-sized frame. A wide header or a hero block would
    // get a giant "CG" laid over its content, which is worse than nothing.
    if (!w || !h || w > 240 || h > 240 || w / h > 1.6 || h / w > 1.6) return;
    if (getComputedStyle(frame).position === "static") frame.style.position = "relative";
    frame.style.setProperty("--cg-mark-size", Math.round(Math.max(10, Math.min(64, Math.min(w, h) * 0.36))) + "px");
    frame.setAttribute("data-cg-mark-fallback", "");
  }

  function onBroken(img) {
    if (!img || img.tagName !== "IMG" || img.hasAttribute("data-cg-img-missing")) return;
    img.setAttribute("data-cg-img-missing", "");
    // nav.js and logo-badge.js draw their own fallback; don't stack a second.
    if (img.hasAttribute("data-cg-owned-fallback")) return;
    if (BRAND_MARK.test(img.getAttribute("src") || "")) markFrame(img);
  }

  // `error` does not bubble, but a capture listener on document sees it.
  document.addEventListener("error", function (event) { onBroken(event.target); }, true);

  function sweep() {
    var imgs = document.images;
    for (var i = 0; i < imgs.length; i++) {
      var img = imgs[i];
      if (img.getAttribute("src") && img.complete && img.naturalWidth === 0) onBroken(img);
    }
  }
  if (document.readyState === "complete") sweep();
  else window.addEventListener("load", sweep);
  // Navigation scripts inject their logos after DOMContentLoaded.
  document.addEventListener("DOMContentLoaded", function () { setTimeout(sweep, 0); });
})();
