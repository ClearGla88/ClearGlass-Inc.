# ClearGlass Inc. — Technology Radar

**Owner:** Architecture · **Cadence:** reviewed weekly with the Architect
Checklist · **Last updated:** 2026-08-14

The radar records how we intend to treat specific technologies, not a ranking of
their quality. Each entry sits in one ring:

| Ring | Meaning |
|------|---------|
| **Adopt** | Default choice; use it unless there's a specific reason not to. |
| **Trial** | Worth a real project on non-critical paths, with a rollback plan. |
| **Assess** | Explore in a sandbox / spike; understand the fit before committing. |
| **Hold** | Not for new work; migrate away or avoid unless already committed. |

> Placement is a governance decision. Nothing moves to **Adopt** without a
> sandbox evaluation and — for anything that touches the commerce OS money paths —
> an approval per `clearglass-commerce/control-plane/app/governance.py`.

---

## Ring: Kubernetes + AI platform maturity

Added 2026-08-14 (Architect Checklist item 4). These entries track how mature
each Kubernetes-for-AI capability is *for us*, i.e. how far we'd trust it in the
ClearGlass estate today — not the upstream project's general maturity.

### Assess

- **KServe / model-serving CRDs on K8s** — standardized inference endpoints,
  canary + autoscale-to-zero. Attractive once we run more than one always-on
  model. *Blocker for higher ring:* we have no GPU node pool provisioned yet, so
  this is paper-only until there's hardware to serve on.
- **Kueue (batch/gang scheduling)** — job-level queueing and quota for training /
  eval / benchmark runs. Directly relevant to the accelerator-benchmark work
  (checklist item 2): a fair-share queue is the clean way to run bakeoffs without
  starving other workloads.
- **Dynamic Resource Allocation (DRA) for GPUs** — the successor to the device
  plugin for fine-grained accelerator scheduling (incl. MIG / partitioned GPUs).
  Assess-only: API still stabilizing across K8s releases; revisit when our
  target cluster version lands it as stable.
- **Ray on Kubernetes (KubeRay)** — distributed orchestration for agent fleets /
  parallel eval harnesses. Maps onto the `sentinel/` Agent Mesh target-state
  docs; assess whether the mesh belongs on Ray or stays stdlib-only per its
  current fail-closed design.
- **Inference gateways (vLLM / TGI behind a gateway)** — token-aware routing,
  batching, and rate control in front of self-hosted models. Assess against the
  cost model in checklist item 6 before committing to self-hosting vs. API.

### Trial

- **GPU Operator + node-level isolation** — the baseline that unblocks every
  entry above. *Trial specifically as the substrate for the accelerator bakeoff
  (item 2) and the agent-sandboxing hardening (item 3):* a single, well-isolated
  GPU node pool with namespace-scoped quotas, gVisor/Kata-style runtime isolation
  for agent workloads, and NetworkPolicy egress limits. Keep it off the
  production commerce cluster — pilot on a separate non-prod cluster.
- **Signed-image admission (cosign + policy controller)** — extends the
  supply-chain posture we already enforce in CI (`release-supply-chain.yml`,
  `sigstore/cosign-installer`) down to the cluster: only admit images whose
  provenance we attested. Natural pairing with checklist item 5 (supply-chain +
  agentic risk).

### Hold

- **Cluster-wide privileged agent runtimes** — running tool-using agents with
  host mounts, `privileged: true`, or cluster-admin service accounts. This
  directly contradicts the commerce OS safety model and the agent-sandboxing
  goal (item 3). Not for new work; anything resembling it needs the
  read-only → draft → approval → execute gate in front of it.

---

## Ring: AI coding agents & models

### Assess

- **Kimi K3 (Moonshot, 2.8T open-weight)** — high-priority radar candidate for
  agentic coding, evaluated in a sandbox lane only. Full editorial assessment,
  trial plan, and KPIs in **[`KIMI_K3_TECH_RADAR.md`](./KIMI_K3_TECH_RADAR.md)**.
  Not a default production model until it clears our own bakeoff.

### Adopt

- **CodeQL (semantic SAST)** — already deployed via `.github/workflows/codeql.yml`,
  scanning `python` and `javascript-typescript` (`build-mode: none`) on PR, push,
  and weekly. This is the repo's standing vuln-detection lane. Tuning candidate
  (checklist item 7): raise recall with the `security-extended` query pack, and
  confirm the alert stream is reviewed rather than merely running.

### Assess

- **Complementary SAST (e.g. Semgrep) as a second non-prod lane** — the genuinely
  *new* tool a "trial one vuln-detection tool" item (7) would add, since CodeQL is
  already in place. Assess only where it catches classes CodeQL misses; do not
  duplicate CodeQL's language coverage.

---

## How to change this radar

1. Open a PR that moves the entry and states the evidence (sandbox result, cost
   figure, risk finding) justifying the new ring.
2. For anything touching commerce OS money paths, link the approval.
3. Note the change in the weekly Architect Checklist report under
   `operations/`.
