"""Google OAuth/OIDC boundary; the application identifies accounts by verified subject only."""

from __future__ import annotations

import base64
import hashlib
import math
import secrets
import time
from dataclasses import dataclass
from typing import Callable, Protocol
from urllib.parse import urlencode

import httpx
import jwt

from .errors import AppError

READ_SCOPE = "https://www.googleapis.com/auth/youtube.readonly"
WRITE_SCOPE = "https://www.googleapis.com/auth/youtube"
TOKEN_URL = "https://oauth2.googleapis.com/token"
JWKS_URL = "https://www.googleapis.com/oauth2/v3/certs"


@dataclass(frozen=True)
class GoogleIdentity:
    sub: str
    tokens: dict


class IdentityProvider(Protocol):
    def authorization_url(
        self,
        state: str,
        nonce: str,
        verifier: str,
        write: bool = True,
    ) -> str: ...

    async def exchange(self, code: str, verifier: str, nonce: str) -> GoogleIdentity: ...

    async def refresh(self, refresh_token: str) -> dict: ...

    async def revoke(self, refresh_token: str) -> None: ...


class GoogleIdentityProvider:
    def __init__(
        self,
        client: httpx.AsyncClient,
        client_id: str,
        client_secret: str,
        redirect_uri: str,
        clock: Callable[[], float] | None = None,
    ):
        self.client = client
        self.client_id = client_id
        self.client_secret = client_secret
        self.redirect_uri = redirect_uri
        self.clock = clock or time.time

    def authorization_url(
        self,
        state: str,
        nonce: str,
        verifier: str,
        write: bool = True,
    ) -> str:
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
        scopes = ["openid", READ_SCOPE]
        if write:
            scopes.append(WRITE_SCOPE)
        return "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(
            {
                "client_id": self.client_id,
                "redirect_uri": self.redirect_uri,
                "response_type": "code",
                "scope": " ".join(scopes),
                "state": state,
                "nonce": nonce,
                "code_challenge_method": "S256",
                "code_challenge": challenge.rstrip(b"=").decode("ascii"),
                "access_type": "offline",
                "prompt": "consent",
                "include_granted_scopes": "true",
            }
        )

    async def exchange(self, code: str, verifier: str, nonce: str) -> GoogleIdentity:
        payload = await self._token_request(
            {
                "grant_type": "authorization_code",
                "code": code,
                "code_verifier": verifier,
                "redirect_uri": self.redirect_uri,
            }
        )
        sub = await self._verified_subject(payload.get("id_token"), nonce)
        return GoogleIdentity(sub=sub, tokens=self._credentials(payload))

    async def refresh(self, refresh_token: str) -> dict:
        payload = await self._token_request(
            {
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
            }
        )
        return self._credentials(payload)

    async def revoke(self, refresh_token: str) -> None:
        try:
            response = await self.client.post(
                "https://oauth2.googleapis.com/revoke",
                data={"token": refresh_token},
            )
        except httpx.RequestError:
            raise AppError(
                "identity_provider_unavailable", "Google could not be reached.", 502
            ) from None
        if not response.is_success:
            raise AppError(
                "identity_provider_error", "Google authorization could not be revoked.", 502
            )

    async def _token_request(self, fields: dict) -> dict:
        try:
            response = await self.client.post(
                TOKEN_URL,
                data={
                    **fields,
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                },
            )
            payload = response.json()
        except (httpx.RequestError, ValueError):
            raise AppError("identity_provider_error", "Google authorization failed.", 502) from None
        if isinstance(payload, dict) and payload.get("error") == "invalid_grant":
            raise AppError("reauthorization_required", "Google authorization must be renewed.", 401)
        if not response.is_success or not isinstance(payload, dict) or payload.get("error"):
            raise AppError("identity_provider_error", "Google authorization failed.", 502)
        return payload

    def _credentials(self, payload: dict) -> dict:
        try:
            access_token = payload["access_token"]
            expires_in = float(payload["expires_in"])
            scope = payload.get("scope", "")
            if (
                not isinstance(access_token, str)
                or not access_token
                or not math.isfinite(expires_in)
                or expires_in <= 0
                or not isinstance(scope, str)
            ):
                raise ValueError
            result = {
                "access_token": access_token,
                "expires_at": self.clock() + expires_in,
                "scope": scope,
            }
            if payload.get("refresh_token"):
                if not isinstance(payload["refresh_token"], str):
                    raise ValueError
                result["refresh_token"] = payload["refresh_token"]
            return result
        except (KeyError, TypeError, ValueError, OverflowError):
            raise AppError(
                "identity_provider_error", "Google returned invalid credentials.", 502
            ) from None

    async def _verified_subject(self, token: str, nonce: str) -> str:
        try:
            header = jwt.get_unverified_header(token)
            if header.get("alg") != "RS256" or not isinstance(header.get("kid"), str):
                raise ValueError
            response = await self.client.get(JWKS_URL)
            response.raise_for_status()
            jwks = response.json()
            matching = [key for key in jwks["keys"] if key.get("kid") == header["kid"]]
            if len(matching) != 1:
                raise ValueError
            key = jwt.PyJWK.from_dict(matching[0], algorithm="RS256").key
            claims = jwt.decode(
                token,
                key,
                algorithms=["RS256"],
                audience=self.client_id,
                issuer=["https://accounts.google.com", "accounts.google.com"],
                options={
                    "require": ["iss", "aud", "exp", "sub", "nonce"],
                    "verify_exp": False,
                    "verify_iat": False,
                    "verify_nbf": False,
                },
            )
            expiry = claims["exp"]
            if (
                isinstance(expiry, bool)
                or not isinstance(expiry, (int, float))
                or not math.isfinite(expiry)
                or expiry <= self.clock()
            ):
                raise ValueError
            if "nbf" in claims and (
                not isinstance(claims["nbf"], (int, float)) or claims["nbf"] > self.clock()
            ):
                raise ValueError
            if (
                not isinstance(claims["nonce"], str)
                or not nonce
                or not secrets.compare_digest(claims["nonce"], nonce)
            ):
                raise ValueError
            if not isinstance(claims["sub"], str) or not claims["sub"]:
                raise ValueError
            return claims["sub"]
        except (
            jwt.PyJWTError,
            httpx.HTTPError,
            ValueError,
            TypeError,
            KeyError,
            AttributeError,
            OverflowError,
        ):
            raise AppError(
                "identity_verification_failed",
                "Google identity could not be verified.",
                401,
            ) from None
