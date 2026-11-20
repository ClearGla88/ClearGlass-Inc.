# packages/ui

Design tokens for the ClearGlass Agent Office console.

`tokens.json` is the source of truth. `apps/web/src/app/globals.css` declares each one as a CSS custom property
(`--cg-<group>-<name>`, colors as `--cg-<name>`), and `tests/test_ui_tokens.py` fails when the two drift.

The tokens are not built into a separate npm package: the console is the only consumer, and Next.js bundles its CSS
from inside `apps/web`. If a second web app appears, publish this folder as a workspace package then.
