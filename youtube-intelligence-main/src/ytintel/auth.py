"""Google OAuth authorization code flow with PKCE and browser-bound single-use state."""

import asyncio
import base64
import hashlib
import secrets
import time
from urllib.parse import urlencode

import httpx

from .errors import AppError

READ_SCOPE = "https://www.googleapis.com/auth/youtube.readonly"
WRITE_SCOPE = "https://www.googleapis.com/auth/youtube.force-ssl"
TOKEN_URL = "https://oauth2.googleapis.com/token"


class OAuth:
    def __init__(self, store, client, client_id, client_secret, redirect_uri):
        self.store, self.client = store, client
        self.client_id, self.client_secret, self.redirect_uri = (
            client_id,
            client_secret,
            redirect_uri,
        )
        self.lock = asyncio.Lock()
        self.account_lock = asyncio.Lock()

    def start(self, write=False):
        if not self.client_id or not self.client_secret:
            raise AppError(
                "oauth_not_configured", "Configure Google OAuth client ID and secret", 503
            )
        state, binding, verifier = [secrets.token_urlsafe(32) for _ in range(3)]
        challenge = (
            base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
            .rstrip(b"=")
            .decode()
        )
        self.store.put(
            "oauth:state:" + state,
            {"binding": binding, "verifier": verifier, "write": write},
            ttl=600,
        )
        query = urlencode(
            dict(
                client_id=self.client_id,
                redirect_uri=self.redirect_uri,
                response_type="code",
                scope=WRITE_SCOPE if write else READ_SCOPE,
                access_type="offline",
                prompt="consent",
                state=state,
                code_challenge=challenge,
                code_challenge_method="S256",
            )
        )
        return "https://accounts.google.com/o/oauth2/v2/auth?" + query, state, binding

    def consume_state(self, state, binding):
        data = self.store.take("oauth:state:" + state)
        if not data or not secrets.compare_digest(data["binding"].encode(), binding.encode()):
            raise AppError("invalid_oauth_state", "Expired, reused or mismatched OAuth state", 400)
        return data

    async def exchange(self, code, state, binding):
        async with self.account_lock:
            await self._exchange(code, state, binding)

    async def _exchange(self, code, state, binding):
        data = self.consume_state(state, binding)
        payload = await self._token(
            dict(
                code=code,
                code_verifier=data["verifier"],
                redirect_uri=self.redirect_uri,
                grant_type="authorization_code",
            )
        )
        # Never mix refresh tokens across independent authorizations/accounts.
        # Re-consent requests a fresh refresh token; missing one means authorize again on expiry.
        for prefix in ("cache:", "draft:"):
            self.store.delete_prefix(prefix)
        payload["expires_at"] = time.time() + payload.get("expires_in", 3600)
        payload["write"] = WRITE_SCOPE in payload.get("scope", "").split()
        self.store.put("oauth:tokens", payload, ttl=30 * 86400)

    async def _token(self, data):
        try:
            r = await self.client.post(
                TOKEN_URL,
                data={**data, "client_id": self.client_id, "client_secret": self.client_secret},
            )
        except httpx.RequestError:
            raise AppError(
                "oauth_unavailable", "Google authorization service unavailable", 503
            ) from None
        if r.status_code != 200:
            raise AppError(
                "reauthorization_required",
                "Authorize Google again; the token was expired or revoked",
                401,
            )
        return r.json()

    async def access_token(self):
        async with self.lock:
            payload = self.store.get("oauth:tokens")
            if not payload:
                raise AppError(
                    "reauthorization_required", "Connect Google from the owner page", 401
                )
            if payload.get("expires_at", 0) < time.time() + 60:
                if not payload.get("refresh_token"):
                    raise AppError(
                        "reauthorization_required",
                        "Refresh token unavailable; authorize again",
                        401,
                    )
                fresh = await self._token(
                    dict(refresh_token=payload["refresh_token"], grant_type="refresh_token")
                )
                payload.update(fresh)
                payload["expires_at"] = time.time() + fresh.get("expires_in", 3600)
                self.store.put("oauth:tokens", payload, ttl=30 * 86400)
            return payload["access_token"]

    def require_write(self):
        if not (self.store.get("oauth:tokens") or {}).get("write"):
            raise AppError(
                "write_scope_required", "Connect Google with playlist-write consent first", 403
            )

    async def disconnect(self):
        async with self.account_lock:
            await self._disconnect()

    async def _disconnect(self):
        payload = self.store.get("oauth:tokens") or {}
        token = payload.get("refresh_token") or payload.get("access_token")
        if token:
            try:
                r = await self.client.post(
                    "https://oauth2.googleapis.com/revoke", data={"token": token}
                )
                if r.status_code not in (200, 400):
                    raise AppError(
                        "revoke_failed", "Revoke access in your Google account before retrying", 503
                    )
            except httpx.RequestError:
                raise AppError(
                    "revoke_failed", "Google unavailable; retry disconnect", 503
                ) from None
        for prefix in ("oauth:", "cache:", "draft:"):
            self.store.delete_prefix(prefix)
