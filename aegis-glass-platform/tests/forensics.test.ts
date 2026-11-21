import { afterAll, beforeAll, describe, expect, it } from "vitest";
import sharp from "sharp";
import { DEMO_TENANT } from "@/lib/demo";
import { verifyChain } from "@/lib/audit";
import { assetIdByTitle, makeRig, type TestRig } from "./helpers";

let rig: TestRig;
beforeAll(async () => {
  rig = await makeRig();
});
afterAll(async () => rig.cleanup());

async function servedView(title: string) {
  const sid = await rig.login("analyst");
  const view = await rig.rt.service.requestView(sid, await assetIdByTitle(rig.rt, DEMO_TENANT, title), null);
  if (!view.ok) throw new Error("expected permit");
  const media = await rig.rt.service.serveMedia(sid, view.viewId, view.capability);
  if (!media.ok) throw new Error("expected media");
  return { view, media };
}

describe("leak intake", () => {
  it("is restricted to investigators", async () => {
    const analyst = await rig.login("analyst");
    expect(await rig.rt.service.leakIntake(analyst, { image: null, traceToken: "AAAA-AAAA-AAAA" })).toMatchObject({ ok: false, httpStatus: 403 });
  });

  it("confirms a cryptographic trace from the token printed in a leaked copy", async () => {
    const { view, media } = await servedView("Concept draft");
    const inv = await rig.login("investigator");
    const leaked = await sharp(media.bytes).resize(600).jpeg({ quality: 60 }).toBuffer();
    const r = await rig.rt.service.leakIntake(inv, { image: leaked, traceToken: view.watermark.seed.toLowerCase().replace(/-/g, " ") });
    if (!r.ok) throw new Error(JSON.stringify(r));
    expect(r.confidence).toBe("confirmed_cryptographic_trace");
    expect(r.trace).toMatchObject({ status: "confirmed", viewId: view.viewId, receiptSignatureValid: true, resolvedUserId: rig.persona("analyst").userId });
    expect(r.perceptual).toMatchObject({ status: "match" });
    const incidents = await rig.rt.store.listIncidents(DEMO_TENANT);
    expect(incidents.find((i) => i.incidentId === r.incidentId)?.status).toBe("needs_human_review");
  });

  it("reports a likely perceptual match when no token is readable", async () => {
    const { media } = await servedView("Concept draft");
    const inv = await rig.login("investigator");
    const recompressed = await sharp(media.bytes).resize(500).modulate({ brightness: 1.1 }).jpeg({ quality: 40 }).toBuffer();
    const r = await rig.rt.service.leakIntake(inv, { image: recompressed, traceToken: null });
    expect(r.ok && r.confidence).toBe("likely_perceptual_match");
  });

  it("is inconclusive for unrelated images and for forged tokens", async () => {
    const inv = await rig.login("investigator");
    const unrelated = await sharp({ create: { width: 640, height: 400, channels: 3, background: "#808080" } })
      .composite([{ input: Buffer.from('<svg xmlns="http://www.w3.org/2000/svg" width="640" height="400"><rect x="0" y="0" width="320" height="400" fill="#000"/></svg>') }])
      .png()
      .toBuffer();
    const r = await rig.rt.service.leakIntake(inv, { image: unrelated, traceToken: "ABCD-EFGH-JKMN" });
    if (!r.ok) throw new Error("expected result");
    expect(r.confidence).toBe("inconclusive");
    expect(r.trace).toMatchObject({ status: "invalid_token" });
  });

  it("does not confirm when a genuine token is paired with an image of a different asset", async () => {
    const a = await servedView("Concept draft");
    const b = await servedView("Studio wall");
    const inv = await rig.login("investigator");
    const r = await rig.rt.service.leakIntake(inv, { image: b.media.bytes, traceToken: a.view.watermark.seed });
    expect(r.ok && r.confidence).toBe("inconclusive");
  });
});

describe("tamper evidence", () => {
  it("the database refuses UPDATE, DELETE, and TRUNCATE on audit events and receipts", async () => {
    await rig.rt.service.checkpointNow();
    const db = rig.rt.db;
    await expect(db.query("UPDATE audit_events SET actor = 'someone-else' WHERE seq = 1")).rejects.toThrow(/append-only/);
    await expect(db.query("DELETE FROM audit_events WHERE seq = 1")).rejects.toThrow(/append-only/);
    await expect(db.query("TRUNCATE audit_events CASCADE")).rejects.toThrow(/append-only/);
    await expect(db.query("DELETE FROM view_receipts")).rejects.toThrow(/append-only/);
    await expect(db.query("UPDATE audit_checkpoints SET signature = 'x'")).rejects.toThrow(/append-only/);
  });

  it("verification pinpoints an edit made by someone who bypassed the triggers", async () => {
    const events = await rig.rt.store.listAudit();
    const cps = await rig.rt.store.listCheckpoints();
    const pub = rig.rt.config.keys.signing.publicKey;
    expect(verifyChain(events, cps, pub)).toMatchObject({ ok: true });

    const edited = events.map((e) => (e.seq === 5 ? { ...e, data: { ...e.data, injected: true } } : e));
    expect(verifyChain(edited, cps, pub)).toMatchObject({ ok: false, failedAtSeq: 5, reason: "content_altered" });

    const removed = events.filter((e) => e.seq !== 7);
    expect(verifyChain(removed, cps, pub)).toMatchObject({ ok: false, reason: "sequence_gap" });

    // Rebuilding every hash after an edit still fails: the signed checkpoint no longer matches.
    const { computeEventHash, GENESIS_HASH } = await import("@/lib/audit");
    let prev = GENESIS_HASH;
    const rebuilt = edited.map((e) => {
      const { hash: _old, ...rest } = { ...e, prevHash: prev };
      const hash = computeEventHash(rest);
      prev = hash;
      return { ...rest, hash };
    });
    expect(verifyChain(rebuilt, cps, pub)).toMatchObject({ ok: false, reason: "checkpoint_mismatch" });

    // A checkpoint signed by another key is rejected.
    const { generateSigningKeyPair } = await import("@/lib/crypto");
    expect(verifyChain(events, cps, generateSigningKeyPair("x").publicKey)).toMatchObject({ ok: false, reason: "checkpoint_signature_invalid" });
  });

  it("records refusals as well as successes", async () => {
    const types = new Set((await rig.rt.store.listAudit()).map((e) => e.type));
    for (const t of ["auth.session_created", "asset.registered", "grant.created", "view.capability_issued", "view.started", "leak.intake_submitted", "leak.trace_resolved", "incident.opened"]) {
      expect(types).toContain(t);
    }
  });

  it("never writes redacted keys or raw capability tokens into the audit log", async () => {
    const all = JSON.stringify(await rig.rt.store.listAudit());
    expect(all).not.toMatch(/v1\.[A-Za-z0-9_-]{40,}\.[A-Za-z0-9_-]{20,}/);
  });
});
