"""Revenue Floor: a governed sales path from an authorized lead to a verified payment.

- ``rules``: pure rules (stages, schemas, consent, content, qualification, provider records).
- ``catalog``: loads and validates ``config/revenue.json``.
- ``compose``: deterministic message templates and execution tickets.
- ``skills``: the handlers revenue agents run through the governed executor.
- ``desk``: ``RevenueDesk``, the service the API and console drive (``Office.revenue``).

The office never contacts a provider. Approved external actions are released as
tickets a person executes through the connector's own interface; see
docs/REVENUE_OPERATIONS.md.
"""
