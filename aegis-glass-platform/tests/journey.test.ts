import { afterAll, beforeAll, describe, expect, it } from "vitest";
import sharp from "sharp";
import { readdir, readFile } from "node:fs/promises";
import { join } from "node:path";
import { DEMO_TENANT, OTHER_TENANT, PROTOTYPE_PURPOSE } from "@/lib/demo";
import { assetIdByTitle, makeRig, type TestRig } from "./helpers";

// The end-to-end journey through the service layer, on real Postgres (PGlite),
// real AES-GCM envelopes on disk, and real image derivation.

let rig: TestRig;
beforeAll(async () => {
  rig = await makeRig();
});
afterAll(async () => rig.cleanup());

async function walk(dir: string): Promise<string[]> {
  const out: string[] = [];
  for (const e of await readdir(dir, { withFileTypes: true })) {
    const p = join(dir, e.name);
    if (e.isDirectory()) out.push(...(await walk(p)));
    else out.push(p);
  }
  return out;
}

describe("protected viewing journey", () => {
  it("stores only sealed originals: no PNG bytes on disk", async () => {
    const root = (rig.rt.blobs as unknown as { root: string }).root;
    const files = await walk(root);
    expect(files.length).toBe(6);
    for (const f of files) {
      const bytes = await readFile(f);
      expect(bytes.subarray(0, 4).toString()).toBe("AEG1");
      expect(bytes.includes(Buffer.from([0x89, 0x50, 0x4e, 0x47]))).toBe(false);
    }
  });

  it("issues a single-use, session-bound capability and serves a watermarked derivative", async () => {
    const sid = await rig.login("analyst");
    const assetId = await assetIdByTitle(rig.rt, DEMO_TENANT, "Concept draft");
    const view = await rig.rt.service.requestView(sid, assetId, null);
    expect(view.ok).toBe(true);
    if (!view.ok) return;
    expect(view.classification).toBe("CONFIDENTIAL");
    expect(view.watermark.density).toBe("standard");
    expect(view.watermark.lines[1]).toContain(view.watermark.seed);
    expect(view.watermark.lines.join(" ")).not.toMatch(/@|\d+\.\d+\.\d+\.\d+/);

    const media = await rig.rt.service.serveMedia(sid, view.viewId, view.capability);
    expect(media.ok).toBe(true);
    if (!media.ok) return;
    const meta = await sharp(media.bytes).metadata();
    expect(meta.format).toBe("webp");
    expect(meta.width).toBeLessThanOrEqual(1600);
    expect(meta.exif).toBeUndefined();

    // Replay of the same capability fails.
    const replay = await rig.rt.service.serveMedia(sid, view.viewId, view.capability);
    expect(replay.ok).toBe(false);
    if (!replay.ok) expect(replay.reasons[0]).toBe("capability_replayed_revoked_or_expired");

    // The signed receipt exists and verifies; tampering breaks it.
    const receipt = await rig.rt.store.getReceiptForView(view.viewId);
    expect(receipt && rig.rt.service.verifyReceipt(receipt)).toBe(true);
    if (receipt) expect(rig.rt.service.verifyReceipt({ ...receipt, payload: { ...receipt.payload, viewerPseudonym: "V-AAAA-AAAA" } })).toBe(false);
  });

  it("refuses a capability presented by a different session", async () => {
    const owner = await rig.login("analyst");
    const thief = await rig.login("analyst");
    const assetId = await assetIdByTitle(rig.rt, DEMO_TENANT, "Concept draft");
    const view = await rig.rt.service.requestView(owner, assetId, null);
    if (!view.ok) throw new Error("expected permit");
    const stolen = await rig.rt.service.serveMedia(thief, view.viewId, view.capability);
    expect(stolen.ok).toBe(false);
    if (!stolen.ok) expect(stolen.reasons[0]).toBe("capability_wrong_session");
    // The rightful session can still use it once.
    expect((await rig.rt.service.serveMedia(owner, view.viewId, view.capability)).ok).toBe(true);
  });

  it("refuses expired and forged capabilities", async () => {
    const sid = await rig.login("analyst");
    const assetId = await assetIdByTitle(rig.rt, DEMO_TENANT, "Concept draft");
    const view = await rig.rt.service.requestView(sid, assetId, null);
    if (!view.ok) throw new Error("expected permit");
    const forged = view.capability.slice(0, -4) + (view.capability.endsWith("AAAA") ? "BBBB" : "AAAA");
    const f = await rig.rt.service.serveMedia(sid, view.viewId, forged);
    expect(!f.ok && f.reasons[0]).toBe("capability_bad_signature");
    rig.clock.now += 10 * 60_000;
    const late = await rig.rt.service.serveMedia(sid, view.viewId, view.capability);
    expect(!late.ok && late.reasons[0]).toBe("capability_expired");
    rig.clock.now -= 10 * 60_000;
  });

  it("isolates tenants: another tenant's asset is indistinguishable from a missing one", async () => {
    const outsider = await rig.login("outsider");
    const assetId = await assetIdByTitle(rig.rt, DEMO_TENANT, "Concept draft");
    const r = await rig.rt.service.requestView(outsider, assetId, null);
    expect(r.ok).toBe(false);
    if (!r.ok) {
      expect(r.httpStatus).toBe(404);
      expect(r.reasons).toEqual(["not_found"]);
    }
    const missing = await rig.rt.service.requestView(outsider, crypto.randomUUID(), null);
    expect(!missing.ok && missing.reasons).toEqual(["not_found"]);
    const theirs = await assetIdByTitle(rig.rt, OTHER_TENANT, "Other tenant");
    expect((await rig.rt.service.requestView(outsider, theirs, null)).ok).toBe(true);
  });

  it("binds restricted access to the stated purpose", async () => {
    const sid = await rig.login("analyst");
    const assetId = await assetIdByTitle(rig.rt, DEMO_TENANT, "Prototype schematic");
    const none = await rig.rt.service.requestView(sid, assetId, null);
    expect(!none.ok && none.reasons).toEqual(["purpose_mismatch"]);
    const wrong = await rig.rt.service.requestView(sid, assetId, "curiosity");
    expect(!wrong.ok && wrong.reasons).toEqual(["purpose_mismatch"]);
    const right = await rig.rt.service.requestView(sid, assetId, PROTOTYPE_PURPOSE);
    expect(right.ok).toBe(true);
  });

  it("requires a passkey step-up for crown-jewel content, then permits the owner", async () => {
    const mfa = await rig.login("admin");
    const assetId = await assetIdByTitle(rig.rt, DEMO_TENANT, "Board roadmap");
    const first = await rig.rt.service.requestView(mfa, assetId, "board prep");
    expect(first.ok).toBe(false);
    if (!first.ok && first.status === "step_up") expect(first.requiredAuth).toBe("phishing_resistant");
    else throw new Error("expected step_up");
    // Non-owners are denied outright, without being told a step-up would help.
    const analyst = await rig.login("analyst", { authLevel: "phishing_resistant" });
    const nope = await rig.rt.service.requestView(analyst, assetId, "board prep");
    expect(!nope.ok && nope.status).toBe("deny");
    const passkey = await rig.login("admin", { authLevel: "phishing_resistant" });
    const ok = await rig.rt.service.requestView(passkey, assetId, null);
    expect(ok.ok).toBe(true);
    if (ok.ok) expect(ok.watermark.density).toBe("dense");
  });

  it("revocation stops delivery immediately and is visible to the viewer", async () => {
    const sid = await rig.login("analyst");
    const assetId = await assetIdByTitle(rig.rt, DEMO_TENANT, "Concept draft");
    const view = await rig.rt.service.requestView(sid, assetId, null);
    if (!view.ok) throw new Error("expected permit");
    expect(await rig.rt.service.viewStatus(sid, view.viewId)).toMatchObject({ active: true });
    const admin = await rig.login("admin");
    expect((await rig.rt.service.revokeSession(admin, sid)).ok).toBe(true);
    expect(await rig.rt.service.viewStatus(sid, view.viewId)).toMatchObject({ active: false, reason: "session_revoked" });
    const served = await rig.rt.service.serveMedia(sid, view.viewId, view.capability);
    expect(!served.ok && served.reasons).toEqual(["session_revoked"]);
  });

  it("opens a human-review incident when a canary asset is viewed, without telling the viewer", async () => {
    const sid = await rig.login("analyst");
    const assetId = await assetIdByTitle(rig.rt, DEMO_TENANT, "Pricing model");
    const view = await rig.rt.service.requestView(sid, assetId, null);
    expect(view.ok).toBe(true);
    expect(JSON.stringify(view)).not.toMatch(/honey|canary/i);
    const incidents = await rig.rt.store.listIncidents(DEMO_TENANT);
    const honey = incidents.filter((i) => i.kind === "honey_access" && i.assetId === assetId);
    expect(honey.length).toBe(1);
    expect(honey[0]?.status).toBe("needs_human_review");
    // Investigators can open canaries without tripping them.
    const inv = await rig.login("investigator");
    await rig.rt.service.requestView(inv, assetId, null);
    expect((await rig.rt.store.listIncidents(DEMO_TENANT)).filter((i) => i.kind === "honey_access").length).toBe(1);
  });

  it("escalates risk from client and server signals, then pauses the session at CRITICAL", async () => {
    const sid = await rig.login("analyst");
    const assetId = await assetIdByTitle(rig.rt, DEMO_TENANT, "Concept draft");
    const view = await rig.rt.service.requestView(sid, assetId, null);
    if (!view.ok) throw new Error("expected permit");
    // devtools 10 -> LOW
    const r1 = await rig.rt.service.recordClientSignal(sid, view.viewId, "devtools_suspected");
    expect(r1.ok && r1.riskState).toBe("LOW");
    // + 2 print attempts (20) = 30 -> GUARDED
    await rig.rt.service.recordClientSignal(sid, view.viewId, "print_attempt");
    const r2 = await rig.rt.service.recordClientSignal(sid, view.viewId, "print_attempt");
    expect(r2.ok && r2.riskState).toBe("GUARDED");
    // + automation (35) = 65 -> HIGH
    const r3 = await rig.rt.service.recordClientSignal(sid, view.viewId, "automation_detected");
    expect(r3.ok && r3.riskState).toBe("HIGH");
    // + 2 copy attempts (6) = 71 -> CRITICAL
    await rig.rt.service.recordClientSignal(sid, view.viewId, "copy_attempt");
    const r4 = await rig.rt.service.recordClientSignal(sid, view.viewId, "copy_attempt");
    expect(r4.ok && r4.riskState).toBe("CRITICAL");
    if (r4.ok) expect(r4.actions).toContain("pause_session");
    // The open view was voided by the pause.
    expect(await rig.rt.service.viewStatus(sid, view.viewId)).toMatchObject({ active: false, reason: "session_paused" });
    const after = await rig.rt.service.requestView(sid, assetId, null);
    expect(!after.ok && after.reasons).toEqual(["session_paused"]);
    const incidents = await rig.rt.store.listIncidents(DEMO_TENANT);
    expect(incidents.some((i) => i.kind === "critical_risk" && i.sessionId === sid && i.status === "needs_human_review")).toBe(true);
  });

  it("downgrades resolution and densifies the watermark at elevated risk", async () => {
    const sid = await rig.login("analyst");
    const assetId = await assetIdByTitle(rig.rt, DEMO_TENANT, "Studio wall");
    const v0 = await rig.rt.service.requestView(sid, assetId, null);
    if (!v0.ok) throw new Error("expected permit");
    expect(v0.watermark.density).toBe("light");
    // print 20 + devtools 10 + copy 9 + focus changes 6 = 45 -> HIGH
    for (let i = 0; i < 2; i++) await rig.rt.service.recordClientSignal(sid, v0.viewId, "print_attempt");
    await rig.rt.service.recordClientSignal(sid, v0.viewId, "devtools_suspected");
    for (let i = 0; i < 3; i++) await rig.rt.service.recordClientSignal(sid, v0.viewId, "copy_attempt");
    for (let i = 0; i < 3; i++) await rig.rt.service.recordClientSignal(sid, v0.viewId, "focus_lost");
    const v1 = await rig.rt.service.requestView(sid, assetId, null);
    if (!v1.ok) throw new Error(`expected permit, got ${JSON.stringify(v1)}`);
    expect(v1.riskState).toBe("HIGH");
    expect(v1.watermark.density).toBe("dense");
    const media = await rig.rt.service.serveMedia(sid, v1.viewId, v1.capability);
    if (!media.ok) throw new Error("expected media");
    expect(media.width).toBeLessThanOrEqual(800);
  });

  it("lists only assets the person is entitled to, without revealing the honey flag", async () => {
    const titles = async (key: "analyst" | "admin" | "investigator" | "outsider") => {
      const cat = await rig.rt.service.listCatalogue(await rig.login(key));
      if (!("assets" in cat)) throw new Error("expected catalogue");
      expect(JSON.stringify(cat.assets)).not.toMatch(/honey/i);
      return cat.assets.map((x) => x.title.split(":")[0]);
    };
    // Analyst: default-visible internal board, design-lab grant (incl. the canary bait), purpose-bound prototype grant.
    expect(await titles("analyst")).toEqual(["Studio wall", "Concept draft", "Prototype schematic", "Pricing model FY27 (draft)"]);
    // Admin owns every seeded asset except the canary, which it sees through the design-lab grant.
    expect(await titles("admin")).toEqual(["Studio wall", "Concept draft", "Prototype schematic", "Board roadmap", "Pricing model FY27 (draft)"]);
    // The analyst never sees the crown-jewel title.
    expect(await titles("analyst")).not.toContain("Board roadmap");
    // The other tenant sees only its own asset.
    expect(await titles("outsider")).toEqual(["Other tenant"]);
  });

  it("keeps an intact, verifiable audit chain across everything above", async () => {
    const inv = await rig.login("investigator");
    await rig.rt.service.checkpointNow();
    const result = await rig.rt.service.verifyAudit(inv);
    expect(result).toMatchObject({ ok: true });
    if ("events" in result) expect(result.events).toBeGreaterThan(30);
  });
});
