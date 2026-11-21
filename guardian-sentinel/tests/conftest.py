"""Every test is offline and deterministic: fixed clock, fake channels and a
fake dispatcher. Nothing touches a real sensor, network or emergency service."""

from __future__ import annotations

import os
import sys

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
PKG_ROOT = os.path.dirname(TESTS_DIR)
for _path in (PKG_ROOT, TESTS_DIR):
    if _path not in sys.path:
        sys.path.insert(0, _path)
