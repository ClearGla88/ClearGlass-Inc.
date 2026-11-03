---
name: CI reliability
about: Improve pull-request validation and actionable CI failures
title: "ci: improve validation reliability"
labels: []
assignees: []
---

## Objective
Create a reliable CI workflow that validates every pull request.

## Scope
- Linting
- Static analysis
- Type checking where applicable
- Unit and integration tests
- Build verification
- Dependency vulnerability scanning
- Clear, actionable failure output

## Acceptance criteria
- Workflow uses least-privilege permissions
- CI validation is separate from deployment
- No secrets are printed to logs
- Failures identify the exact command, file, and likely cause
- Deployment requires explicit human approval
