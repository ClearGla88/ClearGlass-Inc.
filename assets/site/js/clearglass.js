/* ClearGlass Inc. homepage behaviour. Progressive enhancement only: the page
   reads and navigates without this file. Three jobs:
   1. Mobile menu: aria-expanded, focus moves in, Tab stays inside,
      Escape and outside clicks close it, and focus returns to the button.
   2. Contact form: posts only when an endpoint is configured, and reports
      success only on a 2xx response. Never a false "sent" state.
   3. Sticky header fade band, and the footer year. */
(function () {
  "use strict";

  var DESKTOP = window.matchMedia("(min-width: 1024px)");

  function initMenu() {
    var toggle = document.querySelector("[data-menu-toggle]");
    var panel = document.querySelector("[data-mobile-nav]");
    if (!toggle || !panel) return;
    var label = toggle.querySelector("[data-menu-label]");

    function focusables() {
      return Array.prototype.slice.call(panel.querySelectorAll("a[href], button:not([disabled])"));
    }

    function isOpen() {
      return toggle.getAttribute("aria-expanded") === "true";
    }

    function setOpen(open, returnFocus) {
      toggle.setAttribute("aria-expanded", String(open));
      if (label) label.textContent = open ? "Close menu" : "Open menu";
      panel.classList.toggle("is-open", open);
      document.body.classList.toggle("menu-open", open);
      if (open) {
        var first = focusables()[0];
        if (first) first.focus();
      } else if (returnFocus) {
        toggle.focus();
      }
    }

    toggle.addEventListener("click", function () {
      setOpen(!isOpen(), true);
    });

    document.addEventListener("keydown", function (event) {
      if (!isOpen()) return;
      if (event.key === "Escape") {
        event.preventDefault();
        setOpen(false, true);
        return;
      }
      if (event.key !== "Tab") return;
      // Keep focus within the toggle and the open panel.
      var items = [toggle].concat(focusables());
      var index = items.indexOf(document.activeElement);
      var next = event.shiftKey ? index - 1 : index + 1;
      if (index === -1 || next < 0 || next >= items.length) {
        event.preventDefault();
        items[event.shiftKey ? items.length - 1 : 0].focus();
      }
    });

    panel.addEventListener("click", function (event) {
      var link = event.target.closest ? event.target.closest("a[href]") : null;
      if (link) setOpen(false, false);
    });

    document.addEventListener("click", function (event) {
      if (!isOpen()) return;
      if (panel.contains(event.target) || toggle.contains(event.target)) return;
      setOpen(false, false);
    });

    function onBreakpoint() {
      if (DESKTOP.matches && isOpen()) setOpen(false, false);
    }
    if (DESKTOP.addEventListener) DESKTOP.addEventListener("change", onBreakpoint);
    else if (DESKTOP.addListener) DESKTOP.addListener(onBreakpoint);
  }

  function initContactForm() {
    var form = document.querySelector("[data-contact-form]");
    if (!form) return;
    var endpoint = form.getAttribute("data-endpoint");
    var status = form.querySelector("[data-form-status]");

    // No endpoint configured: the fieldset is disabled in the markup, so
    // nothing can be typed or sent. Guard anyway.
    if (!endpoint) {
      form.addEventListener("submit", function (event) {
        event.preventDefault();
      });
      return;
    }

    function report(state, message) {
      if (!status) return;
      status.setAttribute("data-state", state);
      status.textContent = message;
    }

    form.addEventListener("submit", function (event) {
      event.preventDefault();
      if (!form.reportValidity()) return;
      var button = form.querySelector("button[type=submit]");
      if (button) button.disabled = true;
      report("pending", "Sending…");
      fetch(endpoint, {
        method: "POST",
        body: new FormData(form),
        headers: { Accept: "application/json" }
      })
        .then(function (response) {
          if (response.ok) {
            form.reset();
            report("success", "Thank you. Your message was received.");
          } else {
            report("error", "Your message was not sent (the form service returned an error). Please try again later.");
          }
        })
        .catch(function () {
          report("error", "Your message was not sent (no connection to the form service). Please try again later.");
        })
        .then(function () {
          if (button) button.disabled = false;
        });
    });
  }

  function initStickyHeader() {
    var header = document.querySelector("[data-header]");
    var strip = document.querySelector(".utility");
    if (!header || !strip || !("IntersectionObserver" in window)) return;
    new IntersectionObserver(function (entries) {
      header.classList.toggle("is-stuck", !entries[0].isIntersecting);
    }).observe(strip);
  }

  function initYear() {
    var year = String(new Date().getFullYear());
    Array.prototype.forEach.call(document.querySelectorAll("[data-year]"), function (el) {
      el.textContent = year;
    });
  }

  function init() {
    initMenu();
    initContactForm();
    initStickyHeader();
    initYear();
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
