import { describe, expect, it } from "vitest";
import { authorize, entitlementFor, type Grant, type Resource, type Subject } from "@/lib/policy";

const now = 1_800_000_000;
const subject = (over: Partial<Subject> = {}): Subject => ({ userId: "u1", tenantId: "t1", roles: ["member"], authLevel: "mfa", authTime: now - 60, ...over });
const resource = (over: Partial<Resource> = {}): Resource => ({ assetId: "a1", tenantId: "t1", classification: "CONFIDENTIAL", ownerId: "owner", compartment: "lab", honey: false, revoked: false, ...over });
const grant = (over: Partial<Grant> = {}): Grant => ({ grantId: "g1", tenantId: "t1", subjectUserId: "u1", subjectRole: null, assetId: "a1", compartment: null, actions: ["view"], purpose: null, notBefore: now - 10, expiresAt: now + 3600, revoked: false, ...over });
const ctx = { now, riskState: "LOW" as const };

describe("policy decision point", () => {
  it("denies across tenants before evaluating anything else", () => {
    const d = authorize(subject({ tenantId: "t2", roles: ["tenant_admin"] }), "view", resource(), [grant({ tenantId: "t2" })], ctx);
    expect(d).toMatchObject({ effect: "deny", reasons: ["tenant_isolation"] });
  });

  it("denies by default with no entitlement", () => {
    expect(authorize(subject(), "view", resource(), [], ctx)).toMatchObject({ effect: "deny", reasons: ["no_entitlement"] });
  });

  it("never serves originals, whoever asks", () => {
    expect(authorize(subject({ userId: "owner", roles: ["tenant_admin"] }), "download_original", resource({ classification: "PUBLIC" }), [], ctx)).toMatchObject({
      effect: "deny",
      reasons: ["originals_never_served"],
    });
  });

  it("permits an active grant and ignores expired, future, revoked, or wrong-action grants", () => {
    expect(authorize(subject(), "view", resource(), [grant()], ctx).effect).toBe("permit");
    for (const g of [grant({ expiresAt: now - 1 }), grant({ notBefore: now + 10 }), grant({ revoked: true }), grant({ actions: ["export"] }), grant({ assetId: "other" })]) {
      expect(authorize(subject(), "view", resource(), [g], ctx).effect).toBe("deny");
    }
  });

  it("matches compartment and role grants", () => {
    const g = grant({ subjectUserId: null, subjectRole: "member", assetId: null, compartment: "lab" });
    expect(authorize(subject(), "view", resource(), [g], ctx).effect).toBe("permit");
    expect(authorize(subject(), "view", resource({ compartment: "other" }), [g], ctx).effect).toBe("deny");
  });

  it("checks entitlement before authentication, so no step-up prompt leaks existence", () => {
    const d = authorize(subject({ authLevel: "pwd" }), "view", resource({ classification: "CROWN_JEWEL" }), [], ctx);
    expect(d).toMatchObject({ effect: "deny", reasons: ["no_entitlement"] });
  });

  it("requires step-up for weak or stale authentication", () => {
    expect(authorize(subject({ authLevel: "pwd" }), "view", resource(), [grant()], ctx)).toMatchObject({ effect: "step_up", requiredAuth: "mfa" });
    expect(authorize(subject({ authTime: now - 9 * 3600 }), "view", resource(), [grant()], ctx)).toMatchObject({ effect: "step_up", reasons: ["auth_too_old"] });
    expect(authorize(subject({ authTime: now - 20 * 60 }), "view", resource(), [grant()], { now, riskState: "GUARDED" })).toMatchObject({
      effect: "step_up",
      reasons: ["elevated_risk_requires_fresh_auth"],
    });
  });

  it("enforces risk ceilings per classification, and CRITICAL denies everything", () => {
    const restricted = resource({ classification: "RESTRICTED" });
    const g = grant({ purpose: "review" });
    expect(authorize(subject(), "view", restricted, [g], { now, riskState: "HIGH", purpose: "review" })).toMatchObject({ reasons: ["risk_exceeds_classification_ceiling"] });
    expect(authorize(subject(), "view", resource({ classification: "PUBLIC" }), [], { now, riskState: "CRITICAL" })).toMatchObject({ reasons: ["risk_critical"] });
  });

  it("binds purpose for RESTRICTED and above", () => {
    const restricted = resource({ classification: "RESTRICTED" });
    expect(authorize(subject(), "view", restricted, [grant()], ctx)).toMatchObject({ reasons: ["grant_missing_purpose"] });
    expect(authorize(subject(), "view", restricted, [grant({ purpose: "audit" })], { ...ctx, purpose: "other" })).toMatchObject({ reasons: ["purpose_mismatch"] });
    expect(authorize(subject(), "view", restricted, [grant({ purpose: "audit" })], { ...ctx, purpose: " audit " }).effect).toBe("permit");
  });

  it("tightens obligations as risk rises", () => {
    const low = authorize(subject(), "view", resource(), [grant()], ctx);
    const high = authorize(subject({ authTime: now - 30 }), "view", resource(), [grant()], { now, riskState: "HIGH" });
    if (low.effect !== "permit" || high.effect !== "permit") throw new Error("expected permits");
    expect(low.obligations).toMatchObject({ watermark: "standard", maxWidth: 1600, capabilityTtlSeconds: 120 });
    expect(high.obligations).toMatchObject({ watermark: "dense", maxWidth: 800, capabilityTtlSeconds: 60, rotationSeconds: 10 });
  });

  it("disables export for RESTRICTED and above, and requires an explicit export grant below", () => {
    expect(authorize(subject(), "export", resource({ classification: "RESTRICTED" }), [grant({ actions: ["view", "export"] })], ctx)).toMatchObject({
      reasons: ["export_disabled_for_classification"],
    });
    expect(authorize(subject(), "export", resource(), [grant()], ctx).effect).toBe("deny");
    expect(authorize(subject(), "export", resource(), [grant({ actions: ["export"] })], ctx).effect).toBe("permit");
  });

  it("exposes the same entitlement rule to the catalogue", () => {
    expect(entitlementFor(subject(), "view", resource(), [], now)).toBeNull();
    expect(entitlementFor(subject(), "view", resource(), [grant()], now)).toMatchObject({ kind: "grant" });
    expect(entitlementFor(subject({ userId: "owner" }), "view", resource(), [], now)).toMatchObject({ kind: "owner" });
    expect(entitlementFor(subject(), "view", resource({ classification: "INTERNAL" }), [], now)).toMatchObject({ kind: "member_default" });
    expect(entitlementFor(subject({ tenantId: "t2" }), "view", resource({ classification: "INTERNAL" }), [], now)).toBeNull();
  });

  it("flags honey assets for non-investigators only", () => {
    const honey = resource({ honey: true });
    const d1 = authorize(subject(), "view", honey, [grant()], ctx);
    const d2 = authorize(subject({ roles: ["investigator"] }), "view", honey, [], ctx);
    expect(d1.effect === "permit" && d1.obligations.alert).toBe("honey_access");
    expect(d2.effect === "permit" && d2.obligations.alert).toBe(null);
  });
});
