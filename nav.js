/* ClearGlass · homepage-matched global navigation.
   Injects the same premium glass top bar, complete product catalog, mobile menu,
   and clear CTA language on every static page without removing page content. */
(function () {
  "use strict";
  if (window.__cgNavLoaded) return;
  window.__cgNavLoaded = true;

  var PRODUCTS = [
    ["Artemis IV Core", "artemis-iv.html", "Tactical intelligence core", "🧭"],
    ["Artemis VI", "artemis.html", "Ontario intelligence deployment", "🛰"],
    ["Artemis OS", "artemis-os.html", "Intelligence operating system", "◎"],
    ["Artemis 2040", "artemis-2040.html", "Long-horizon intelligence", "◌"],
    ["Artemis Self-Evolving", "artemis-self-evolving-platform.html", "Governed improvement loop", "↻"],
    ["AI Cyber Intelligence", "artemis-ai-cyber-intelligence-platform.html", "Cyber intelligence platform", "✦"],
    ["AVALON · Artemis + Percival", "artemis-percival.html", "Unified fusion core", "⬣"],
    ["PERCIVAL OS", "percival-os.html", "Governed command center", "◐"],
    ["SENTINEL", "sentinel.html", "Live geospatial command", "◉"],
    ["GUARDIAN", "guardian.html", "Intelligence command interface", "🌐"],
    ["BLUEDESK", "bluedesk.html", "CISO risk console", "🛡"],
    ["BLUEDESK Mobile", "bluedesk-mobile.html", "Phone-first risk console", "▣"],
    ["ClearGlass NEXUS", "clearglass-nexus.html", "Full-spectrum intelligence", "◆"],
    ["NEXUS v12", "ClearGlass-NEXUS-v12-FINAL.html", "Flagship platform build", "◇"],
    ["Intelligence Command Surface", "intelligence-command-surface.html", "Unified operational picture", "🗺"],
    ["Intelligence Interface", "intelligence-interface.html", "Analyst workspace", "🖥"],
    ["Flowsint", "flowsint.html", "OSINT investigation graph", "🕸"],
    ["Network Flow Intelligence", "clearglass.html", "Living network structure", "⌁"],
    ["Ontario OSINT Deck", "Ontario-osint.html", "Regional OSINT control", "⌖"],
    ["Agent Mesh", "agentmesh.html", "Multi-agent orchestration", "⌗"],
    ["AI Operator Workspace", "ai-operator.html", "Human-in-the-loop ops", "🜂"],
    ["CONDUIT", "conduit.html", "Self-hosted automation", "⟿"],
    ["PostLoop", "postloop.html", "Content engine", "⟲"],
    ["AutoMap", "automap.html", "Architecture orchestration", "⌘"],
    ["Command Console", "command-console.html", "Cyber operations hub", "▤"],
    ["Event Control Surface", "saas-platform.html", "Event-driven operations", "◆"],
    ["Systems Console", "systems.html", "PERCIVAL operations", "▦"],
    ["Control Surface", "control-surface.html", "Live command dashboard", "▧"],
    ["CG OS", "CG-os.html", "ClearGlass command HUD", "◫"],
    ["Command Center", "command-center.html", "Executive operations deck", "⌁"],
    ["Platform Command Center", "platform-command-center.html", "Live monorepo dashboard", "🗂"],
    ["Authority Network", "authority-network.html", "Connected knowledge graph", "🔗"],
    ["CLEARSIGHT", "clearsight.html", "Edge-AI camera vision", "🎥"],
    ["ZEPHYR Air Control", "air-control.html", "Air systems control", "🜁"],
    ["Air Systems Control", "air-systems-control.html", "Airspace control surface", "✈"],
    ["ClearPulse", "clearpulse.html", "Healthcare intelligence", "📡"],
    ["ClearPulse Architecture", "clearpulse-architecture.html", "Forensic-AI whitepaper", "✚"],
    ["AEGIS", "aegis.html", "Legal process shield", "⚖"],
    ["ClearCounsel", "corporate-legal-advisor.html", "Corporate legal AI", "§"],
    ["ClearBank Legal AI", "banking-law-advisor.html", "Banking law intelligence", "🏦"],
    ["ClearTax AI", "tax.html", "Tax intelligence", "🧾"],
    ["Government Solutions", "government.html", "Public-sector systems", "🏛"],
    ["Counter-UAS OS", "counter-uas-commercialization-os.html", "Counter-drone platform", "◎"],
    ["Speed Vision AI", "traffic-enforcement.html", "Traffic enforcement AI", "◈"],
    ["SATS Digital Twin", "sats-digital-twin.html", "Transit simulation", "▱"],
    ["SMB Suite", "smb.html", "Small-business systems", "▰"],
    ["SMB Cyber Trust Kit", "smb-cyber-trust-kit.html", "Cyber resilience kit", "🔐"],
    ["Revenue Engine", "revenue-engine.html", "AI growth system", "💹"],
    ["Opal-Koboi Assets", "products/opal-koboi/index.html", "Product asset library", "✧"],
    ["Artemis IV Core · Asset", "products/opal-koboi/artemis-iv-core.html", "Product sheet", "🧭"],
    ["Artemis VI · Asset", "products/opal-koboi/artemis-vi.html", "Product sheet", "🛰"],
    ["Guardian · Asset", "products/opal-koboi/guardian.html", "Product sheet", "🌐"],
    ["Revenue Engine · Asset", "products/opal-koboi/revenue-engine.html", "Product sheet", "💹"],
    ["SMB Suite · Asset", "products/opal-koboi/smb-suite.html", "Product sheet", "▰"],
    ["Ultra Glass", "ultra-glass.html", "Glass intelligence UI", "◫"],
    ["ClearGlass Ultra", "clearglass-ultra.html", "See-through command UI", "◩"],
    ["Aurora Glass", "futuristic.html", "Design study", "✺"],
    ["Button System", "button-system.html", "Glass UI components", "◍"],
    ["Button Lab", "button-lab.html", "Control components", "◌"],
    ["Hover Menu", "hover-menu.html", "Glass interaction study", "◔"],
    ["Web Design & Development", "web-design.html", "Growth infrastructure", "💻"],
    ["Store", "store.html", "Book an engagement", "🛒"],
    ["Side Store", "side-store.html", "Electronics and components", "🔌"],
    ["Advanced Systems Catalog", "advanced-features-tools-systems.html", "Governed systems index", "▨"],
    ["Artemis Blue Team", "artemis-blue-team.html", "Defensive automation", "🛡"],
    ["Cyber Defense Console", "cyber-defense-console.html", "Command center brief", "▤"],
    ["Environmental Cyber Risk", "environmental-cyber-risk.html", "Environmental threat model", "♧"],
    ["StegoForge", "stegoforge.html", "Media assurance terminal", "🖼"],
    ["ATT&CK Prompt Core", "attack-prompt-core.html", "Threat-informed prompt core", "🎯"],
    ["Minerals Intelligence Platform", "minerals-platform.html", "Critical-minerals command center", "⛏"],
    ["Intelligence Platform", "intelligence-platform.html", "Full-stack intel architecture", "✦"],
    ["Intelligence Services", "intelligence.html", "Advisory and OSINT", "◈"],
    ["Percival Build", "percival-build.html", "Build architecture", "◐"],
    ["Procurement Legal Tech", "procurement-legal-tech.html", "Procurement integrity AI", "⚖"],
    ["Pricing", "pricing.html", "Plans and engagements", "₵"]
  ];
  var TOP = [["Vision","index.html#vision"],["Services","index.html#services"],["Products","products.html"],["Government","index.html#government"],["Insights","blog/"],["Contact","index.html#contact"]];
  var COMPANY = [["Authority Grid", "authority-network.html", "⌁"]];
  var script = document.currentScript || Array.prototype.slice.call(document.scripts).filter(function(s){return /nav\.js(?:\?|$)/.test(s.src);}).pop();
  var base = script ? new URL('.', script.src).href : new URL('.', location.href).href;
  function href(path){ return /^https?:|^mailto:|^#/.test(path) ? path : new URL(path, base).href; }
  var here = (location.pathname.split('/').pop() || 'index.html').toLowerCase();
  function esc(s){return String(s).replace(/[&<>\"]/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;'}[c];});}
  var css = [
    ".cg-native-nav-hidden,.cg-native-header-hidden{display:none!important}.cg-global-nav-enabled{--cg-unified-nav-offset:clamp(82px,7vw,108px)}",
    ".cg-topnav{position:fixed;top:clamp(10px,1.25vw,18px);left:50%;transform:translateX(-50%);width:min(1480px,calc(100% - clamp(1rem,2.4vw,3rem)));z-index:2147483000;min-height:76px;display:flex;align-items:center;justify-content:space-between;gap:clamp(.75rem,1.5vw,1.75rem);padding:clamp(.5rem,.7vw,.7rem) clamp(.75rem,1.2vw,1.25rem);border-radius:999px;border:1px solid rgba(221,228,255,.78);background:linear-gradient(90deg,rgba(233,241,255,.26),rgba(20,31,61,.88) 13%,rgba(11,18,38,.94) 48%,rgba(41,32,82,.9) 78%,rgba(139,92,246,.32));backdrop-filter:blur(34px) saturate(1.85);-webkit-backdrop-filter:blur(34px) saturate(1.85);box-shadow:0 30px 88px rgba(18,24,52,.18),0 16px 44px rgba(87,54,170,.26),inset 0 1px 0 rgba(255,255,255,.72),inset 0 -1px 0 rgba(196,142,255,.72),0 0 0 1px rgba(133,163,255,.22);font-family:Urbanist,Inter,system-ui,sans-serif;isolation:isolate;overflow:visible;transition:transform .24s cubic-bezier(.4,0,.2,1),opacity .18s ease,visibility 0s linear;will-change:transform,opacity}",
    ".cg-topnav.cg-scroll-hidden{transform:translate(-50%,calc(-100% - 32px));opacity:0;visibility:hidden;pointer-events:none;transition-delay:0s,0s,.24s}",
    ".cg-topnav *{box-sizing:border-box}.cg-brand{position:relative;display:flex;align-items:center;gap:clamp(9px,1vw,14px);min-width:max-content;color:#f9fbff;text-decoration:none}.cg-mark{width:54px;height:54px;border-radius:50%;display:grid;place-items:center;overflow:hidden;flex:0 0 auto}.cg-mark img{width:96%;height:96%;object-fit:contain;border-radius:50%}.cg-name{font-family:'Cormorant Garamond',Georgia,serif;font-size:clamp(1.15rem,1.55vw,1.75rem);font-weight:650;white-space:nowrap}.cg-name em{font-style:italic;font-weight:400;color:#cbb7ff;margin-left:.32rem}",
    ".cg-links{display:flex;align-items:center;gap:clamp(.15rem,.45vw,.5rem);margin-left:auto}.cg-links a,.cg-dropbtn{color:rgba(242,246,255,.93);text-decoration:none;font-size:clamp(.78rem,.78vw,.9rem);font-weight:650;padding:10px 9px 13px;border-radius:15px;border:0;background:transparent;cursor:pointer}.cg-links a:hover,.cg-dropbtn:hover{color:#fff;background:rgba(255,255,255,.065)}",
    ".cg-cta{display:inline-flex!important;align-items:center;gap:8px;background:linear-gradient(180deg,rgba(11,14,28,.98),rgba(3,5,13,.99))!important;color:#fff!important;margin-left:clamp(.45rem,1vw,1.15rem);padding:11px 16px!important;border:1px solid rgba(205,146,255,.82)!important;border-radius:15px!important}",
    ".cg-drop{position:relative}.cg-menu{position:absolute;top:calc(100% + 10px);left:50%;transform:translateX(-50%) translateY(-6px);width:min(900px,92vw);max-height:min(72vh,720px);overflow:auto;display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:7px;padding:10px;background:rgba(16,24,50,.96);border:1px solid rgba(185,156,255,.36);border-radius:24px;opacity:0;pointer-events:none;visibility:hidden;transition:opacity .18s,transform .18s,visibility 0s linear .18s}.cg-drop:hover .cg-menu,.cg-drop.is-open .cg-menu{opacity:1;pointer-events:auto;visibility:visible;transform:translateX(-50%) translateY(0);transition-delay:0s}.cg-dropcaret{margin-left:-6px;border:0;background:transparent;color:rgba(242,246,255,.93);font-size:.9rem;line-height:1;padding:10px 6px 13px;border-radius:12px;cursor:pointer}.cg-dropcaret:hover{color:#fff;background:rgba(255,255,255,.065)}.cg-dropcaret[aria-expanded='true']{color:#fff;background:rgba(255,255,255,.1)}.cg-prod{display:flex!important;gap:10px!important;align-items:center!important;padding:8px!important;border-radius:12px!important;color:#eef4ff!important;text-decoration:none}.cg-ic{width:26px;height:26px;border-radius:10px;background:rgba(255,255,255,.08);display:grid;place-items:center;flex:0 0 auto}",
    ".cg-toggle{display:none;border:1px solid rgba(196,139,255,.55);background:rgba(7,10,24,.7);color:#fff;border-radius:14px;padding:10px}.cg-mobile{position:fixed;top:104px;left:.75rem;right:.75rem;z-index:2147482999;display:none;grid-template-columns:1fr;gap:4px;max-height:calc(100vh - 120px);overflow:auto;padding:10px;background:rgba(16,24,50,.98);border:1px solid rgba(185,156,255,.36);border-radius:24px}.cg-mobile.open{display:grid}.cg-mobile a{padding:12px 14px;border-radius:12px;text-decoration:none;color:#eef4ff;font-weight:650}.cg-label{font-family:'IBM Plex Mono',monospace;font-size:10px;letter-spacing:.15em;text-transform:uppercase;color:#aeb9d5;padding:10px 14px 4px}",
    ".cg-topnav+main,.cg-topnav~main{scroll-margin-top:106px}.cg-topnav~:is(main,.page,.wrap){padding-top:max(104px,env(safe-area-inset-top))}@media(max-width:1240px){.cg-links{display:none}.cg-toggle{display:block}.cg-topnav{min-height:68px}.cg-mark{width:48px;height:48px}.cg-menu{grid-template-columns:1fr}}@media(max-width:760px){.cg-topnav{top:6px;width:calc(100% - .75rem);min-height:58px;padding:.35rem .65rem}.cg-name{font-size:18px}.cg-name em{display:none}.cg-mark{width:42px;height:42px}.cg-mobile{top:72px;max-height:calc(100vh - 84px)}}",
    // Motion is optional: the nav slide, the dropdown fades and smooth
    // scrolling collapse to instant state changes when the viewer has
    // asked their OS for reduced motion.
    "@media (prefers-reduced-motion: reduce){.cg-topnav,.cg-topnav.cg-scroll-hidden,.cg-menu,.cg-mobile,.cg-toggle{transition:none!important;animation:none!important}.cg-topnav{will-change:auto}html{scroll-behavior:auto!important}}",
    /* Visually-hidden label for the catalog disclosure button. Without this
       rule its "Show all products" text renders as literal text beside the
       caret, so the rule and the markup must ship together. */
    ".cg-sr-only{position:absolute!important;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0}",
    ".cg-topnav :is(a,button):focus-visible,.cg-mobile a:focus-visible{outline:3px solid #fff;outline-offset:2px;box-shadow:0 0 0 6px rgba(146,180,255,.55)}",
    ".cg-links a[aria-current=\"page\"],.cg-mobile a[aria-current=\"page\"]{color:#fff;background:rgba(255,255,255,.12)}.cg-links a[aria-current=\"page\"]:after{opacity:1;transform:translateX(-50%) scaleX(1.35)}.cg-mobile a[aria-current=\"page\"]{box-shadow:inset 3px 0 0 #ca78ff}"
  ].join("");
  function isNativePrimaryNav(el){
    if (!el || el.id === 'cg-global-nav' || el.id === 'cg-mobile-nav') return false;
    if (el.closest('#cg-related,footer,.footer,.site-footer,.gov-footer,.cgr-box,.cg-topnav,.cg-mobile')) return false;
    var label = (el.getAttribute('aria-label') || '').toLowerCase();
    var cls = (' ' + (el.className || '') + ' ').toLowerCase();
    var id = (' ' + (el.id || '') + ' ').toLowerCase();
    if (/related|footer|breadcrumb|pagination|tabs|subnav|secondary/.test(label + cls + id)) return false;
    if (el.closest('header,.st-header,.site-header,.topbar,.navbar,.cg-command-bar')) return true;
    if (/primary|main|navigation/.test(label)) return true;
    return /( nav | navbar | topbar | header-nav | ag-nav | site-nav | cg-nav )/.test(cls) || /( navbar | nav )/.test(id);
  }
  function hideNativeNavigation(root){
    var scope = root && root.querySelectorAll ? root : document;
    Array.prototype.forEach.call(scope.querySelectorAll('nav,[role="navigation"]'), function(el){
      if (!isNativePrimaryNav(el)) return;
      el.classList.add('cg-native-nav-hidden');
      var shell = el.closest('header,.st-header,.site-header,.topbar,.navbar,.cg-command-bar');
      if (shell && shell !== document.body && !shell.closest('footer,.footer,.site-footer,.cgr-box')) shell.classList.add('cg-native-header-hidden');
    });
    document.body.classList.add('cg-global-nav-enabled');
  }
  /* ── accessibility primitives ────────────────────────────────────────────
     The injected chrome is the site's only navigation, so it has to carry the
     full keyboard contract itself: a bypass link, an honest active-route
     signal, and modal surfaces that trap, restore, and release focus. */
  var FOCUSABLE = 'a[href],button:not([disabled]),input:not([disabled]),select:not([disabled]),textarea:not([disabled]),[tabindex]:not([tabindex="-1"])';

  function focusables(root){
    return Array.prototype.filter.call(root.querySelectorAll(FOCUSABLE), function(el){
      // checkVisibility also accounts for visibility:hidden and opacity:0,
      // which still report client rects but are not in the tab order.
      if (typeof el.checkVisibility === 'function'){
        return el.checkVisibility({ visibilityProperty: true, opacityProperty: true });
      }
      return el.getClientRects().length > 0;
    });
  }

  function trapFocus(container, event){
    var items = focusables(container);
    if (!items.length) return;
    var first = items[0], last = items[items.length - 1];
    if (event.shiftKey && document.activeElement === first){ event.preventDefault(); last.focus(); }
    else if (!event.shiftKey && document.activeElement === last){ event.preventDefault(); first.focus(); }
  }

  /* Closing the drawer is also driven by the scroll handler, so the closer is
     shared rather than duplicated — otherwise a scroll-close would strand focus
     on an element that is no longer rendered. */
  var closeDrawer = function(){};
  var drawerIsOpen = function(){ return false; };

  /* The skip link is owned by cg-a11y.js, not here. That module ships the
     .cg-skip styles and runs on every page regardless of which navigation
     system the page loads, so duplicating the injection in nav.js risked an
     unstyled, permanently visible link whenever nav.js won the race. */

  function markActiveRoute(scope){
    var matches = [];
    Array.prototype.forEach.call(scope.querySelectorAll('a[href]'), function(a){
      var url;
      try { url = new URL(a.href, location.href); } catch (e) { return; }
      if (url.host !== location.host){
        // Indicate off-site destinations without changing the visual chrome.
        a.setAttribute('rel', 'noopener noreferrer');
        a.setAttribute('data-cg-external', 'true');
        return;
      }
      var file = (url.pathname.split('/').pop() || 'index.html').toLowerCase();
      // Section links (index.html#services) share a file with the page itself;
      // requiring the hash to match keeps section links from all matching home.
      if (file === here && (!url.hash || url.hash === location.hash)) matches.push(a);
    });
    // The catalog menu repeats destinations that already appear in the top-level
    // bar (Products → products.html, and "All Products" inside it). Marking every
    // copy would announce the same page as current several times, so only the
    // first — the top-level entry — carries the state.
    if (matches.length) matches[0].setAttribute('aria-current', 'page');
  }

  function installProductsDisclosure(nav){
    var drop = nav.querySelector('.cg-drop');
    var caret = nav.querySelector('.cg-dropcaret');
    var menu = nav.querySelector('#cg-products-menu');
    if (!drop || !caret || !menu) return;
    function setOpen(open){
      drop.classList.toggle('is-open', open);
      caret.setAttribute('aria-expanded', open ? 'true' : 'false');
    }
    caret.addEventListener('click', function(){
      var willOpen = caret.getAttribute('aria-expanded') !== 'true';
      setOpen(willOpen);
      if (willOpen){ var f = focusables(menu); if (f[0]) f[0].focus(); }
    });
    drop.addEventListener('keydown', function(e){
      if (e.key === 'Escape' && drop.classList.contains('is-open')){
        e.stopPropagation();
        setOpen(false);
        caret.focus();
      }
    });
    drop.addEventListener('focusout', function(){
      window.setTimeout(function(){
        if (!drop.contains(document.activeElement)) setOpen(false);
      }, 0);
    });
    document.addEventListener('click', function(e){
      if (drop.classList.contains('is-open') && !drop.contains(e.target)) setOpen(false);
    });
  }

  function installMobileDrawer(btn, mob){
    var lastFocus = null;
    function setOpen(open){
      mob.classList.toggle('open', open);
      btn.setAttribute('aria-expanded', open ? 'true' : 'false');
      btn.setAttribute('aria-label', open ? 'Close navigation' : 'Open navigation');
      if (open){
        lastFocus = document.activeElement;
        var f = focusables(mob);
        if (f[0]) f[0].focus();
      } else if (lastFocus && lastFocus.focus){
        lastFocus.focus();
        lastFocus = null;
      }
    }
    btn.addEventListener('click', function(){ setOpen(!mob.classList.contains('open')); });
    mob.addEventListener('keydown', function(e){ if (e.key === 'Tab') trapFocus(mob, e); });
    mob.addEventListener('click', function(e){ if (e.target.closest('a')) setOpen(false); });
    document.addEventListener('keydown', function(e){
      if (e.key === 'Escape' && mob.classList.contains('open')) setOpen(false);
    });
    closeDrawer = function(){ if (mob.classList.contains('open')) setOpen(false); };
    drawerIsOpen = function(){ return mob.classList.contains('open'); };
  }

  /* The Cmd/Ctrl+K command palette that used to live here was removed when
     global-nav-search.js landed: that module binds the same Cmd/Ctrl+K (and
     "/") and provides site-wide search, so keeping both meant two overlays
     opening on one keystroke. Search is now owned there, not here. */

  function build(){
    if (document.getElementById('cg-global-nav')) return;
    var st=document.createElement('style'); st.textContent=css; document.head.appendChild(st);
    hideNativeNavigation(document);
    var nav=document.createElement('nav'); nav.id='cg-global-nav'; nav.className='cg-topnav'; nav.setAttribute('aria-label','Primary navigation');
    var menu=PRODUCTS.map(function(p){return '<a class="cg-prod" href="'+href(p[1])+'"><span class="cg-ic">'+p[3]+'</span><span><b>'+esc(p[0])+'</b><small>'+esc(p[2])+'</small></span></a>';}).join('');
    menu+=COMPANY.map(function(c){return '<a class="cg-prod" href="'+href(c[1])+'"><span class="cg-ic">'+c[2]+'</span><span><b>'+esc(c[0])+'</b><small>Company</small></span></a>';}).join('');
    nav.innerHTML='<a class="cg-brand" href="'+href('index.html')+'"><span class="cg-mark logo-orb" aria-hidden="true"><img src="'+href('assets/images/clearglass-logo-256.webp')+'" alt="" class="site-logo"></span><span class="cg-name">ClearGlassInc. <em>2040</em></span></a><div class="cg-links">'+TOP.map(function(t){return t[0]==='Products'?'<span class="cg-drop"><a class="cg-dropbtn" href="'+href('products.html')+'">Products</a><button type="button" class="cg-dropcaret" aria-expanded="false" aria-controls="cg-products-menu"><span class="cg-sr-only">Show all products</span><span aria-hidden="true">⌄</span></button><span class="cg-menu" id="cg-products-menu"><a class="cg-prod" href="'+href('products.html')+'"><span class="cg-ic">▨</span><span><b>All Products</b><small>Unified catalog</small></span></a>'+menu+'</span></span>':'<a href="'+href(t[1])+'">'+t[0]+'</a>';}).join('')+'<a class="cg-cta" href="'+href('store.html')+'">Book a Security Engagement</a></div><button class="cg-toggle" aria-label="Open navigation" aria-expanded="false">☰</button>';
    var mob=document.createElement('div'); mob.className='cg-mobile'; mob.id='cg-mobile-nav'; mob.innerHTML='<div class="cg-label">Navigation</div>'+TOP.map(function(t){return '<a href="'+href(t[1])+'">'+t[0]+'</a>';}).join('')+'<a href="'+href('store.html')+'">Book a Security Engagement</a><div class="cg-label">Products</div>'+PRODUCTS.map(function(p){return '<a href="'+href(p[1])+'">'+esc(p[0])+'</a>';}).join('');
    document.body.appendChild(nav); document.body.appendChild(mob);
    hideNativeNavigation(document);
    var observer=new MutationObserver(function(mutations){mutations.forEach(function(m){Array.prototype.forEach.call(m.addedNodes,function(node){if(node && node.nodeType===1) hideNativeNavigation(node.parentNode || node);});});});
    observer.observe(document.body,{childList:true,subtree:true});
    // These wire up the keyboard contract. They were defined but never called
    // for two releases after a merge resolved this block to the pre-contract
    // version, leaving the drawer untrapped and the catalog unopenable by
    // keyboard while the functions sat as dead code. Keep the calls together
    // with the definitions when resolving conflicts here.
    mob.setAttribute('aria-label','Site navigation');
    var btn=nav.querySelector('.cg-toggle');
    btn.setAttribute('aria-controls','cg-mobile-nav');
    markActiveRoute(nav);
    markActiveRoute(mob);
    installProductsDisclosure(nav);
    installMobileDrawer(btn,mob);
  }
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',build);else build();
})();