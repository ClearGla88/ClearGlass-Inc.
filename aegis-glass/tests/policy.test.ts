import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { authorize, type AuthorizeInput } from "../lib/policy.ts";
import type { Asset, Grant, Principal } from "../lib/types.ts";

const NOW = 1_800_000_000;

function principal(over: Partial<Principal> = {}): Principal {
  return { userId: "u1", tenantId: "t1", displayName: "U1", roles: ["viewer"], authLevel: "mfa", authTime: NOW - 60, sessionId: "s1", ...over };
}

function asset(over: Partial<Asset> = {}): Asset {
  return { id: "a1", tenantId: "t1", title: "A", altText: "A", classification: "CONFIDENTIAL", ownerId: "owner", compartments: [], isHoney: false, storageKey: "k", mime: "image/png", ...over };
}

function grant(over: Partial<Grant> = {}): Grant {
  return { id: "g1", tenantId: "t1", userId: "u1", assetId: "a1", actions: ["view"], purpose: "review", expiresAt: NOW + 3600, ...over };
}

function input(over: Partial<AuthorizeInput> = {}): AuthorizeInput {
  return { principal: principal(), asset: asset(), action: "view", grants: [], risk: "LOW", now: NOW, ...over };
}

describe("authorize", () => {
  it("allows a CONFIDENTIAL view with MFA and returns the class obligations", () => {
    const d = authorize(input());
    assert.equal(d.allow, true);
    if (d.allow) assert.deepEqual(d.obligations, { previewMaxWidth: 1280, capabilityTtlSeconds: 60, watermarkDensity: 2 });
  });

  it("denies across tenants before anything else", () => {
    const d = authorize(input({ principal: principal({ tenantId: "t2", roles: ["tenant_admin"] }) }));
    assert.equal(d.allow, false);
    if (!d.allow) assert.equal(d.reason, "tenant_mismatch");
  });

  it("denies everything in CRITICAL risk, even the owner", () => {
    const d = authorize(input({ principal: principal({ userId: "owner" }), risk: "CRITICAL" }));
    assert.equal(d.allow, false);
    if (!d.allow) assert.equal(d.reason, "risk_critical");
  });

  it("requires step-up when the auth level is too weak", () => {
    const d = authorize(input({ principal: principal({ authLevel: "password" }) }));
    assert.equal(d.allow, false);
    if (!d.allow) {
      assert.equal(d.reason, "step_up_required");
      assert.equal(d.stepUp, true);
    }
  });

  it("CROWN_JEWEL needs a grant and authentication within 15 minutes", () => {
    const strong = principal({ authLevel: "phishing_resistant" });
    const cj = asset({ classification: "CROWN_JEWEL" });
    const noGrant = authorize(input({ principal: strong, asset: cj }));
    assert.equal(noGrant.allow, false);
    if (!noGrant.allow) assert.equal(noGrant.reason, "grant_required");

    assert.equal(authorize(input({ principal: strong, asset: cj, grants: [grant()] })).allow, true);

    const stale = authorize(input({ principal: { ...strong, authTime: NOW - 16 * 60 }, asset: cj, grants: [grant()] }));
    assert.equal(stale.allow, false);
    if (!stale.allow) assert.equal(stale.reason, "step_up_required");
  });

  it("does not give tenant admins implicit access to RESTRICTED content", () => {
    const admin = principal({ roles: ["tenant_admin"], authLevel: "phishing_resistant" });
    const d = authorize(input({ principal: admin, asset: asset({ classification: "RESTRICTED" }) }));
    assert.equal(d.allow, false);
    if (!d.allow) assert.equal(d.reason, "grant_required");
  });

  it("ignores expired, revoked, wrong-user and wrong-tenant grants", () => {
    const strong = principal({ authLevel: "phishing_resistant" });
    const restricted = asset({ classification: "RESTRICTED" });
    for (const g of [
      grant({ expiresAt: NOW - 1 }),
      grant({ revokedAt: NOW - 10 }),
      grant({ userId: "someone-else" }),
      grant({ tenantId: "t2" }),
      grant({ actions: ["export"] }),
    ]) {
      assert.equal(authorize(input({ principal: strong, asset: restricted, grants: [g] })).allow, false, JSON.stringify(g));
    }
  });

  it("honours compartment grants", () => {
    const a = asset({ compartments: ["atlas"] });
    assert.equal(authorize(input({ asset: a })).allow, false);
    assert.equal(authorize(input({ asset: a, grants: [grant({ assetId: undefined, compartment: "atlas" })] })).allow, true);
    assert.equal(authorize(input({ asset: a, grants: [grant({ assetId: undefined, compartment: "other" })] })).allow, false);
  });

  it("never allows export of RESTRICTED or CROWN_JEWEL, and needs an editor role for export", () => {
    const editor = principal({ roles: ["editor"], authLevel: "phishing_resistant" });
    for (const classification of ["RESTRICTED", "CROWN_JEWEL"] as const) {
      const d = authorize(input({ principal: editor, asset: asset({ classification }), action: "export", grants: [grant({ actions: ["view", "export"] })] }));
      assert.equal(d.allow, false);
      if (!d.allow) assert.equal(d.reason, "export_forbidden_for_classification");
    }
    const viewerExport = authorize(input({ action: "export" }));
    assert.equal(viewerExport.allow, false);
    if (!viewerExport.allow) assert.equal(viewerExport.reason, "role_insufficient");
  });

  it("tightens obligations as risk rises", () => {
    const guarded = authorize(input({ risk: "GUARDED" }));
    const high = authorize(input({ risk: "HIGH" }));
    assert.ok(guarded.allow && high.allow);
    if (guarded.allow && high.allow) {
      assert.equal(guarded.obligations.watermarkDensity, 3);
      assert.deepEqual(high.obligations, { previewMaxWidth: 640, capabilityTtlSeconds: 20, watermarkDensity: 4 });
    }
  });

  it("HIGH risk demands fresh phishing-resistant auth for RESTRICTED", () => {
    const p = principal({ authLevel: "phishing_resistant", authTime: NOW - 3600 });
    const restricted = asset({ classification: "RESTRICTED" });
    assert.equal(authorize(input({ principal: p, asset: restricted, grants: [grant()] })).allow, true);
    const d = authorize(input({ principal: p, asset: restricted, grants: [grant()], risk: "HIGH" }));
    assert.equal(d.allow, false);
    if (!d.allow) assert.equal(d.reason, "step_up_required");
  });
});
