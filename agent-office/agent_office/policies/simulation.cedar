// Simulation missions run against sandbox tools only. Even a human approval
// cannot let a simulation reach a production system.

@id("simulation.never-touches-production")
forbid (principal is Agent, action, resource is Tool)
when { context.mission_mode == "simulation" && resource.environment == "production" };
