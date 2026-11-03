"""Immutable identity and credentials bound to a single request."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from .security.protocols import QuotaPolicy


@dataclass(frozen=True)
class UserContext:
    user_id: str
    credentials: Callable[[], Awaitable[str]]
    quota: QuotaPolicy
    generation: int | None = None

    def __post_init__(self):
        if not isinstance(self.user_id, str) or not self.user_id.strip():
            raise ValueError("Nonempty user_id required")
        if not callable(self.credentials):
            raise ValueError("Credentials accessor required")


@dataclass(frozen=True)
class AnonymousContext:
    client_ip: str
    quota: QuotaPolicy
