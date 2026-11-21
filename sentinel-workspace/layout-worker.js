/* ClearGlass Sentinel Workspace · force-layout worker.
   Runs core.createForceLayout off the main thread, so a large layout does not
   compete with rendering. Every message carries the job number it belongs to;
   the page ignores results from superseded jobs and terminates this worker to
   cancel one. Input is plain data (ids and endpoints) — no dataset text. */
"use strict";
importScripts("core.js");

self.onmessage = function (ev) {
  var m = ev.data;
  if (!m || m.type !== "force") return;
  var C = self.SentinelCore;
  var pinned = new Map((m.pinned || []).map(function (p) { return [p.id, { x: p.x, y: p.y }]; }));
  var t0 = Date.now(), lastPost = 0;
  var lay = C.createForceLayout(m.nodes, m.edges, { seed: m.seed, pinned: pinned });
  while (!lay.done()) {
    lay.step(5);
    if (Date.now() - lastPost > 100) { self.postMessage({ type: "progress", job: m.job, progress: lay.progress() }); lastPost = Date.now(); }
  }
  var pos = lay.positions(), ids = [], xy = new Float64Array(pos.size * 2), i = 0;
  pos.forEach(function (p, id) { ids.push(id); xy[i++] = p.x; xy[i++] = p.y; });
  self.postMessage({ type: "done", job: m.job, ids: ids, xy: xy, params: lay.params, runtime_ms: Date.now() - t0 }, [xy.buffer]);
};
