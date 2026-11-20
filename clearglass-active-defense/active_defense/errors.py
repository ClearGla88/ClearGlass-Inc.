"""Domain errors. Each carries the HTTP status the API returns for it."""

from __future__ import annotations


class DomainError(Exception):
    status = 400

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class Rejected(DomainError):
    """An ingestion request was refused. The status is chosen per reason."""

    def __init__(self, status: int, reason: str) -> None:
        super().__init__(reason)
        self.status = status


class NotFound(DomainError):
    status = 404


class Conflict(DomainError):
    status = 409


class Forbidden(DomainError):
    status = 403


class Invalid(DomainError):
    status = 422
