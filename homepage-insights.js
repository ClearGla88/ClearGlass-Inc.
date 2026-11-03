/* ClearGlass · homepage Insights showcase
   Progressive enhancement only. Reads blog/posts.json as the content source of truth,
   mounts a non-fixed editorial showcase on the homepage, and fails closed if content
   cannot be loaded. No global HUD, overlay, assistant or telemetry surface is added. */
(function () {
  "use strict";

  if (window.__cgHomepageInsights) return;
  window.__cgHomepageInsights = true;

  var normalizedPath = (location.pathname || "/").replace(/\/+$/, "") || "/";
  var canonical = document.querySelector('link[rel="canonical"]');
  var canonicalHref = canonical ? canonical.href : "";
  var isHomepage = normalizedPath === "/" ||
    /\/index\.html$/i.test(normalizedPath) ||
    canonicalHref === "https://www.clearglassinc.com/";
  if (!isHomepage || document.getElementById("cg-home-insights")) return;

  var MAX_POSTS = 4;
  var reduceMotion = false;
  try { reduceMotion = matchMedia("(prefers-reduced-motion: reduce)").matches; } catch (e) {}

  function assetUrl(path) {
    try {
      return new URL(String(path || "").replace(/^\/+/, ""), document.baseURI).href;
    } catch (e) {
      return path;
    }
  }

  function make(tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text != null) node.textContent = text;
    return node;
  }

  function postRank(post) {
    var rank = Number(post && post.deskRank);
    return isFinite(rank) && rank > 0 ? rank : 9999;
  }

  function formatDate(value) {
    if (!value) return "";
    try {
      return new Intl.DateTimeFormat("en-CA", {
        year: "numeric",
        month: "short",
        day: "numeric"
      }).format(new Date(value + "T12:00:00"));
    } catch (e) {
      return value;
    }
  }

  function isNew(value) {
    if (!value) return false;
    var stamp = Date.parse(value + "T12:00:00Z");
    if (!isFinite(stamp)) return false;
    var age = Date.now() - stamp;
    return age >= 0 && age <= 8 * 24 * 60 * 60 * 1000;
  }

  function badge(text, kind) {
    var node = make("span", "cg-hi-badge" + (kind ? " cg-hi-badge--" + kind : ""), text);
    return node;
  }

  function buildCard(post, lead) {
    var href = assetUrl(post.url || "blog/");
    var article = make("article", lead ? "cg-hi-card cg-hi-card--lead" : "cg-hi-card");
    article.setAttribute("data-insight-slug", post.slug || "");

    var link = make("a", "cg-hi-link");
    link.href = href;
    link.setAttribute("data-insight-open", post.slug || "");
    link.setAttribute("aria-label", "Read: " + (post.title || "ClearGlass Insight"));

    var meta = make("div", "cg-hi-meta");
    meta.appendChild(badge("DESK PICK #" + postRank(post), "rank"));
    if (isNew(post.date)) meta.appendChild(badge("NEW", "new"));
    if (post.category) meta.appendChild(badge(post.category));
    if (post.readMinutes) meta.appendChild(badge(post.readMinutes + " MIN"));

    var title = make(lead ? "h3" : "h4", "cg-hi-title", post.title || "ClearGlass Insight");
    var description = make("p", "cg-hi-desc", post.description || "ClearGlass intelligence analysis.");

    var footer = make("div", "cg-hi-footer");
    var date = make("span", "cg-hi-date", formatDate(post.date));
    var action = make("span", "cg-hi-action", lead ? "Read flagship analysis →" : "Read analysis →");
    footer.appendChild(date);
    footer.appendChild(action);

    link.appendChild(meta);
    link.appendChild(title);
    link.appendChild(description);
    link.appendChild(footer);
    article.appendChild(link);

    return article;
  }

  function injectStyles() {
    if (document.getElementById("cg-home-insights-style")) return;
    var style = document.createElement("style");
    style.id = "cg-home-insights-style";
    style.textContent =
      "#cg-home-insights{position:relative;overflow:hidden;background:radial-gradient(circle at 10% 10%,rgba(56,189,248,.14),transparent 30%),radial-gradient(circle at 88% 78%,rgba(167,139,250,.17),transparent 34%),linear-gradient(145deg,#07111f 0%,#0b1730 45%,#11172a 100%);color:#f8fafc;padding:clamp(78px,10vw,128px) 0;isolation:isolate;contain:layout style paint}" +
      "#cg-home-insights:before{content:'';position:absolute;inset:0;pointer-events:none;background-image:linear-gradient(rgba(148,163,184,.055) 1px,transparent 1px),linear-gradient(90deg,rgba(148,163,184,.045) 1px,transparent 1px);background-size:34px 34px;mask-image:linear-gradient(to bottom,rgba(0,0,0,.9),transparent)}" +
      "#cg-home-insights .cg-hi-shell{position:relative;z-index:1;width:min(1180px,92vw);margin:0 auto;padding:0 clamp(1rem,3vw,2rem)}" +
      "#cg-home-insights .cg-hi-head{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:28px;align-items:end;margin-bottom:36px}" +
      "#cg-home-insights .cg-hi-kicker{font-family:var(--mono,'IBM Plex Mono',monospace);font-size:11px;font-weight:700;letter-spacing:.2em;color:#67e8f9;margin-bottom:14px;text-transform:uppercase}" +
      "#cg-home-insights h2{font-family:var(--serif,'Cormorant Garamond',serif);font-size:clamp(2.7rem,6vw,5.8rem);font-weight:300;line-height:.98;letter-spacing:-.035em;max-width:820px;color:#fff;margin:0}" +
      "#cg-home-insights h2 strong{font-weight:600;background:linear-gradient(90deg,#67e8f9,#c4b5fd,#f0abfc);-webkit-background-clip:text;background-clip:text;color:transparent}" +
      "#cg-home-insights .cg-hi-intro{max-width:760px;margin-top:20px;color:rgba(226,232,240,.72);font-size:clamp(1rem,1.6vw,1.15rem);line-height:1.75}" +
      "#cg-home-insights .cg-hi-all{display:inline-flex;align-items:center;justify-content:center;min-height:46px;padding:0 20px;border:1px solid rgba(103,232,249,.3);border-radius:999px;color:#e6fbff;background:rgba(8,21,41,.55);backdrop-filter:blur(12px);text-decoration:none;font-size:13px;font-weight:700;white-space:nowrap;transition:transform .2s ease,border-color .2s ease,background .2s ease}" +
      "#cg-home-insights .cg-hi-all:hover,#cg-home-insights .cg-hi-all:focus-visible{transform:translateY(-2px);border-color:#67e8f9;background:rgba(103,232,249,.1);outline:none}" +
      "#cg-home-insights .cg-hi-grid{display:grid;grid-template-columns:minmax(0,1.38fr) minmax(0,.62fr);gap:18px;align-items:stretch}" +
      "#cg-home-insights .cg-hi-secondary{display:grid;grid-template-columns:1fr;gap:18px}" +
      "#cg-home-insights .cg-hi-card{min-width:0;border:1px solid rgba(148,163,184,.18);border-radius:24px;background:linear-gradient(155deg,rgba(255,255,255,.09),rgba(255,255,255,.035));box-shadow:0 24px 70px rgba(0,0,0,.24),inset 0 1px 0 rgba(255,255,255,.08);overflow:hidden;transform:translateY(14px);opacity:0;transition:transform .45s cubic-bezier(.2,.8,.2,1),opacity .45s ease,border-color .22s ease,box-shadow .22s ease}" +
      "#cg-home-insights .cg-hi-card.is-visible{transform:none;opacity:1}" +
      "#cg-home-insights .cg-hi-card--lead{min-height:520px;background:radial-gradient(circle at 80% 10%,rgba(103,232,249,.18),transparent 32%),linear-gradient(145deg,rgba(255,255,255,.105),rgba(255,255,255,.035))}" +
      "#cg-home-insights .cg-hi-link{display:flex;height:100%;min-height:100%;flex-direction:column;padding:clamp(24px,4vw,44px);text-decoration:none;color:inherit}" +
      "#cg-home-insights .cg-hi-secondary .cg-hi-link{padding:24px}" +
      "#cg-home-insights .cg-hi-meta{display:flex;flex-wrap:wrap;gap:8px;margin-bottom:24px}" +
      "#cg-home-insights .cg-hi-badge{display:inline-flex;align-items:center;min-height:29px;padding:0 10px;border:1px solid rgba(148,163,184,.22);border-radius:999px;font-family:var(--mono,'IBM Plex Mono',monospace);font-size:9.5px;letter-spacing:.12em;text-transform:uppercase;color:#cbd5e1;background:rgba(7,17,31,.36)}" +
      "#cg-home-insights .cg-hi-badge--rank{border-color:rgba(196,181,253,.42);color:#ddd6fe}" +
      "#cg-home-insights .cg-hi-badge--new{border-color:rgba(110,231,183,.38);color:#a7f3d0}" +
      "#cg-home-insights .cg-hi-title{font-family:var(--serif,'Cormorant Garamond',serif);font-weight:500;letter-spacing:-.025em;line-height:1.03;color:#fff;margin:0}" +
      "#cg-home-insights .cg-hi-card--lead .cg-hi-title{font-size:clamp(2.4rem,5vw,5rem);max-width:900px}" +
      "#cg-home-insights .cg-hi-secondary .cg-hi-title{font-size:clamp(1.55rem,2.8vw,2.15rem)}" +
      "#cg-home-insights .cg-hi-desc{margin-top:18px;color:rgba(226,232,240,.72);font-size:15px;line-height:1.72;max-width:780px}" +
      "#cg-home-insights .cg-hi-secondary .cg-hi-desc{display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden;font-size:13.5px;line-height:1.58}" +
      "#cg-home-insights .cg-hi-footer{display:flex;align-items:center;justify-content:space-between;gap:18px;margin-top:auto;padding-top:26px;font-family:var(--mono,'IBM Plex Mono',monospace);font-size:10px;letter-spacing:.08em;text-transform:uppercase;color:#94a3b8}" +
      "#cg-home-insights .cg-hi-action{color:#67e8f9;font-weight:700}" +
      "#cg-home-insights .cg-hi-card:hover{border-color:rgba(103,232,249,.42);box-shadow:0 28px 80px rgba(0,0,0,.34),0 0 34px rgba(56,189,248,.08),inset 0 1px 0 rgba(255,255,255,.1)}" +
      "#cg-home-insights .cg-hi-link:focus-visible{outline:2px solid #67e8f9;outline-offset:-4px;border-radius:22px}" +
      "@media(max-width:900px){#cg-home-insights .cg-hi-head{grid-template-columns:1fr;align-items:start}#cg-home-insights .cg-hi-grid{grid-template-columns:1fr}#cg-home-insights .cg-hi-secondary{grid-template-columns:repeat(3,minmax(0,1fr))}#cg-home-insights .cg-hi-card--lead{min-height:460px}}" +
      "@media(max-width:700px){#cg-home-insights{padding:72px 0}#cg-home-insights .cg-hi-shell{width:min(100%,94vw);padding:0 10px}#cg-home-insights .cg-hi-secondary{grid-template-columns:1fr}#cg-home-insights .cg-hi-card{border-radius:20px}#cg-home-insights .cg-hi-card--lead{min-height:500px}#cg-home-insights .cg-hi-link,#cg-home-insights .cg-hi-secondary .cg-hi-link{padding:24px 20px}#cg-home-insights .cg-hi-card--lead .cg-hi-title{font-size:clamp(2.45rem,11vw,4.25rem)}#cg-home-insights .cg-hi-footer{align-items:flex-end}.cg-hi-date{max-width:45%}}" +
      "@media(prefers-reduced-motion:reduce){#cg-home-insights .cg-hi-card{opacity:1;transform:none;transition:none}#cg-home-insights .cg-hi-all{transition:none}}";
    document.head.appendChild(style);
  }

  function addStructuredData(posts) {
    if (document.getElementById("cg-home-insights-jsonld")) return;
    var script = document.createElement("script");
    script.id = "cg-home-insights-jsonld";
    script.type = "application/ld+json";
    script.textContent = JSON.stringify({
      "@context": "https://schema.org",
      "@type": "ItemList",
      "name": "Featured ClearGlass Insights",
      "itemListElement": posts.map(function (post, index) {
        return {
          "@type": "ListItem",
          "position": index + 1,
          "url": assetUrl(post.url),
          "name": post.title
        };
      })
    });
    document.head.appendChild(script);
  }

  function prefetchOnIntent(root) {
    var links = root.querySelectorAll("a[data-insight-open]");
    Array.prototype.forEach.call(links, function (link) {
      var done = false;
      function prefetch() {
        if (done || !link.href) return;
        done = true;
        if (document.querySelector('link[rel="prefetch"][href="' + link.href.replace(/"/g, "\\\"") + '"]')) return;
        var hint = document.createElement("link");
        hint.rel = "prefetch";
        hint.href = link.href;
        document.head.appendChild(hint);
      }
      link.addEventListener("pointerenter", prefetch, { once: true, passive: true });
      link.addEventListener("focus", prefetch, { once: true });
    });
  }

  function reveal(root) {
    var cards = root.querySelectorAll(".cg-hi-card");
    if (reduceMotion || !("IntersectionObserver" in window)) {
      Array.prototype.forEach.call(cards, function (card) { card.classList.add("is-visible"); });
      return;
    }
    var observer = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (!entry.isIntersecting) return;
        entry.target.classList.add("is-visible");
        observer.unobserve(entry.target);
      });
    }, { rootMargin: "100px 0px", threshold: 0.08 });
    Array.prototype.forEach.call(cards, function (card, index) {
      card.style.transitionDelay = Math.min(index * 55, 165) + "ms";
      observer.observe(card);
    });
  }

  function mount(posts) {
    if (!posts || !posts.length || document.getElementById("cg-home-insights")) return;
    injectStyles();

    var section = make("section", "cg-home-insights");
    section.id = "cg-home-insights";
    section.setAttribute("aria-labelledby", "cg-home-insights-title");
    section.setAttribute("data-cg-home-insights", "ranked");

    var shell = make("div", "cg-hi-shell");
    var head = make("div", "cg-hi-head");
    var headCopy = make("div", "cg-hi-headcopy");
    headCopy.appendChild(make("div", "cg-hi-kicker", "INTELLIGENCE DESK · FEATURED ANALYSIS"));
    var heading = make("h2");
    heading.id = "cg-home-insights-title";
    heading.appendChild(document.createTextNode("Ideas engineered to "));
    var strong = make("strong", "", "earn attention.");
    heading.appendChild(strong);
    headCopy.appendChild(heading);
    headCopy.appendChild(make("p", "cg-hi-intro", "Deep sensing, without false certainty. The homepage now previews the highest-ranked published ClearGlass analysis directly from the Insights desk, with evidence-led briefs across AI, cybersecurity, OSINT, systems and frontier intelligence."));

    var all = make("a", "cg-hi-all", "Explore all Insights →");
    all.href = assetUrl("blog/");
    head.appendChild(headCopy);
    head.appendChild(all);

    var grid = make("div", "cg-hi-grid");
    grid.appendChild(buildCard(posts[0], true));
    var secondary = make("div", "cg-hi-secondary");
    posts.slice(1).forEach(function (post) { secondary.appendChild(buildCard(post, false)); });
    grid.appendChild(secondary);

    shell.appendChild(head);
    shell.appendChild(grid);
    section.appendChild(shell);

    var anchor = document.getElementById("timeline") || document.getElementById("founder") || document.querySelector("footer");
    if (anchor && anchor.parentNode) anchor.parentNode.insertBefore(section, anchor);
    else {
      var main = document.querySelector("main") || document.body;
      main.appendChild(section);
    }

    addStructuredData(posts);
    prefetchOnIntent(section);
    reveal(section);

    section.addEventListener("click", function (event) {
      var link = event.target.closest ? event.target.closest("a[data-insight-open]") : null;
      if (!link) return;
      try {
        window.dispatchEvent(new CustomEvent("cg:insight-open", {
          detail: { slug: link.getAttribute("data-insight-open") || "", href: link.href }
        }));
      } catch (e) {}
    });

    try {
      window.dispatchEvent(new CustomEvent("cg:insights-mounted", {
        detail: { count: posts.length, source: "blog/posts.json", ranking: "deskRank" }
      }));
    } catch (e) {}
  }

  fetch(assetUrl("blog/posts.json"), { cache: "no-cache", credentials: "same-origin" })
    .then(function (response) {
      if (!response.ok) throw new Error("Insights index unavailable: " + response.status);
      return response.json();
    })
    .then(function (data) {
      var posts = data && Array.isArray(data.posts) ? data.posts.slice() : [];
      posts = posts.filter(function (post) {
        return post && post.status === "published" && post.featured === true && post.title && post.url;
      });
      posts.sort(function (a, b) {
        var rankDelta = postRank(a) - postRank(b);
        if (rankDelta) return rankDelta;
        return String(b.date || "").localeCompare(String(a.date || ""));
      });
      mount(posts.slice(0, MAX_POSTS));
    })
    .catch(function () {
      document.documentElement.setAttribute("data-cg-home-insights", "degraded");
    });
})();
