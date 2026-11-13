#!/usr/bin/env python3
"""ClearShield command-line entry point.

    python3 clearshield.py init --watch /etc/hosts
    python3 clearshield.py baseline
    python3 clearshield.py scan
    python3 clearshield.py verify
    python3 clearshield.py audio-wav --wav sample.wav

See README.md. Requires Python 3.10 or newer; no third-party packages.
"""

import sys

if sys.version_info < (3, 10):
    sys.exit("ClearShield requires Python 3.10 or newer.")

from clearshield_core.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
