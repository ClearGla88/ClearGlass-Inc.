import { describe, expect, it } from "vitest";
import { generateKeyPairSync } from "node:crypto";
import sharp from "sharp";
import { issueCapability, sessionBinding, verifyCapability, type CapabilityClaims } from "@/lib/capability";
import { issueTraceToken, pseudonym, verifyTraceToken } from "@/lib/trace";
import { epochFor, layoutFor, watermarkLines, watermarkSvg } from "@/lib/watermark";
import { assetAad, LocalKeyWrapper, openObject, sealObject } from "@/lib/envelope";
import { dHash, hamming } from "@/lib/image";
import { assessRisk, stateForScore } from "@/lib/risk";
import { canonicalJson, randomKey } from "@/lib/crypto";
import { loadConfig, ConfigError } from "@/lib/config";
import { PERCEPTUAL_MATCH_MAX_DISTANCE } from "@/lib/service";

const key = randomKey();

describe("capabilities", () => {
  const claims = (over: Partial<CapabilityClaims> = {}): CapabilityClaims => ({
    v: 1, cid: "c", vid: "v", aid: "a", tid: "t", sb: sessionBinding(key, "s1"), path: "/api/media/v", iat: 1000, exp: 1060, ...over,
  });
  const expect_ = { now: 1010, path: "/api/media/v", sessionId: "s1" };

  it("verifies a valid token", () => {
    expect(verifyCapability(key, issueCapability(key, claims()), expect_)).toMatchObject({ ok: true });
  });
  it("rejects tampering, wrong key, wrong path, wrong session, expiry, and junk", () => {
    const t = issueCapability(key, claims());
    const [h, b, s] = t.split(".") as [string, string, string];
    const other = Buffer.from(JSON.stringify({ ...claims(), exp: 9_999_999 })).toString("base64url");
    expect(verifyCapability(key, `${h}.${other}.${s}`, expect_)).toMatchObject({ reason: "bad_signature" });
    expect(verifyCapability(randomKey(), t, expect_)).toMatchObject({ reason: "bad_signature" });
    expect(verifyCapability(key, t, { ...expect_, path: "/api/media/x" })).toMatchObject({ reason: "wrong_path" });
    expect(verifyCapability(key, t, { ...expect_, sessionId: "s2" })).toMatchObject({ reason: "wrong_session" });
    expect(verifyCapability(key, t, { ...expect_, now: 1100 })).toMatchObject({ reason: "expired" });
    for (const junk of [null, "", "v2.a.b", `${h}.${b}`, "v1.!!.??", "x".repeat(5000)]) expect(verifyCapability(key, junk, expect_).ok).toBe(false);
  });
});

describe("trace tokens and pseudonyms", () => {
  it("round-trips, survives retyping with confusable letters, and rejects typos", () => {
    const t = issueTraceToken(key);
    expect(t).toMatch(/^[0-9A-HJKMNP-TV-Z]{4}-[0-9A-HJKMNP-TV-Z]{4}-[0-9A-HJKMNP-TV-Z]{4}$/);
    expect(verifyTraceToken(key, t)).toEqual({ valid: true, token: t });
    const retyped = t.toLowerCase().replace(/-/g, " ").replace(/0/g, "o").replace(/1/g, "l");
    expect(verifyTraceToken(key, retyped)).toEqual({ valid: true, token: t });
    const flipped = (t[0] === "A" ? "B" : "A") + t.slice(1);
    expect(verifyTraceToken(key, flipped)).toMatchObject({ valid: false });
    expect(verifyTraceToken(randomKey(), t)).toMatchObject({ valid: false, reason: "bad_check" });
  });
  it("derives stable pseudonyms that differ per key and per person", () => {
    const a = pseudonym(key, "V", "tenant", "user-a");
    expect(a).toMatch(/^V-[0-9A-Z]{4}-[0-9A-Z]{4}$/);
    expect(pseudonym(key, "V", "tenant", "user-a")).toBe(a);
    expect(pseudonym(key, "V", "tenant", "user-b")).not.toBe(a);
    expect(pseudonym(randomKey(), "V", "tenant", "user-a")).not.toBe(a);
  });
});

describe("watermark", () => {
  it("carries pseudonyms and trace token only", () => {
    const lines = watermarkLines({ classification: "CROWN_JEWEL", tenantPseudonym: "T-AAAA-BBBB", viewerPseudonym: "V-CCCC-DDDD", sessionFragment: "S-EEEE", traceToken: "1234-5678-9ABC", issuedAt: "2026-11-06T12:34:56.789Z" });
    expect(lines).toEqual(["CROWN JEWEL · T-AAAA-BBBB · V-CCCC-DDDD · S-EEEE", "TRACE 1234-5678-9ABC · 2026-11-06 12:34Z"]);
  });
  it("is deterministic within an epoch and moves between epochs", () => {
    const e = epochFor(1_700_000_000_000, 20);
    expect(layoutFor("seed", e, "standard")).toEqual(layoutFor("seed", e, "standard"));
    expect(layoutFor("seed", e + 1, "standard")).not.toEqual(layoutFor("seed", e, "standard"));
    const l = layoutFor("seed", e, "dense");
    expect(l.angleDeg).toBeGreaterThanOrEqual(-38);
    expect(l.angleDeg).toBeLessThanOrEqual(-22);
  });
  it("escapes text into SVG and renders through sharp", async () => {
    const svg = watermarkSvg(400, 300, ["<b>&\"'"], layoutFor("s", 1, "light"), "light");
    expect(svg).not.toContain("<b>");
    expect(svg).toContain("&lt;b&gt;&amp;&quot;&apos;");
    const png = await sharp(Buffer.from(svg)).png().toBuffer();
    expect((await sharp(png).metadata()).width).toBe(400);
  });
});

describe("envelope encryption", () => {
  const wrapper = new LocalKeyWrapper(new Map([["k1", randomKey()]]), "k1");
  const aad = assetAad("tenant-1", "asset-1");
  it("round-trips and binds ciphertext to its asset", async () => {
    const { sealed, keyId } = await sealObject(wrapper, Buffer.from("master bytes"), aad);
    expect(keyId).toBe("k1");
    expect(sealed.includes(Buffer.from("master bytes"))).toBe(false);
    expect((await openObject(wrapper, sealed, aad)).toString()).toBe("master bytes");
    await expect(openObject(wrapper, sealed, assetAad("tenant-1", "asset-2"))).rejects.toThrow();
  });
  it("detects tampering and refuses an unknown or wrong KEK", async () => {
    const { sealed } = await sealObject(wrapper, Buffer.from("master bytes"), aad);
    const flipped = Buffer.from(sealed);
    flipped[flipped.length - 1] = (flipped[flipped.length - 1] as number) ^ 1;
    await expect(openObject(wrapper, flipped, aad)).rejects.toThrow();
    await expect(openObject(new LocalKeyWrapper(new Map([["k1", randomKey()]]), "k1"), sealed, aad)).rejects.toThrow();
    await expect(openObject(new LocalKeyWrapper(new Map([["k2", randomKey()]]), "k2"), sealed, aad)).rejects.toThrow(/unknown KEK/);
  });
  it("supports KEK rotation: old objects still open after a new active key is added", async () => {
    const k1 = randomKey();
    const before = await sealObject(new LocalKeyWrapper(new Map([["k1", k1]]), "k1"), Buffer.from("v1"), aad);
    const rotated = new LocalKeyWrapper(new Map([["k1", k1], ["k2", randomKey()]]), "k2");
    expect((await openObject(rotated, before.sealed, aad)).toString()).toBe("v1");
    expect((await sealObject(rotated, Buffer.from("v2"), aad)).keyId).toBe("k2");
  });
});

describe("perceptual hash", () => {
  const scene = (hueA: string, hueB: string, shape: string) =>
    sharp(Buffer.from(`<svg xmlns="http://www.w3.org/2000/svg" width="800" height="500"><defs><linearGradient id="g"><stop offset="0" stop-color="${hueA}"/><stop offset="1" stop-color="${hueB}"/></linearGradient></defs><rect width="800" height="500" fill="url(#g)"/>${shape}</svg>`)).png().toBuffer();
  it("matches resized, recompressed, colour-shifted copies and separates different images", async () => {
    const a = await scene("#102030", "#a0c0e0", '<circle cx="250" cy="250" r="160" fill="#fff"/><rect x="520" y="80" width="200" height="340" fill="#000"/>');
    const b = await scene("#e0a020", "#201008", '<rect x="60" y="60" width="300" height="120" fill="#000"/><circle cx="600" cy="360" r="110" fill="#fff"/>');
    const ha = await dHash(a);
    const smaller = await sharp(a).resize(300).jpeg({ quality: 45 }).toBuffer();
    const tinted = await sharp(a).modulate({ brightness: 1.15, saturation: 0.6 }).toBuffer();
    // Asserted against the threshold leak intake actually uses.
    expect(hamming(ha, await dHash(smaller))).toBeLessThanOrEqual(PERCEPTUAL_MATCH_MAX_DISTANCE);
    expect(hamming(ha, await dHash(tinted))).toBeLessThanOrEqual(PERCEPTUAL_MATCH_MAX_DISTANCE);
    expect(hamming(ha, await dHash(b))).toBeGreaterThan(2 * PERCEPTUAL_MATCH_MAX_DISTANCE);
  });
});

describe("risk engine", () => {
  const base = { newDevice: false, impossibleTravel: false, badAsnReputation: false, sessionAgeSeconds: 60, failedAuthzLast15m: 0, viewRequestsLastMinute: 1, distinctAssetsLast5m: 1, clientSignalsLast15m: {} };
  it("explains every point and maps scores to states", () => {
    const r = assessRisk({ ...base, newDevice: true, failedAuthzLast15m: 10, viewRequestsLastMinute: 25 });
    expect(r.contributions.map((c) => c.signal)).toEqual(["new_device", "failed_authorization", "view_rate"]);
    expect(r.score).toBe(15 + 32 + 20);
    expect(r.state).toBe("HIGH");
    expect([0, 19, 20, 44, 45, 69, 70, 100].map(stateForScore)).toEqual(["LOW", "LOW", "GUARDED", "GUARDED", "HIGH", "HIGH", "CRITICAL", "CRITICAL"]);
  });
  it("caps repeated low-value client signals", () => {
    const r = assessRisk({ ...base, clientSignalsLast15m: { focus_lost: 500, context_menu: 500 } });
    expect(r.score).toBe(10 + 5);
  });
});

describe("canonical JSON and configuration", () => {
  it("sorts keys recursively and refuses non-finite numbers", () => {
    expect(canonicalJson({ b: 1, a: { d: [3, { z: 1, y: 2 }], c: undefined } })).toBe('{"a":{"d":[3,{"y":2,"z":1}]},"b":1}');
    expect(() => canonicalJson({ x: Number.NaN })).toThrow();
  });
  it("fails closed in production, naming what is missing", () => {
    const k = () => randomKey().toString("base64url");
    const prod: Record<string, string> = { AEGIS_ENV: "production", AEGIS_APP_ORIGIN: "https://vault.example.com", AEGIS_DATABASE_URL: "postgres://db/aegis" };
    expect(() => loadConfig(prod)).toThrow(/AEGIS_CAPABILITY_KEY is required/);
    expect(() => loadConfig({ ...prod, AEGIS_APP_ORIGIN: "http://vault.example.com" })).toThrow(/https origin/);
    expect(() => loadConfig({ ...prod, AEGIS_DEV_LOGIN: "1" })).toThrow(/AEGIS_DEV_LOGIN/);
    const same = k();
    const keys = { AEGIS_CAPABILITY_KEY: same, AEGIS_TRACE_KEY: same, AEGIS_PSEUDONYM_KEY: k(), AEGIS_SESSION_KEY: k(), AEGIS_KEK: k(), AEGIS_KEK_ID: "kek-1" };
    expect(() => loadConfig({ ...prod, ...keys })).toThrow(/distinct/);
    expect(() => loadConfig({ ...prod, ...keys, AEGIS_TRACE_KEY: k() })).toThrow(/AEGIS_SIGNING_JWK is required/);
    const { privateKey } = generateKeyPairSync("ed25519");
    const jwk = Buffer.from(JSON.stringify(privateKey.export({ format: "jwk" }))).toString("base64url");
    expect(() => loadConfig({ ...prod, ...keys, AEGIS_TRACE_KEY: k(), AEGIS_SIGNING_JWK: jwk })).toThrow(ConfigError);
    expect(() => loadConfig({ ...prod, ...keys, AEGIS_TRACE_KEY: k(), AEGIS_SIGNING_JWK: jwk })).toThrow(/BLOCKED: production sign-in needs an OIDC/);
  });
});
