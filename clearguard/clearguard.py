#!/usr/bin/env python3
"""ClearGuard command-line entry point.

    python3 clearguard.py startup
    python3 clearguard.py say "Guardian, what is unavailable?"
    python3 clearguard.py simulate examples/scenario_design_walkthrough.json

See README.md. Requires Python 3.10 or newer; no third-party packages.
"""

import sys

if sys.version_info < (3, 10):
    sys.exit("ClearGuard requires Python 3.10 or newer.")

from clearguard_core.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
