/* ClearGlass Inc // AEGIS-OMEGA
   Progressive enhancement control plane. Defensive, additive and fail-contained. */
(function(){
  'use strict';
  if(window.ClearGlassAEGIS&&window.ClearGlassAEGIS.version==='OMEGA') return;

  var root=document.documentElement;
  var reduceQuery=window.matchMedia('(prefers-reduced-motion: reduce)');
  var fineQuery=window.matchMedia('(pointer:fine)');
  var connection=navigator.connection||navigator.mozConnection||navigator.webkitConnection||null;
  var saveData=Boolean(connection&&connection.saveData);
  var cores=Number(navigator.hardwareConcurrency||0);
  var memory=Number(navigator.deviceMemory||0);
  var compact=window.matchMedia('(max-width:760px)').matches;

  function resolveTier(){
    if(reduceQuery.matches||saveData) return 'MINIMAL';
    if(compact||(cores&&cores<=4)||(memory&&memory<=4)) return 'BALANCED';
    return 'FULL';
  }

  var tier=resolveTier();
  root.dataset.aegisOmega='ready';
  root.dataset.aegisTier=tier;

  var capabilities=Object.freeze({
    opticalGlass:true,
    neonLighting:tier!=='MINIMAL',
    missionMotion:!reduceQuery.matches,
    telemetryRail:true,
    commandPalette:true,
    pointerDepth:tier==='FULL'&&fineQuery.matches,
    offscreenSuspension:'IntersectionObserver' in window,
    visibilitySuspension:true,
    missionEvents:true
  });

  var runtimeStyle=document.createElement('style');
  runtimeStyle.id='aegis-omega-runtime-safety';
  runtimeStyle.textContent='.omega-offscreen,.omega-offscreen *{animation-play-state:paused!important}html.aegis-omega-paused .omega-offscreen{animation-play-state:paused!important}';
  document.head.appendChild(runtimeStyle);

  function emit(name,detail){
    var payload=Object.assign({source:'AEGIS-OMEGA',tier:tier},detail||{});
    document.dispatchEvent(new CustomEvent(name,{detail:payload}));
  }
  function on(name,handler){document.addEventListener(name,handler);return function(){document.removeEventListener(name,handler);};}

  var api={
    version:'OMEGA',
    get tier(){return tier;},
    capabilities:capabilities,
    emit:emit,
    on:on,
    snapshot:function(){return {version:'OMEGA',tier:tier,capabilities:capabilities,hidden:document.hidden,reducedMotion:reduceQuery.matches};}
  };
  Object.defineProperty(window,'ClearGlassAEGIS',{value:api,configurable:false,writable:false});

  function text(value){return document.createTextNode(value);}
  function make(tag,className){var el=document.createElement(tag);if(className)el.className=className;return el;}

  var telemetry=make('div','omega-telemetry');
  telemetry.setAttribute('aria-hidden','true');
  telemetry.title='Interface presentation telemetry only; not infrastructure or security telemetry.';
  var identity=make('span');
  var dot=make('i');
  dot.setAttribute('aria-hidden','true');
  identity.appendChild(dot);identity.appendChild(text('UI / AEGIS-Ω'));
  var tierNode=make('span');tierNode.appendChild(text('TIER / '+tier));
  var sectionNode=make('span');sectionNode.appendChild(text('SECTION / HOME'));
  telemetry.appendChild(identity);telemetry.appendChild(tierNode);telemetry.appendChild(sectionNode);
  document.body.appendChild(telemetry);

  function sectionName(section,index){
    var explicit=section.getAttribute('data-mission-id')||section.id;
    if(explicit) return explicit.replace(/[-_]+/g,' ').trim().slice(0,28);
    var heading=section.querySelector('h1,h2,h3');
    if(heading&&heading.textContent.trim()) return heading.textContent.trim().slice(0,28);
    return 'SECTOR '+String(index+1).padStart(2,'0');
  }

  var sections=Array.prototype.slice.call(document.querySelectorAll('main>section,.sect,.cta-sect,.signup-sect'));
  var activeSection=null;
  var sectionNames=new Map();
  sections.forEach(function(section,index){sectionNames.set(section,sectionName(section,index));});

  if('IntersectionObserver' in window&&sections.length){
    var sectionObserver=new IntersectionObserver(function(entries){
      var visible=entries.filter(function(entry){return entry.isIntersecting;}).sort(function(a,b){return b.intersectionRatio-a.intersectionRatio;});
      if(!visible.length) return;
      var next=visible[0].target;
      if(next===activeSection) return;
      var previous=activeSection;
      activeSection=next;
      if(previous) emit('mission:exit',{section:sectionNames.get(previous)||''});
      var name=sectionNames.get(next)||'SECTOR';
      sectionNode.textContent='SECTION / '+name.toUpperCase();
      next.classList.add('omega-section-acquired');
      emit('mission:enter',{section:name});
    },{threshold:[.12,.3,.55],rootMargin:'-18% 0px -48% 0px'});
    sections.forEach(function(section){sectionObserver.observe(section);});
  }

  if(capabilities.offscreenSuspension){
    var effectTargets=document.querySelectorAll('.artemis-reticle,.artemis-grid,.hero-prism,.hero-lines,.radar,.scanner,[data-omega-effect]');
    var effectObserver=new IntersectionObserver(function(entries){
      entries.forEach(function(entry){entry.target.classList.toggle('omega-offscreen',!entry.isIntersecting);});
    },{rootMargin:'180px 0px 180px 0px',threshold:0});
    effectTargets.forEach(function(target){effectObserver.observe(target);});
  }

  function bindOptInDepth(){
    if(!capabilities.pointerDepth) return;
    document.querySelectorAll('[data-omega-depth="true"]').forEach(function(card){
      if(card.dataset.omegaDepthBound==='true') return;
      card.dataset.omegaDepthBound='true';
      card.classList.add('omega-depth','omega-energy-edge');
      var frame=0;
      function move(event){
        if(frame) cancelAnimationFrame(frame);
        frame=requestAnimationFrame(function(){
          var rect=card.getBoundingClientRect();
          var nx=((event.clientX-rect.left)/Math.max(rect.width,1))-.5;
          var ny=((event.clientY-rect.top)/Math.max(rect.height,1))-.5;
          card.style.setProperty('--omega-rx',(-ny*3.2).toFixed(2)+'deg');
          card.style.setProperty('--omega-ry',(nx*3.2).toFixed(2)+'deg');
        });
      }
      function reset(){card.style.setProperty('--omega-rx','0deg');card.style.setProperty('--omega-ry','0deg');}
      card.addEventListener('pointermove',move,{passive:true});
      card.addEventListener('pointerleave',reset,{passive:true});
    });
  }
  bindOptInDepth();

  function collectCommands(){
    var seen=new Set();
    var commands=[];
    document.querySelectorAll('.nav a[href],nav a[href],.mobile-menu a[href]').forEach(function(link){
      var label=(link.textContent||'').replace(/\s+/g,' ').trim();
      if(!label) return;
      try{
        var url=new URL(link.getAttribute('href'),location.href);
        if(url.origin!==location.origin) return;
        var key=url.pathname+url.search+url.hash+'|'+label.toLowerCase();
        if(seen.has(key)) return;
        seen.add(key);
        commands.push({label:label,href:url.href,path:url.pathname});
      }catch(ignore){}
    });
    return commands.slice(0,36);
  }

  function installPalette(){
    var commands=collectCommands();
    if(!capabilities.commandPalette||commands.length<4) return;

    var overlay=make('div','omega-command-palette');
    overlay.hidden=true;
    overlay.setAttribute('role','dialog');overlay.setAttribute('aria-modal','true');overlay.setAttribute('aria-label','ClearGlass command palette');
    var panel=make('div','omega-command-panel');
    var head=make('div','omega-command-head');
    var input=document.createElement('input');
    input.type='search';input.autocomplete='off';input.spellcheck=false;input.placeholder='Navigate ClearGlass…';input.setAttribute('aria-label','Filter navigation commands');
    var key=make('kbd');key.appendChild(text('ESC'));
    var list=make('ul','omega-command-results');
    head.appendChild(input);head.appendChild(key);panel.appendChild(head);panel.appendChild(list);overlay.appendChild(panel);document.body.appendChild(overlay);
    var previousFocus=null;

    function render(query){
      var needle=(query||'').trim().toLowerCase();
      list.replaceChildren();
      commands.filter(function(command){return !needle||command.label.toLowerCase().includes(needle)||command.path.toLowerCase().includes(needle);}).slice(0,12).forEach(function(command){
        var li=document.createElement('li');var a=document.createElement('a');var label=make('span');var meta=make('small');
        a.href=command.href;label.appendChild(text(command.label));meta.appendChild(text(command.path));a.appendChild(label);a.appendChild(meta);li.appendChild(a);list.appendChild(li);
      });
    }
    function open(){
      previousFocus=document.activeElement;overlay.hidden=false;render('');input.value='';input.focus();emit('navigation:open',{surface:'command-palette'});
    }
    function close(){
      if(overlay.hidden) return;overlay.hidden=true;emit('navigation:close',{surface:'command-palette'});if(previousFocus&&typeof previousFocus.focus==='function')previousFocus.focus();
    }
    input.addEventListener('input',function(){render(input.value);});
    overlay.addEventListener('pointerdown',function(event){if(event.target===overlay)close();});
    overlay.addEventListener('keydown',function(event){
      if(event.key==='Escape'){event.preventDefault();close();}
      if(event.key==='Enter'){
        var first=list.querySelector('a');if(first&&document.activeElement===input){event.preventDefault();first.click();}
      }
    });
    document.addEventListener('keydown',function(event){
      /* global-nav-search.js binds the same Cmd/Ctrl+K and is loaded alongside
         this module by platform.js, so both palettes used to open on one
         keystroke across all 43 pages that load platform.js. That module owns
         the shortcut: it is the discoverable one (visible control in the nav,
         plus "/"), while this palette has no launcher of its own. Checking the
         flag at keydown rather than at bind time keeps the outcome independent
         of which of the two deferred scripts happens to execute first. */
      if(window.__cgGlobalNavSearch){if(!overlay.hidden&&event.key==='Escape')close();return;}
      if((event.ctrlKey||event.metaKey)&&event.key.toLowerCase()==='k'){event.preventDefault();overlay.hidden?open():close();}
      else if(event.key==='Escape'&&!overlay.hidden)close();
    });
  }
  installPalette();

  function syncVisibility(){
    root.classList.toggle('aegis-omega-paused',document.hidden);
    emit(document.hidden?'animation:pause':'animation:resume',{reason:'document-visibility'});
  }
  document.addEventListener('visibilitychange',syncVisibility);

  function syncMotion(){
    if(reduceQuery.matches){tier='MINIMAL';root.dataset.aegisTier=tier;tierNode.textContent='TIER / '+tier;root.classList.add('aegis-omega-reduced');}
    else root.classList.remove('aegis-omega-reduced');
  }
  if(typeof reduceQuery.addEventListener==='function')reduceQuery.addEventListener('change',syncMotion);
  else if(typeof reduceQuery.addListener==='function')reduceQuery.addListener(syncMotion);

  emit('status:change',{state:'interface-ready'});
})();
