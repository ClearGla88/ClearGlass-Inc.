# ClearGlass Inc.

**Transparency is infrastructure.**

ClearGlass Inc. is an Ontario-focused cybersecurity, AI-governance, OSINT, automation, and intelligence-platform company. This repository is the primary engineering and web platform for ClearGlassInc.com, including the public website, product surfaces, research systems, operational data, automation, and platform architecture.

## Repository status

Verified against this tree on 2026-11-05.

The repository was populated by "Add files via upload" commits, and almost every file sits at the repository root. Much of the original source tree is not in this repository: `scripts/`, `tools/` (apart from the hygiene check), `data/`, `assets/`, `services/`, `sentinel/`, `clearglass-commerce/`, `.circleci/`, and the `artemis` Python package. The sections from **Governed Data Fabric** onward describe that original layout. Read them as design documentation, not as a description of what this tree contains or runs.

The website pages (`*.html`, `*.css`, `*.js`, `sitemap*.xml`, `CNAME`, `.nojekyll`) live at the root on purpose. GitHub Pages serves them from there.

**Runs in this tree**

| Component | Files | Verified by |
|---|---|---|
| Content agent (governed 50/30/20 drafts) | `content_agent.py`, `content_seed.example.json` | `tests/test_content_agent.py`, CI smoke run |
| Agent-army orchestrator | `orchestrator.py`, `config.json` | CI smoke run |
| Auto-heal controller | `auto_heal.py`, `error-patterns.json`, `healing-strategies.json` | `tests/test_auto_heal.py`. It expects its state in `.github/auto-heal/` and exits with status 2, before any API call, when that directory is missing (as it is now). |
| Agent crypto runtime (Rust, `age`) | `Cargo.toml`, `Cargo.lock`, `src/` | `cargo test --locked`; `.github/workflows/agent-army-crypto.yml` also builds the release binary and checks the CLI encrypt/decrypt round trip and tamper rejection |
| Repository hygiene gate | `tools/repo_hygiene.py`, `tools/repo_hygiene_baseline.json` | `tests/test_repo_hygiene.py`, CI |
| Legal intelligence modules | `legal_intelligence_core.py`, `artemis_legal_agent_mvp.py` | Their tests are kept outside this repository |
| Aegis Glass platform (Next.js, PostgreSQL) | `aegis-glass-platform/` | `npm test` (62 tests, incl. a PostgreSQL 16 server) and `npm run build` via `.github/workflows/aegis-glass-ci.yml`. Production sign-in is blocked until an OIDC adapter exists; see `aegis-glass-platform/docs/ARCHITECTURE.md` |
| ClearGlass Agent Office (governed multi-agent operations: FastAPI, Next.js console, PostgreSQL schema) | `clearglass-agent-office/` | `pytest` (100 tests, incl. a PostgreSQL 16 server), a Daily Operations Loop smoke run, and the console's `npm run build` via `.github/workflows/agent-office-ci.yml`. External connectors are dry-run; see `clearglass-agent-office/README.md` |

**Does not run in this tree**

- **Workflows:** about 77 workflow files sit at the root instead of in `.github/workflows/`, so GitHub never runs them. The active workflows are `baseline-ci.yml`, `jekyll-gh-pages.yml`, `agent-army-crypto.yml`, `aegis-glass-ci.yml`, and `agent-office-ci.yml` in `.github/workflows/`. Many root workflows run on a schedule, write to the repository, deploy, or read secrets, and many call scripts that are missing. Review each one before moving it into `.github/workflows/`; don't move them in bulk.
- **Node tooling:** `npm run typecheck`, `npm test`, `npm run sync:stripe`, and `npm run provenance` fail because their TypeScript sources under `scripts/` are missing. `npm ci` does install the locked dependencies.
- **Python package:** `pyproject.toml` declares an `artemis` package, console scripts, and test paths that are absent. `pip install .` produces no usable package.

**Local checks**

```bash
python3 -m pip install -r requirements.txt
python3 -m pytest -q
python3 tools/repo_hygiene.py
ruff check --select E9,F .
cargo test --locked
```

See `CONTRIBUTING.md` for the full workflow.

## Live Platform

- Website: https://www.clearglassinc.com
- Intelligence Platform: https://www.clearglassinc.com/intelligence-platform.html
- Governed Data Fabric Diagnostics: https://www.clearglassinc.com/data-fabric.html
- Ontario OSINT: https://www.clearglassinc.com/Ontario-osint.html
- Products: https://www.clearglassinc.com/products.html
- Store: https://www.clearglassinc.com/store.html

## Core Systems

- **ClearGlass Nexus** — central intelligence and orchestration layer
- **Artemis** — AI/cyber intelligence product family
- **Guardian / Sentinel** — defensive cybersecurity and monitoring surfaces
- **Ontario OSINT** — public-source intelligence and regional analysis
- **XENOLITH** — sovereign intelligence-lattice research platform
- **ClearGlass Data Fabric** — governed same-origin repository data layer
- **Growth / SEO / Commerce** — revenue, marketing, search, and product systems

## Governed Data Fabric

Repository-backed operational data is cataloged through `data/catalog.json` and accessed through `assets/js/clearglass-data-fabric.js`.

The fabric provides:

- same-origin loading
- parent-traversal blocking
- JSON and CSV decoding
- module and root-dataset discovery
- browser health checks
- restricted browser access for sensitive workflow boundaries such as `data/leads`

Run the offline validator when a local checkout is available:

```bash
python3 scripts/validate_data_fabric.py
node --check assets/js/clearglass-data-fabric.js
```

## Actions-Independent Release Path

GitHub Pages is configured from `main` and can publish through the repository's legacy Pages build path. The site also includes browser-based data-fabric diagnostics so the public runtime can be checked without depending on a GitHub-hosted Actions runner.

See `docs/ACTIONS_BILLING_FALLBACK.md` for the operational fallback and recovery procedure.

## Secure CircleCI Orchestration

`.circleci/config.yml` is the guarded CircleCI 2.1 orchestration entry point for repository validation, GitHub-workflow validation, frontend/animation artifact builds, sandbox agent checks, and approved Fly.io releases of the ClearGlass agent service.

### Workflows

- **`validate`** is the default branch/pull-request path. It runs preflight, dependency verification, lint/type/test/build, dependency and secret scans, GitHub workflow validation, frontend/animation smoke tests, and sandbox agent contract tests. It performs no deployment or GitHub mutation.
- **`staging_release`** exists only when the manually supplied pipeline parameter `deploy_staging=true`. Preflight additionally requires `run_validation=true`, `target_environment=staging`, `emergency_stop=false`, and a branch ref. All validation/security jobs must pass before the `staging-deploy` context is available to the deployment job.
- **`production_release`** exists only when the manually supplied pipeline parameter `deploy_production=true`. Preflight additionally requires `run_validation=true`, `target_environment=production`, `emergency_stop=false`, and either the protected `main` branch or a trusted signed `v...` release tag. A CircleCI `hold_production` approval job must be approved before the `production-deploy` context can be used.

Ordinary commits cannot deploy because all mutation parameters default to `false`. Invalid parameter combinations fail in `security_preflight` before a deploy context is attached.

### Manual pipeline parameters

| Parameter | Type | Default | Purpose |
|---|---|---:|---|
| `run_validation` | boolean | `true` | Run the validation chain. Required for either deployment. |
| `run_github_automation_checks` | boolean | `false` | Add extended, read-only GitHub workflow checks. Never triggers or writes GitHub Actions. |
| `run_agent_health_checks` | boolean | `false` | Add extended local/sandbox agent HTTP contract checks. |
| `deploy_staging` | boolean | `false` | Request a staging release. Requires `target_environment=staging`. |
| `deploy_production` | boolean | `false` | Request a production release. Requires `target_environment=production` and approval. |
| `enable_agents` | boolean | `false` | Reserved for a separately reviewed activation adapter. Currently fails closed if set `true`. |
| `deploy_animations` | boolean | `false` | Reserved for a separately reviewed frontend publication adapter. Currently fails closed if set `true`. |
| `emergency_stop` | boolean | `false` | Global mutation stop. If `true`, every deployment/activation/publication request is rejected. |
| `target_environment` | enum | `none` | One of `none`, `staging`, or `production`. |

Trigger release pipelines from CircleCI's manual pipeline trigger surface and supply only the parameters needed for that release. Do not place secret values in pipeline parameters.

### Required restricted contexts

Create and restrict these CircleCI contexts before enabling release workflows:

**`ci-readonly`**

- Must not contain a GitHub write token, deploy token, or other repository-mutation credential.
- For signed production tag verification, set `TRUSTED_RELEASE_SIGNER_FINGERPRINT` and `TRUSTED_RELEASE_SIGNER_PUBLIC_KEY_B64` to the reviewed release-signing public identity. These values are verification material, not private signing credentials.

**`staging-deploy`**

- `FLY_API_TOKEN` — staging-scoped Fly.io credential.
- `FLYCTL_VERSION` — exact approved Fly CLI version; `latest` is rejected.
- `STAGING_FLY_APP=REPLACE_ME` — dedicated staging Fly.io app. Do not point this at the production app.
- `STAGING_HEALTH_URL` — optional explicit staging health endpoint; defaults to the selected Fly app `/health` endpoint.

**`production-deploy`**

- `FLY_API_TOKEN` — production-scoped Fly.io credential.
- `FLYCTL_VERSION` — exact approved Fly CLI version; `latest` is rejected.
- `PRODUCTION_FLY_APP` — optional; defaults to the repository's existing `clearglass-agent-service` app.
- `PRODUCTION_HEALTH_URL` — optional explicit health endpoint.

Restrict the staging and production contexts to the appropriate CircleCI security groups/project controls. Production credentials must never be copied into `ci-readonly`.

### GitHub automation boundary

CircleCI validates `.github/workflows/**`, YAML syntax, repository workflow governance, and immutable action pinning. It does **not** trigger, rerun, unblock, cancel, approve, or modify GitHub Actions and it does not auto-merge pull requests. Any future GitHub write integration requires a separately approved GitHub App/token scope, a new explicit pipeline parameter defaulting to `false`, and an independent review of the affected repository rules and environments.

### Frontend animations and agents

The frontend/animation job builds deterministic assets, syntax-checks browser JavaScript, runs a local static smoke test, and stores a commit-addressed archive plus SHA-256 evidence. It does not publish the site.

`deploy_animations=true` is intentionally rejected until `REPLACE_ME_ANIMATION_DEPLOY_ADAPTER` is replaced with a reviewed deployment path that does not bypass GitHub Pages/repository protections.

The agent job imports and tests the FastAPI service locally, verifies `/health`, OpenAPI schema availability, authenticated/unauthenticated permission boundaries, and extended sandbox behavior when requested. Autonomous activation is not performed.

`enable_agents=true` is intentionally rejected until `REPLACE_ME_AGENT_ACTIVATION_ADAPTER` and an enforceable runtime rate-limit policy are implemented and reviewed.

### Dependency and secret gates

- Node uses `npm ci` with the committed `package-lock.json`.
- The deployed agent service requires exact `==` pins in `services/clearglass_agent_service/requirements.txt`.
- Root Python validation follows the repository's existing `requirements.txt` constraint plus `pyproject.toml` test-extra installation contract; the pipeline records SHA-256 hashes of dependency inputs for evidence.
- `npm audit` high/critical findings and all `pip-audit` findings block deployment unless the exact advisory identifier is reviewed in `scripts/ci/security-allowlist.txt`.
- Changed text/code files are scanned with `detect-secrets`; any candidate fails closed and must be investigated rather than silently suppressed in CI.

### Immutable deployment and evidence

Fly releases use a commit-addressed image tag (`sha-$CIRCLE_SHA1`) and resolve it to a registry digest before deployment. A previously created commit image is reused rather than overwritten. Before mutation, the pipeline records the currently deployed image so rollback is possible. Deployment evidence is stored under `deploy-evidence/` as CircleCI artifacts.

Post-deploy verification requires:

1. the running Fly image to resolve to the digest recorded by the pipeline;
2. 20/20 successful `/health` requests (synthetic error-rate guardrail of 0%);
3. the protected `/policy` endpoint to fail closed when called without credentials; and
4. for production, the public ClearGlass homepage to return HTTP 200 and expected brand content.

A deployment is not considered successful until these checks pass.

### Rollback procedure

**Staging:** deployment or post-deploy verification failure automatically redeploys the previously recorded immutable image and verifies `/health`. The rollback result is written to the deployment evidence.

**Production:** post-deploy failure does not silently mutate production again. CircleCI records the exact rollback command and prior image in the production deployment artifacts. After incident review and approval, run the same release workspace with the `production-deploy` context and execute:

```bash
bash scripts/ci/fly_rollback.sh production
```

The script reads `deploy-evidence/production-previous-image.txt`, redeploys that exact image, verifies `/health`, and records the rollback result. Do not substitute an unreviewed tag or `latest` image.

No rollback procedure rotates secrets, changes repository permissions, alters organization settings, deletes data, or bypasses a protected environment.

## Repository Safety

- No credentials or private API keys belong in source control.
- Production secrets must remain in approved external secret stores or platform configuration.
- Public OSINT and cybersecurity functions are defensive, lawful, and evidence-oriented.
- Counter-UAS material in this repository is a component/research area; it is **not** the identity or primary purpose of this repository.

## Company

**ClearGlass Inc.**  
Ontario, Canada  
https://www.clearglassinc.com

© 2026 ClearGlass Inc. All rights reserved except where a file or third-party component states otherwise.
