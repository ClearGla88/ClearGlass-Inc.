/* ClearGlass · Neon button pointer light (v1.0)
   Companion to /assets/css/future-buttons.css. Moves the inner highlight of
   a .cg-neon-button toward the pointer by writing --cg-mx / --cg-my. One
   passive, delegated listener, at most one style write per animation frame.
   Does nothing on touch-only devices or under reduced motion. */
(function () {
  "use strict";
  if (window.__cgFutureButtons) return;
  window.__cgFutureButtons = true;

  function mq(q) { try { return window.matchMedia(q).matches; } catch (e) { return false; } }
  if (mq("(hover: none)") || mq("(prefers-reduced-motion: reduce)")) return;

  var target = null, x = 0, y = 0, queued = false;

  function paint() {
    queued = false;
    if (!target) return;
    var r = target.getBoundingClientRect();
    if (!r.width || !r.height) return;
    target.style.setProperty("--cg-mx", ((x - r.left) / r.width * 100).toFixed(1) + "%");
    target.style.setProperty("--cg-my", ((y - r.top) / r.height * 100).toFixed(1) + "%");
  }

  document.addEventListener("pointermove", function (event) {
    var el = event.target && event.target.closest ? event.target.closest(".cg-neon-button") : null;
    if (el !== target && target) {
      target.style.removeProperty("--cg-mx");
      target.style.removeProperty("--cg-my");
    }
    target = el;
    if (!el) return;
    x = event.clientX;
    y = event.clientY;
    if (!queued) { queued = true; requestAnimationFrame(paint); }
  }, { passive: true });
})();
