/* ClearGlass Sentinel Workspace · core analysis module.
   ────────────────────────────────────────────────────────────────────────────
   Pure functions only: no DOM, no network, no storage, no clock unless one is
   passed in. The browser loads this as a classic script (window.SentinelCore).
   The repository root package.json declares "type": "module", so Node tests
   import it for its side effect and read globalThis.SentinelCore; a CommonJS
   consumer gets module.exports. Every analytical rule the workspace shows
   to an analyst lives here, so it can be tested and reproduced outside the UI.

   Data contract: "clearglass.sentinel/1" — see sentinel-workspace/README.md.
   Nothing in this module fabricates timestamps, confidence values or evidence:
   unknown values stay null and are reported as unknown. */
(function (root, factory) {
  "use strict";
  var api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.SentinelCore = api;
}(typeof globalThis !== "undefined" ? globalThis : (typeof self !== "undefined" ? self : this), function () {
  "use strict";

  var SCHEMA = "clearglass.sentinel/1";
  var NOTEBOOK_SCHEMA = "clearglass.sentinel.notebook/1";
  var VIEW_SCHEMA = "clearglass.sentinel.view/1";
  var CORE_VERSION = "1.0.0";

  var LIMITS = Object.freeze({
    maxBytes: 5 * 1024 * 1024,
    maxDepth: 12,
    maxSources: 2000,
    maxEntities: 5000,
    maxObservations: 20000,
    maxRelationships: 20000,
    maxClaims: 5000,
    maxMergeCandidates: 2000,
    maxText: 4000,
    maxLabel: 200,
    maxId: 128,
    maxRefs: 500,
    maxErrors: 200
  });

  var ENTITY_TYPES = ["person", "organization", "domain", "ip", "system", "document", "account", "certificate", "topic", "other"];
  var REVIEW_STATES = ["unreviewed", "confirmed", "disputed", "rejected"];
  var CLAIM_KINDS = ["observed", "derived", "hypothesized", "analyst-assessed"];
  var CLAIM_STATUS = ["supported", "contradicted", "unresolved"];
  var RELIABILITY = ["A", "B", "C", "D", "E", "F", "unknown"];
  var EXTRACTION_METHODS = ["manual", "parser", "model", "unknown"];
  var ASSESSMENTS = ["consistent", "inconsistent", "neutral"];
  var COLLECTIONS = ["sources", "entities", "observations", "relationships", "claims", "merge_candidates"];
  var COLLECTION_LIMIT = {
    sources: LIMITS.maxSources, entities: LIMITS.maxEntities, observations: LIMITS.maxObservations,
    relationships: LIMITS.maxRelationships, claims: LIMITS.maxClaims, merge_candidates: LIMITS.maxMergeCandidates
  };

  var ID_RE = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/;
  var REL_TYPE_RE = /^[a-z][a-z0-9_]{0,47}$/;
  var ISO_RE = /^\d{4}-\d{2}-\d{2}(T\d{2}:\d{2}(:\d{2}(\.\d{1,6})?)?(Z|[+-]\d{2}:\d{2}))?$/;
  var FORBIDDEN_KEYS = { "__proto__": true, "constructor": true, "prototype": true };
  var CITE_RE = /\[ref:([^\]\s]{1,128})\]/g;

  /* ───────────────────────── small utilities ───────────────────────── */

  function isPlainObject(v) { return v !== null && typeof v === "object" && !Array.isArray(v); }
  function has(o, k) { return Object.prototype.hasOwnProperty.call(o, k); }
  function clone(v) { return v === undefined ? undefined : JSON.parse(JSON.stringify(v)); }
  function uniq(arr) { var s = new Set(), out = []; arr.forEach(function (x) { if (!s.has(x)) { s.add(x); out.push(x); } }); return out; }
  function cmpStr(a, b) { return a < b ? -1 : a > b ? 1 : 0; }
  function perfNow() { return (typeof performance !== "undefined" && performance.now) ? performance.now() : Date.now(); }
  function round(n, d) { var p = Math.pow(10, d || 0); return Math.round(n * p) / p; }
  function isoOf(now) { return (now instanceof Date ? now : new Date(now === undefined ? Date.now() : now)).toISOString(); }

  function timeValue(s) {
    if (s === null || s === undefined) return null;
    var t = Date.parse(s);
    return isNaN(t) ? null : t;
  }
  function isValidTime(s) { return typeof s === "string" && ISO_RE.test(s) && !isNaN(Date.parse(s)); }

  function utf8Bytes(str) {
    if (typeof TextEncoder !== "undefined") return new TextEncoder().encode(str);
    var out = [], i, c;
    for (i = 0; i < str.length; i++) {
      c = str.charCodeAt(i);
      if (c >= 0xd800 && c <= 0xdbff && i + 1 < str.length) {
        var d = str.charCodeAt(i + 1);
        if (d >= 0xdc00 && d <= 0xdfff) { c = 0x10000 + ((c - 0xd800) << 10) + (d - 0xdc00); i++; }
      }
      if (c < 0x80) out.push(c);
      else if (c < 0x800) out.push(0xc0 | (c >> 6), 0x80 | (c & 63));
      else if (c < 0x10000) out.push(0xe0 | (c >> 12), 0x80 | ((c >> 6) & 63), 0x80 | (c & 63));
      else out.push(0xf0 | (c >> 18), 0x80 | ((c >> 12) & 63), 0x80 | ((c >> 6) & 63), 0x80 | (c & 63));
    }
    return new Uint8Array(out);
  }

  /* SHA-256 (FIPS 180-4). Synchronous and dependency-free so fingerprints work
     in insecure contexts, workers, file:// and Node alike. Verified against
     node:crypto in tests/sentinel_workspace/core.test.js. */
  var K256 = [
    0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
    0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
    0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
    0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
    0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
    0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
    0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
    0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2
  ];
  function sha256Hex(input) {
    var bytes = typeof input === "string" ? utf8Bytes(input) : input;
    var len = bytes.length, bitLenHi = Math.floor(len / 0x20000000), bitLenLo = (len << 3) >>> 0;
    var padded = new Uint8Array(((len + 9 + 63) >> 6) << 6);
    padded.set(bytes); padded[len] = 0x80;
    var p = padded.length;
    padded[p - 8] = (bitLenHi >>> 24) & 255; padded[p - 7] = (bitLenHi >>> 16) & 255;
    padded[p - 6] = (bitLenHi >>> 8) & 255; padded[p - 5] = bitLenHi & 255;
    padded[p - 4] = (bitLenLo >>> 24) & 255; padded[p - 3] = (bitLenLo >>> 16) & 255;
    padded[p - 2] = (bitLenLo >>> 8) & 255; padded[p - 1] = bitLenLo & 255;
    var h0 = 0x6a09e667, h1 = 0xbb67ae85, h2 = 0x3c6ef372, h3 = 0xa54ff53a,
      h4 = 0x510e527f, h5 = 0x9b05688c, h6 = 0x1f83d9ab, h7 = 0x5be0cd19;
    var w = new Uint32Array(64);
    for (var off = 0; off < p; off += 64) {
      for (var i = 0; i < 16; i++) {
        var j = off + i * 4;
        w[i] = (padded[j] << 24) | (padded[j + 1] << 16) | (padded[j + 2] << 8) | padded[j + 3];
      }
      for (i = 16; i < 64; i++) {
        var x = w[i - 15], y = w[i - 2];
        var s0 = ((x >>> 7) | (x << 25)) ^ ((x >>> 18) | (x << 14)) ^ (x >>> 3);
        var s1 = ((y >>> 17) | (y << 15)) ^ ((y >>> 19) | (y << 13)) ^ (y >>> 10);
        w[i] = (w[i - 16] + s0 + w[i - 7] + s1) | 0;
      }
      var a = h0, b = h1, c = h2, d = h3, e = h4, f = h5, g = h6, h = h7;
      for (i = 0; i < 64; i++) {
        var S1 = ((e >>> 6) | (e << 26)) ^ ((e >>> 11) | (e << 21)) ^ ((e >>> 25) | (e << 7));
        var ch = (e & f) ^ (~e & g);
        var t1 = (h + S1 + ch + K256[i] + w[i]) | 0;
        var S0 = ((a >>> 2) | (a << 30)) ^ ((a >>> 13) | (a << 19)) ^ ((a >>> 22) | (a << 10));
        var maj = (a & b) ^ (a & c) ^ (b & c);
        var t2 = (S0 + maj) | 0;
        h = g; g = f; f = e; e = (d + t1) | 0; d = c; c = b; b = a; a = (t1 + t2) | 0;
      }
      h0 = (h0 + a) | 0; h1 = (h1 + b) | 0; h2 = (h2 + c) | 0; h3 = (h3 + d) | 0;
      h4 = (h4 + e) | 0; h5 = (h5 + f) | 0; h6 = (h6 + g) | 0; h7 = (h7 + h) | 0;
    }
    return [h0, h1, h2, h3, h4, h5, h6, h7].map(function (v) { return ("00000000" + (v >>> 0).toString(16)).slice(-8); }).join("");
  }

  /* Canonical JSON: object keys sorted, no whitespace, undefined dropped. Two
     datasets with the same content always produce the same fingerprint. */
  function canonicalJSON(v) {
    if (v === undefined) return "null";
    if (v === null || typeof v !== "object") {
      if (typeof v === "number" && !isFinite(v)) return "null";
      return JSON.stringify(v);
    }
    if (Array.isArray(v)) return "[" + v.map(canonicalJSON).join(",") + "]";
    var keys = Object.keys(v).filter(function (k) { return v[k] !== undefined; }).sort();
    return "{" + keys.map(function (k) { return JSON.stringify(k) + ":" + canonicalJSON(v[k]); }).join(",") + "}";
  }

  function datasetContent(ds) {
    var out = {};
    Object.keys(ds).forEach(function (k) { if (k !== "export") out[k] = ds[k]; });
    return out;
  }
  function fingerprint(ds) { return "sha256:" + sha256Hex(canonicalJSON(datasetContent(ds))); }
  function shortFingerprint(fp) { return fp ? fp.replace("sha256:", "").slice(0, 12) : "—"; }

  /* Deterministic PRNG for reproducible layouts (seed is recorded with results). */
  function mulberry32(seed) {
    var a = seed >>> 0;
    return function () {
      a = (a + 0x6d2b79f5) | 0;
      var t = Math.imul(a ^ (a >>> 15), 1 | a);
      t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }

  /* ───────────────────────── validation ───────────────────────── */

  function newCtx() {
    var errors = [], warnings = [];
    return {
      errors: errors, warnings: warnings,
      err: function (path, msg) { if (errors.length < LIMITS.maxErrors) errors.push({ path: path, message: msg }); },
      warn: function (path, msg) { if (warnings.length < LIMITS.maxErrors) warnings.push({ path: path, message: msg }); },
      result: function () { return { ok: errors.length === 0, errors: errors, warnings: warnings, truncated: errors.length >= LIMITS.maxErrors }; }
    };
  }

  function walkKeys(v, path, depth, ctx) {
    if (depth > LIMITS.maxDepth) { ctx.err(path, "Nesting deeper than " + LIMITS.maxDepth + " levels is not accepted."); return; }
    if (Array.isArray(v)) { for (var i = 0; i < v.length; i++) walkKeys(v[i], path + "[" + i + "]", depth + 1, ctx); return; }
    if (isPlainObject(v)) {
      Object.keys(v).forEach(function (k) {
        if (has(FORBIDDEN_KEYS, k)) ctx.err(path + "." + k, "Key \"" + k + "\" is not allowed.");
        else walkKeys(v[k], path + "." + k, depth + 1, ctx);
      });
    }
  }

  function checkString(ctx, value, path, max, re, required) {
    if (value === undefined || value === null) { if (required) ctx.err(path, "Required text is missing."); return false; }
    if (typeof value !== "string") { ctx.err(path, "Must be text."); return false; }
    if (required && !value.trim()) { ctx.err(path, "Must not be empty."); return false; }
    if (value.length > max) { ctx.err(path, "Longer than " + max + " characters."); return false; }
    if (re && !re.test(value)) { ctx.err(path, "Has an invalid format."); return false; }
    return true;
  }
  function checkEnum(ctx, value, path, allowed) {
    if (allowed.indexOf(value) === -1) { ctx.err(path, "Must be one of: " + allowed.join(", ") + "."); return false; }
    return true;
  }
  /* Time fields must be PRESENT. null is the explicit "unknown" value. */
  function checkTimeField(ctx, rec, key, path, required) {
    if (!has(rec, key)) {
      if (required) ctx.err(path + "." + key, "Must be present; use null when the time is unknown.");
      return;
    }
    var v = rec[key];
    if (v === null) return;
    if (!isValidTime(v)) ctx.err(path + "." + key, "Must be an ISO 8601 date or date-time with a time zone, or null.");
  }
  function checkUri(ctx, value, path) {
    if (value === undefined || value === null) return;
    if (!checkString(ctx, value, path, 2048, null, false)) return;
    if (!/^https?:\/\/[^\s]+$/i.test(value)) ctx.err(path, "Only http: and https: links are accepted.");
  }
  function checkRefList(ctx, list, path, required) {
    if (list === undefined || list === null) { if (required) ctx.err(path, "Required list is missing."); return []; }
    if (!Array.isArray(list)) { ctx.err(path, "Must be a list of identifiers."); return []; }
    if (list.length > LIMITS.maxRefs) { ctx.err(path, "More than " + LIMITS.maxRefs + " references."); return []; }
    var out = [];
    list.forEach(function (id, i) {
      if (typeof id !== "string" || !ID_RE.test(id)) ctx.err(path + "[" + i + "]", "Not a valid identifier.");
      else out.push(id);
    });
    return out;
  }
  function checkEvidenceBlock(ctx, ev, path) {
    if (!isPlainObject(ev)) { ctx.err(path, "Must be an object with supporting and contradicting lists."); return { supporting: [], contradicting: [] }; }
    return {
      supporting: checkRefList(ctx, ev.supporting, path + ".supporting", true),
      contradicting: checkRefList(ctx, ev.contradicting, path + ".contradicting", true)
    };
  }

  function validateDataset(doc) {
    var ctx = newCtx();
    if (!isPlainObject(doc)) { ctx.err("$", "Dataset must be a JSON object."); return ctx.result(); }
    walkKeys(doc, "$", 0, ctx);
    if (ctx.errors.length) return ctx.result();
    if (doc.schema !== SCHEMA) ctx.err("$.schema", "Expected \"" + SCHEMA + "\".");
    Object.keys(doc).forEach(function (k) {
      if (["schema", "dataset", "export"].concat(COLLECTIONS).indexOf(k) === -1) ctx.warn("$." + k, "Unknown top-level key ignored.");
    });

    var meta = doc.dataset;
    if (!isPlainObject(meta)) ctx.err("$.dataset", "Dataset metadata object is required.");
    else {
      checkString(ctx, meta.id, "$.dataset.id", LIMITS.maxId, ID_RE, true);
      checkString(ctx, meta.title, "$.dataset.title", LIMITS.maxLabel, null, true);
      checkString(ctx, meta.version, "$.dataset.version", 64, null, true);
      checkString(ctx, meta.description, "$.dataset.description", LIMITS.maxText, null, false);
      if (typeof meta.synthetic !== "boolean") ctx.err("$.dataset.synthetic", "Must be true or false. The workspace never assumes data is real.");
      checkTimeField(ctx, meta, "as_of", "$.dataset", true);
      if (meta.export_policy !== undefined) {
        if (!isPlainObject(meta.export_policy)) ctx.err("$.dataset.export_policy", "Must be an object.");
        else if (meta.export_policy.restricted_attribute_keys !== undefined) {
          var rk = meta.export_policy.restricted_attribute_keys;
          if (!Array.isArray(rk) || rk.some(function (k) { return typeof k !== "string" || k.length > 64; })) {
            ctx.err("$.dataset.export_policy.restricted_attribute_keys", "Must be a list of attribute names.");
          }
        }
      }
    }

    if (!Array.isArray(doc.entities)) ctx.err("$.entities", "An entities list is required.");
    COLLECTIONS.forEach(function (c) {
      if (doc[c] === undefined) return;
      if (!Array.isArray(doc[c])) ctx.err("$." + c, "Must be a list.");
      else if (doc[c].length > COLLECTION_LIMIT[c]) ctx.err("$." + c, "More than " + COLLECTION_LIMIT[c] + " records; split the dataset.");
    });
    if (ctx.errors.length) return ctx.result();

    var kindOf = new Map();
    COLLECTIONS.forEach(function (c) {
      (doc[c] || []).forEach(function (rec, i) {
        var path = "$." + c + "[" + i + "]";
        if (!isPlainObject(rec)) { ctx.err(path, "Must be an object."); return; }
        if (!checkString(ctx, rec.id, path + ".id", LIMITS.maxId, ID_RE, true)) return;
        if (kindOf.has(rec.id)) ctx.err(path + ".id", "Duplicate identifier \"" + rec.id + "\" (identifiers are unique across the whole dataset).");
        else kindOf.set(rec.id, c);
      });
    });
    function expect(id, c, path) {
      if (kindOf.get(id) !== c) ctx.err(path, "\"" + id + "\" is not a known " + c.replace(/s$/, "").replace("_", " ") + " identifier.");
    }

    (doc.sources || []).forEach(function (s, i) {
      var p = "$.sources[" + i + "]";
      if (!isPlainObject(s)) return;
      checkString(ctx, s.title, p + ".title", LIMITS.maxLabel, null, true);
      checkString(ctx, s.kind, p + ".kind", 64, null, true);
      checkUri(ctx, s.uri, p + ".uri");
      checkString(ctx, s.independence_group, p + ".independence_group", LIMITS.maxId, ID_RE, false);
      checkTimeField(ctx, s, "collected_at", p, false);
      if (!isPlainObject(s.assessment)) ctx.err(p + ".assessment", "Source assessment is required (use reliability \"unknown\" when unassessed).");
      else {
        checkEnum(ctx, s.assessment.reliability, p + ".assessment.reliability", RELIABILITY);
        checkString(ctx, s.assessment.basis, p + ".assessment.basis", LIMITS.maxText, null, true);
      }
    });

    (doc.entities || []).forEach(function (e, i) {
      var p = "$.entities[" + i + "]";
      if (!isPlainObject(e)) return;
      checkEnum(ctx, e.type, p + ".type", ENTITY_TYPES);
      checkString(ctx, e.label, p + ".label", LIMITS.maxLabel, null, true);
      if (e.aliases !== undefined) {
        if (!Array.isArray(e.aliases)) ctx.err(p + ".aliases", "Must be a list of text values.");
        else e.aliases.forEach(function (a, j) { checkString(ctx, a, p + ".aliases[" + j + "]", LIMITS.maxLabel, null, true); });
      }
      if (e.attributes !== undefined) {
        if (!isPlainObject(e.attributes)) ctx.err(p + ".attributes", "Must be an object.");
        else Object.keys(e.attributes).forEach(function (k) {
          var v = e.attributes[k];
          if (k.length > 64) ctx.err(p + ".attributes", "Attribute name longer than 64 characters.");
          if (!(v === null || typeof v === "boolean" || (typeof v === "number" && isFinite(v)) || (typeof v === "string" && v.length <= LIMITS.maxText))) {
            ctx.err(p + ".attributes." + k, "Attribute values must be text, numbers, true/false or null.");
          }
        });
      }
      checkRefList(ctx, e.source_ids, p + ".source_ids", false).forEach(function (id, j) { expect(id, "sources", p + ".source_ids[" + j + "]"); });
      if (e.original_ids !== undefined) {
        if (!Array.isArray(e.original_ids)) ctx.err(p + ".original_ids", "Must be a list of text values.");
        else e.original_ids.forEach(function (a, j) { checkString(ctx, a, p + ".original_ids[" + j + "]", 256, null, true); });
      }
    });

    (doc.observations || []).forEach(function (o, i) {
      var p = "$.observations[" + i + "]";
      if (!isPlainObject(o)) return;
      if (checkString(ctx, o.source_id, p + ".source_id", LIMITS.maxId, ID_RE, true)) expect(o.source_id, "sources", p + ".source_id");
      checkString(ctx, o.location, p + ".location", LIMITS.maxLabel, null, false);
      checkString(ctx, o.excerpt, p + ".excerpt", LIMITS.maxText, null, true);
      checkRefList(ctx, o.about, p + ".about", true).forEach(function (id, j) { expect(id, "entities", p + ".about[" + j + "]"); });
      checkTimeField(ctx, o, "observed_at", p, true);
      checkTimeField(ctx, o, "collected_at", p, true);
      checkTimeField(ctx, o, "ingested_at", p, true);
      if (!isPlainObject(o.extraction)) ctx.err(p + ".extraction", "Extraction method is required.");
      else {
        checkEnum(ctx, o.extraction.method, p + ".extraction.method", EXTRACTION_METHODS);
        checkString(ctx, o.extraction.version, p + ".extraction.version", 64, null, false);
        var conf = o.extraction.confidence;
        if (conf !== undefined && conf !== null && !(typeof conf === "number" && conf >= 0 && conf <= 1)) {
          ctx.err(p + ".extraction.confidence", "Must be null (not supplied) or a number from 0 to 1.");
        }
      }
    });

    (doc.relationships || []).forEach(function (r, i) {
      var p = "$.relationships[" + i + "]";
      if (!isPlainObject(r)) return;
      checkString(ctx, r.type, p + ".type", 48, REL_TYPE_RE, true);
      if (checkString(ctx, r.from, p + ".from", LIMITS.maxId, ID_RE, true)) expect(r.from, "entities", p + ".from");
      if (checkString(ctx, r.to, p + ".to", LIMITS.maxId, ID_RE, true)) expect(r.to, "entities", p + ".to");
      if (typeof r.directed !== "boolean") ctx.err(p + ".directed", "Must state whether the relationship is directed (true/false).");
      checkString(ctx, r.semantics, p + ".semantics", LIMITS.maxText, null, false);
      checkString(ctx, r.derivation, p + ".derivation", LIMITS.maxText, null, false);
      checkEnum(ctx, r.review, p + ".review", REVIEW_STATES);
      var ev = checkEvidenceBlock(ctx, r.evidence, p + ".evidence");
      ev.supporting.concat(ev.contradicting).forEach(function (id) { expect(id, "observations", p + ".evidence"); });
      checkTimeField(ctx, r, "first_observed", p, true);
      checkTimeField(ctx, r, "last_observed", p, true);
      var f = timeValue(r.first_observed), l = timeValue(r.last_observed);
      if (f !== null && l !== null && f > l) ctx.err(p + ".first_observed", "first_observed is later than last_observed.");
    });

    (doc.claims || []).forEach(function (c, i) {
      var p = "$.claims[" + i + "]";
      if (!isPlainObject(c)) return;
      checkString(ctx, c.statement, p + ".statement", LIMITS.maxText, null, true);
      checkEnum(ctx, c.kind, p + ".kind", CLAIM_KINDS);
      checkEnum(ctx, c.status, p + ".status", CLAIM_STATUS);
      checkEnum(ctx, c.review, p + ".review", REVIEW_STATES);
      checkRefList(ctx, c.about, p + ".about", true).forEach(function (id, j) { expect(id, "entities", p + ".about[" + j + "]"); });
      var ev = checkEvidenceBlock(ctx, c.evidence, p + ".evidence");
      ev.supporting.concat(ev.contradicting).forEach(function (id) { expect(id, "observations", p + ".evidence"); });
      if (c.derivation !== undefined && c.derivation !== null) {
        if (!isPlainObject(c.derivation)) ctx.err(p + ".derivation", "Must be an object with method and inputs.");
        else {
          checkString(ctx, c.derivation.method, p + ".derivation.method", LIMITS.maxLabel, null, true);
          checkRefList(ctx, c.derivation.inputs, p + ".derivation.inputs", true).forEach(function (id, j) {
            if (!kindOf.has(id)) ctx.err(p + ".derivation.inputs[" + j + "]", "\"" + id + "\" is not a known identifier.");
          });
        }
      }
    });

    (doc.merge_candidates || []).forEach(function (m, i) {
      var p = "$.merge_candidates[" + i + "]";
      if (!isPlainObject(m)) return;
      var ents = checkRefList(ctx, m.entities, p + ".entities", true);
      ents.forEach(function (id, j) { expect(id, "entities", p + ".entities[" + j + "]"); });
      if (uniq(ents).length < 2) ctx.err(p + ".entities", "A merge candidate needs at least two distinct entities.");
      if (!Array.isArray(m.criteria) || !m.criteria.length) ctx.err(p + ".criteria", "Explain the match criteria (at least one).");
      else m.criteria.forEach(function (c, j) { checkString(ctx, c, p + ".criteria[" + j + "]", LIMITS.maxText, null, true); });
    });

    return ctx.result();
  }

  /* Returns a copy containing only known fields with defaults filled in, so
     extra keys in an imported file can never reach rendering or export. */
  function normalizeDataset(doc) {
    var m = doc.dataset;
    function ev(b) { return { supporting: (b.supporting || []).slice(), contradicting: (b.contradicting || []).slice() }; }
    function opt(o, k) { return o[k] === undefined ? undefined : o[k]; }
    return {
      schema: SCHEMA,
      dataset: {
        id: m.id, title: m.title, version: m.version, description: m.description || "",
        synthetic: m.synthetic, as_of: m.as_of,
        export_policy: { restricted_attribute_keys: ((m.export_policy && m.export_policy.restricted_attribute_keys) || []).slice() }
      },
      sources: (doc.sources || []).map(function (s) {
        return {
          id: s.id, title: s.title, kind: s.kind, uri: s.uri || null,
          independence_group: s.independence_group || s.id,
          collected_at: s.collected_at === undefined ? null : s.collected_at,
          assessment: { reliability: s.assessment.reliability, basis: s.assessment.basis }
        };
      }),
      entities: doc.entities.map(function (e) {
        return {
          id: e.id, type: e.type, label: e.label, aliases: (e.aliases || []).slice(),
          attributes: clone(e.attributes || {}), source_ids: (e.source_ids || []).slice(),
          original_ids: (e.original_ids || []).slice()
        };
      }),
      observations: (doc.observations || []).map(function (o) {
        return {
          id: o.id, source_id: o.source_id, location: o.location || null, excerpt: o.excerpt,
          about: o.about.slice(), observed_at: o.observed_at, collected_at: o.collected_at, ingested_at: o.ingested_at,
          extraction: {
            method: o.extraction.method, version: o.extraction.version || null,
            confidence: (o.extraction.confidence === undefined) ? null : o.extraction.confidence
          }
        };
      }),
      relationships: (doc.relationships || []).map(function (r) {
        return {
          id: r.id, type: r.type, from: r.from, to: r.to, directed: r.directed,
          semantics: r.semantics || "", derivation: opt(r, "derivation") || null, review: r.review,
          evidence: ev(r.evidence), first_observed: r.first_observed, last_observed: r.last_observed
        };
      }),
      claims: (doc.claims || []).map(function (c) {
        return {
          id: c.id, statement: c.statement, kind: c.kind, status: c.status, review: c.review,
          about: c.about.slice(), evidence: ev(c.evidence),
          derivation: c.derivation ? { method: c.derivation.method, inputs: c.derivation.inputs.slice() } : null
        };
      }),
      merge_candidates: (doc.merge_candidates || []).map(function (mc) {
        return { id: mc.id, entities: uniq(mc.entities), criteria: mc.criteria.slice() };
      })
    };
  }

  function parseDataset(text) {
    if (typeof text !== "string") return { ok: false, errors: [{ path: "$", message: "Input must be text." }], warnings: [] };
    var bytes = utf8Bytes(text).length;
    if (bytes > LIMITS.maxBytes) {
      return { ok: false, bytes: bytes, warnings: [], errors: [{ path: "$", message: "File is " + bytes + " bytes; the limit is " + LIMITS.maxBytes + " bytes." }] };
    }
    var doc;
    try { doc = JSON.parse(text); } catch (e) {
      return { ok: false, bytes: bytes, warnings: [], errors: [{ path: "$", message: "Not valid JSON: " + String(e.message).slice(0, 200) }] };
    }
    var v = validateDataset(doc);
    if (!v.ok) return { ok: false, bytes: bytes, errors: v.errors, warnings: v.warnings, truncated: v.truncated };
    var ds = normalizeDataset(doc);
    return { ok: true, bytes: bytes, errors: [], warnings: v.warnings, dataset: ds, fingerprint: fingerprint(ds) };
  }

  /* ───────────────────────── indexing ───────────────────────── */

  function pushMap(map, key, val) { var a = map.get(key); if (a) a.push(val); else map.set(key, [val]); }

  function buildIndex(ds) {
    var idx = {
      entity: new Map(), source: new Map(), observation: new Map(), relationship: new Map(),
      claim: new Map(), merge: new Map(),
      relsByEntity: new Map(), obsByEntity: new Map(), claimsByEntity: new Map(), citedBy: new Map(),
      entityTypes: [], relTypes: [], timeExtent: { min: null, max: null }, undatedObservations: 0
    };
    ds.sources.forEach(function (s) { idx.source.set(s.id, s); });
    ds.entities.forEach(function (e) { idx.entity.set(e.id, e); });
    ds.observations.forEach(function (o) {
      idx.observation.set(o.id, o);
      o.about.forEach(function (id) { pushMap(idx.obsByEntity, id, o); });
      var t = timeValue(o.observed_at);
      if (t === null) idx.undatedObservations++;
      else {
        if (idx.timeExtent.min === null || t < idx.timeExtent.min) idx.timeExtent.min = t;
        if (idx.timeExtent.max === null || t > idx.timeExtent.max) idx.timeExtent.max = t;
      }
    });
    ds.relationships.forEach(function (r) {
      idx.relationship.set(r.id, r);
      pushMap(idx.relsByEntity, r.from, r);
      if (r.to !== r.from) pushMap(idx.relsByEntity, r.to, r);
      r.evidence.supporting.forEach(function (o) { pushMap(idx.citedBy, o, { kind: "relationship", id: r.id, role: "supporting" }); });
      r.evidence.contradicting.forEach(function (o) { pushMap(idx.citedBy, o, { kind: "relationship", id: r.id, role: "contradicting" }); });
    });
    ds.claims.forEach(function (c) {
      idx.claim.set(c.id, c);
      c.about.forEach(function (id) { pushMap(idx.claimsByEntity, id, c); });
      c.evidence.supporting.forEach(function (o) { pushMap(idx.citedBy, o, { kind: "claim", id: c.id, role: "supporting" }); });
      c.evidence.contradicting.forEach(function (o) { pushMap(idx.citedBy, o, { kind: "claim", id: c.id, role: "contradicting" }); });
    });
    ds.merge_candidates.forEach(function (m) { idx.merge.set(m.id, m); });
    idx.entityTypes = uniq(ds.entities.map(function (e) { return e.type; })).sort(function (a, b) {
      return ENTITY_TYPES.indexOf(a) - ENTITY_TYPES.indexOf(b);
    });
    idx.relTypes = uniq(ds.relationships.map(function (r) { return r.type; })).sort(cmpStr);
    return idx;
  }

  function kindOf(idx, id) {
    if (idx.entity.has(id)) return "entity";
    if (idx.relationship.has(id)) return "relationship";
    if (idx.observation.has(id)) return "observation";
    if (idx.claim.has(id)) return "claim";
    if (idx.source.has(id)) return "source";
    if (idx.merge.has(id)) return "merge_candidate";
    return null;
  }
  function knownIds(idx) {
    var s = new Set();
    ["entity", "relationship", "observation", "claim", "source", "merge"].forEach(function (k) {
      idx[k].forEach(function (_v, id) { s.add(id); });
    });
    return s;
  }

  /* ───────────────────────── entity resolution ───────────────────────── */

  /* Confirmed merges come from analyst decisions in the notebook, never from
     the dataset and never from name similarity alone. The surviving identifier
     is the lexicographically smallest member, so the result does not depend on
     decision order. Every original identifier stays reachable. */
  function mergeResolver(groups) {
    var parent = new Map();
    function find(x) {
      var r = x;
      while (parent.has(r) && parent.get(r) !== r) r = parent.get(r);
      var c = x;
      while (parent.has(c) && parent.get(c) !== r) { var n = parent.get(c); parent.set(c, r); c = n; }
      return r;
    }
    function union(a, b) {
      var ra = find(a), rb = find(b);
      if (ra === rb) return;
      if (ra < rb) parent.set(rb, ra); else parent.set(ra, rb);
    }
    (groups || []).forEach(function (g) {
      g.forEach(function (id) { if (!parent.has(id)) parent.set(id, id); });
      for (var i = 1; i < g.length; i++) union(g[0], g[i]);
    });
    var members = new Map();
    parent.forEach(function (_v, id) { pushMap(members, find(id), id); });
    members.forEach(function (list) { list.sort(cmpStr); });
    return {
      canonicalOf: function (id) { return parent.has(id) ? find(id) : id; },
      membersOf: function (id) { var r = parent.has(id) ? find(id) : id; return members.get(r) || [id]; },
      isMerged: function (id) { var r = parent.has(id) ? find(id) : id; return (members.get(r) || []).length > 1; }
    };
  }
  var IDENTITY_RESOLVER = mergeResolver([]);

  /* ───────────────────────── graph projection + filters ───────────────────────── */

  /* Three outcomes, never guessed: a definite overlap passes, a definite miss
     fails, and an interval whose unknown end (or start) decides the answer is
     "uncertain" and follows w.includeUnknown — the same rule as fully undated
     relationships. A missing last_observed is not read as "still ongoing". */
  function windowOverlap(rel, w) {
    if (!w) return "yes";
    var f = timeValue(rel.first_observed), l = timeValue(rel.last_observed);
    var from = timeValue(w.from), to = timeValue(w.to);
    if (f === null && l === null) return "unknown";
    if (f !== null && l !== null) {
      if (from !== null && l < from) return "no";
      if (to !== null && f > to) return "no";
      return "yes";
    }
    if (f !== null) {
      if (to !== null && f > to) return "no";
      if (from === null || f >= from) return "yes";
      return "unknown";
    }
    if (from !== null && l < from) return "no";
    if (to === null || l <= to) return "yes";
    return "unknown";
  }
  function windowAllows(rel, w) {
    var o = windowOverlap(rel, w);
    return o === "yes" || (o === "unknown" && !!(w && w.includeUnknown));
  }

  function projectEdges(ds, resolver) {
    var r = resolver || IDENTITY_RESOLVER;
    return ds.relationships.map(function (rel) {
      return { id: rel.id, from: r.canonicalOf(rel.from), to: r.canonicalOf(rel.to), rel: rel };
    });
  }

  function bfsDistances(nodeIds, edges, start, maxDepth) {
    var adj = new Map();
    nodeIds.forEach(function (id) { adj.set(id, []); });
    edges.forEach(function (e) {
      if (e.from === e.to) return;
      if (adj.has(e.from) && adj.has(e.to)) { adj.get(e.from).push(e.to); adj.get(e.to).push(e.from); }
    });
    var dist = new Map();
    if (!adj.has(start)) return dist;
    dist.set(start, 0);
    var queue = [start], head = 0;
    while (head < queue.length) {
      var cur = queue[head++], d = dist.get(cur);
      if (maxDepth !== undefined && maxDepth !== null && d >= maxDepth) continue;
      adj.get(cur).forEach(function (n) { if (!dist.has(n)) { dist.set(n, d + 1); queue.push(n); } });
    }
    return dist;
  }

  /* opts: { resolver, filters: {entityTypes, relTypes, review, window}, focus, hops, keep }
     A null/absent filter list means "no restriction". */
  function buildGraph(ds, idx, opts) {
    opts = opts || {};
    var resolver = opts.resolver || IDENTITY_RESOLVER;
    var f = opts.filters || {};
    var allowType = f.entityTypes ? new Set(f.entityTypes) : null;
    var allowRel = f.relTypes ? new Set(f.relTypes) : null;
    var allowReview = f.review ? new Set(f.review) : null;

    var nodesById = new Map();
    ds.entities.forEach(function (e) {
      var cid = resolver.canonicalOf(e.id);
      if (!nodesById.has(cid)) {
        var canon = idx.entity.get(cid) || e;
        var members = resolver.membersOf(cid);
        var types = uniq(members.map(function (m) { return (idx.entity.get(m) || e).type; }));
        nodesById.set(cid, { id: cid, entity: canon, type: canon.type, label: canon.label, members: members, typeConflict: types.length > 1, forced: false });
      }
    });
    var allEdges = projectEdges(ds, resolver);
    var totals = { nodes: nodesById.size, edges: allEdges.length };

    var typeOk = function (id) { var n = nodesById.get(id); return !!n && (!allowType || allowType.has(n.type)); };
    var excluded = { byEntityType: 0, byRelType: 0, byReview: 0, byWindow: 0, byFocus: 0 };
    var edges = allEdges.filter(function (e) {
      if (allowRel && !allowRel.has(e.rel.type)) { excluded.byRelType++; return false; }
      if (allowReview && !allowReview.has(e.rel.review)) { excluded.byReview++; return false; }
      if (!windowAllows(e.rel, f.window)) { excluded.byWindow++; return false; }
      if (!typeOk(e.from) || !typeOk(e.to)) { excluded.byEntityType++; return false; }
      return true;
    });
    var visible = [];
    nodesById.forEach(function (n) { if (typeOk(n.id)) visible.push(n.id); });

    var focus = opts.focus ? resolver.canonicalOf(opts.focus) : null;
    var dist = null;
    if (focus && nodesById.has(focus) && opts.hops) {
      var pool = visible.indexOf(focus) === -1 ? visible.concat([focus]) : visible;
      dist = bfsDistances(pool, edges, focus, opts.hops);
      var before = edges.length;
      visible = pool.filter(function (id) { return dist.has(id); });
      edges = edges.filter(function (e) { return dist.has(e.from) && dist.has(e.to); });
      excluded.byFocus = before - edges.length;
    }

    var visibleSet = new Set(visible);
    var forced = [];
    (opts.keep || []).forEach(function (id) {
      var cid = resolver.canonicalOf(id);
      if (nodesById.has(cid) && !visibleSet.has(cid)) { visibleSet.add(cid); forced.push(cid); }
    });
    var nodes = [];
    visibleSet.forEach(function (id) {
      var n = nodesById.get(id);
      nodes.push(Object.assign({}, n, { forced: forced.indexOf(id) !== -1, distance: dist && dist.has(id) ? dist.get(id) : null }));
    });
    nodes.sort(function (a, b) { return cmpStr(a.id, b.id); });
    var hidden = { nodes: totals.nodes - nodes.length + forced.length, edges: totals.edges - edges.length };
    if (hidden.nodes < 0) hidden.nodes = 0;
    return {
      nodes: nodes, edges: edges, totals: totals, hidden: hidden, forced: forced, excluded: excluded,
      scope: (nodes.length - forced.length === totals.nodes && edges.length === totals.edges) ? "full" : "subgraph",
      focus: dist ? focus : null, hops: dist ? opts.hops : 0
    };
  }

  /* ───────────────────────── path analysis ───────────────────────── */

  /* Fewest-hop paths under explicit constraints. A path qualifies because every
     step satisfies the constraints — nothing more. It is not a measure of
     strength, likelihood, risk or causation. */
  function findPaths(edges, params) {
    var p = Object.assign({ direction: "any", maxHops: 4, limit: 20, relTypes: null, review: null, window: null }, params || {});
    p.maxHops = Math.max(1, Math.min(8, p.maxHops | 0));
    p.limit = Math.max(1, Math.min(50, p.limit | 0));
    var allowRel = p.relTypes ? new Set(p.relTypes) : null;
    var allowReview = p.review ? new Set(p.review) : null;
    var excluded = { byRelType: 0, byReview: 0, byWindow: 0, selfLoops: 0 };
    var adj = new Map();
    function add(a, step) { pushMap(adj, a, step); }
    var eligible = 0;
    edges.forEach(function (e) {
      if (e.from === e.to) { excluded.selfLoops++; return; }
      if (allowRel && !allowRel.has(e.rel.type)) { excluded.byRelType++; return; }
      if (allowReview && !allowReview.has(e.rel.review)) { excluded.byReview++; return; }
      if (!windowAllows(e.rel, p.window)) { excluded.byWindow++; return; }
      eligible++;
      var directed = e.rel.directed;
      add(e.from, { edge: e, next: e.to, traversal: directed ? "forward" : "undirected" });
      if (!directed || p.direction === "any") add(e.to, { edge: e, next: e.from, traversal: directed ? "reverse" : "undirected" });
    });
    adj.forEach(function (list) { list.sort(function (a, b) { return cmpStr(a.edge.id, b.edge.id) || cmpStr(a.next, b.next); }); });

    var result = { params: p, paths: [], shortestLength: null, reachable: false, truncated: false, exploredNodes: 0, eligibleEdges: eligible, excluded: excluded };
    if (!p.from || !p.to || p.from === p.to) return result;
    var dist = new Map([[p.from, 0]]), parents = new Map(), queue = [p.from], head = 0;
    while (head < queue.length) {
      var cur = queue[head++], d = dist.get(cur);
      if (cur === p.to) continue;
      if (d >= p.maxHops) continue;
      (adj.get(cur) || []).forEach(function (step) {
        var n = step.next;
        if (!dist.has(n)) { dist.set(n, d + 1); queue.push(n); }
        if (dist.get(n) === d + 1) pushMap(parents, n, { prev: cur, step: step });
      });
    }
    result.exploredNodes = dist.size;
    if (!dist.has(p.to)) return result;
    result.reachable = true;
    result.shortestLength = dist.get(p.to);
    var out = [];
    (function walk(node, acc) {
      if (out.length >= p.limit) { result.truncated = true; return; }
      if (node === p.from) { out.push(acc.slice().reverse()); return; }
      (parents.get(node) || []).forEach(function (pp) {
        if (out.length >= p.limit) { result.truncated = true; return; }
        acc.push({
          relationship: pp.step.edge.id, type: pp.step.edge.rel.type, from: pp.prev, to: node,
          traversal: pp.step.traversal, review: pp.step.edge.rel.review,
          supporting: pp.step.edge.rel.evidence.supporting.length, contradicting: pp.step.edge.rel.evidence.contradicting.length
        });
        walk(pp.prev, acc);
        acc.pop();
      });
    })(p.to, []);
    result.paths = out.map(function (steps) { return { length: steps.length, steps: steps }; });
    return result;
  }

  /* ───────────────────────── graph metrics ───────────────────────── */

  var METRIC_DEFINITIONS = Object.freeze({
    degree: "Degree counts relationship records touching an entity in the current scope. Parallel records each count. Self-loops are counted separately and excluded from degree and density.",
    distinctNeighbors: "Distinct neighbours counts other entities connected by at least one record, ignoring direction and duplicates.",
    densityUndirected: "Undirected density = distinct connected entity pairs {u,v} (u≠v) ÷ n(n−1)/2. Undefined for fewer than two entities.",
    densityDirected: "Directed density = distinct ordered pairs (u→v) (u≠v) ÷ n(n−1). Undirected records contribute both orders.",
    components: "Weakly connected components: groups of entities linked by any path when direction is ignored. Isolated entities are components of size 1.",
    duplicates: "Duplicate records share the same endpoints and type (undirected records compare endpoints in either order). They are kept, because each may carry different evidence.",
    caution: "Degree and connectivity describe the recorded data in this scope. They do not measure importance, authority, intent, involvement or guilt, and they change when filters change."
  });

  function computeMetrics(nodes, edges) {
    var ids = nodes.map(function (n) { return n.id; });
    var n = ids.length;
    var deg = new Map();
    ids.forEach(function (id) { deg.set(id, { in: 0, out: 0, undirected: 0, total: 0, selfLoops: 0, neighbors: new Set() }); });
    var selfLoops = 0, duplicates = 0, seenTriple = new Set(), unordered = new Set(), ordered = new Set();
    edges.forEach(function (e) {
      var a = deg.get(e.from), b = deg.get(e.to);
      if (!a || !b) return;
      var key = e.rel.directed ? e.from + "\u0000" + e.to : [e.from, e.to].sort().join("\u0000");
      var triple = key + "\u0000" + e.rel.type + "\u0000" + (e.rel.directed ? "d" : "u");
      if (seenTriple.has(triple)) duplicates++; else seenTriple.add(triple);
      if (e.from === e.to) { selfLoops++; a.selfLoops++; return; }
      if (e.rel.directed) { a.out++; b.in++; ordered.add(e.from + "\u0000" + e.to); }
      else { a.undirected++; b.undirected++; ordered.add(e.from + "\u0000" + e.to); ordered.add(e.to + "\u0000" + e.from); }
      a.neighbors.add(e.to); b.neighbors.add(e.from);
      unordered.add([e.from, e.to].sort().join("\u0000"));
    });
    var parent = new Map();
    ids.forEach(function (id) { parent.set(id, id); });
    function find(x) { while (parent.get(x) !== x) { parent.set(x, parent.get(parent.get(x))); x = parent.get(x); } return x; }
    edges.forEach(function (e) {
      if (!parent.has(e.from) || !parent.has(e.to)) return;
      var ra = find(e.from), rb = find(e.to);
      if (ra !== rb) { if (ra < rb) parent.set(rb, ra); else parent.set(ra, rb); }
    });
    var comps = new Map();
    ids.forEach(function (id) { pushMap(comps, find(id), id); });
    var components = [];
    comps.forEach(function (list) { list.sort(cmpStr); components.push({ size: list.length, ids: list }); });
    components.sort(function (a, b) { return b.size - a.size || cmpStr(a.ids[0], b.ids[0]); });

    var degree = {};
    deg.forEach(function (d, id) {
      degree[id] = { in: d.in, out: d.out, undirected: d.undirected, total: d.in + d.out + d.undirected, selfLoops: d.selfLoops, distinctNeighbors: d.neighbors.size };
    });
    var ranked = ids.slice().sort(function (a, b) { return degree[b].total - degree[a].total || cmpStr(a, b); });
    return {
      nodeCount: n,
      edgeRecords: edges.length,
      distinctPairs: unordered.size,
      selfLoops: selfLoops,
      duplicateRecords: duplicates,
      densityUndirected: n < 2 ? null : round(unordered.size / (n * (n - 1) / 2), 6),
      densityDirected: n < 2 ? null : round(ordered.size / (n * (n - 1)), 6),
      componentCount: components.length,
      largestComponent: components.length ? components[0].size : 0,
      isolated: components.filter(function (c) { return c.size === 1; }).length,
      components: components,
      degree: degree,
      topByDegree: ranked.slice(0, 10).map(function (id) { return { id: id, total: degree[id].total, distinctNeighbors: degree[id].distinctNeighbors }; }),
      definitions: METRIC_DEFINITIONS
    };
  }

  /* Wraps any analysis so its result carries what is needed to reproduce it. */
  function runAnalysis(spec, fn, now) {
    var t0 = perfNow();
    var result = fn();
    var t1 = perfNow();
    return {
      name: spec.name,
      algorithm: spec.algorithm,
      algorithm_version: spec.version || CORE_VERSION,
      core_version: CORE_VERSION,
      params: clone(spec.params || {}),
      scope: spec.scope || null,
      dataset_fingerprint: spec.fingerprint || null,
      seed: spec.seed === undefined ? null : spec.seed,
      approximation: spec.approximation || null,
      limitations: (spec.limitations || []).slice(),
      executed_at: isoOf(now),
      runtime_ms: round(t1 - t0, 2),
      result: result
    };
  }

  /* ───────────────────────── layouts ───────────────────────── */

  function nodeOrder(a, b) {
    return (ENTITY_TYPES.indexOf(a.type) - ENTITY_TYPES.indexOf(b.type)) ||
      cmpStr(String(a.label).toLowerCase(), String(b.label).toLowerCase()) || cmpStr(a.id, b.id);
  }

  /* Radial layout. Without a focus: one sector per entity type around the
     circle. With a focus: concentric rings by hop distance (direction ignored),
     each ring ordered by the mean angle of its parents to reduce crossings. */
  function layoutRadial(nodes, edges, opts) {
    opts = opts || {};
    var pos = new Map(), rings = [];
    var sorted = nodes.slice().sort(nodeOrder);
    var n = sorted.length;
    if (!n) return { positions: pos, rings: rings, mode: "empty" };
    var focus = opts.focus && sorted.some(function (x) { return x.id === opts.focus; }) ? opts.focus : null;
    if (!focus) {
      var groups = [], cur = null;
      sorted.forEach(function (node) {
        if (!cur || cur.type !== node.type) { cur = { type: node.type, nodes: [] }; groups.push(cur); }
        cur.nodes.push(node);
      });
      var ringCount = Math.max(1, Math.ceil(n / 64));
      var gap = groups.length > 1 ? Math.min(0.18, 1.2 / groups.length) : 0;
      var usable = Math.PI * 2 - gap * groups.length;
      var angle = -Math.PI / 2 + gap / 2;
      var sectors = [];
      groups.forEach(function (g) {
        var span = usable * (g.nodes.length / n);
        var perRing = Math.ceil(g.nodes.length / ringCount);
        g.nodes.forEach(function (node, i) {
          var ring = i % ringCount, k = Math.floor(i / ringCount);
          var slots = Math.max(1, perRing);
          var a = angle + span * ((k + 0.5) / slots);
          var r = ringCount === 1 ? 1 : 0.62 + 0.38 * (ring / (ringCount - 1));
          pos.set(node.id, { x: Math.cos(a) * r, y: Math.sin(a) * r });
        });
        sectors.push({ type: g.type, start: angle, end: angle + span, count: g.nodes.length });
        angle += span + gap;
      });
      for (var ri = 0; ri < ringCount; ri++) rings.push({ radius: ringCount === 1 ? 1 : 0.62 + 0.38 * (ri / (ringCount - 1)), label: null, count: null });
      return { positions: pos, rings: rings, sectors: sectors, mode: "type-sectors" };
    }
    var dist = bfsDistances(sorted.map(function (x) { return x.id; }), edges, focus);
    var maxD = 0;
    dist.forEach(function (d) { if (d > maxD) maxD = d; });
    var unreachable = sorted.filter(function (x) { return !dist.has(x.id); });
    var levels = [];
    sorted.forEach(function (x) { if (dist.has(x.id)) { var d = dist.get(x.id); (levels[d] = levels[d] || []).push(x); } });
    var outer = maxD + (unreachable.length ? 1 : 0);
    var radiusOf = function (d) { return outer === 0 ? 0 : d / outer; };
    pos.set(focus, { x: 0, y: 0 });
    var angleOf = new Map([[focus, -Math.PI / 2]]);
    var adj = new Map();
    edges.forEach(function (e) { if (e.from !== e.to) { pushMap(adj, e.from, e.to); pushMap(adj, e.to, e.from); } });
    for (var d = 1; d < levels.length; d++) {
      var level = levels[d] || [];
      var withTarget = level.map(function (x) {
        var ps = (adj.get(x.id) || []).filter(function (p) { return dist.get(p) === d - 1 && angleOf.has(p); });
        var sx = 0, sy = 0;
        ps.forEach(function (p) { sx += Math.cos(angleOf.get(p)); sy += Math.sin(angleOf.get(p)); });
        var t = ps.length ? Math.atan2(sy, sx) : 0;
        return { node: x, target: t };
      });
      withTarget.sort(function (a, b) { return (a.target - b.target) || nodeOrder(a.node, b.node); });
      var start = withTarget.length ? withTarget[0].target : 0;
      withTarget.forEach(function (w, i) {
        var a = d === 1 ? -Math.PI / 2 + (Math.PI * 2 * i) / withTarget.length : start + (Math.PI * 2 * i) / withTarget.length;
        angleOf.set(w.node.id, a);
        pos.set(w.node.id, { x: Math.cos(a) * radiusOf(d), y: Math.sin(a) * radiusOf(d) });
      });
      rings.push({ radius: radiusOf(d), label: d === 1 ? "1 hop" : d + " hops", count: level.length });
    }
    unreachable.forEach(function (x, i) {
      var a = -Math.PI / 2 + (Math.PI * 2 * i) / unreachable.length;
      pos.set(x.id, { x: Math.cos(a), y: Math.sin(a) });
    });
    if (unreachable.length) rings.push({ radius: 1, label: "not connected in view", count: unreachable.length });
    return { positions: pos, rings: rings, mode: "focus-rings", focus: focus };
  }

  /* Hierarchical layering for directed relationships. Refuses (rather than
     inventing an order) when directed cycles exist. */
  function layoutHierarchical(nodes, edges) {
    var ids = nodes.map(function (x) { return x.id; }), idset = new Set(ids);
    var indeg = new Map(), succ = new Map(), pred = new Map();
    ids.forEach(function (id) { indeg.set(id, 0); });
    var directed = 0;
    edges.forEach(function (e) {
      if (!e.rel.directed || e.from === e.to || !idset.has(e.from) || !idset.has(e.to)) return;
      directed++;
      pushMap(succ, e.from, e.to); pushMap(pred, e.to, e.from);
      indeg.set(e.to, indeg.get(e.to) + 1);
    });
    var queue = ids.filter(function (id) { return indeg.get(id) === 0; }).sort(cmpStr), order = [], head = 0;
    var remaining = new Map(indeg);
    while (head < queue.length) {
      var cur = queue[head++]; order.push(cur);
      (succ.get(cur) || []).forEach(function (s) { remaining.set(s, remaining.get(s) - 1); if (remaining.get(s) === 0) queue.push(s); });
    }
    if (order.length < ids.length) {
      return { ok: false, reason: "Directed cycle among " + (ids.length - order.length) + " entities. A hierarchical layout needs acyclic directed relationships, so none is drawn." };
    }
    if (!directed) return { ok: false, reason: "No directed relationships in view, so there is no hierarchy to draw." };
    var layer = new Map();
    order.forEach(function (id) {
      var l = 0;
      (pred.get(id) || []).forEach(function (p) { l = Math.max(l, layer.get(p) + 1); });
      layer.set(id, l);
    });
    var linked = new Set();
    edges.forEach(function (e) { if (e.rel.directed && e.from !== e.to) { linked.add(e.from); linked.add(e.to); } });
    var maxL = 0;
    layer.forEach(function (l, id) { if (linked.has(id) && l > maxL) maxL = l; });
    var rows = [];
    var byId = new Map(nodes.map(function (x) { return [x.id, x]; }));
    ids.forEach(function (id) {
      var r = linked.has(id) ? layer.get(id) : maxL + 1;
      (rows[r] = rows[r] || []).push(id);
    });
    var pos = new Map(), xs = new Map();
    var rowCount = rows.length;
    rows.forEach(function (row, r) {
      if (!row) return;
      row.sort(function (a, b) {
        function bary(id) {
          var ps = (pred.get(id) || []).filter(function (p) { return xs.has(p); });
          if (!ps.length) return null;
          return ps.reduce(function (s, p) { return s + xs.get(p); }, 0) / ps.length;
        }
        var ba = bary(a), bb = bary(b);
        if (ba !== null && bb !== null && ba !== bb) return ba - bb;
        return nodeOrder(byId.get(a), byId.get(b));
      });
      row.forEach(function (id, i) {
        var x = row.length === 1 ? 0 : -1 + (2 * i) / (row.length - 1);
        xs.set(id, x);
        pos.set(id, { x: x, y: rowCount === 1 ? 0 : -1 + (2 * r) / (rowCount - 1) });
      });
    });
    return { ok: true, positions: pos, layers: rowCount, unlinkedRow: rows[maxL + 1] ? maxL + 1 : null, mode: "hierarchical" };
  }

  /* Seeded force-directed layout (Fruchterman–Reingold). Built as a stepper so
     the UI can time-slice it, show progress and cancel stale runs. Above 600
     entities repulsion only considers neighbouring grid cells — an
     approximation that is reported with the result. */
  function createForceLayout(nodes, edges, opts) {
    opts = opts || {};
    var seed = (opts.seed === undefined ? 1337 : opts.seed) >>> 0;
    var rand = mulberry32(seed);
    var n = nodes.length;
    var iterations = opts.iterations || (n <= 200 ? 300 : n <= 1000 ? 200 : 120);
    var pinned = opts.pinned || new Map();
    var initial = opts.initial || new Map();
    var approximate = n > 600;
    var k = Math.sqrt(4 / Math.max(1, n));
    var idxOf = new Map();
    var x = new Float64Array(n), y = new Float64Array(n), dx = new Float64Array(n), dy = new Float64Array(n);
    var fixed = new Uint8Array(n);
    var sorted = nodes.slice().sort(function (a, b) { return cmpStr(a.id, b.id); });
    sorted.forEach(function (node, i) {
      idxOf.set(node.id, i);
      var p = pinned.get(node.id) || initial.get(node.id);
      if (p) { x[i] = p.x; y[i] = p.y; } else {
        var a = rand() * Math.PI * 2, r = Math.sqrt(rand());
        x[i] = Math.cos(a) * r; y[i] = Math.sin(a) * r;
      }
      if (pinned.has(node.id)) fixed[i] = 1;
    });
    var links = [];
    edges.forEach(function (e) {
      var a = idxOf.get(e.from), b = idxOf.get(e.to);
      if (a !== undefined && b !== undefined && a !== b) links.push([a, b]);
    });
    var iter = 0, t0 = 0.12;
    function repulseExact() {
      for (var i = 0; i < n; i++) {
        for (var j = i + 1; j < n; j++) {
          var ddx = x[i] - x[j], ddy = y[i] - y[j];
          var d2 = ddx * ddx + ddy * ddy;
          if (d2 < 1e-9) { ddx = (rand() - 0.5) * 1e-3; ddy = (rand() - 0.5) * 1e-3; d2 = ddx * ddx + ddy * ddy; }
          var f = (k * k) / d2;
          dx[i] += ddx * f; dy[i] += ddy * f; dx[j] -= ddx * f; dy[j] -= ddy * f;
        }
      }
    }
    function repulseGrid() {
      var cell = 2 * k, grid = new Map();
      for (var i = 0; i < n; i++) {
        var key = Math.floor(x[i] / cell) + ":" + Math.floor(y[i] / cell);
        pushMap(grid, key, i);
      }
      grid.forEach(function (list, key) {
        var parts = key.split(":"), cx = +parts[0], cy = +parts[1];
        for (var ox = -1; ox <= 1; ox++) for (var oy = -1; oy <= 1; oy++) {
          var other = grid.get((cx + ox) + ":" + (cy + oy));
          if (!other) continue;
          list.forEach(function (i) {
            other.forEach(function (j) {
              if (j <= i) return;
              var ddx = x[i] - x[j], ddy = y[i] - y[j];
              var d2 = ddx * ddx + ddy * ddy;
              if (d2 < 1e-9) { ddx = (rand() - 0.5) * 1e-3; ddy = (rand() - 0.5) * 1e-3; d2 = ddx * ddx + ddy * ddy; }
              var f = (k * k) / d2;
              dx[i] += ddx * f; dy[i] += ddy * f; dx[j] -= ddx * f; dy[j] -= ddy * f;
            });
          });
        }
      });
    }
    function stepOnce() {
      dx.fill(0); dy.fill(0);
      if (approximate) repulseGrid(); else repulseExact();
      for (var l = 0; l < links.length; l++) {
        var a = links[l][0], b = links[l][1];
        var ddx = x[a] - x[b], ddy = y[a] - y[b];
        var d = Math.sqrt(ddx * ddx + ddy * ddy) || 1e-6;
        var f = d / k;
        dx[a] -= ddx * f; dy[a] -= ddy * f; dx[b] += ddx * f; dy[b] += ddy * f;
      }
      var temp = t0 * (1 - iter / iterations) + 0.002;
      for (var i = 0; i < n; i++) {
        if (fixed[i]) continue;
        dx[i] -= x[i] * 0.06; dy[i] -= y[i] * 0.06;
        var len = Math.sqrt(dx[i] * dx[i] + dy[i] * dy[i]) || 1e-9;
        var m = Math.min(len, temp);
        x[i] += (dx[i] / len) * m; y[i] += (dy[i] / len) * m;
      }
      iter++;
    }
    return {
      params: { seed: seed, iterations: iterations, approximation: approximate ? "grid-neighbourhood repulsion (n > 600)" : null, pinned: pinned.size },
      step: function (count) { var c = count || 1; while (c-- > 0 && iter < iterations) stepOnce(); return iter >= iterations; },
      done: function () { return iter >= iterations; },
      progress: function () { return iterations ? iter / iterations : 1; },
      positions: function () {
        var out = new Map();
        sorted.forEach(function (node, i) { out.set(node.id, { x: x[i], y: y[i] }); });
        return out;
      }
    };
  }
  function layoutForce(nodes, edges, opts) {
    var lay = createForceLayout(nodes, edges, opts);
    lay.step(Infinity);
    return { positions: lay.positions(), params: lay.params, mode: "force" };
  }

  /* ───────────────────────── evidence assessment ───────────────────────── */

  function assessEvidence(idx, refs) {
    function expand(ids) {
      return (ids || []).map(function (id) {
        var o = idx.observation.get(id);
        if (!o) return { id: id, missing: true };
        return { id: id, missing: false, observation: o, source: idx.source.get(o.source_id) || null };
      });
    }
    var sup = expand(refs && refs.supporting), con = expand(refs && refs.contradicting);
    function groups(list) {
      var g = new Map();
      list.forEach(function (x) {
        if (x.missing) return;
        var key = x.source ? x.source.independence_group : "unknown-source";
        pushMap(g, key, x.id);
      });
      return g;
    }
    var gs = groups(sup), gc = groups(con);
    var present = sup.filter(function (x) { return !x.missing; });
    var all = present.concat(con.filter(function (x) { return !x.missing; }));
    var conf = all.filter(function (x) { return x.observation.extraction.confidence !== null; });
    var latestObserved = null, latestCollected = null, undated = 0;
    all.forEach(function (x) {
      var to = timeValue(x.observation.observed_at), tc = timeValue(x.observation.collected_at);
      if (to === null) undated++; else if (latestObserved === null || to > latestObserved) latestObserved = to;
      if (tc !== null && (latestCollected === null || tc > latestCollected)) latestCollected = tc;
    });
    var reliab = new Map();
    all.forEach(function (x) { if (x.source) reliab.set(x.source.id, x.source); });
    return {
      supporting: sup,
      contradicting: con,
      missing: sup.concat(con).filter(function (x) { return x.missing; }).map(function (x) { return x.id; }),
      corroboration: {
        records: present.length,
        independentGroups: gs.size,
        dependentRecords: present.length - gs.size,
        groups: Array.from(gs.entries()).map(function (e) { return { group: e[0], records: e[1] }; }),
        contradictingGroups: gc.size
      },
      extraction: {
        supplied: conf.map(function (x) { return { id: x.id, confidence: x.observation.extraction.confidence, method: x.observation.extraction.method }; }),
        notSupplied: all.length - conf.length,
        methods: uniq(all.map(function (x) { return x.observation.extraction.method + (x.observation.extraction.version ? "@" + x.observation.extraction.version : ""); }))
      },
      sources: Array.from(reliab.values()).map(function (s) { return { id: s.id, title: s.title, reliability: s.assessment.reliability, basis: s.assessment.basis, group: s.independence_group }; }),
      freshness: {
        latestObserved: latestObserved === null ? null : new Date(latestObserved).toISOString(),
        latestCollected: latestCollected === null ? null : new Date(latestCollected).toISOString(),
        undated: undated
      }
    };
  }

  function relRefs(idx, kind, id) {
    if (kind === "relationship") { var r = idx.relationship.get(id); return r ? r.evidence : null; }
    if (kind === "claim") { var c = idx.claim.get(id); return c ? c.evidence : null; }
    if (kind === "entity") {
      return { supporting: (idx.obsByEntity.get(id) || []).map(function (o) { return o.id; }), contradicting: [] };
    }
    if (kind === "observation") return { supporting: [id], contradicting: [] };
    return null;
  }

  function plural(n, one, many) { return n + " " + (n === 1 ? one : (many || one + "s")); }

  /* Rule-based summary — no model. Each sentence lists the record IDs it rests on. */
  function summarize(idx, kind, id, resolver) {
    var r = resolver || IDENTITY_RESOLVER;
    var label = function (eid) { var e = idx.entity.get(r.canonicalOf(eid)) || idx.entity.get(eid); return e ? e.label : eid; };
    var out = [];
    if (kind === "relationship") {
      var rel = idx.relationship.get(id);
      if (!rel) return out;
      var a = assessEvidence(idx, rel.evidence);
      out.push({ text: label(rel.from) + (rel.directed ? " → " : " — ") + rel.type.replace(/_/g, " ") + (rel.directed ? " → " : " — ") + label(rel.to) + ". Analyst review state: " + rel.review + ".", cites: [rel.id] });
      out.push({
        text: "Supported by " + plural(a.corroboration.records, "observation record") + " from " + plural(a.corroboration.independentGroups, "independent source group") +
          (a.corroboration.dependentRecords > 0 ? " (" + plural(a.corroboration.dependentRecords, "record") + " share an upstream source and are not counted as independent)" : "") + ".",
        cites: rel.evidence.supporting
      });
      out.push({ text: rel.evidence.contradicting.length ? plural(rel.evidence.contradicting.length, "record") + " contradict it." : "No contradicting records are attached.", cites: rel.evidence.contradicting });
      out.push({ text: (rel.first_observed || rel.last_observed) ? "Recorded observation window: " + (rel.first_observed || "unknown") + " to " + (rel.last_observed || "unknown") + "." : "The observation window is unknown.", cites: [] });
      if (a.missing.length) out.push({ text: plural(a.missing.length, "cited record") + " could not be found in this dataset.", cites: [] });
      return out;
    }
    if (kind === "claim") {
      var c = idx.claim.get(id);
      if (!c) return out;
      var ac = assessEvidence(idx, c.evidence);
      out.push({ text: "Claim recorded as " + c.kind.toUpperCase() + ", status " + c.status + ", review " + c.review + ".", cites: [c.id] });
      out.push({ text: plural(ac.corroboration.records, "supporting record") + " across " + plural(ac.corroboration.independentGroups, "independent source group") + "; " + plural(c.evidence.contradicting.length, "contradicting record") + ".", cites: c.evidence.supporting.concat(c.evidence.contradicting) });
      if (c.derivation) out.push({ text: "Derived by: " + c.derivation.method + ".", cites: c.derivation.inputs.filter(function (x) { return kindOf(idx, x); }) });
      return out;
    }
    if (kind === "entity") {
      var members = r.membersOf(id);
      var rels = [], obs = [], claims = [];
      members.forEach(function (m) {
        (idx.relsByEntity.get(m) || []).forEach(function (x) { rels.push(x); });
        (idx.obsByEntity.get(m) || []).forEach(function (x) { obs.push(x); });
        (idx.claimsByEntity.get(m) || []).forEach(function (x) { claims.push(x); });
      });
      rels = uniq(rels); obs = uniq(obs); claims = uniq(claims);
      var e = idx.entity.get(r.canonicalOf(id)) || idx.entity.get(id);
      if (!e) return out;
      out.push({ text: e.label + " is recorded as type \"" + e.type + "\"" + (members.length > 1 ? ", merged by analyst decision from " + plural(members.length, "record") : "") + ".", cites: members });
      var types = uniq(rels.map(function (x) { return x.type.replace(/_/g, " "); })).sort();
      out.push({ text: "It appears in " + plural(rels.length, "relationship record") + (types.length ? " (" + types.join(", ") + ")" : "") + ", " + plural(obs.length, "observation") + " and " + plural(claims.length, "claim") + ".", cites: [] });
      var reviewed = rels.filter(function (x) { return x.review === "confirmed"; }).length;
      var disputed = rels.filter(function (x) { return x.review === "disputed"; }).length;
      out.push({ text: reviewed + " of its relationships are analyst-confirmed" + (disputed ? "; " + disputed + " are disputed" : "") + ".", cites: [] });
      return out;
    }
    return out;
  }

  /* ───────────────────────── citations ───────────────────────── */

  function cite(id) { return "[ref:" + id + "]"; }
  function validateCitations(text, known) {
    var set = known instanceof Set ? known : new Set(known || []);
    var cited = [], invalid = [], m;
    CITE_RE.lastIndex = 0;
    while ((m = CITE_RE.exec(String(text || ""))) !== null) {
      if (cited.indexOf(m[1]) === -1) cited.push(m[1]);
      if (!set.has(m[1]) && invalid.indexOf(m[1]) === -1) invalid.push(m[1]);
    }
    return { cited: cited, invalid: invalid, ok: invalid.length === 0 };
  }

  /* ───────────────────────── exports ───────────────────────── */

  function csvCell(v) {
    if (v === null || v === undefined) return "";
    if (typeof v === "number") return isFinite(v) ? String(v) : "";
    if (typeof v === "boolean") return v ? "true" : "false";
    var s = typeof v === "string" ? v : JSON.stringify(v);
    /* Spreadsheet formula injection: neutralise cells that a spreadsheet would
       evaluate (OWASP CSV injection guidance). */
    if (/^[=+\-@\t\r]/.test(s)) s = "'" + s;
    if (/[",\r\n]/.test(s) || /^\s|\s$/.test(s)) s = "\"" + s.replace(/"/g, "\"\"") + "\"";
    return s;
  }
  function toCSV(columns, rows) {
    var lines = [columns.map(csvCell).join(",")];
    rows.forEach(function (row) { lines.push(columns.map(function (c) { return csvCell(row[c]); }).join(",")); });
    return lines.join("\r\n") + "\r\n";
  }

  function restrictedKeys(ds) { return (ds.dataset.export_policy && ds.dataset.export_policy.restricted_attribute_keys) || []; }
  function redactAttributes(attrs, keys) {
    var out = {}, removed = [];
    Object.keys(attrs || {}).forEach(function (k) { if (keys.indexOf(k) !== -1) removed.push(k); else out[k] = attrs[k]; });
    return { attributes: out, removed: removed };
  }

  function entitiesCSV(ds) {
    var keys = restrictedKeys(ds);
    return toCSV(["id", "type", "label", "aliases", "attributes", "source_ids", "original_ids"], ds.entities.map(function (e) {
      return {
        id: e.id, type: e.type, label: e.label, aliases: e.aliases.join(" | "),
        attributes: JSON.stringify(redactAttributes(e.attributes, keys).attributes),
        source_ids: e.source_ids.join(" "), original_ids: e.original_ids.join(" ")
      };
    }));
  }
  function relationshipsCSV(ds) {
    return toCSV(["id", "type", "from", "to", "directed", "review", "first_observed", "last_observed", "supporting", "contradicting", "semantics"], ds.relationships.map(function (r) {
      return {
        id: r.id, type: r.type, from: r.from, to: r.to, directed: r.directed, review: r.review,
        first_observed: r.first_observed === null ? "unknown" : r.first_observed,
        last_observed: r.last_observed === null ? "unknown" : r.last_observed,
        supporting: r.evidence.supporting.join(" "), contradicting: r.evidence.contradicting.join(" "), semantics: r.semantics
      };
    }));
  }

  function exportDataset(ds, opts) {
    opts = opts || {};
    var keys = restrictedKeys(ds);
    var out = clone(datasetContent(ds));
    var removed = [];
    out.entities.forEach(function (e) {
      var r = redactAttributes(e.attributes, keys);
      e.attributes = r.attributes;
      r.removed.forEach(function (k) { removed.push(e.id + ".attributes." + k); });
    });
    out.export = {
      exported_at: isoOf(opts.now),
      exported_by: "ClearGlass Sentinel Workspace core " + CORE_VERSION,
      source_fingerprint: fingerprint(ds),
      content_fingerprint: fingerprint(out),
      restricted_fields_removed: removed,
      note: removed.length ? "Fields restricted by the dataset export policy were removed; the content fingerprint therefore differs from the source fingerprint." : "No fields were restricted; content and source fingerprints match."
    };
    return out;
  }

  function evidenceManifest(ds, idx, ids, opts) {
    opts = opts || {};
    var items = uniq(ids || []).map(function (id) {
      var o = idx.observation.get(id);
      if (!o) return { id: id, status: "missing from current dataset" };
      var s = idx.source.get(o.source_id);
      return {
        id: o.id, status: "present", excerpt_sha256: sha256Hex(o.excerpt), excerpt: o.excerpt,
        source: s ? { id: s.id, title: s.title, kind: s.kind, uri: s.uri, reliability: s.assessment.reliability, basis: s.assessment.basis, independence_group: s.independence_group } : null,
        location: o.location, observed_at: o.observed_at, collected_at: o.collected_at, ingested_at: o.ingested_at,
        extraction: o.extraction, about: o.about,
        cited_by: (idx.citedBy.get(o.id) || []).map(function (c) { return c.kind + ":" + c.id + ":" + c.role; })
      };
    });
    return {
      schema: "clearglass.sentinel.evidence-manifest/1",
      dataset: { id: ds.dataset.id, version: ds.dataset.version, synthetic: ds.dataset.synthetic, fingerprint: fingerprint(ds) },
      generated_at: isoOf(opts.now),
      items: items,
      note: "Excerpt hashes let a reviewer confirm an excerpt is unchanged. They are not a signature and do not prove the excerpt is accurate."
    };
  }

  /* ───────────────────────── snapshot comparison ───────────────────────── */

  function diffDatasets(a, b) {
    var out = { from: { id: a.dataset.id, version: a.dataset.version, as_of: a.dataset.as_of, fingerprint: fingerprint(a) },
      to: { id: b.dataset.id, version: b.dataset.version, as_of: b.dataset.as_of, fingerprint: fingerprint(b) },
      sameDataset: a.dataset.id === b.dataset.id, collections: {}, totals: { added: 0, notPresent: 0, modified: 0 } };
    COLLECTIONS.forEach(function (c) {
      var ma = new Map(a[c].map(function (x) { return [x.id, x]; })), mb = new Map(b[c].map(function (x) { return [x.id, x]; }));
      var added = [], notPresent = [], modified = [];
      mb.forEach(function (rec, id) { if (!ma.has(id)) added.push(id); });
      ma.forEach(function (rec, id) {
        if (!mb.has(id)) { notPresent.push(id); return; }
        var other = mb.get(id);
        if (canonicalJSON(rec) !== canonicalJSON(other)) {
          var fields = uniq(Object.keys(rec).concat(Object.keys(other))).filter(function (k) { return canonicalJSON(rec[k]) !== canonicalJSON(other[k]); }).sort();
          modified.push({ id: id, fields: fields, before: clone(rec), after: clone(other) });
        }
      });
      added.sort(cmpStr); notPresent.sort(cmpStr); modified.sort(function (x, y) { return cmpStr(x.id, y.id); });
      out.collections[c] = { added: added, notPresent: notPresent, modified: modified };
      out.totals.added += added.length; out.totals.notPresent += notPresent.length; out.totals.modified += modified.length;
    });
    out.caveats = [
      "\"Not present\" means the record is absent from the later snapshot. It does not mean the underlying fact was deleted or stopped being true.",
      "\"Added\" means newly present in the dataset. Check observed_at to see whether the event itself is new or only newly collected.",
      "A change to an extraction field (method, version) is a processing change, not a change in the source."
    ];
    return out;
  }

  /* ───────────────────────── investigation notebook ───────────────────────── */

  function createNotebook(ds, now) {
    var t = isoOf(now);
    return {
      schema: NOTEBOOK_SCHEMA, dataset_id: ds.dataset.id, dataset_version: ds.dataset.version, dataset_fingerprint: fingerprint(ds),
      created_at: t, updated_at: t, seq: 0,
      question: "", scope_note: "",
      hypotheses: [], matrix: {}, evidence: [], assumptions: [], open_questions: [], annotations: [],
      conclusion: null, conclusion_history: [], merge_decisions: []
    };
  }
  function nbNext(nb, prefix) { nb.seq += 1; return prefix + "-" + nb.seq; }
  function nbTouch(nb, now) { nb.updated_at = isoOf(now); return nb; }
  function requireText(v, what, max) {
    var s = typeof v === "string" ? v.trim() : "";
    if (!s) throw new Error(what + " is required.");
    if (s.length > (max || LIMITS.maxText)) throw new Error(what + " is too long.");
    return s;
  }

  var Notebook = {
    setQuestion: function (nb, question, scopeNote, now) {
      var n = clone(nb);
      n.question = String(question || "").slice(0, LIMITS.maxText);
      if (scopeNote !== undefined) n.scope_note = String(scopeNote || "").slice(0, LIMITS.maxText);
      return nbTouch(n, now);
    },
    addHypothesis: function (nb, h, now) {
      var n = clone(nb);
      n.hypotheses.push({ id: nbNext(n, "hyp"), label: requireText(h.label, "Hypothesis label", LIMITS.maxLabel), statement: String(h.statement || "").slice(0, LIMITS.maxText), created_at: isoOf(now) });
      return nbTouch(n, now);
    },
    removeHypothesis: function (nb, id, now) {
      if (nb.conclusion && nb.conclusion.hypothesis_id === id && nb.conclusion.state === "recorded") throw new Error("Reopen the conclusion before removing the hypothesis it selects.");
      var n = clone(nb);
      n.hypotheses = n.hypotheses.filter(function (h) { return h.id !== id; });
      delete n.matrix[id];
      return nbTouch(n, now);
    },
    attachEvidence: function (nb, evidenceId, note, now) {
      var n = clone(nb);
      if (!n.evidence.some(function (e) { return e.id === evidenceId; })) n.evidence.push({ id: evidenceId, note: String(note || "").slice(0, LIMITS.maxText), added_at: isoOf(now) });
      return nbTouch(n, now);
    },
    detachEvidence: function (nb, evidenceId, now) {
      var n = clone(nb);
      n.evidence = n.evidence.filter(function (e) { return e.id !== evidenceId; });
      Object.keys(n.matrix).forEach(function (h) { delete n.matrix[h][evidenceId]; });
      return nbTouch(n, now);
    },
    setAssessment: function (nb, hypId, evidenceId, value, now) {
      if (value !== null && ASSESSMENTS.indexOf(value) === -1) throw new Error("Assessment must be consistent, inconsistent, neutral or cleared.");
      if (!nb.hypotheses.some(function (h) { return h.id === hypId; })) throw new Error("Unknown hypothesis.");
      if (!nb.evidence.some(function (e) { return e.id === evidenceId; })) throw new Error("Attach the evidence to the investigation first.");
      var n = clone(nb);
      n.matrix[hypId] = n.matrix[hypId] || {};
      if (value === null) delete n.matrix[hypId][evidenceId]; else n.matrix[hypId][evidenceId] = value;
      return nbTouch(n, now);
    },
    addAnnotation: function (nb, targetId, text, now) {
      var n = clone(nb);
      n.annotations.push({ id: nbNext(n, "ann"), target: String(targetId), text: requireText(text, "Annotation"), created_at: isoOf(now) });
      return nbTouch(n, now);
    },
    removeAnnotation: function (nb, id, now) {
      var n = clone(nb);
      n.annotations = n.annotations.filter(function (a) { return a.id !== id; });
      return nbTouch(n, now);
    },
    addItem: function (nb, list, text, now) {
      if (list !== "assumptions" && list !== "open_questions") throw new Error("Unknown list.");
      var n = clone(nb);
      n[list].push({ id: nbNext(n, list === "assumptions" ? "asm" : "oq"), text: requireText(text, "Text"), status: "open", created_at: isoOf(now) });
      return nbTouch(n, now);
    },
    toggleItem: function (nb, list, id, now) {
      var n = clone(nb);
      (n[list] || []).forEach(function (it) { if (it.id === id) it.status = it.status === "open" ? "resolved" : "open"; });
      return nbTouch(n, now);
    },
    recordConclusion: function (nb, c, now) {
      var hyp = c.hypothesis_id || null;
      if (hyp && !nb.hypotheses.some(function (h) { return h.id === hyp; })) throw new Error("Unknown hypothesis.");
      var n = clone(nb);
      var entry = {
        hypothesis_id: hyp,
        text: requireText(c.text, "Conclusion"),
        rationale: requireText(c.rationale, "Rationale"),
        state: "recorded",
        recorded_at: isoOf(now)
      };
      if (n.conclusion) n.conclusion_history.push(Object.assign({ action: "superseded", at: isoOf(now) }, n.conclusion));
      n.conclusion = entry;
      return nbTouch(n, now);
    },
    reopenConclusion: function (nb, reason, now) {
      if (!nb.conclusion || nb.conclusion.state !== "recorded") throw new Error("There is no recorded conclusion to reopen.");
      var n = clone(nb);
      n.conclusion_history.push(Object.assign({ action: "reopened", reason: requireText(reason, "Reason for reopening"), at: isoOf(now) }, n.conclusion));
      n.conclusion = Object.assign({}, n.conclusion, { state: "reopened", reopened_at: isoOf(now) });
      return nbTouch(n, now);
    },
    /* Merge decisions are appended, never rewritten. "candidate" undoes a decision. */
    decideMerge: function (nb, candidateId, decision, rationale, now) {
      if (["confirmed", "rejected", "candidate"].indexOf(decision) === -1) throw new Error("Unknown merge decision.");
      var n = clone(nb);
      n.merge_decisions.push({ candidate: candidateId, decision: decision, rationale: decision === "candidate" ? String(rationale || "Decision undone.") : requireText(rationale, "Merge rationale"), at: isoOf(now) });
      return nbTouch(n, now);
    }
  };

  function mergeState(nb, candidateId) {
    var state = "candidate";
    (nb && nb.merge_decisions || []).forEach(function (d) { if (d.candidate === candidateId) state = d.decision; });
    return state;
  }
  function confirmedMergeGroups(nb, idx) {
    var groups = [];
    idx.merge.forEach(function (m, id) { if (mergeState(nb, id) === "confirmed") groups.push(m.entities.slice()); });
    return groups;
  }

  function matrixSummary(nb, idx) {
    return nb.hypotheses.map(function (h) {
      var row = nb.matrix[h.id] || {};
      var counts = { consistent: 0, inconsistent: 0, neutral: 0, unassessed: 0 };
      var inconsistentGroups = new Set();
      nb.evidence.forEach(function (e) {
        var v = row[e.id];
        if (!v) { counts.unassessed++; return; }
        counts[v]++;
        if (v === "inconsistent") {
          var o = idx.observation.get(e.id), s = o && idx.source.get(o.source_id);
          inconsistentGroups.add(s ? s.independence_group : "unknown:" + e.id);
        }
      });
      return { id: h.id, label: h.label, counts: counts, inconsistentGroups: inconsistentGroups.size };
    });
  }

  function validateNotebook(nb) {
    var ctx = newCtx();
    if (!isPlainObject(nb)) { ctx.err("$", "Notebook must be an object."); return ctx.result(); }
    walkKeys(nb, "$", 0, ctx);
    if (nb.schema !== NOTEBOOK_SCHEMA) ctx.err("$.schema", "Expected \"" + NOTEBOOK_SCHEMA + "\".");
    ["hypotheses", "evidence", "assumptions", "open_questions", "annotations", "conclusion_history", "merge_decisions"].forEach(function (k) {
      if (!Array.isArray(nb[k])) ctx.err("$." + k, "Must be a list.");
    });
    if (!isPlainObject(nb.matrix)) ctx.err("$.matrix", "Must be an object.");
    if (typeof nb.seq !== "number") ctx.err("$.seq", "Must be a number.");
    if (nb.conclusion !== null && !isPlainObject(nb.conclusion)) ctx.err("$.conclusion", "Must be null or an object.");
    return ctx.result();
  }

  /* ───────────────────────── brief ───────────────────────── */

  function md(s) { return String(s === null || s === undefined ? "" : s).replace(/[<>]/g, function (c) { return c === "<" ? "&lt;" : "&gt;"; }).replace(/\r?\n/g, " ").trim(); }
  function mdCell(s) { return md(s).replace(/\|/g, "\\|"); }

  function buildBrief(input) {
    var ds = input.dataset, idx = input.index, nb = input.notebook, runs = input.runs || [];
    var known = knownIds(idx);
    var fp = fingerprint(ds);
    var missing = [];
    function ref(id) { if (known.has(id)) return cite(id); if (missing.indexOf(id) === -1) missing.push(id); return "`" + md(id) + "` (missing from current dataset)"; }
    var hypLabel = function (id) { var h = nb.hypotheses.filter(function (x) { return x.id === id; })[0]; return h ? h.label : id; };
    var L = [];
    var status = !nb.conclusion ? "DRAFT — no conclusion recorded" : nb.conclusion.state === "recorded" ? "Conclusion recorded " + nb.conclusion.recorded_at : "REOPENED " + (nb.conclusion.reopened_at || "") + " — previous conclusion under revision";
    L.push("# Investigation brief — " + md(ds.dataset.title), "");
    L.push("> Review status: " + status);
    if (ds.dataset.synthetic) L.push("> SYNTHETIC DATASET. Every entity, record and time in it is fictional. Do not treat it as intelligence.");
    L.push("> Layer tags: [OBSERVED] = recorded in a source · [DERIVED] = computed from records · [HYPOTHESIZED] = candidate explanation · [ANALYST-ASSESSED] = analyst judgement.", "");

    L.push("## 1. Investigative question", "", nb.question ? md(nb.question) : "_No question recorded._", "");
    L.push("## 2. Scope and dataset", "");
    L.push("- Dataset: " + md(ds.dataset.title) + " (`" + md(ds.dataset.id) + "`, version " + md(ds.dataset.version) + ")");
    L.push("- Dataset as of: " + (ds.dataset.as_of || "unknown"));
    L.push("- Content fingerprint: `" + fp + "`");
    if (nb.dataset_fingerprint && nb.dataset_fingerprint !== fp) L.push("- WARNING: this notebook was started on a different dataset version (`" + md(nb.dataset_fingerprint) + "`). Re-check every reference.");
    if (nb.scope_note) L.push("- Analyst scope note: " + md(nb.scope_note));
    if (input.viewSummary) L.push("- Workspace view at export: " + md(input.viewSummary));
    L.push("");

    L.push("## 3. Key findings", "");
    L.push("### Analyst conclusion [ANALYST-ASSESSED]", "");
    if (!nb.conclusion) L.push("_No conclusion recorded. This brief is a working draft._");
    else {
      L.push("- State: " + nb.conclusion.state);
      L.push("- Selected hypothesis: " + (nb.conclusion.hypothesis_id ? md(hypLabel(nb.conclusion.hypothesis_id)) : "none (insufficient evidence to choose)"));
      L.push("- Conclusion: " + md(nb.conclusion.text));
      L.push("- Rationale: " + md(nb.conclusion.rationale));
    }
    L.push("");
    L.push("### Hypotheses [HYPOTHESIZED]", "");
    if (!nb.hypotheses.length) L.push("_No hypotheses recorded._");
    else {
      L.push("| Hypothesis | Consistent | Inconsistent | Neutral | Not assessed | Independent groups among inconsistent |", "|---|---|---|---|---|---|");
      matrixSummary(nb, idx).forEach(function (s) {
        L.push("| " + mdCell(s.label) + " | " + s.counts.consistent + " | " + s.counts.inconsistent + " | " + s.counts.neutral + " | " + s.counts.unassessed + " | " + s.inconsistentGroups + " |");
      });
      L.push("", "Counts describe the analyst's assessments. They are not probabilities, and records that share an upstream source are not independent confirmation.");
      nb.hypotheses.forEach(function (h) { if (h.statement) L.push("- " + md(h.label) + ": " + md(h.statement)); });
    }
    L.push("");

    L.push("## 4. Supporting and contradicting evidence [OBSERVED]", "");
    if (!nb.evidence.length) L.push("_No evidence attached to the investigation._");
    nb.evidence.forEach(function (e) {
      var o = idx.observation.get(e.id);
      if (!o) { L.push("- " + ref(e.id)); return; }
      var s = idx.source.get(o.source_id);
      L.push("- " + ref(o.id) + " \"" + md(o.excerpt) + "\"");
      L.push("  - Source: " + (s ? md(s.title) + " " + ref(s.id) + " — reliability " + s.assessment.reliability + " (" + md(s.assessment.basis) + "); independence group `" + md(s.independence_group) + "`" : "unknown"));
      L.push("  - Location: " + md(o.location || "not recorded") + " · observed " + (o.observed_at || "unknown") + " · collected " + (o.collected_at || "unknown") + " · ingested " + (o.ingested_at || "unknown"));
      L.push("  - Extraction: " + o.extraction.method + (o.extraction.version ? " " + md(o.extraction.version) : "") + " · confidence " + (o.extraction.confidence === null ? "not supplied" : o.extraction.confidence));
      var marks = nb.hypotheses.map(function (h) { var v = (nb.matrix[h.id] || {})[o.id]; return v ? md(h.label) + ": " + v : null; }).filter(Boolean);
      if (marks.length) L.push("  - Analyst assessment [ANALYST-ASSESSED]: " + marks.join("; "));
      if (e.note) L.push("  - Analyst note [ANALYST-ASSESSED]: " + md(e.note));
    });
    L.push("");

    L.push("## 5. Annotations [ANALYST-ASSESSED]", "");
    if (!nb.annotations.length) L.push("_None._");
    nb.annotations.forEach(function (a) { L.push("- " + ref(a.target) + " " + md(a.text) + " (" + a.created_at + ")"); });
    L.push("");

    L.push("## 6. Methods [DERIVED]", "");
    if (!runs.length) L.push("_No computed analyses were included._");
    runs.forEach(function (r) {
      L.push("- " + md(r.name) + " — " + md(r.algorithm) + " v" + md(r.algorithm_version) + " · executed " + r.executed_at + " · " + r.runtime_ms + " ms");
      L.push("  - Scope: " + md(r.scope || "not recorded") + " · dataset `" + md(r.dataset_fingerprint || "unknown") + "`");
      L.push("  - Parameters: `" + md(canonicalJSON(r.params)) + "`" + (r.seed !== null && r.seed !== undefined ? " · seed " + r.seed : "") + (r.approximation ? " · approximation: " + md(r.approximation) : ""));
      if (r.summary) L.push("  - Result: " + md(r.summary));
      (r.limitations || []).forEach(function (l) { L.push("  - Limitation: " + md(l)); });
    });
    L.push("");

    L.push("## 7. Assumptions", "");
    if (!nb.assumptions.length) L.push("_None recorded._");
    nb.assumptions.forEach(function (a) { L.push("- [" + (a.status === "open" ? "open" : "resolved") + "] " + md(a.text)); });
    L.push("");
    L.push("## 8. Unresolved questions", "");
    var openQ = nb.open_questions.filter(function (q) { return q.status === "open"; });
    if (!openQ.length) L.push("_None recorded._");
    openQ.forEach(function (q) { L.push("- " + md(q.text)); });
    L.push("");

    L.push("## 9. Limitations", "");
    if (ds.dataset.synthetic) L.push("- The dataset is synthetic. No finding here describes a real entity or event.");
    L.push("- Undated observations in the dataset: " + idx.undatedObservations + ".");
    var unassessed = matrixSummary(nb, idx).reduce(function (s, x) { return s + x.counts.unassessed; }, 0);
    if (unassessed) L.push("- " + unassessed + " hypothesis–evidence cells are not assessed.");
    L.push("- Graph metrics describe recorded relationships in the stated scope only; they are not measures of importance, intent or involvement.");
    L.push("- No AI model was used to produce this brief. Summaries are rule-based and cite record IDs.");
    L.push("- Notebook state was stored in this browser's local storage, which the user can edit. It is not a tamper-evident audit record.");
    (input.extraLimitations || []).forEach(function (l) { L.push("- " + md(l)); });
    if (missing.length) L.push("- " + missing.length + " referenced record(s) are missing from the current dataset: " + missing.map(function (m) { return "`" + md(m) + "`"; }).join(", ") + ".");
    L.push("");
    L.push("## 10. Review status", "", "- " + status);
    if (nb.conclusion_history.length) {
      nb.conclusion_history.forEach(function (h) { L.push("- " + h.action + " " + (h.at || "") + (h.reason ? " — " + md(h.reason) : "") + (h.text ? " (was: " + md(h.text) + ")" : "")); });
    }
    L.push("", "---", "Generated " + isoOf(input.now) + " by ClearGlass Sentinel Workspace core " + CORE_VERSION + ". Each citation is \"ref:\" plus a record identifier in square brackets, and every one was checked against the dataset.");
    var markdown = L.join("\n") + "\n";
    var check = validateCitations(markdown, known);
    return { ok: check.ok, markdown: markdown, citations: check, missingRefs: missing };
  }

  /* ───────────────────────── view state ───────────────────────── */

  function validateView(v, idx) {
    var ctx = newCtx();
    if (!isPlainObject(v)) { ctx.err("$", "View state must be an object."); return ctx.result(); }
    walkKeys(v, "$", 0, ctx);
    if (v.schema !== VIEW_SCHEMA) ctx.err("$.schema", "Expected \"" + VIEW_SCHEMA + "\".");
    if (v.layout !== undefined && ["radial", "force", "hierarchical"].indexOf(v.layout) === -1) ctx.err("$.layout", "Unknown layout.");
    if (v.hops !== undefined && [0, 1, 2].indexOf(v.hops) === -1) ctx.err("$.hops", "Hops must be 0, 1 or 2.");
    ["entityTypes", "relTypes", "review", "pinned"].forEach(function (k) {
      if (v[k] !== undefined && v[k] !== null && (!Array.isArray(v[k]) || v[k].some(function (x) { return typeof x !== "string"; }))) ctx.err("$." + k, "Must be a list of text values or null.");
    });
    if (idx && v.focus && !idx.entity.has(v.focus)) ctx.warn("$.focus", "Focus entity is not in this dataset and will be ignored.");
    return ctx.result();
  }

  return Object.freeze({
    SCHEMA: SCHEMA, NOTEBOOK_SCHEMA: NOTEBOOK_SCHEMA, VIEW_SCHEMA: VIEW_SCHEMA, CORE_VERSION: CORE_VERSION,
    LIMITS: LIMITS, ENTITY_TYPES: ENTITY_TYPES, REVIEW_STATES: REVIEW_STATES, CLAIM_KINDS: CLAIM_KINDS,
    CLAIM_STATUS: CLAIM_STATUS, RELIABILITY: RELIABILITY, ASSESSMENTS: ASSESSMENTS, METRIC_DEFINITIONS: METRIC_DEFINITIONS,
    sha256Hex: sha256Hex, canonicalJSON: canonicalJSON, fingerprint: fingerprint, shortFingerprint: shortFingerprint,
    mulberry32: mulberry32, isValidTime: isValidTime, timeValue: timeValue,
    validateDataset: validateDataset, normalizeDataset: normalizeDataset, parseDataset: parseDataset,
    buildIndex: buildIndex, kindOf: kindOf, knownIds: knownIds,
    mergeResolver: mergeResolver, projectEdges: projectEdges, windowAllows: windowAllows, windowOverlap: windowOverlap, bfsDistances: bfsDistances,
    buildGraph: buildGraph, findPaths: findPaths, computeMetrics: computeMetrics, runAnalysis: runAnalysis,
    layoutRadial: layoutRadial, layoutHierarchical: layoutHierarchical, createForceLayout: createForceLayout, layoutForce: layoutForce,
    assessEvidence: assessEvidence, relRefs: relRefs, summarize: summarize,
    cite: cite, validateCitations: validateCitations,
    csvCell: csvCell, toCSV: toCSV, entitiesCSV: entitiesCSV, relationshipsCSV: relationshipsCSV,
    exportDataset: exportDataset, evidenceManifest: evidenceManifest, diffDatasets: diffDatasets,
    createNotebook: createNotebook, Notebook: Notebook, mergeState: mergeState, confirmedMergeGroups: confirmedMergeGroups,
    matrixSummary: matrixSummary, validateNotebook: validateNotebook, buildBrief: buildBrief, validateView: validateView
  });
}));
