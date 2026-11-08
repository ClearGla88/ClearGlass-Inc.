"""API authentication, role checks, and rate limits.

Roles:
- ``operator``: the human who approves, hires, edits grants, and pulls the
  emergency stop. Token: ``OFFICE_OPERATOR_TOKEN``.
- ``viewer``: read-only access to every view. Token: ``OFFICE_VIEWER_TOKEN``.

Modes:
- ``OFFICE_ENV=development`` with no tokens set: open local mode. Requests act
  as the configured operator and every response carries
  ``X-Office-Auth: development-open``. Bind to 127.0.0.1 only.
- ``OFFICE_ENV=production``: ``OFFICE_OPERATOR_TOKEN`` is required. Without it
  the app refuses to start (fail closed).

Tokens are compared in constant time. OAuth 2.0 / OIDC sign-in is the
production target (docs/ROADMAP.md, week 3); the bearer tokens are its
stand-in, not a replacement.
"""

from __future__ import annotations

import hmac
import os
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field

from fastapi import HTTPException, Request, status

from agent_core.approvals import Principal

MIN_TOKEN_CHARS = 32


@dataclass(frozen=True)
class Settings:
    env: str = "development"
    operator_token: str | None = None
    viewer_token: str | None = None
    operator_id: str = "operator.founder"
    cors_origins: tuple[str, ...] = ()
    mutations_per_minute: int = 30

    @property
    def open_mode(self) -> bool:
        return self.env != "production" and not self.operator_token

    @classmethod
    def from_env(cls, operator_id: str) -> Settings:
        origins = tuple(o.strip() for o in os.environ.get("OFFICE_CORS_ORIGINS", "").split(",") if o.strip())
        return cls(
            env=os.environ.get("OFFICE_ENV", "development").lower(),
            operator_token=os.environ.get("OFFICE_OPERATOR_TOKEN") or None,
            viewer_token=os.environ.get("OFFICE_VIEWER_TOKEN") or None,
            operator_id=operator_id,
            cors_origins=origins,
            mutations_per_minute=int(os.environ.get("OFFICE_MUTATIONS_PER_MINUTE", "30")),
        )

    def validate(self) -> None:
        if self.env not in ("development", "production", "test"):
            raise RuntimeError(f"OFFICE_ENV must be development, production, or test (got {self.env!r})")
        if self.env == "production":
            if not self.operator_token:
                raise RuntimeError("OFFICE_ENV=production requires OFFICE_OPERATOR_TOKEN; refusing to start")
            for name, tok in (
                ("OFFICE_OPERATOR_TOKEN", self.operator_token),
                ("OFFICE_VIEWER_TOKEN", self.viewer_token),
            ):
                if tok is not None and len(tok) < MIN_TOKEN_CHARS:
                    raise RuntimeError(f"{name} must be at least {MIN_TOKEN_CHARS} characters")
            if "*" in self.cors_origins:
                raise RuntimeError("wildcard CORS origins are not allowed in production")


def _bearer(request: Request) -> str | None:
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    return token.strip() if scheme.lower() == "bearer" and token.strip() else None


def _eq(a: str | None, b: str | None) -> bool:
    return bool(a and b) and hmac.compare_digest(a.encode(), b.encode())  # type: ignore[union-attr]


def principal_for(request: Request) -> Principal:
    settings: Settings = request.app.state.settings
    if settings.open_mode:
        return Principal(settings.operator_id, "human", "operator")
    token = _bearer(request)
    if token is None:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "missing bearer token", headers={"WWW-Authenticate": "Bearer"}
        )
    if _eq(token, settings.operator_token):
        return Principal(settings.operator_id, "human", "operator")
    if _eq(token, settings.viewer_token):
        return Principal("viewer", "human", "viewer")
    raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid token", headers={"WWW-Authenticate": "Bearer"})


def require_viewer(request: Request) -> Principal:
    return principal_for(request)


def require_operator(request: Request) -> Principal:
    principal = principal_for(request)
    if principal.role != "operator":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "operator role required")
    request.app.state.limiter.check(request)
    return principal


@dataclass
class RateLimiter:
    per_minute: int
    _hits: dict[str, deque[float]] = field(default_factory=lambda: defaultdict(deque))
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def check(self, request: Request) -> None:
        key = request.client.host if request.client else "unknown"
        now = time.monotonic()
        with self._lock:
            hits = self._hits[key]
            while hits and now - hits[0] > 60:
                hits.popleft()
            if len(hits) >= self.per_minute:
                raise HTTPException(
                    status.HTTP_429_TOO_MANY_REQUESTS, "rate limit exceeded", headers={"Retry-After": "60"}
                )
            hits.append(now)
