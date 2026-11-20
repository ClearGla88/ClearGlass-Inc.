// Base policy set. Cedar denies by default: a request that no permit matches
// is refused, and any forbid overrides every permit.
//
// `context.approved_by_human` is true only when the gate holds a human
// approval bound to this exact request (agent, tool, action, payload, task).

@id("base.read-write-non-production")
permit (principal is Agent, action in [Action::"read", Action::"write"], resource is Tool)
when { resource.environment != "production" };

@id("base.execute-low-medium")
permit (principal is Agent, action == Action::"execute", resource is Tool)
when { context.risk == "low" || context.risk == "medium" };

@id("base.execute-high-critical-with-human-approval")
permit (principal is Agent, action == Action::"execute", resource is Tool)
when { (context.risk == "high" || context.risk == "critical") && context.approved_by_human };

@id("base.inactive-agents-cannot-act")
forbid (principal is Agent, action, resource is Tool)
unless { principal.status == "active" };

@id("base.no-governance-tampering")
forbid (principal is Agent, action, resource is Tool)
when { resource.category == "governance" };

@id("base.production-requires-human-approval")
forbid (principal is Agent, action, resource is Tool)
when { resource.environment == "production" }
unless { action == Action::"execute" && context.approved_by_human };

@id("base.critical-requires-capable-agent")
forbid (principal is Agent, action == Action::"execute", resource is Tool)
when { context.risk == "critical" }
unless { principal.can_request_critical };
