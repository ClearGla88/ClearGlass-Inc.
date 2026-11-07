"""ClearGlass Agent Office: a governed operating kernel for AI agents.

Agents hold identities, grants and reporting lines. Every tool call they make
passes the nine-stage governance gate in :mod:`agent_office.gate` before it can
have an effect, and every decision lands in the hash-chained ledger in
:mod:`agent_office.audit`.

The entry point for programmatic use is :class:`agent_office.office.Office`.
"""

__version__ = "0.1.0"
