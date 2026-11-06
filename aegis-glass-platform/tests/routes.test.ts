import { afterAll, beforeAll, beforeEach, describe, expect, it } from "vitest";
import sharp from "sharp";
import { setRuntime } from "@/lib/runtime";
import { resetRateLimits } from "@/lib/http";
import { DEMO_TENANT } from "@/lib/demo";
import { securityHeaders } from "@/lib/headers";
import * as login from "@/app/api/dev/login/route";
import * as view from "@/app/api/assets/[assetId]/view/route";
import * as media from "@/app/api/media/[viewId]/route";
import * as status from "@/app/api/views/[viewId]/status/route";
import * as signal from "@/app/api/risk/signal/route";
import * as upload from "@/app/api/assets/route";
import * as leak from "@/app/api/leak-intake/route";
import * as verify from "@/app/api/audit/verify/route";
import * as revokeSession from "@/app/api/sessions/[sessionId]/revoke/route";
import { assetIdByTitle, makeRig, type TestRig } from "./helpers";

// HTTP-level tests: the real route handlers, invoked with real Request objects.

let rig: TestRig;
const ORIGIN = "http://localhost:3000";
beforeAll(async () => {
  rig = await makeRig();
  setRuntime(rig.rt);
});
afterAll(async () => {
  setRuntime(null);
  await rig.cleanup();
});
beforeEach(() => resetRateLimits());

const req = (path: string, init: RequestInit & { cookie?: string } = {}) => {
  const headers = new Headers(init.headers);
  if (init.cookie) headers.set("cookie", init.cookie);
  if (init.method === "POST" && !headers.has("origin")) headers.set("origin", ORIGIN);
  return new Request(`${ORIGIN}${path}`, { ...init, headers });
};
const jsonBody = (body: unknown) => ({ method: "POST", body: JSON.stringify(body), headers: { "content-type": "application/json" } });
const params = <T>(p: T) => ({ params: Promise.resolve(p) });

async function signIn(persona: string): Promise<string> {
  const res = await login.POST(req("/api/dev/login", jsonBody({ persona })));
  expect(res.status).toBe(200);
  const setCookie = res.headers.get("set-cookie") ?? "";
  expect(setCookie).toMatch(/HttpOnly/);
  expect(setCookie).toMatch(/SameSite=Strict/);
  return setCookie.split(";")[0] as string;
}

describe("HTTP layer", () => {
  it("refuses cross-origin state changes (CSRF)", async () => {
    const cookie = await signIn("analyst");
    const assetId = await assetIdByTitle(rig.rt, DEMO_TENANT, "Concept draft");
    const res = await view.POST(req(`/api/assets/${assetId}/view`, { ...jsonBody({}), cookie, headers: { origin: "https://evil.example", "content-type": "application/json" } }), params({ assetId }));
    expect(res.status).toBe(403);
    const noOrigin = new Request(`${ORIGIN}/api/assets/${assetId}/view`, { method: "POST", body: "{}", headers: { cookie, "sec-fetch-site": "cross-site" } });
    expect((await view.POST(noOrigin, params({ assetId }))).status).toBe(403);
  });

  it("requires a session and rejects forged cookies", async () => {
    const assetId = await assetIdByTitle(rig.rt, DEMO_TENANT, "Concept draft");
    expect((await view.POST(req(`/api/assets/${assetId}/view`, jsonBody({})), params({ assetId }))).status).toBe(401);
    const forged = "aegis_session=v1.ZmFrZQ.AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA";
    expect((await view.POST(req(`/api/assets/${assetId}/view`, { ...jsonBody({}), cookie: forged }), params({ assetId }))).status).toBe(401);
  });

  it("serves media once, with no-store caching, only with the capability header", async () => {
    const cookie = await signIn("analyst");
    const assetId = await assetIdByTitle(rig.rt, DEMO_TENANT, "Concept draft");
    const permit = await (await view.POST(req(`/api/assets/${assetId}/view`, { ...jsonBody({}), cookie }), params({ assetId }))).json();
    expect(permit.status).toBe("permit");
    expect(permit.capability).toMatch(/^v1\./);
    expect(permit.mediaPath).not.toContain(permit.capability);

    const withoutHeader = await media.GET(req(permit.mediaPath, { cookie }), params({ viewId: permit.viewId }));
    expect(withoutHeader.status).toBe(403);
    // A failed attempt does not burn the capability: only a verified request consumes it.
    const ok = await media.GET(req(permit.mediaPath, { cookie, headers: { "x-aegis-capability": permit.capability, "sec-fetch-site": "same-origin" } }), params({ viewId: permit.viewId }));
    expect(ok.status).toBe(200);
    expect(ok.headers.get("content-type")).toBe("image/webp");
    expect(ok.headers.get("cache-control")).toContain("no-store");
    expect(ok.headers.get("x-aegis-receipt")).toMatch(/^[0-9a-f-]{36}$/);
    expect((await sharp(Buffer.from(await ok.arrayBuffer())).metadata()).format).toBe("webp");

    const again = await media.GET(req(permit.mediaPath, { cookie, headers: { "x-aegis-capability": permit.capability } }), params({ viewId: permit.viewId }));
    expect(again.status).toBe(403);
    const crossSite = await media.GET(req(permit.mediaPath, { cookie, headers: { "x-aegis-capability": permit.capability, "sec-fetch-site": "cross-site" } }), params({ viewId: permit.viewId }));
    expect(crossSite.status).toBe(403);
  });

  it("reports revocation to the viewer and refuses further views", async () => {
    const cookie = await signIn("analyst");
    const admin = await signIn("admin");
    const assetId = await assetIdByTitle(rig.rt, DEMO_TENANT, "Concept draft");
    const permit = await (await view.POST(req(`/api/assets/${assetId}/view`, { ...jsonBody({}), cookie }), params({ assetId }))).json();
    const before = await (await status.GET(req(`/api/views/${permit.viewId}/status`, { cookie }), params({ viewId: permit.viewId }))).json();
    expect(before).toEqual({ active: true, reason: null });
    const sessionId = (await rig.rt.store.getView(permit.viewId))?.sessionId as string;
    expect((await revokeSession.POST(req(`/api/sessions/${sessionId}/revoke`, { method: "POST", cookie: admin }), params({ sessionId }))).status).toBe(200);
    const after = await (await status.GET(req(`/api/views/${permit.viewId}/status`, { cookie }), params({ viewId: permit.viewId }))).json();
    expect(after).toEqual({ active: false, reason: "session_revoked" });
  });

  it("validates signal input and enforces rate limits", async () => {
    const cookie = await signIn("analyst");
    expect((await signal.POST(req("/api/risk/signal", { ...jsonBody({ viewId: "x", kind: "nope" }), cookie }))).status).toBe(400);
    const assetId = await assetIdByTitle(rig.rt, DEMO_TENANT, "Studio wall");
    let last = 0;
    for (let i = 0; i < 95; i++) last = (await view.POST(req(`/api/assets/${assetId}/view`, { ...jsonBody({}), cookie }), params({ assetId }))).status;
    expect(last).toBe(429);
  });

  it("accepts a valid upload, rejects a non-image, and blocks honey uploads by non-investigators", async () => {
    const cookie = await signIn("analyst");
    const png = await sharp({ create: { width: 320, height: 200, channels: 3, background: "#204060" } }).png().toBuffer();
    const form = (file: Blob, honey = "false") => {
      const f = new FormData();
      f.set("file", file, "x.png");
      f.set("title", "Uploaded sketch");
      f.set("altText", "A plain blue rectangle");
      f.set("classification", "CONFIDENTIAL");
      f.set("compartment", "design-lab");
      f.set("honey", honey);
      return f;
    };
    expect((await upload.POST(req("/api/assets", { method: "POST", body: form(new Blob([png])), cookie }))).status).toBe(201);
    expect((await upload.POST(req("/api/assets", { method: "POST", body: form(new Blob([Buffer.from("<script>alert(1)</script>")])), cookie }))).status).toBe(422);
    expect((await upload.POST(req("/api/assets", { method: "POST", body: form(new Blob([png]), "true"), cookie }))).status).toBe(403);
  });

  it("restricts forensics to investigators and returns an intact chain", async () => {
    const analyst = await signIn("analyst");
    const f = new FormData();
    f.set("traceToken", "AAAA-AAAA-AAAA");
    expect((await leak.POST(req("/api/leak-intake", { method: "POST", body: f, cookie: analyst }))).status).toBe(403);
    expect((await verify.POST(req("/api/audit/verify", { method: "POST", cookie: analyst }))).status).toBe(403);
    const inv = await signIn("investigator");
    const r = await (await verify.POST(req("/api/audit/verify", { method: "POST", cookie: inv }))).json();
    expect(r).toMatchObject({ ok: true });
    expect(r.checkpoints).toBeGreaterThanOrEqual(1);
  });
});

describe("security headers", () => {
  it("sets a nonce CSP without unsafe-inline scripts, framing denial, and HSTS on https", () => {
    const h = securityHeaders({ nonce: "abc", dev: false, https: true });
    const csp = h["Content-Security-Policy"] as string;
    expect(csp).toContain("script-src 'self' 'nonce-abc' 'strict-dynamic'");
    expect(csp).not.toMatch(/script-src[^;]*unsafe-inline/);
    expect(csp).not.toContain("unsafe-eval");
    expect(csp).toContain("frame-ancestors 'none'");
    expect(h["Strict-Transport-Security"]).toContain("max-age=63072000");
    expect(h["Permissions-Policy"]).toContain("display-capture=()");
    expect(securityHeaders({ nonce: "abc", dev: true, https: false })["Strict-Transport-Security"]).toBeUndefined();
  });
});
