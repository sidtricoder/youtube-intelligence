"""Per-account Google credential lifecycle, isolated from MCP protocol and tool services."""

import asyncio
import time

from .errors import AppError
from .identity import WRITE_SCOPE, IdentityProvider
from .observability import event
from .security.protocols import TokenStore
from .tenancy import ScopedStore


class Credentials:
    def __init__(self, store: TokenStore, identity_provider: IdentityProvider):
        self.store, self.idp = store, identity_provider
        self._locks: dict[str, asyncio.Lock] = {}
        self._workflow_locks: dict[str, asyncio.Lock] = {}

    def workflow_lock(self, user_id: str) -> asyncio.Lock:
        return self._workflow_locks.setdefault(user_id, asyncio.Lock())

    def invalidate(self, user_id: str, generation: int | None = None) -> None:
        self.store.revoke_user(user_id, expected_generation=generation)
        event("auth.user_revoked")

    async def access(self, user_id: str) -> str:
        async with self._locks.setdefault(user_id, asyncio.Lock()):
            generation = self.store.generation(user_id)
            tokens = self.store.google(user_id)
            if not tokens:
                self.invalidate(user_id, generation)
                raise AppError("reauthorization_required", "Sign in with Google again", 401)
            if tokens.get("expires_at", 0) <= time.time() + 60:
                if not tokens.get("refresh_token"):
                    self.invalidate(user_id, generation)
                    raise AppError("reauthorization_required", "Sign in with Google again", 401)
                event("google.refresh_started")
                try:
                    refreshed = await self.idp.refresh(tokens["refresh_token"])
                except AppError as exc:
                    event(
                        "google.refresh_failed",
                        warning=True,
                        error_code=exc.code,
                        status=exc.status,
                    )
                    if exc.status == 401:
                        self.invalidate(user_id, generation)
                    raise
                previous = dict(tokens)
                tokens.update({k: v for k, v in refreshed.items() if v is not None and v != ""})
                if not self.store.save_google_if_current(user_id, previous, tokens, generation):
                    raise AppError(
                        "reauthorization_required",
                        "Google authorization changed; retry sign-in",
                        401,
                    )
                event("google.refresh_completed")
            return tokens["access_token"]

    def require_write(self, user_id: str) -> None:
        tokens = self.store.google(user_id) or {}
        if WRITE_SCOPE not in tokens.get("scope", "").split():
            raise AppError(
                "write_scope_required", "Enable playlist writes on your approval page", 403
            )

    async def disconnect(self, user_id: str) -> dict:
        async with self.workflow_lock(user_id):
            async with self._locks.setdefault(user_id, asyncio.Lock()):
                tokens = self.store.google(user_id) or {}
                generation = self.store.generation(user_id)
                # Revoke local authority before the remote request, even if Google is unreachable.
                self.invalidate(user_id, generation)
                ScopedStore(self.store.raw, user_id).delete_prefix("")
                revoked = True
                try:
                    if tokens.get("refresh_token"):
                        await self.idp.revoke(tokens["refresh_token"])
                except AppError:
                    revoked = False
                event("account.disconnected", outcome="revoked" if revoked else "local_only")
                return {
                    "status": "disconnected",
                    "google_grant_revoked": revoked,
                    "notice": "If Google was unreachable, remove access in your Google Account permissions."
                    if not revoked
                    else "Your tokens, drafts and personal cache were deleted.",
                }
