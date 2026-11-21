import { afterAll, beforeAll, describe, expect, it } from "vitest";
import pg from "pg";
import { DEMO_TENANT } from "@/lib/demo";
import { assetIdByTitle, makeRig, type TestRig } from "./helpers";

// Runs the production adapter (pg.Pool) against a real PostgreSQL server.
// Set AEGIS_TEST_PG_ADMIN_URL (a role allowed to CREATE DATABASE) to enable it.
// Without it the suite is reported as skipped, not passed.

const adminUrl = process.env.AEGIS_TEST_PG_ADMIN_URL;

describe.skipIf(!adminUrl)("PostgreSQL server adapter (requires AEGIS_TEST_PG_ADMIN_URL)", () => {
  const dbName = `aegis_test_${process.pid}_${Date.now()}`;
  let rig: TestRig;

  beforeAll(async () => {
    const admin = new pg.Client({ connectionString: adminUrl });
    await admin.connect();
    await admin.query(`CREATE DATABASE ${dbName}`);
    await admin.end();
    const url = new URL(adminUrl as string);
    url.pathname = `/${dbName}`;
    rig = await makeRig({ databaseUrl: url.toString() });
  });

  afterAll(async () => {
    await rig?.cleanup();
    const admin = new pg.Client({ connectionString: adminUrl });
    await admin.connect();
    await admin.query(`DROP DATABASE IF EXISTS ${dbName}`);
    await admin.end();
  });

  it("migrates, serves a single-use view, and refuses replay", async () => {
    expect(rig.rt.db.engine).toBe("postgres");
    const sid = await rig.login("analyst");
    const assetId = await assetIdByTitle(rig.rt, DEMO_TENANT, "Concept draft");
    const v = await rig.rt.service.requestView(sid, assetId, null);
    if (!v.ok) throw new Error(JSON.stringify(v));
    expect((await rig.rt.service.serveMedia(sid, v.viewId, v.capability)).ok).toBe(true);
    expect((await rig.rt.service.serveMedia(sid, v.viewId, v.capability)).ok).toBe(false);
  });

  it("lets exactly one of many concurrent requests spend a capability", async () => {
    const sid = await rig.login("analyst");
    const assetId = await assetIdByTitle(rig.rt, DEMO_TENANT, "Studio wall");
    const v = await rig.rt.service.requestView(sid, assetId, null);
    if (!v.ok) throw new Error("expected permit");
    const results = await Promise.all(Array.from({ length: 8 }, () => rig.rt.service.serveMedia(sid, v.viewId, v.capability)));
    expect(results.filter((r) => r.ok).length).toBe(1);
  });

  it("serialises concurrent audit appends into one unbroken chain", async () => {
    await Promise.all(Array.from({ length: 25 }, (_, i) => rig.rt.service.audit({ type: "risk.signal_recorded", tenantId: DEMO_TENANT, actor: "system", severity: "info", data: { i } })));
    const inv = await rig.login("investigator");
    await rig.rt.service.checkpointNow();
    expect(await rig.rt.service.verifyAudit(inv)).toMatchObject({ ok: true });
  });

  it("enforces append-only triggers on the server too", async () => {
    await expect(rig.rt.db.query("DELETE FROM audit_events")).rejects.toThrow(/append-only/);
    await expect(rig.rt.db.query("UPDATE view_receipts SET signature = 'x'")).rejects.toThrow(/append-only/);
  });
});
