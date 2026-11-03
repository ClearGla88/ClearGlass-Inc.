---
name: Security baseline
about: Establish and document a secure repository baseline
title: "security: establish baseline"
labels: []
assignees: []
---

## Objective
Establish a secure baseline without exposing sensitive information.

## Scope
- Add `SECURITY.md`
- Add `CODEOWNERS`
- Recommend secret scanning and dependency auditing
- Audit GitHub Actions permissions
- Identify hardcoded secrets, unsafe workflow patterns, and excessive token permissions
- Recommend secret-manager or OIDC-based authentication where applicable

## Acceptance criteria
- Changes delivered through a pull request
- Default GitHub Actions permissions are read-only unless a job explicitly requires more
- Third-party Actions are pinned to full commit SHAs where practical
- No secrets, internal endpoints, or exploit details are committed
- Findings include severity, evidence, remediation, and rollback plan
