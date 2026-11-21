# Aegis Glass platform

Server-enforced, attributable viewing of confidential images, built as a self-contained Next.js 15 app.

- **Single-use access:** every view is authorised by policy, delivered once, and resized to the viewer's risk level.
- **Attribution:** each copy is watermarked with the viewer's pseudonym and a verifiable trace token, and signed.
- **Audit:** every decision is recorded in a hash-chained trail that the database refuses to edit.

The static site's `aegis-glass.js` at the repository root is a separate, client-only deterrence layer. This package is the server half that makes attribution verifiable.

**Read [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) first.** It has the threat model and the status of each component. It also sets out the limits: no web app can stop a camera or an OS screenshot, and production sign-in is blocked until an OIDC adapter exists.

## Run it locally

Requires Node.js 22.

```bash
npm ci
AEGIS_ENV=development npm run dev        # http://localhost:3000
```

Development mode generates fresh keys per process and seeds a demo tenant with synthetic images and four personas:
- **analyst:** an MFA member.
- **admin:** owns the crown-jewel asset and must step up to a passkey to open it.
- **investigator:** runs leak intake and audit verification.
- **outsider:** another tenant, used to check isolation.

Data lives in `.aegis-data/` (git-ignored).

With no `AEGIS_ENV`, a production build (`NODE_ENV=production`) runs in production mode. That mode refuses to start without every key and an identity provider.

## Checks

```bash
npm run typecheck
npm test                                  # 58 tests on in-process PostgreSQL (PGlite)
AEGIS_TEST_PG_ADMIN_URL=postgres://user@host:5432/postgres npm test   # adds 4 tests on a real PostgreSQL server
npm run build
npm audit
```

## Layout

| Path | Contents |
|---|---|
| `src/lib/` | Policy, risk, capabilities, trace tokens, watermark, envelope encryption, image derivation, audit chain, store, service |
| `src/app/api/` | Route handlers (view, media, status, risk signal, upload, leak intake, audit verify, revoke, health, dev sign-in) |
| `src/components/` | Workspace, `SecureAssetViewer`, investigator panel |
| `db/migrations/` | PostgreSQL schema with append-only triggers |
| `tests/` | Unit, journey, HTTP, forensics, and PostgreSQL-server suites |
| `docs/ARCHITECTURE.md` | Diagrams, trust boundaries, STRIDE, control matrix, rollout, rollback, activation checklist |

## Dependency notes

- `overrides.next.postcss` lifts the postcss inside Next 15.5 from 8.4.31 to 8.5.30, which fixes GHSA-qx2v-qp2m-jg93 and the related source-map advisories. postcss stays on the same major version.
- `.npmrc` sets `legacy-peer-deps`, because npm 10.9 crashes resolving vitest 4.1's peer set. Every peer this package needs is declared explicitly.
