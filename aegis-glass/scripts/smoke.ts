// End-to-end smoke test over real HTTP against a running demo server.
//
//   AEGIS_MODE=demo npx next start -p 3100 &
//   node scripts/smoke.ts http://localhost:3100
//
// Exits non-zero on the first failed check.

const BASE = process.argv[2] ?? "http://localhost:3100";
const ORIGIN = new URL(BASE).origin;
let failures = 0;
let passes = 0;

function check(name: string, condition: boolean, detail = ""): void {
  if (condition) {
    passes += 1;
    console.log(`  ok   ${name}`);
  } else {
    failures += 1;
    console.log(`  FAIL ${name}${detail ? ` — ${detail}` : ""}`);
  }
}

class Browser {
  cookies = new Map<string, string>();

  private cookieHeader(): string {
    return [...this.cookies].map(([k, v]) => `${k}=${v}`).join("; ");
  }

  private store(res: Response): void {
    for (const line of res.headers.getSetCookie()) {
      const [pair] = line.split(";");
      const i = pair.indexOf("=");
      const name = pair.slice(0, i);
      const value = pair.slice(i + 1);
      if (/Max-Age=0/i.test(line) || value === "") this.cookies.delete(name);
      else this.cookies.set(name, value);
    }
  }

  async post(path: string, body: unknown = {}, opts: { csrf?: boolean; origin?: string } = {}): Promise<Response> {
    const headers: Record<string, string> = { "Content-Type": "application/json", Cookie: this.cookieHeader() };
    if (opts.csrf !== false) headers["x-aegis-request"] = "1";
    headers.Origin = opts.origin ?? ORIGIN;
    const res = await fetch(BASE + path, { method: "POST", headers, body: JSON.stringify(body), redirect: "manual" });
    this.store(res);
    return res;
  }

  async get(path: string): Promise<Response> {
    const res = await fetch(BASE + path, { headers: { Cookie: this.cookieHeader() }, redirect: "manual" });
    this.store(res);
    return res;
  }

  lastSetCookie: string[] = [];

  async login(persona: string): Promise<void> {
    const res = await this.post("/api/dev/login", { persona });
    if (res.status !== 200) throw new Error(`login ${persona} failed: ${res.status}`);
    this.lastSetCookie = res.headers.getSetCookie();
  }

  async capability(assetId: string): Promise<{ status: number; body: Record<string, unknown> }> {
    const res = await this.post(`/api/assets/${assetId}/capability`);
    return { status: res.status, body: (await res.json()) as Record<string, unknown> };
  }
}

async function main(): Promise<void> {
  console.log(`Smoke test against ${BASE}`);

  console.log("Security headers");
  const home = await fetch(BASE + "/");
  const csp = home.headers.get("content-security-policy") ?? "";
  check("CSP has a per-request script nonce", /script-src 'self' 'nonce-[A-Za-z0-9+/=]+' 'strict-dynamic'/.test(csp), csp);
  check("CSP forbids framing", csp.includes("frame-ancestors 'none'"));
  check("CSP has no unsafe-eval in production", !csp.includes("unsafe-eval"));
  check("HSTS set", (home.headers.get("strict-transport-security") ?? "").includes("max-age=63072000"));
  check("X-Frame-Options DENY", home.headers.get("x-frame-options") === "DENY");
  check("no X-Powered-By", home.headers.get("x-powered-by") === null);
  const html = await home.text();
  const nonce = /'nonce-([^']+)'/.exec(csp)?.[1] ?? "";
  check("Next.js scripts carry the nonce", nonce !== "" && html.includes(`nonce="${nonce}"`));

  console.log("CSRF");
  const anon = new Browser();
  check("POST without the CSRF header is refused", (await anon.post("/api/dev/login", { persona: "analyst" }, { csrf: false })).status === 403);
  check("POST from another origin is refused", (await anon.post("/api/dev/login", { persona: "analyst" }, { origin: "https://evil.example" })).status === 403);

  console.log("Viewing");
  const analyst = new Browser();
  await analyst.login("analyst");
  const sessionLine = analyst.lastSetCookie.find((l) => l.startsWith("aegis_session=")) ?? "";
  check(
    "session cookie is HttpOnly, Secure, SameSite=Strict",
    /;\s*HttpOnly/i.test(sessionLine) && /;\s*Secure/i.test(sessionLine) && /;\s*SameSite=Strict/i.test(sessionLine),
    sessionLine.replace(/=[^;]+/, "=…"),
  );
  const cap = await analyst.capability("a-atlas-concept");
  check("entitled viewer gets a capability", cap.status === 200, JSON.stringify(cap.body));
  const url = String(cap.body.url ?? "");
  const media = await analyst.get(url);
  const bytes = new Uint8Array(await media.arrayBuffer());
  check("preview is served as WebP", media.status === 200 && media.headers.get("content-type") === "image/webp" && bytes.length > 1000);
  check("preview is never cached", media.headers.get("cache-control") === "no-store, private, max-age=0");
  check("preview is same-origin only", media.headers.get("cross-origin-resource-policy") === "same-origin");
  check("replaying the URL fails", (await analyst.get(url)).status === 410);

  const cap2 = await analyst.capability("a-palette");
  const thief = new Browser();
  check("a leaked URL without a session fails", (await thief.get(String(cap2.body.url))).status === 401);
  await thief.login("analyst");
  check("a leaked URL in another session fails", (await thief.get(String(cap2.body.url))).status === 403);

  check("another tenant's asset looks missing", (await analyst.capability("a-other-plan")).status === 404);
  check("garbage asset IDs are rejected", (await analyst.capability("..%2F..%2Fetc")).status === 404);

  console.log("Step-up");
  const before = await analyst.capability("a-atlas-proto");
  check("RESTRICTED asks for step-up on an MFA session", before.status === 401 && before.body.error === "step_up_required");
  check("step-up succeeds", (await analyst.post("/api/dev/step-up")).status === 200);
  check("RESTRICTED opens after step-up", (await analyst.capability("a-atlas-proto")).status === 200);

  console.log("Separation of duties");
  const admin = new Browser();
  await admin.login("admin");
  check("tenant admin cannot open CROWN-JEWEL", (await admin.capability("a-core-whiteboard")).status === 403);

  console.log("Investigation");
  const investigator = new Browser();
  await investigator.login("investigator");
  const trace = /T-[0-9A-Z]{10}/.exec(String((cap.body.watermark as { lines: string[] }).lines[0]))?.[0] ?? "";
  const resolved = await investigator.get(`/api/traces/${trace}`);
  const evidence = (await resolved.json()) as { evidenceGrade?: string; receipt?: { body: { userId: string } } };
  check("investigator resolves the trace to a signed receipt", resolved.status === 200 && evidence.evidenceGrade === "confirmed_cryptographic_trace");
  check("receipt names the viewing account", evidence.receipt?.body.userId === "u-analyst");
  check("an admin cannot resolve traces", (await admin.get(`/api/traces/${trace}`)).status === 403);

  console.log("Revocation and audit");
  const sessionId = JSON.parse(Buffer.from(String(analyst.cookies.get("aegis_session")).split(".")[0], "base64url").toString()).sid as string;
  check("admin revokes the analyst session", (await admin.post("/api/sessions/revoke", { sessionId })).status === 200);
  const after = await analyst.capability("a-palette");
  check("revoked session is cut off", after.status === 401 && after.body.error === "session_revoked");

  const verify = await admin.post("/api/audit/verify");
  const verdict = (await verify.json()) as { ok?: boolean; checked?: number };
  check("audit chain verifies intact", verify.status === 200 && verdict.ok === true && (verdict.checked ?? 0) > 10, JSON.stringify(verdict));

  console.log(`\n${passes} passed, ${failures} failed`);
  process.exit(failures === 0 ? 0 : 1);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
