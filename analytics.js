/* ClearGlass privacy-conscious analytics and conversion instrumentation.

   The event layer is active on every page through /stealth-glass.js. It never
   records form-field values, names, email addresses, phone numbers, query
   strings, or persistent cross-session identifiers. By default events remain
   in an in-memory queue. A verified operator can enable one destination with
   head metadata, without changing the event contract:

     <meta name="cg-analytics-provider" content="ga4">
     <meta name="cg-ga4-id" content="G-XXXXXXXXXX">

   or a same-origin, privacy-reviewed collector:

     <meta name="cg-analytics-provider" content="first-party">
     <meta name="cg-analytics-endpoint" content="/api/analytics">

   Plausible is also supported with provider=plausible and cg-analytics-domain.
   No destination is activated with a placeholder or malformed identifier. */
(function () {
  "use strict";
  if (window.__cgAnalytics) return;
  window.__cgAnalytics = true;

  var SAFE_PROPERTY_KEYS = {
    page_path: true,
    link_domain: true,
    link_text: true,
    offer_id: true,
    value: true,
    currency: true,
    placement: true,
    form_id: true,
    source: true,
    medium: true,
    campaign: true,
    term: true,
    content: true,
    lead_id: true,
    status: true
  };
  var PROVIDERS = { queue: true, ga4: true, plausible: true, "first-party": true };
  var ATTRIBUTION_KEY = "cg.attribution";
  var SESSION_KEY = "cg.analytics.session";

  function meta(name) {
    var node = document.querySelector('meta[name="' + name + '"]');
    return node ? String(node.content || "").trim() : "";
  }

  function safeSessionGet(key) {
    try { return sessionStorage.getItem(key); } catch (error) { return null; }
  }

  function safeSessionSet(key, value) {
    try { sessionStorage.setItem(key, value); } catch (error) { /* unavailable */ }
  }

  function sessionId() {
    var current = safeSessionGet(SESSION_KEY);
    if (current) return current;
    var value = "cg-";
    if (window.crypto && typeof window.crypto.randomUUID === "function") {
      value += window.crypto.randomUUID();
    } else {
      value += Date.now().toString(36) + "-" + Math.random().toString(36).slice(2, 10);
    }
    safeSessionSet(SESSION_KEY, value);
    return value;
  }

  function cleanText(value, limit) {
    return String(value == null ? "" : value).replace(/\s+/g, " ").trim().slice(0, limit);
  }

  function eventName(value) {
    return cleanText(value, 40).toLowerCase().replace(/[^a-z0-9_]/g, "_");
  }

  function cleanProperties(input) {
    var output = {};
    Object.keys(input || {}).forEach(function (key) {
      if (!SAFE_PROPERTY_KEYS[key]) return;
      var value = input[key];
      if (typeof value === "number" && isFinite(value)) output[key] = value;
      else if (typeof value === "string") output[key] = cleanText(value, 100);
    });
    return output;
  }

  function attribution() {
    var existing = safeSessionGet(ATTRIBUTION_KEY);
    if (existing) {
      try { return JSON.parse(existing); } catch (error) { /* replace below */ }
    }
    var params = new URLSearchParams(location.search);
    var value = {
      source: cleanText(params.get("utm_source") || "", 100),
      medium: cleanText(params.get("utm_medium") || "", 100),
      campaign: cleanText(params.get("utm_campaign") || "", 100),
      term: cleanText(params.get("utm_term") || "", 100),
      content: cleanText(params.get("utm_content") || "", 100)
    };
    safeSessionSet(ATTRIBUTION_KEY, JSON.stringify(value));
    return value;
  }

  var declared = window.CG_ANALYTICS_CONFIG &&
    typeof window.CG_ANALYTICS_CONFIG === "object" ? window.CG_ANALYTICS_CONFIG : {};
  var CONFIG = {
    provider: (meta("cg-analytics-provider") || cleanText(declared.provider, 20) || "queue").toLowerCase(),
    measurementId: meta("cg-ga4-id") || cleanText(declared.measurementId, 24),
    domain: meta("cg-analytics-domain") || cleanText(declared.domain, 100) || "www.clearglassinc.com",
    endpoint: meta("cg-analytics-endpoint") || cleanText(declared.endpoint, 160)
  };
  if (!PROVIDERS[CONFIG.provider]) CONFIG.provider = "queue";

  window.cgDataLayer = window.cgDataLayer || [];
  window.dataLayer = window.dataLayer || [];
  window.plausible = window.plausible || function () {
    (window.plausible.q = window.plausible.q || []).push(arguments);
  };

  function injectScript(src, attrs) {
    var script = document.createElement("script");
    script.src = src;
    script.defer = true;
    Object.keys(attrs || {}).forEach(function (key) { script.setAttribute(key, attrs[key]); });
    (document.head || document.documentElement).appendChild(script);
  }

  function gtag() { window.dataLayer.push(arguments); }

  window.cgAnalyticsConsent = function (granted) {
    if (CONFIG.provider !== "ga4" || !/^G-[A-Z0-9]{6,20}$/.test(CONFIG.measurementId)) return;
    var state = granted === true ? "granted" : "denied";
    gtag("consent", "update", {
      analytics_storage: state,
      ad_storage: "denied",
      ad_user_data: "denied",
      ad_personalization: "denied"
    });
  };

  if (CONFIG.provider === "ga4" && /^G-[A-Z0-9]{6,20}$/.test(CONFIG.measurementId)) {
    gtag("consent", "default", {
      analytics_storage: "denied",
      ad_storage: "denied",
      ad_user_data: "denied",
      ad_personalization: "denied"
    });
    gtag("js", new Date());
    gtag("config", CONFIG.measurementId, {
      send_page_view: false,
      allow_google_signals: false,
      allow_ad_personalization_signals: false
    });
    injectScript("https://www.googletagmanager.com/gtag/js?id=" + encodeURIComponent(CONFIG.measurementId));
  } else if (CONFIG.provider === "plausible" && CONFIG.domain) {
    injectScript("https://plausible.io/js/script.js", { "data-domain": CONFIG.domain });
  }

  function sendFirstParty(payload) {
    if (!CONFIG.endpoint || !/^\//.test(CONFIG.endpoint)) return;
    var body = JSON.stringify(payload);
    if (navigator.sendBeacon) {
      navigator.sendBeacon(CONFIG.endpoint, new Blob([body], { type: "application/json" }));
      return;
    }
    fetch(CONFIG.endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: body,
      keepalive: true,
      credentials: "same-origin"
    }).catch(function () { /* telemetry must never break the page */ });
  }

  function track(name, properties) {
    var normalizedName = eventName(name);
    if (!normalizedName) return;
    var props = cleanProperties(Object.assign({}, attribution(), properties || {}));
    var payload = {
      event: normalizedName,
      properties: props,
      page_path: location.pathname,
      session_id: sessionId(),
      occurred_at: new Date().toISOString()
    };
    window.cgDataLayer.push(payload);
    window.dispatchEvent(new CustomEvent("clearglass:analytics", { detail: payload }));
    if (CONFIG.provider === "ga4" && /^G-[A-Z0-9]{6,20}$/.test(CONFIG.measurementId)) {
      gtag("event", normalizedName, props);
    } else if (CONFIG.provider === "plausible") {
      window.plausible(normalizedName, { props: props });
    } else if (CONFIG.provider === "first-party") {
      sendFirstParty(payload);
    }
  }
  window.cgTrack = track;

  function offerFor(node) {
    return cleanText(node.getAttribute("data-cg-offer") || "unspecified", 60);
  }

  document.addEventListener("click", function (event) {
    var link = event.target.closest && event.target.closest("a[href]");
    if (!link) return;
    var url;
    try { url = new URL(link.href, location.href); } catch (error) { return; }
    var explicitEvent = link.getAttribute("data-cg-event");
    var props = {
      link_domain: url.hostname,
      link_text: cleanText(link.textContent, 80),
      offer_id: offerFor(link),
      placement: cleanText(link.getAttribute("data-cg-placement") || "", 60)
    };
    var value = Number(link.getAttribute("data-cg-value"));
    if (isFinite(value) && value > 0) props.value = value;
    props.currency = cleanText(link.getAttribute("data-cg-currency") || "", 8);

    if (/^(buy|book|checkout)\.stripe\.com$/i.test(url.hostname)) {
      safeSessionSet("cg.checkout." + props.offer_id, "started");
      track(explicitEvent || "begin_checkout", props);
    } else if (url.protocol === "mailto:") {
      track(explicitEvent || "contact_click", props);
    } else if (explicitEvent) {
      track(explicitEvent, props);
    }
  });

  document.addEventListener("submit", function (event) {
    var form = event.target;
    if (!form || !form.matches || !form.matches("[data-cg-lead-form]")) return;
    track("generate_lead", {
      form_id: cleanText(form.id || "lead-form", 60),
      offer_id: cleanText(form.getAttribute("data-cg-offer") || "", 60),
      value: Number(form.getAttribute("data-cg-value")) || 0,
      currency: cleanText(form.getAttribute("data-cg-currency") || "CAD", 8)
    });
  });

  track("page_view", { page_path: location.pathname });
})();
