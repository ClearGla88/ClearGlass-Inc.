// Critical action protocol for deployments: a human approval alone is not
// enough. The request must carry a rollback plan, and the test evidence must
// be a completed, passing sandbox check (the gate verifies that reference).

@id("deployment.needs-rollback-evidence-and-approval")
forbid (principal is Agent, action == Action::"execute", resource is Tool)
when { resource.category == "deployment" }
unless { context.approved_by_human && context.has_rollback_plan && context.has_test_evidence };
