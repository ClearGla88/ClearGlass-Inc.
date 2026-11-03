# ClearGlass-Inc Engineering Standards

## Purpose
These instructions apply to all code, documentation, workflows, and pull requests in this repository.

## Security
- Never hardcode secrets, API keys, tokens, credentials, private URLs, or internal hostnames.
- Validate and sanitize all external input.
- Use parameterized queries and safe file handling.
- Apply least-privilege permissions to GitHub Actions and deployed services.
- Flag any suspected secret exposure immediately and recommend rotation.

## Code quality
- Keep functions focused and appropriately sized.
- Use clear, intention-revealing names.
- Handle errors explicitly and consistently.
- Remove dead code and unused dependencies.
- Preserve existing architecture unless a change is explicitly approved.

## Testing
- Add tests for new behavior, bug fixes, security controls, and critical paths.
- Cover edge cases, failure modes, configuration, and authorization boundaries.
- Report the exact validation commands and results in every pull request.

## Documentation
- Keep documentation factual, current, concise, and non-promotional.
- Do not add unsupported claims about capabilities, customers, performance, or security posture.
- Update relevant documentation whenever behavior, setup, architecture, or workflows change.

## Pull requests
- Use a feature branch.
- Keep changes small and reversible.
- Include rationale, validation evidence, security review, risk, rollback plan, and follow-ups.
- Do not push directly to the default branch.
