import assert from "node:assert/strict";
import { describe, it } from "node:test";
import sharp from "sharp";
import { verifyChain } from "../lib/audit.ts";
import { dhash, hammingDistance, matchGrade } from "../lib/preview.ts";
import { verifyReceipt } from "../lib/receipts.ts";
import { DEMO_TENANT, syntheticImage } from "../lib/seed.ts";
import { harness, tokenFromUrl } from "./helpers.ts";

describe("capability issuance", () => {
  it("issues a short-lived, watermarked capability to an entitled viewer", async () => {
    const h = await harness();
    const analyst = h.login("analyst");
    const r = await h.service.requestCapability(analyst, "a-atlas-concept");
    assert.equal(r.status, 200);
    if (r.status !== 200) return;
    assert.match(r.body.url, /^\/api\/media\/[A-Za-z0-9_-]+\.[A-Za-z0-9_-]{43}$/);
    assert.equal(r.body.classification, "CONFIDENTIAL");
    assert.equal(r.body.watermark.lines.length, 2);
    assert.match(r.body.watermark.lines[0], /^CONFIDENTIAL · T-[0-9A-Z]{10}$/);
    const ttl = (Date.parse(r.body.expiresAt) - h.clock.ms) / 1000;
    assert.ok(ttl > 0 && ttl <= 60, `ttl ${ttl}`);
  });

  it("answers 404 for another tenant's asset, exactly as for a missing one", async () => {
    const h = await harness();
    const analyst = h.login("analyst");
    const cross = await h.service.requestCapability(analyst, "a-other-plan");
    const missing = await h.service.requestCapability(analyst, "a-does-not-exist");
    assert.deepEqual(cross, { status: 404, body: { error: "not_found" } });
    assert.deepEqual(missing, cross);
  });

  it("asks for step-up instead of serving RESTRICTED content on an MFA session", async () => {
    const h = await harness();
    const r = await h.service.requestCapability(h.login("analyst"), "a-atlas-proto");
    assert.deepEqual(r, { status: 401, body: { error: "step_up_required" } });
    const stepped = await h.service.requestCapability(h.login("analyst", { authLevel: "phishing_resistant" }), "a-atlas-proto");
    assert.equal(stepped.status, 200);
  });

  it("keeps CROWN-JEWEL content from the tenant admin, and gives it to the owner", async () => {
    const h = await harness();
    assert.deepEqual(await h.service.requestCapability(h.login("admin"), "a-core-whiteboard"), { status: 403, body: { error: "forbidden" } });
    const owner = await h.service.requestCapability(h.login("owner"), "a-core-whiteboard");
    assert.equal(owner.status, 200);
    if (owner.status === 200) assert.equal(owner.body.previewMaxWidth, 800);
  });

  it("rate-limits capability requests per session", async () => {
    const h = await harness();
    const analyst = h.login("analyst");
    let last;
    for (let i = 0; i < 31; i += 1) last = await h.service.requestCapability(analyst, "a-palette");
    assert.deepEqual(last, { status: 429, body: { error: "rate_limited" } });
  });
});

describe("media delivery", () => {
  it("serves one watermarked preview, signs a receipt, then refuses replay", async () => {
    const h = await harness();
    const analyst = h.login("analyst");
    const cap = await h.service.requestCapability(analyst, "a-atlas-concept");
    assert.equal(cap.status, 200);
    if (cap.status !== 200) return;
    const token = tokenFromUrl(cap.body.url);

    const first = await h.service.serveMedia(analyst, token);
    assert.equal(first.status, 200);
    if (first.status !== 200) return;
    const meta = await sharp(first.bytes).metadata();
    assert.equal(meta.format, "webp");
    assert.ok((meta.width ?? 0) <= 1280);
    assert.equal(meta.exif, undefined);

    const replay = await h.service.serveMedia(analyst, token);
    assert.deepEqual(replay, { status: 410, error: "already_used" });

    const investigator = h.login("investigator");
    const resolved = await h.service.resolveTrace(investigator, first.traceToken);
    assert.equal(resolved.status, 200);
    if (resolved.status === 200) {
      assert.equal(resolved.signatureValid, true);
      assert.equal(resolved.receipt.body.userId, "u-analyst");
      assert.equal(resolved.receipt.body.assetId, "a-atlas-concept");
      assert.equal(verifyReceipt({ ...resolved.receipt, body: { ...resolved.receipt.body, userId: "u-owner" } }, h.service.deps.keys.receiptPublic), false);
    }
  });

  it("makes a leaked URL useless in any other session", async () => {
    const h = await harness();
    const analyst = h.login("analyst");
    const cap = await h.service.requestCapability(analyst, "a-palette");
    assert.equal(cap.status, 200);
    if (cap.status !== 200) return;
    const token = tokenFromUrl(cap.body.url);
    assert.deepEqual(await h.service.serveMedia(undefined, token), { status: 401, error: "unauthenticated" });
    assert.deepEqual(await h.service.serveMedia(h.login("analyst"), token), { status: 403, error: "forbidden" });
    assert.deepEqual(await h.service.serveMedia(h.login("outsider"), token), { status: 403, error: "forbidden" });
    // The rightful session can still use it once.
    assert.equal((await h.service.serveMedia(analyst, token)).status, 200);
  });

  it("expires capabilities", async () => {
    const h = await harness();
    const analyst = h.login("analyst");
    const cap = await h.service.requestCapability(analyst, "a-atlas-concept");
    if (cap.status !== 200) assert.fail("expected capability");
    h.clock.ms += 70_000;
    assert.deepEqual(await h.service.serveMedia(analyst, tokenFromUrl(cap.body.url)), { status: 410, error: "expired" });
  });

  it("enforces a grant revoked after the capability was issued", async () => {
    const h = await harness();
    const analyst = h.login("analyst");
    const cap = await h.service.requestCapability(analyst, "a-atlas-concept");
    if (cap.status !== 200) assert.fail("expected capability");
    const revoked = await h.service.revokeGrant(h.login("admin"), "g-analyst-atlas");
    assert.deepEqual(revoked, { ok: true });
    assert.deepEqual(await h.service.serveMedia(analyst, tokenFromUrl(cap.body.url)), { status: 403, error: "forbidden" });
  });

  it("cuts off a revoked session immediately", async () => {
    const h = await harness();
    const analyst = h.login("analyst");
    const cap = await h.service.requestCapability(analyst, "a-palette");
    if (cap.status !== 200) assert.fail("expected capability");
    assert.deepEqual(await h.service.revokeSession(h.login("admin"), analyst.sessionId, "lost laptop"), { ok: true });
    assert.deepEqual(await h.service.serveMedia(analyst, tokenFromUrl(cap.body.url)), { status: 403, error: "session_revoked" });
    assert.deepEqual(await h.service.requestCapability(analyst, "a-palette"), { status: 401, body: { error: "session_revoked" } });
  });

  it("only lets an admin revoke sessions in their own tenant", async () => {
    const h = await harness();
    const outsider = h.login("outsider");
    await h.service.registerSession(outsider, 3600);
    assert.deepEqual(await h.service.revokeSession(h.login("admin"), outsider.sessionId, "x"), { ok: false, error: "forbidden" });
    assert.deepEqual(await h.service.revokeSession(h.login("analyst"), h.login("owner").sessionId, "x"), { ok: false, error: "forbidden" });
  });

  it("matches a served preview to its original with a perceptual hash, even after recompression", async () => {
    const h = await harness();
    const owner = h.login("owner");
    const cap = await h.service.requestCapability(owner, "a-palette");
    if (cap.status !== 200) assert.fail("expected capability");
    const served = await h.service.serveMedia(owner, tokenFromUrl(cap.body.url));
    if (served.status !== 200) assert.fail("expected media");
    const leaked = await sharp(served.bytes).resize(500).jpeg({ quality: 50 }).toBuffer();
    const original = await syntheticImage(190, "Palette study");
    const unrelated = await syntheticImage(20, "Something else");
    const d = hammingDistance(await dhash(leaked), await dhash(original));
    assert.equal(matchGrade(d), "likely_match", `distance ${d}`);
    assert.ok(hammingDistance(await dhash(leaked), await dhash(unrelated)) > d);
  });
});

describe("honey assets and risk", () => {
  it("opens a human-review case when a decoy is requested, and still answers normally", async () => {
    const h = await harness();
    const analyst = h.login("analyst");
    const r = await h.service.requestCapability(analyst, "a-partner-draft");
    assert.equal(r.status, 200);
    if (r.status === 200) assert.equal(r.body.riskState, "HIGH");
    await h.service.requestCapability(analyst, "a-partner-draft");
    const cases = await h.service.listCases(h.login("investigator"));
    assert.equal(cases.status, 200);
    if (cases.status === 200) {
      const honey = cases.cases.filter((c) => c.kind === "honey_access");
      assert.equal(honey.length, 1, "deduplicated per session and asset");
      assert.equal(honey[0].status, "needs_review");
      assert.equal(honey[0].subjectUserId, "u-analyst");
    }
  });

  it("pauses a session that turns CRITICAL and keeps it paused", async () => {
    const h = await harness();
    const analyst = h.login("analyst");
    // 35 (impossible travel) + 25 (bad network) + 10 (new device) = 70 = CRITICAL.
    const bad = { impossibleTravel: true, networkReputation: "bad" as const, deviceId: "unseen-device" };
    const r = await h.service.requestCapability(analyst, "a-palette", bad);
    assert.deepEqual(r, { status: 401, body: { error: "session_paused" } });
    const later = await h.service.requestCapability(analyst, "a-palette");
    assert.deepEqual(later, { status: 401, body: { error: "session_paused" } });
    const cases = await h.service.listCases(h.login("admin"));
    if (cases.status === 200) assert.ok(cases.cases.some((c) => c.kind === "risk_critical"));
  });
});

describe("investigator access and audit integrity", () => {
  it("limits trace resolution to investigators with phishing-resistant sign-in", async () => {
    const h = await harness();
    assert.deepEqual(await h.service.resolveTrace(h.login("admin"), "T-X"), { status: 403, error: "forbidden" });
    assert.deepEqual(await h.service.resolveTrace(h.login("investigator", { authLevel: "mfa" }), "T-X"), { status: 403, error: "forbidden" });
    assert.deepEqual(await h.service.resolveTrace(h.login("investigator"), "T-X"), { status: 404, error: "not_found" });
  });

  it("records every decision in a chain that verifies, and logs no email addresses", async () => {
    const h = await harness();
    const analyst = h.login("analyst");
    const ok = await h.service.requestCapability(analyst, "a-atlas-concept");
    await h.service.requestCapability(analyst, "a-core-whiteboard");
    await h.service.requestCapability(analyst, "a-other-plan");
    if (ok.status === 200) await h.service.serveMedia(analyst, tokenFromUrl(ok.body.url));

    const records = await h.service.deps.audit.all();
    const types = records.map((r) => r.type);
    for (const t of ["capability.issued", "capability.denied", "media.served"]) assert.ok(types.includes(t as never), t);
    assert.ok(records.every((r) => r.tenantId === DEMO_TENANT));
    assert.ok(!JSON.stringify(records).includes("@"));

    const verdict = await h.service.verifyAudit(h.login("admin"));
    assert.equal(verdict.status, 200);
    if (verdict.status === 200) assert.equal(verdict.result.ok, true);
    assert.equal(verifyChain(await h.service.deps.audit.all(), h.auditMacKey).ok, true);
  });
});
