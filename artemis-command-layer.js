(function(){
  'use strict';
  var reduce=window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  var cards=document.querySelectorAll('.tech-card,.product-card,.command-panel,.ops-card,.value-card');
  cards.forEach(function(card){
    card.classList.add('artemis-instrumented');
    var corner=document.createElement('span');
    corner.className='artemis-corner';
    corner.setAttribute('aria-hidden','true');
    card.appendChild(corner);
    if(!reduce){card.addEventListener('pointermove',function(event){
      var bounds=card.getBoundingClientRect();
      card.style.setProperty('--mx',(event.clientX-bounds.left)+'px');
      card.style.setProperty('--my',(event.clientY-bounds.top)+'px');
    },{passive:true});}
  });
  var toggle=document.querySelector('.artemis-toggle');
  if(toggle){toggle.addEventListener('click',function(){
    var active=toggle.getAttribute('aria-pressed')==='true';
    toggle.setAttribute('aria-pressed',String(!active));
    toggle.classList.toggle('is-active',!active);
    document.documentElement.classList.toggle('artemis-telemetry-off',active);
  });}
})();

/* ClearGlassInc Artemis Elite Mission Control layer.
   Additive only: extends existing components without replacing page content,
   routes, forms, analytics, products, navigation, or deployment behavior. */
(function(){
  'use strict';

  if(document.documentElement.dataset.artemisElite==='ready') return;
  document.documentElement.dataset.artemisElite='ready';

  var motionQuery=window.matchMedia('(prefers-reduced-motion: reduce)');
  var finePointer=window.matchMedia('(pointer:fine)');
  var style=document.createElement('style');
  style.id='artemis-elite-runtime';
  style.textContent=`
    :root{
      --cg-elite-cyan:#56e7ff;
      --cg-elite-blue:#38bdf8;
      --cg-elite-violet:#a78bfa;
      --cg-elite-green:#34d399;
      --cg-elite-ink:#050811;
      --cg-elite-ease:cubic-bezier(.4,0,.2,1);
    }
    html[data-artemis-elite="ready"] .artemis-instrumented{
      isolation:isolate;
      transform:translateZ(0);
    }
    html[data-artemis-elite="ready"] .artemis-instrumented>.artemis-energy-line{
      position:absolute;
      z-index:3;
      left:14px;
      right:14px;
      bottom:0;
      height:1px;
      pointer-events:none;
      opacity:.54;
      background:linear-gradient(90deg,transparent,rgba(86,231,255,.86),rgba(167,139,250,.7),transparent);
      box-shadow:0 0 14px rgba(86,231,255,.24);
      transform:scaleX(.34);
      transform-origin:center;
      transition:transform .42s var(--cg-elite-ease),opacity .42s var(--cg-elite-ease);
    }
    html[data-artemis-elite="ready"] .artemis-instrumented:hover>.artemis-energy-line,
    html[data-artemis-elite="ready"] .artemis-instrumented:focus-within>.artemis-energy-line{
      opacity:.95;
      transform:scaleX(1);
    }
    html[data-artemis-elite="ready"] .artemis-instrumented>.artemis-sweep{
      position:absolute;
      z-index:1;
      top:-40%;
      bottom:-40%;
      width:18%;
      left:-32%;
      pointer-events:none;
      opacity:0;
      transform:skewX(-18deg) translate3d(0,0,0);
      background:linear-gradient(90deg,transparent,rgba(255,255,255,.16),rgba(86,231,255,.09),transparent);
      filter:blur(1px);
    }
    html[data-artemis-elite="ready"] .artemis-instrumented.is-artemis-sweeping>.artemis-sweep{
      animation:artemisEliteSweep 1.45s var(--cg-elite-ease) 1;
    }
    html[data-artemis-elite="ready"] .btn{
      min-height:44px;
      overflow:hidden;
      transform:translateZ(0);
    }
    html[data-artemis-elite="ready"] .btn::after{
      content:"";
      position:absolute;
      z-index:2;
      top:-70%;
      bottom:-70%;
      left:-35%;
      width:22%;
      pointer-events:none;
      opacity:0;
      background:linear-gradient(90deg,transparent,rgba(255,255,255,.58),rgba(86,231,255,.2),transparent);
      transform:skewX(-18deg);
      transition:opacity .2s ease;
    }
    html[data-artemis-elite="ready"] .btn:hover::after,
    html[data-artemis-elite="ready"] .btn:focus-visible::after{
      opacity:.7;
      animation:artemisEliteButtonSweep .9s var(--cg-elite-ease) 1;
    }
    html[data-artemis-elite="ready"] .btn:active{
      transform:translateY(1px) scale(.985);
    }
    html[data-artemis-elite="ready"] .artemis-controls{
      padding:8px;
      border:1px solid rgba(86,231,255,.18);
      border-radius:999px;
      background:linear-gradient(135deg,rgba(255,255,255,.68),rgba(239,248,255,.46));
      box-shadow:0 14px 42px rgba(7,17,31,.09),0 0 0 1px rgba(167,139,250,.06),inset 0 1px 0 rgba(255,255,255,.88);
      -webkit-backdrop-filter:blur(18px) saturate(1.28);
      backdrop-filter:blur(18px) saturate(1.28);
    }
    html[data-artemis-elite="ready"] .artemis-controls::before{
      content:"MISSION CONTROL";
      align-self:center;
      padding:0 5px 0 3px;
      font:700 7px/1 var(--mono,monospace);
      letter-spacing:.16em;
      color:rgba(7,17,31,.42);
    }
    html[data-artemis-elite="ready"] .artemis-toggle,
    html[data-artemis-elite="ready"] .artemis-chip{
      position:relative;
      overflow:hidden;
    }
    html[data-artemis-elite="ready"] .artemis-toggle::after,
    html[data-artemis-elite="ready"] .artemis-chip::after{
      content:"";
      position:absolute;
      left:10%;
      right:10%;
      bottom:0;
      height:1px;
      opacity:.2;
      background:linear-gradient(90deg,transparent,var(--cg-elite-cyan),transparent);
      transition:opacity .25s ease,transform .25s ease;
      transform:scaleX(.4);
    }
    html[data-artemis-elite="ready"] .artemis-toggle:hover::after,
    html[data-artemis-elite="ready"] .artemis-toggle:focus-visible::after,
    html[data-artemis-elite="ready"] .artemis-chip:hover::after,
    html[data-artemis-elite="ready"] .artemis-chip:focus-visible::after{
      opacity:.9;
      transform:scaleX(1);
    }
    html[data-artemis-elite="ready"] .artemis-elite-status{
      display:inline-flex;
      align-items:center;
      gap:7px;
      min-height:34px;
      padding:7px 11px;
      border-radius:999px;
      border:1px solid rgba(52,211,153,.22);
      background:rgba(240,253,250,.58);
      color:#08765f;
      box-shadow:inset 0 1px rgba(255,255,255,.85),0 8px 26px rgba(7,17,31,.05);
      font:700 8px/1 var(--mono,monospace);
      letter-spacing:.11em;
      text-transform:uppercase;
      white-space:nowrap;
    }
    html[data-artemis-elite="ready"] .artemis-elite-status i{
      width:7px;
      height:7px;
      border-radius:50%;
      background:var(--cg-elite-green);
      box-shadow:0 0 0 4px rgba(52,211,153,.12),0 0 13px rgba(52,211,153,.66);
      animation:artemisElitePulse 2.35s var(--cg-elite-ease) infinite;
    }
    html[data-artemis-elite="ready"] .hero-command-rail .hero-signal{
      position:relative;
      overflow:hidden;
    }
    html[data-artemis-elite="ready"] .hero-command-rail .hero-signal::after{
      content:"";
      position:absolute;
      inset:auto 12px 0;
      height:1px;
      opacity:.32;
      background:linear-gradient(90deg,transparent,rgba(86,231,255,.78),transparent);
    }
    html[data-artemis-elite="ready"] .hero-options .hero-option,
    html[data-artemis-elite="ready"] .hero-command-rail .hero-signal,
    html[data-artemis-elite="ready"] .artemis-controls{
      will-change:transform,opacity;
    }
    html[data-artemis-elite="ready"] .artemis-elite-reveal{
      opacity:0;
      transform:translate3d(0,24px,0) scale(.988);
      transition:opacity .72s var(--cg-elite-ease),transform .72s var(--cg-elite-ease);
      transition-delay:var(--artemis-delay,0ms);
    }
    html[data-artemis-elite="ready"] .artemis-elite-reveal.is-artemis-visible{
      opacity:1;
      transform:translate3d(0,0,0) scale(1);
    }
    html[data-artemis-elite="ready"] .nav.artemis-nav-energy{
      box-shadow:0 10px 34px rgba(10,12,16,.08),0 0 0 1px rgba(86,231,255,.05),0 0 28px rgba(56,189,248,.045);
    }
    html[data-artemis-elite="ready"] .nav.artemis-nav-energy.scrolled{
      box-shadow:0 14px 38px rgba(10,12,16,.12),0 0 0 1px rgba(86,231,255,.08),0 0 30px rgba(56,189,248,.06);
    }
    @supports not ((backdrop-filter:blur(1px)) or (-webkit-backdrop-filter:blur(1px))){
      html[data-artemis-elite="ready"] .artemis-controls{background:rgba(248,251,255,.97)}
    }
    @keyframes artemisElitePulse{
      50%{box-shadow:0 0 0 8px rgba(52,211,153,0),0 0 18px rgba(52,211,153,.78)}
    }
    @keyframes artemisEliteSweep{
      0%{left:-32%;opacity:0}
      18%{opacity:.52}
      70%{opacity:.24}
      100%{left:118%;opacity:0}
    }
    @keyframes artemisEliteButtonSweep{
      from{left:-35%}
      to{left:118%}
    }
    @media(max-width:760px){
      html[data-artemis-elite="ready"] .artemis-controls{
        max-width:min(96vw,560px);
        border-radius:18px;
        padding:7px;
      }
      html[data-artemis-elite="ready"] .artemis-controls::before{display:none}
      html[data-artemis-elite="ready"] .artemis-elite-status{order:-1}
    }
    @media(prefers-reduced-motion:reduce){
      html[data-artemis-elite="ready"] .artemis-elite-reveal{
        opacity:1!important;
        transform:none!important;
        transition:none!important;
      }
      html[data-artemis-elite="ready"] .artemis-elite-status i,
      html[data-artemis-elite="ready"] .artemis-instrumented.is-artemis-sweeping>.artemis-sweep,
      html[data-artemis-elite="ready"] .btn:hover::after,
      html[data-artemis-elite="ready"] .btn:focus-visible::after{
        animation:none!important;
      }
    }
  `;
  document.head.appendChild(style);

  var nav=document.querySelector('.nav');
  if(nav) nav.classList.add('artemis-nav-energy');

  var controls=document.querySelector('.artemis-controls');
  if(controls && !controls.querySelector('.artemis-elite-status')){
    var status=document.createElement('span');
    status.className='artemis-elite-status';
    status.title='Interface presentation status; not external infrastructure telemetry.';
    status.innerHTML='<i aria-hidden="true"></i><span>Interface / Ready</span>';
    controls.appendChild(status);
  }

  var cards=document.querySelectorAll('.tech-card,.product-card,.command-panel,.ops-card,.value-card,.cg-card,.hero-option');
  cards.forEach(function(card,index){
    if(!card.classList.contains('artemis-instrumented')) card.classList.add('artemis-instrumented');
    if(!card.querySelector(':scope > .artemis-energy-line')){
      var energy=document.createElement('span');
      energy.className='artemis-energy-line';
      energy.setAttribute('aria-hidden','true');
      card.appendChild(energy);
    }
    if(!card.querySelector(':scope > .artemis-sweep')){
      var sweep=document.createElement('span');
      sweep.className='artemis-sweep';
      sweep.setAttribute('aria-hidden','true');
      card.appendChild(sweep);
    }
    card.style.setProperty('--artemis-delay',Math.min(index%8,7)*70+'ms');
  });

  var revealTargets=document.querySelectorAll('.hero-options .hero-option,.hero-command-rail .hero-signal,.artemis-controls,.tech-card,.product-card,.command-panel,.ops-card,.value-card,.cg-card');
  if(motionQuery.matches || !('IntersectionObserver' in window)){
    revealTargets.forEach(function(el){el.classList.add('artemis-elite-reveal','is-artemis-visible');});
  }else{
    var revealObserver=new IntersectionObserver(function(entries,observer){
      entries.forEach(function(entry){
        if(entry.isIntersecting){
          entry.target.classList.add('is-artemis-visible');
          observer.unobserve(entry.target);
        }
      });
    },{threshold:.08,rootMargin:'0px 0px -24px 0px'});
    revealTargets.forEach(function(el){
      el.classList.add('artemis-elite-reveal');
      revealObserver.observe(el);
    });
  }

  if(finePointer.matches && !motionQuery.matches){
    cards.forEach(function(card){
      if(card.dataset.artemisElitePointer==='bound') return;
      card.dataset.artemisElitePointer='bound';
      card.addEventListener('pointermove',function(event){
        var bounds=card.getBoundingClientRect();
        var x=event.clientX-bounds.left;
        var y=event.clientY-bounds.top;
        card.style.setProperty('--mx',x+'px');
        card.style.setProperty('--my',y+'px');
      },{passive:true});
    });
  }

  var sweepIndex=0;
  var sweepTimer=null;
  function scheduleSweep(){
    if(motionQuery.matches || document.hidden || !cards.length) return;
    window.clearTimeout(sweepTimer);
    sweepTimer=window.setTimeout(function(){
      if(document.hidden || motionQuery.matches) return;
      var eligible=Array.prototype.filter.call(cards,function(card){
        var rect=card.getBoundingClientRect();
        return rect.bottom>0 && rect.top<window.innerHeight;
      });
      if(eligible.length){
        var card=eligible[sweepIndex%eligible.length];
        sweepIndex+=1;
        card.classList.remove('is-artemis-sweeping');
        void card.offsetWidth;
        card.classList.add('is-artemis-sweeping');
        window.setTimeout(function(){card.classList.remove('is-artemis-sweeping');},1600);
      }
      scheduleSweep();
    },7200);
  }

  function syncMotionPreference(){
    if(motionQuery.matches){
      window.clearTimeout(sweepTimer);
      document.querySelectorAll('.artemis-elite-reveal').forEach(function(el){el.classList.add('is-artemis-visible');});
    }else{
      scheduleSweep();
    }
  }

  document.addEventListener('visibilitychange',function(){
    if(document.hidden){
      window.clearTimeout(sweepTimer);
    }else{
      scheduleSweep();
    }
  });

  if(typeof motionQuery.addEventListener==='function') motionQuery.addEventListener('change',syncMotionPreference);
  else if(typeof motionQuery.addListener==='function') motionQuery.addListener(syncMotionPreference);

  scheduleSweep();
})();

/* AEGIS-X Mission Control augmentation.
   Decorative states are explicitly UI presentation states, never fabricated infrastructure telemetry. */
(function(){
  'use strict';
  if(document.documentElement.dataset.aegisX==='ready') return;
  document.documentElement.dataset.aegisX='ready';

  var reduceQuery=window.matchMedia('(prefers-reduced-motion: reduce)');
  var mobileQuery=window.matchMedia('(max-width:760px)');
  var connection=navigator.connection||navigator.mozConnection||navigator.webkitConnection;
  var saveData=Boolean(connection&&connection.saveData);
  var constrainedCpu=typeof navigator.hardwareConcurrency==='number'&&navigator.hardwareConcurrency<=4;
  var performanceLite=saveData||constrainedCpu;
  document.documentElement.classList.toggle('aegis-performance-lite',performanceLite);

  var style=document.createElement('style');
  style.id='aegis-x-runtime';
  style.textContent=`
    :root{
      --motion-instant:120ms;
      --motion-fast:220ms;
      --motion-standard:480ms;
      --motion-cinematic:800ms;
      --ease-command:cubic-bezier(.22,1,.36,1);
      --ease-system:cubic-bezier(.4,0,.2,1);
      --aegis-cyan:#56e7ff;
      --aegis-blue:#38bdf8;
      --aegis-violet:#a78bfa;
      --aegis-green:#34d399;
    }
    html[data-aegis-x="ready"] .aegis-scroll-rail{
      position:fixed;z-index:86;right:14px;top:50%;width:4px;height:min(42vh,360px);
      transform:translateY(-50%);border-radius:999px;pointer-events:none;
      background:rgba(86,231,255,.10);box-shadow:0 0 0 1px rgba(86,231,255,.08);
      overflow:hidden;
    }
    html[data-aegis-x="ready"] .aegis-scroll-rail>i{
      position:absolute;inset:0;display:block;transform-origin:50% 0;transform:scaleY(var(--aegis-progress,0));
      background:linear-gradient(180deg,var(--aegis-cyan),var(--aegis-violet));
      box-shadow:0 0 14px rgba(86,231,255,.44);will-change:transform;
    }
    html[data-aegis-x="ready"] .aegis-boot-status{
      position:absolute;z-index:5;top:104px;left:50%;display:flex;align-items:center;gap:9px;
      min-height:30px;padding:7px 12px;border:1px solid rgba(86,231,255,.20);border-radius:999px;
      transform:translate3d(-50%,-8px,0);opacity:0;pointer-events:none;color:#bcefff;
      background:linear-gradient(135deg,rgba(5,12,28,.72),rgba(25,15,54,.54));
      box-shadow:inset 0 1px rgba(255,255,255,.06),0 10px 28px rgba(7,17,31,.12),0 0 24px rgba(86,231,255,.08);
      -webkit-backdrop-filter:blur(16px) saturate(1.2);backdrop-filter:blur(16px) saturate(1.2);
      font:700 8px/1 var(--mono,monospace);letter-spacing:.13em;text-transform:uppercase;
      animation:aegisBoot var(--motion-cinematic) var(--ease-command) .12s forwards,aegisBootExit .42s var(--ease-system) 1.7s forwards;
    }
    html[data-aegis-x="ready"] .aegis-boot-status i{
      width:7px;height:7px;border-radius:50%;background:var(--aegis-green);
      box-shadow:0 0 0 4px rgba(52,211,153,.12),0 0 14px rgba(52,211,153,.70);
      animation:aegisSignal 2.35s var(--ease-system) infinite;
    }
    html[data-aegis-x="ready"] .aegis-acquire-target{
      position:relative;isolation:isolate;
    }
    html[data-aegis-x="ready"] .aegis-acquire-target::after{
      content:"";position:absolute;z-index:0;left:3%;right:3%;top:0;height:1px;pointer-events:none;
      opacity:0;transform:scaleX(.18);transform-origin:left;
      background:linear-gradient(90deg,transparent,rgba(86,231,255,.82),rgba(167,139,250,.58),transparent);
      box-shadow:0 0 16px rgba(86,231,255,.16);
      transition:opacity var(--motion-standard) var(--ease-system),transform var(--motion-cinematic) var(--ease-command);
    }
    html[data-aegis-x="ready"] .aegis-acquire-target.aegis-acquired::after{opacity:.72;transform:scaleX(1)}
    html[data-aegis-x="ready"] .aegis-acquire-target>.container{position:relative;z-index:1}
    html[data-aegis-x="ready"] .aegis-ui-state{
      position:fixed;z-index:85;left:14px;bottom:14px;display:inline-flex;align-items:center;gap:7px;
      min-height:30px;padding:7px 10px;border-radius:999px;pointer-events:none;
      border:1px solid rgba(86,231,255,.16);background:rgba(5,12,28,.70);color:#a8d9e8;
      box-shadow:0 8px 30px rgba(7,17,31,.16),inset 0 1px rgba(255,255,255,.04);
      -webkit-backdrop-filter:blur(14px);backdrop-filter:blur(14px);
      font:700 7px/1 var(--mono,monospace);letter-spacing:.12em;text-transform:uppercase;
    }
    html[data-aegis-x="ready"] .aegis-ui-state i{width:6px;height:6px;border-radius:50%;background:var(--aegis-cyan);box-shadow:0 0 11px rgba(86,231,255,.72)}
    html.aegis-performance-lite .aegis-ui-state,
    html.aegis-performance-lite .aegis-scroll-rail{box-shadow:none}
    html.aegis-performance-lite .aegis-acquire-target::after{box-shadow:none}
    @keyframes aegisBoot{to{opacity:1;transform:translate3d(-50%,0,0)}}
    @keyframes aegisBootExit{to{opacity:0;transform:translate3d(-50%,-6px,0)}}
    @keyframes aegisSignal{55%{box-shadow:0 0 0 8px rgba(52,211,153,0),0 0 18px rgba(52,211,153,.76)}}
    @media(max-width:760px){
      html[data-aegis-x="ready"] .aegis-scroll-rail{display:none}
      html[data-aegis-x="ready"] .aegis-ui-state{left:10px;bottom:10px;opacity:.86}
      html[data-aegis-x="ready"] .aegis-boot-status{top:96px;max-width:calc(100vw - 32px);white-space:nowrap}
    }
    @media(prefers-reduced-motion:reduce){
      html[data-aegis-x="ready"] .aegis-boot-status{display:none!important;animation:none!important}
      html[data-aegis-x="ready"] .aegis-boot-status i{animation:none!important}
      html[data-aegis-x="ready"] .aegis-acquire-target::after{transition:none!important}
      html[data-aegis-x="ready"] .aegis-scroll-rail>i{will-change:auto}
    }
  `;
  document.head.appendChild(style);

  var hero=document.querySelector('.hero,#hero');
  if(hero&&!hero.querySelector('.aegis-boot-status')&&!reduceQuery.matches){
    var boot=document.createElement('div');
    boot.className='aegis-boot-status';
    boot.setAttribute('aria-hidden','true');
    boot.innerHTML='<i></i><span>AEGIS-X / Interface Ready</span>';
    hero.appendChild(boot);
    window.setTimeout(function(){if(boot.parentNode)boot.parentNode.removeChild(boot);},2400);
  }

  var state=document.querySelector('.aegis-ui-state');
  if(!state){
    state=document.createElement('div');
    state.className='aegis-ui-state';
    state.setAttribute('aria-hidden','true');
    state.title='Decorative interface state; not live infrastructure telemetry.';
    state.innerHTML='<i></i><span>UI / ACTIVE</span>';
    document.body.appendChild(state);
  }

  var rail=document.querySelector('.aegis-scroll-rail');
  if(!rail&&!mobileQuery.matches){
    rail=document.createElement('div');
    rail.className='aegis-scroll-rail';
    rail.setAttribute('aria-hidden','true');
    rail.innerHTML='<i></i>';
    document.body.appendChild(rail);
  }

  var ticking=false;
  function syncProgress(){
    ticking=false;
    if(!rail)return;
    var max=Math.max(document.documentElement.scrollHeight-window.innerHeight,1);
    var progress=Math.max(0,Math.min(1,window.scrollY/max));
    rail.style.setProperty('--aegis-progress',String(progress));
  }
  function requestProgress(){
    if(ticking||document.hidden)return;
    ticking=true;
    window.requestAnimationFrame(syncProgress);
  }
  if(rail){
    syncProgress();
    window.addEventListener('scroll',requestProgress,{passive:true});
    window.addEventListener('resize',requestProgress,{passive:true});
  }

  var sections=document.querySelectorAll('main>section,.sect,.cta-sect,.signup-sect');
  sections.forEach(function(section){section.classList.add('aegis-acquire-target');});
  if(reduceQuery.matches||!('IntersectionObserver' in window)){
    sections.forEach(function(section){section.classList.add('aegis-acquired');});
  }else{
    var acquisitionObserver=new IntersectionObserver(function(entries){
      entries.forEach(function(entry){
        if(entry.isIntersecting)entry.target.classList.add('aegis-acquired');
      });
    },{threshold:.08,rootMargin:'0px 0px -12% 0px'});
    sections.forEach(function(section){acquisitionObserver.observe(section);});
  }

  function syncVisibility(){
    document.documentElement.classList.toggle('aegis-paused',document.hidden);
    if(!document.hidden)requestProgress();
  }
  document.addEventListener('visibilitychange',syncVisibility);

  function syncReducedMotion(){
    if(reduceQuery.matches){
      document.querySelectorAll('.aegis-acquire-target').forEach(function(section){section.classList.add('aegis-acquired');});
    }
  }
  if(typeof reduceQuery.addEventListener==='function')reduceQuery.addEventListener('change',syncReducedMotion);
  else if(typeof reduceQuery.addListener==='function')reduceQuery.addListener(syncReducedMotion);
})();
