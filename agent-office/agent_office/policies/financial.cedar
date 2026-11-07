// Money moves only with a human approval, and never above the amount the
// human approved.

@id("finance.within-human-approved-amount")
forbid (principal is Agent, action == Action::"execute", resource is Tool)
when { resource.category == "finance" || context.amount_cents > 0 }
unless { context.approved_by_human && context.amount_cents <= context.approved_amount_cents };
