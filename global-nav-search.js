/* ClearGlass · Global Navigation Search
   Progressive enhancement only. Attaches one compact search control to the existing
   navigation, indexes same-origin public pages lazily from sitemap.xml, and fails
   closed without changing navigation structure, routes, overlays, or page runtimes. */
(function () {
  "use strict";
  if (window.__cgGlobalNavSearch) return;
  window.__cgGlobalNavSearch = true;

  var nav = document.querySelector("nav.nav, nav#navbar, nav[aria-label='Primary navigation']");
  if (!nav || nav.querySelector("[data-cg-nav-search]")) return;

  var MAX_FETCHED_PAGES = 72;
  var MAX_BODY_CHARS = 5000;
  var MAX_RESULTS = 8;
  var CACHE_KEY = "cg-nav-search-index-v1";
  var CACHE_TTL = 6 * 60 * 60 * 1000;
  var docs = [];
  var byUrl = Object.create(null);
  var indexingStarted = false;
  var activeIndex = -1;

  function sameOrigin(url) {
    try { return new URL(url, location.href).origin === location.origin; }
    catch (e) { return false; }
  }

  function normalizeUrl(url) {
    try {
      var u = new URL(url, location.href);
      u.hash = "";
      return u.href;
    } catch (e) { return ""; }
  }

  function usefulPage(url) {
    if (!sameOrigin(url)) return false;
    try {
      var u = new URL(url, location.href);
      var p = u.pathname.toLowerCase();
      if (/\.(?:css|js|json|xml|txt|map|png|jpe?g|gif|webp|svg|ico|pdf|zip|woff2?|ttf|mp4|webm)$/i.test(p)) return false;
      return !/(?:\/api\/|\/assets\/|\/node_modules\/|\/\.git\/)/.test(p);
    } catch (e) { return false; }
  }

  function clean(text) {
    return String(text || "").replace(/\s+/g, " ").trim();
  }

  function addDoc(doc) {
    var url = normalizeUrl(doc && doc.url);
    if (!url || !usefulPage(url)) return null;
    var existing = byUrl[url];
    if (existing) {
      Object.keys(doc).forEach(function (key) {
        if (doc[key]) existing[key] = doc[key];
      });
      return existing;
    }
    var item = {
      url: url,
      title: clean(doc.title) || clean(new URL(url).pathname.split("/").filter(Boolean).pop()) || "ClearGlass",
      description: clean(doc.description),
      headings: clean(doc.headings),
      body: clean(doc.body),
      path: new URL(url).pathname,
      fetched: !!doc.fetched
    };
    docs.push(item);
    byUrl[url] = item;
    return item;
  }

  function seedCurrentDocument() {
    var desc = document.querySelector('meta[name="description"]');
    var headings = Array.prototype.map.call(document.querySelectorAll("h1,h2,h3"), function (el) { return el.textContent; }).join(" ");
    addDoc({
      url: location.href,
      title: document.title,
      description: desc ? desc.content : "",
      headings: headings,
      body: document.body ? document.body.innerText.slice(0, MAX_BODY_CHARS) : "",
      fetched: true
    });
    Array.prototype.forEach.call(document.querySelectorAll("a[href]"), function (a) {
      if (!usefulPage(a.href)) return;
      addDoc({ url: a.href, title: a.textContent, description: a.getAttribute("aria-label") || "" });
    });
  }

  function injectStyles() {
    if (document.getElementById("cg-global-nav-search-style")) return;
    var style = document.createElement("style");
    style.id = "cg-global-nav-search-style";
    style.textContent =
      ".cg-nav-search{position:relative;display:flex;align-items:center;z-index:6;flex:0 0 auto}" +
      ".cg-nav-search__button{width:42px;height:42px;display:grid;place-items:center;border:1px solid rgba(205,146,255,.42);border-radius:999px;background:rgba(9,13,28,.78);color:#f5f7ff;cursor:pointer;box-shadow:0 0 18px rgba(166,92,255,.22),inset 0 1px 0 rgba(255,255,255,.12);transition:transform .16s ease,border-color .16s ease,background .16s ease}" +
      ".cg-nav-search__button:hover,.cg-nav-search__button:focus-visible{transform:translateY(-1px);border-color:rgba(142,234,255,.78);background:rgba(18,25,47,.95);outline:none}" +
      ".cg-nav-search__button svg{width:19px;height:19px;display:block}" +
      ".cg-nav-search__panel{position:absolute;top:calc(100% + 14px);right:0;width:min(430px,calc(100vw - 28px));border:1px solid rgba(183,202,255,.22);border-radius:20px;background:linear-gradient(155deg,rgba(7,13,29,.985),rgba(25,20,49,.985));backdrop-filter:blur(24px) saturate(1.25);-webkit-backdrop-filter:blur(24px) saturate(1.25);box-shadow:0 24px 70px rgba(0,0,0,.42),0 0 35px rgba(132,82,255,.16);padding:12px;color:#f8fbff}" +
      ".cg-nav-search__panel[hidden]{display:none!important}" +
      ".cg-nav-search__field{display:flex;align-items:center;gap:9px;border:1px solid rgba(164,196,255,.24);border-radius:14px;background:rgba(255,255,255,.065);padding:0 12px}" +
      ".cg-nav-search__field svg{width:17px;height:17px;opacity:.76;flex:0 0 auto}" +
      ".cg-nav-search__input{width:100%;min-width:0;height:48px;border:0;outline:0;background:transparent;color:#fff;font:600 14px/1.2 var(--sans,system-ui,sans-serif)}" +
      ".cg-nav-search__input::placeholder{color:rgba(226,232,240,.58)}" +
      ".cg-nav-search__kbd{font:600 9px/1 var(--mono,monospace);letter-spacing:.06em;color:rgba(226,232,240,.58);border:1px solid rgba(255,255,255,.14);border-radius:6px;padding:5px 6px;white-space:nowrap}" +
      ".cg-nav-search__status{min-height:30px;padding:10px 5px 5px;font:600 10px/1.4 var(--mono,monospace);letter-spacing:.08em;text-transform:uppercase;color:rgba(196,214,255,.58)}" +
      ".cg-nav-search__results{display:grid;gap:5px;max-height:min(56vh,440px);overflow:auto;overscroll-behavior:contain;padding:2px}" +
      ".cg-nav-search__result{display:block;border:1px solid transparent;border-radius:13px;padding:11px 12px;text-decoration:none;color:#f8fbff;background:transparent}" +
      ".cg-nav-search__result:hover,.cg-nav-search__result.is-active,.cg-nav-search__result:focus-visible{background:rgba(126,176,255,.10);border-color:rgba(126,213,255,.23);outline:none}" +
      ".cg-nav-search__title{display:block;font:700 13px/1.35 var(--sans,system-ui,sans-serif)}" +
      ".cg-nav-search__meta{display:block;margin-top:4px;font:500 10px/1.35 var(--mono,monospace);color:rgba(191,205,230,.66);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}" +
      ".cg-nav-search__snippet{display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;margin-top:6px;font:500 11.5px/1.45 var(--sans,system-ui,sans-serif);color:rgba(226,232,240,.68)}" +
      "@media(max-width:1240px){.cg-nav-search{margin-left:auto;margin-right:8px}.cg-nav-search__button{width:40px;height:40px}.cg-nav-search__panel{right:-48px}}" +
      "@media(max-width:620px){.cg-nav-search{margin-right:5px}.cg-nav-search__button{width:38px;height:38px}.cg-nav-search__panel{position:fixed;top:calc(82px + env(safe-area-inset-top));right:10px;left:10px;width:auto;max-height:calc(100dvh - 96px - env(safe-area-inset-top))}.cg-nav-search__results{max-height:calc(100dvh - 205px - env(safe-area-inset-top))}.cg-nav-search__kbd{display:none}}" +
      "@media(prefers-reduced-motion:reduce){.cg-nav-search__button{transition:none}}";
    document.head.appendChild(style);
  }

  function makeIcon() {
    return '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><circle cx="11" cy="11" r="6.5"></circle><path d="m16 16 4.2 4.2"></path></svg>';
  }

  injectStyles();
  seedCurrentDocument();

  var wrap = document.createElement("div");
  wrap.className = "cg-nav-search";
  wrap.setAttribute("data-cg-nav-search", "true");

  var button = document.createElement("button");
  button.type = "button";
  button.className = "cg-nav-search__button";
  button.setAttribute("aria-label", "Search ClearGlass");
  button.setAttribute("aria-expanded", "false");
  button.setAttribute("aria-controls", "cgNavSearchPanel");
  button.innerHTML = makeIcon();

  var panel = document.createElement("div");
  panel.id = "cgNavSearchPanel";
  panel.className = "cg-nav-search__panel";
  panel.hidden = true;
  panel.setAttribute("role", "search");

  var field = document.createElement("div");
  field.className = "cg-nav-search__field";
  field.innerHTML = makeIcon();

  var input = document.createElement("input");
  input.className = "cg-nav-search__input";
  input.type = "search";
  input.autocomplete = "off";
  input.spellcheck = false;
  input.placeholder = "Search products, insights, services…";
  input.setAttribute("aria-label", "Search the ClearGlass website");
  input.setAttribute("aria-controls", "cgNavSearchResults");
  input.setAttribute("aria-autocomplete", "list");

  var shortcut = document.createElement("span");
  shortcut.className = "cg-nav-search__kbd";
  shortcut.setAttribute("aria-hidden", "true");
  shortcut.textContent = (navigator.platform && /Mac/i.test(navigator.platform)) ? "⌘ K" : "CTRL K";

  var status = document.createElement("div");
  status.className = "cg-nav-search__status";
  status.setAttribute("aria-live", "polite");
  status.textContent = "Type to search ClearGlass";

  var results = document.createElement("div");
  results.id = "cgNavSearchResults";
  results.className = "cg-nav-search__results";
  results.setAttribute("role", "listbox");

  field.appendChild(input);
  field.appendChild(shortcut);
  panel.appendChild(field);
  panel.appendChild(status);
  panel.appendChild(results);
  wrap.appendChild(button);
  wrap.appendChild(panel);

  var toggle = nav.querySelector(".nav-toggle");
  if (toggle) nav.insertBefore(wrap, toggle);
  else nav.appendChild(wrap);

  function cacheRead() {
    try {
      var raw = sessionStorage.getItem(CACHE_KEY);
      if (!raw) return false;
      var payload = JSON.parse(raw);
      if (!payload || !payload.at || Date.now() - payload.at > CACHE_TTL || !Array.isArray(payload.docs)) return false;
      payload.docs.forEach(addDoc);
      return payload.docs.length > 0;
    } catch (e) { return false; }
  }

  function cacheWrite() {
    try {
      var compact = docs.filter(function (d) { return d.fetched; }).map(function (d) {
        return { url:d.url, title:d.title, description:d.description, headings:d.headings, body:d.body, fetched:true };
      });
      sessionStorage.setItem(CACHE_KEY, JSON.stringify({ at:Date.now(), docs:compact }));
    } catch (e) {}
  }

  function fetchDoc(item) {
    if (!item || item.fetched) return Promise.resolve(item);
    return fetch(item.url, { credentials:"same-origin", headers:{ "Accept":"text/html" } }).then(function (res) {
      if (!res.ok || !/text\/html/i.test(res.headers.get("content-type") || "")) return item;
      return res.text().then(function (html) {
        var parsed = new DOMParser().parseFromString(html, "text/html");
        var desc = parsed.querySelector('meta[name="description"]');
        var title = parsed.querySelector("title");
        var headings = Array.prototype.map.call(parsed.querySelectorAll("h1,h2,h3"), function (el) { return el.textContent; }).join(" ");
        var main = parsed.querySelector("main") || parsed.body;
        item.title = clean(title && title.textContent) || item.title;
        item.description = clean(desc && desc.content) || item.description;
        item.headings = clean(headings);
        item.body = clean(main && main.textContent).slice(0, MAX_BODY_CHARS);
        item.fetched = true;
        return item;
      });
    }).catch(function () { return item; });
  }

  function runPool(items, workers) {
    var cursor = 0;
    var active = [];
    function worker() {
      function next() {
        if (cursor >= items.length) return Promise.resolve();
        var item = items[cursor++];
        return fetchDoc(item).then(function () {
          if (!panel.hidden && input.value.trim()) render(input.value);
          return next();
        });
      }
      return next();
    }
    for (var i = 0; i < workers; i++) active.push(worker());
    return Promise.all(active);
  }

  function startIndexing() {
    if (indexingStarted) return;
    indexingStarted = true;
    if (cacheRead()) {
      status.textContent = "Search index ready";
      return;
    }
    status.textContent = "Preparing site search…";
    fetch(new URL("/sitemap.xml", location.origin).href, { credentials:"same-origin" }).then(function (res) {
      if (!res.ok) throw new Error("sitemap unavailable");
      return res.text();
    }).then(function (xml) {
      var parsed = new DOMParser().parseFromString(xml, "application/xml");
      var urls = Array.prototype.map.call(parsed.querySelectorAll("loc"), function (loc) { return clean(loc.textContent); });
      urls.filter(usefulPage).forEach(function (url) { addDoc({ url:url }); });
      var queue = docs.filter(function (d) { return !d.fetched; }).slice(0, MAX_FETCHED_PAGES);
      return runPool(queue, 3).then(function () {
        cacheWrite();
        if (!panel.hidden) status.textContent = "Search index ready";
      });
    }).catch(function () {
      status.textContent = "Search ready · local navigation index";
    });
  }

  function score(item, query) {
    var q = query.toLowerCase();
    var terms = q.split(/\s+/).filter(Boolean);
    var title = item.title.toLowerCase();
    var desc = item.description.toLowerCase();
    var headings = item.headings.toLowerCase();
    var body = item.body.toLowerCase();
    var path = item.path.toLowerCase();
    var value = 0;
    if (title === q) value += 140;
    if (title.indexOf(q) !== -1) value += 90;
    if (path.indexOf(q.replace(/\s+/g, "-")) !== -1) value += 55;
    if (headings.indexOf(q) !== -1) value += 48;
    if (desc.indexOf(q) !== -1) value += 40;
    if (body.indexOf(q) !== -1) value += 20;
    terms.forEach(function (term) {
      if (title.indexOf(term) !== -1) value += 18;
      if (path.indexOf(term) !== -1) value += 11;
      if (headings.indexOf(term) !== -1) value += 9;
      if (desc.indexOf(term) !== -1) value += 7;
      if (body.indexOf(term) !== -1) value += 3;
    });
    return value;
  }

  function snippetFor(item, query) {
    var source = item.description || item.headings || item.body || item.path;
    var text = clean(source);
    if (!text) return "";
    var lower = text.toLowerCase();
    var at = lower.indexOf(query.toLowerCase());
    var start = Math.max(0, at > -1 ? at - 70 : 0);
    var out = text.slice(start, start + 180);
    return (start ? "…" : "") + out + (text.length > start + 180 ? "…" : "");
  }

  function render(query) {
    var q = clean(query);
    results.textContent = "";
    activeIndex = -1;
    input.removeAttribute("aria-activedescendant");
    if (q.length < 2) {
      status.textContent = indexingStarted ? "Type at least 2 characters" : "Type to search ClearGlass";
      return;
    }
    var ranked = docs.map(function (item) { return { item:item, score:score(item, q) }; })
      .filter(function (row) { return row.score > 0; })
      .sort(function (a,b) { return b.score - a.score || a.item.title.localeCompare(b.item.title); })
      .slice(0, MAX_RESULTS);
    status.textContent = ranked.length ? ranked.length + (ranked.length === 1 ? " result" : " results") : (indexingStarted ? "No matches yet" : "No matches");
    ranked.forEach(function (row, index) {
      var a = document.createElement("a");
      a.className = "cg-nav-search__result";
      a.href = row.item.url;
      a.id = "cgNavSearchResult" + index;
      a.setAttribute("role", "option");
      a.setAttribute("aria-selected", "false");
      var title = document.createElement("span");
      title.className = "cg-nav-search__title";
      title.textContent = row.item.title;
      var meta = document.createElement("span");
      meta.className = "cg-nav-search__meta";
      meta.textContent = row.item.path;
      var snippet = document.createElement("span");
      snippet.className = "cg-nav-search__snippet";
      snippet.textContent = snippetFor(row.item, q);
      a.appendChild(title);
      a.appendChild(meta);
      if (snippet.textContent) a.appendChild(snippet);
      results.appendChild(a);
    });
  }

  function resultNodes() { return Array.prototype.slice.call(results.querySelectorAll(".cg-nav-search__result")); }
  function setActive(next) {
    var nodes = resultNodes();
    if (!nodes.length) return;
    activeIndex = Math.max(0, Math.min(next, nodes.length - 1));
    nodes.forEach(function (node, i) {
      var active = i === activeIndex;
      node.classList.toggle("is-active", active);
      node.setAttribute("aria-selected", String(active));
    });
    input.setAttribute("aria-activedescendant", nodes[activeIndex].id);
    nodes[activeIndex].scrollIntoView({ block:"nearest" });
  }

  function openSearch() {
    panel.hidden = false;
    button.setAttribute("aria-expanded", "true");
    startIndexing();
    window.setTimeout(function () { input.focus({ preventScroll:true }); }, 0);
  }

  function closeSearch() {
    panel.hidden = true;
    button.setAttribute("aria-expanded", "false");
    activeIndex = -1;
    input.removeAttribute("aria-activedescendant");
  }

  button.addEventListener("click", function () { panel.hidden ? openSearch() : closeSearch(); });
  input.addEventListener("input", function () { render(input.value); });
  input.addEventListener("keydown", function (event) {
    var nodes = resultNodes();
    if (event.key === "ArrowDown") { event.preventDefault(); setActive(activeIndex < 0 ? 0 : activeIndex + 1); }
    else if (event.key === "ArrowUp") { event.preventDefault(); setActive(activeIndex < 0 ? nodes.length - 1 : activeIndex - 1); }
    else if (event.key === "Enter" && activeIndex >= 0 && nodes[activeIndex]) { event.preventDefault(); nodes[activeIndex].click(); }
    else if (event.key === "Escape") { event.preventDefault(); closeSearch(); button.focus(); }
  });
  document.addEventListener("pointerdown", function (event) {
    if (!panel.hidden && !wrap.contains(event.target)) closeSearch();
  });
  document.addEventListener("keydown", function (event) {
    var target = event.target;
    var typing = target && /^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName) || (target && target.isContentEditable);
    var shortcutHit = (event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k";
    var slashHit = event.key === "/" && !typing && !event.ctrlKey && !event.metaKey && !event.altKey;
    if (!shortcutHit && !slashHit) return;
    event.preventDefault();
    openSearch();
  });
})();