# Aegis Glass

Protected, attributable previews for confidential concept work: images, screenshots, drafts and prototypes.

Every view is authorized on its own, delivered once as a short-lived, watermarked, reduced-resolution preview, recorded with a signed receipt, and written to a tamper-evident audit trail. Access can be withdrawn within seconds.

It cannot stop someone photographing their screen, and nothing on the web can. It makes that slower, less useful and traceable. See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the threat model, control matrix, rollout plan and limits.

## Status

| Part | State |
|---|---|
| Enforcement core (`lib/`) | Built and tested |
| Next.js 16 app and viewer | Built and tested in Chromium |
| PostgreSQL schema | Designed and verified on PostgreSQL 16; not yet used by the app |
| Production adapters (Postgres, Redis, KMS, OIDC) | Not built. Production mode refuses to start |

## Run the demo

Requires Node 22.18 or later.

```bash
cd aegis-glass
npm ci
npm run build
AEGIS_MODE=demo npm start     # http://localhost:3000
```

Demo mode uses in-memory stores, a local key-encryption key and random keys generated at startup. Everything resets when the server stops, and all content is synthetic.

Things to try:

1. Sign in as **Analyst**. Open "Atlas homepage concept" and watch the watermark move every 20 seconds.
2. Open "Atlas v2 prototype screens". It asks for a passkey; choose **Verify with passkey**.
3. Open "Partner shortlist draft". It's a decoy: the session goes to HIGH risk and a review case opens.
4. In another browser profile, sign in as **Investigator**. Verify the audit chain, read the case, and paste a trace token (the `T-…` code in any watermark) to resolve it to a signed receipt.
5. Sign in as **Tenant admin** and revoke the analyst's session from the case. The analyst's preview disappears within one refresh.

## Checks

```bash
npm test                         # 42 unit and service tests
npx tsc --noEmit                 # types
npm run build                    # production build
npm run schema:check             # schema guarantees on a throwaway PostgreSQL
AEGIS_MODE=demo npx next start -p 3100 &
node scripts/smoke.ts http://localhost:3100    # 29 HTTP checks
```

## Layout

```
lib/          enforcement core: policy, capabilities, risk, preview rendering, receipts, audit, encryption
app/          Next.js routes and pages
components/   SecureAssetViewer, vault, investigator panel, demo sign-in
proxy.ts      CSP nonce, security headers, CSRF
db/           production PostgreSQL schema
docs/         architecture and security design
scripts/      HTTP smoke test, schema check
tests/        node:test suites
```
