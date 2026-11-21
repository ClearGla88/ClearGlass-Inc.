import assert from "node:assert/strict";
import { generateKeyPairSync, randomBytes } from "node:crypto";
import { describe, it } from "node:test";
import { AuditLog, MemoryAuditSink, signCheckpoint, verifyChain, verifyCheckpoint, type AuditRecord } from "../lib/audit.ts";
import { canonicalJson } from "../lib/canonical.ts";
import { signCapability, verifyCapability } from "../lib/capability.ts";
import { LocalKms, openObject, sealObject } from "../lib/envelope.ts";
import { assessRisk } from "../lib/risk.ts";
import { issueSessionCookie, readSessionCookie } from "../lib/session.ts";
import { pseudonym, watermarkLines } from "../lib/watermark.ts";
import { escapeXml, layoutFor, watermarkOverlaySvg, watermarkTileSvg } from "../lib/watermark-layout.ts";

const capPayload = { jti: "j1", aid: "a1", tid: "t1", uid: "u1", sid: "s1", act: "view" as const, nbf: 1000, exp: 1060, w: 800, d: 3, tr: "T-1", seed: 42 };

describe("capability tokens", () => {
  const keys = { k1: randomBytes(32), k2: randomBytes(32) };

  it("round-trips and supports key rotation", () => {
    const t1 = signCapability({ activeKid: "k1", keys }, capPayload);
    const t2 = signCapability({ activeKid: "k2", keys }, capPayload);
    const r1 = verifyCapability(keys, t1, 1010);
    const r2 = verifyCapability(keys, t2, 1010);
    assert.ok(r1.ok && r2.ok);
    if (r1.ok) assert.equal(r1.payload.aid, "a1");
  });

  it("rejects tampering, unknown keys, early use, expiry and junk", () => {
    const token = signCapability({ activeKid: "k1", keys }, capPayload);
    const [body, sig] = token.split(".");
    const forged = Buffer.from(JSON.stringify({ ...JSON.parse(Buffer.from(body, "base64url").toString()), aid: "a2" })).toString("base64url");
    assert.deepEqual(verifyCapability(keys, `${forged}.${sig}`, 1010), { ok: false, reason: "bad_signature" });
    assert.deepEqual(verifyCapability({ k2: keys.k2 }, token, 1010), { ok: false, reason: "unknown_key" });
    assert.deepEqual(verifyCapability(keys, token, 900), { ok: false, reason: "not_yet_valid" });
    assert.deepEqual(verifyCapability(keys, token, 1070), { ok: false, reason: "expired" });
    for (const junk of ["", "abc", "a.b.c", `${body}.`, "x".repeat(5000)]) {
      assert.equal(verifyCapability(keys, junk, 1010).ok, false);
    }
  });

  it("cannot be steered to a prototype key name", () => {
    const evil = Buffer.from(JSON.stringify({ ...capPayload, v: 1, kid: "__proto__" })).toString("base64url");
    assert.equal(verifyCapability(keys, `${evil}.${"A".repeat(43)}`, 1010).ok, false);
  });
});

describe("audit chain", () => {
  async function filled(key: Buffer): Promise<AuditRecord[]> {
    const log = new AuditLog(new MemoryAuditSink(), key);
    await Promise.all(
      Array.from({ length: 25 }, (_, i) => log.append({ type: "media.served", tenantId: "t1", actor: `u${i}`, subject: "a1", data: { i } })),
    );
    return log.all();
  }

  it("serializes concurrent appends into one valid chain", async () => {
    const key = randomBytes(32);
    const records = await filled(key);
    assert.deepEqual(records.map((r) => r.seq), Array.from({ length: 25 }, (_, i) => i + 1));
    assert.deepEqual(verifyChain(records, key), { ok: true, checked: 25 });
  });

  it("detects edits, deletions, reordering and a wrong key", async () => {
    const key = randomBytes(32);
    const records = await filled(key);
    const edited = records.map((r) => ({ ...r }));
    edited[10] = { ...edited[10], data: { i: 999 } };
    assert.equal(verifyChain(edited, key).problem, "hash_mismatch");

    const deleted = records.filter((_, i) => i !== 5);
    assert.equal(verifyChain(deleted, key).problem, "sequence_gap");

    const rehashed = records.map((r) => ({ ...r }));
    rehashed[3] = { ...rehashed[3], prevHash: "f".repeat(64) };
    assert.equal(verifyChain(rehashed, key).ok, false);

    assert.equal(verifyChain(records, randomBytes(32)).problem, "mac_mismatch");
  });

  it("signs verifiable checkpoints", async () => {
    const key = randomBytes(32);
    const records = await filled(key);
    const pair = generateKeyPairSync("ed25519");
    const cp = signCheckpoint(records[records.length - 1], pair.privateKey);
    assert.equal(verifyCheckpoint(cp, pair.publicKey), true);
    assert.equal(verifyCheckpoint({ ...cp, seq: cp.seq + 1 }, pair.publicKey), false);
  });
});

describe("envelope encryption", () => {
  const kms = new LocalKms({ k1: randomBytes(32) }, "k1");

  it("round-trips and binds the ciphertext to its tenant and asset", async () => {
    const plain = randomBytes(4096);
    const sealed = await sealObject(kms, "t1", "a1", plain);
    assert.notEqual(sealed.ciphertext, plain.toString("base64"));
    assert.deepEqual(await openObject(kms, "t1", "a1", sealed), plain);
    await assert.rejects(openObject(kms, "t1", "a2", sealed));
    await assert.rejects(openObject(kms, "t2", "a1", sealed));
  });

  it("rejects modified ciphertext", async () => {
    const sealed = await sealObject(kms, "t1", "a1", randomBytes(256));
    const ct = Buffer.from(sealed.ciphertext, "base64");
    ct[ct.length - 1] ^= 0x01;
    await assert.rejects(openObject(kms, "t1", "a1", { ...sealed, ciphertext: ct.toString("base64") }));
  });
});

describe("watermark", () => {
  it("escapes markup in every line", () => {
    const svg = watermarkTileSvg(['<script>alert("x")</script> & co'], layoutFor(1, 1, 3), 3);
    assert.ok(!svg.includes("<script>"));
    assert.ok(svg.includes("&lt;script&gt;"));
    assert.equal(escapeXml(`'"<>&`), "&apos;&quot;&lt;&gt;&amp;");
  });

  it("is deterministic per seed and epoch, and moves between epochs", () => {
    assert.deepEqual(layoutFor(7, 100, 2), layoutFor(7, 100, 2));
    assert.notDeepEqual(layoutFor(7, 100, 2), layoutFor(7, 101, 2));
  });

  it("draws nothing at density 0", () => {
    assert.equal(watermarkOverlaySvg(100, 100, ["x"], layoutFor(1, 1, 0), 0), "");
  });

  it("carries pseudonyms, never raw identifiers", () => {
    const key = randomBytes(32);
    const lines = watermarkLines(
      {
        classification: "CROWN_JEWEL",
        tenantPseudonym: pseudonym(key, "O", "t-demo"),
        viewerPseudonym: pseudonym(key, "V", "t-demo:ava@example.com"),
        sessionFragment: pseudonym(key, "S", "sess-1").slice(0, 6),
        traceToken: "T-ABCDEFGHJK",
      },
      new Date(Date.UTC(2026, 10, 21, 15, 4)),
    );
    const text = lines.join(" ");
    assert.match(text, /^CROWN-JEWEL · T-ABCDEFGHJK V-[0-9A-Z]{8} · S-[0-9A-Z]{4} · O-[0-9A-Z]{8} · 2026-11-21 15:04Z$/);
    assert.ok(!text.includes("@") && !text.includes("t-demo"));
  });
});

describe("risk engine", () => {
  const quiet = { newDevice: false, impossibleTravel: false, networkReputation: "good" as const, deniedAttempts10m: 0, viewRequests5m: 1, distinctAssets5m: 1, honeyTouches: 0, outsideConfiguredHours: false };

  it("explains every point and maps scores to states", () => {
    assert.equal(assessRisk(quiet).state, "LOW");
    const r = assessRisk({ ...quiet, newDevice: true, networkReputation: "unknown", outsideConfiguredHours: true });
    assert.equal(r.score, 20);
    assert.equal(r.state, "GUARDED");
    assert.deepEqual(r.contributions.map((c) => c.signal), ["newDevice", "networkReputation", "outsideConfiguredHours"]);
    assert.equal(assessRisk({ ...quiet, honeyTouches: 1 }).state, "HIGH");
    assert.equal(assessRisk({ ...quiet, impossibleTravel: true, distinctAssets5m: 20, deniedAttempts10m: 3 }).state, "CRITICAL");
  });
});

describe("session cookie", () => {
  const key = randomBytes(32);
  const p = { userId: "u1", tenantId: "t1", displayName: "U", roles: ["viewer" as const], authLevel: "mfa" as const, authTime: 1000, sessionId: "s1" };

  it("round-trips, expires, and rejects forgery or escalated roles", () => {
    const cookie = issueSessionCookie(key, p, 1000, 60);
    assert.deepEqual(readSessionCookie(key, cookie, 1030), p);
    assert.equal(readSessionCookie(key, cookie, 1061), undefined);
    assert.equal(readSessionCookie(randomBytes(32), cookie, 1030), undefined);
    const [body, sig] = cookie.split(".");
    const claims = JSON.parse(Buffer.from(body, "base64url").toString());
    const escalated = Buffer.from(JSON.stringify({ ...claims, roles: ["tenant_admin"] })).toString("base64url");
    assert.equal(readSessionCookie(key, `${escalated}.${sig}`, 1030), undefined);
  });
});

describe("canonical JSON", () => {
  it("sorts keys at every depth and drops undefined", () => {
    assert.equal(canonicalJson({ b: 1, a: { d: [2, { z: 1, y: 2 }], c: undefined } }), '{"a":{"d":[2,{"y":2,"z":1}]},"b":1}');
    assert.throws(() => canonicalJson({ n: Number.NaN }));
  });
});
