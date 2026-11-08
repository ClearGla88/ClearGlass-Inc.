// SHADOW CANDIDATE. Evaluated on every request and logged, never enforced.
// Proposal: require a human approval before an agent writes long-term memory,
// to close the memory-poisoning path. Read the divergence report
// (GET /api/v1/policies/shadow-report) before promoting. Promotion means moving
// this file up one directory in a reviewed pull request.

@id("shadow.long-term-memory-writes-need-approval")
forbid (principal is Agent, action, resource is Tool)
when { resource.key == "memory.propose" }
unless { context.approved_by_human };
