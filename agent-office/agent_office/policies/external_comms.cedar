// Nothing leaves the company without a human approval: publishing, email,
// or any request the agent marks as external.

@id("comms.external-needs-human-approval")
forbid (principal is Agent, action == Action::"execute", resource is Tool)
when { resource.category == "comms" || context.external }
unless { context.approved_by_human };
