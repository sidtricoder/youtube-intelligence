"""OAuth authorization server backed by the MCP SDK's request validation and routes."""

import re
import secrets
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    AuthorizeError,
    RefreshToken,
    RegistrationError,
    TokenError,
)
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken
from sqlalchemy import select

from .store import digest


class VerifiedAccessToken(AccessToken):
    user_id: str
    family: str


class BoundRefreshToken(RefreshToken):
    family: str


def valid_redirect(uri):
    parsed = urlsplit(str(uri))
    return bool(
        parsed.hostname
        and not parsed.fragment
        and not parsed.username
        and not parsed.password
        and "*" not in str(uri)
        and (
            parsed.scheme == "https"
            or (parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1", "::1"})
        )
    )


class AuthServer:
    def __init__(self, store, issuer):
        self.store = store
        self.issuer = issuer.rstrip("/")
        self.resource = self.issuer + "/mcp/"

    async def get_client(self, client_id):
        data = self.store._get(self.store.oauth_clients, client_id)
        return OAuthClientInformationFull.model_validate(data) if data else None

    async def register_client(self, client_info):
        if not client_info.redirect_uris or not all(
            valid_redirect(uri) for uri in client_info.redirect_uris
        ):
            raise RegistrationError(
                "invalid_redirect_uri",
                "Use HTTPS or a loopback redirect URI without fragments or userinfo",
            )
        if client_info.token_endpoint_auth_method not in {
            "none",
            "client_secret_post",
            "client_secret_basic",
        }:
            raise RegistrationError(
                "invalid_client_metadata", "Unsupported client authentication method"
            )
        self.store._put(
            self.store.oauth_clients,
            client_info.client_id,
            client_info.model_dump(mode="json"),
            365 * 86400,
        )

    async def authorize(self, client, params):
        if not valid_redirect(params.redirect_uri) or str(params.redirect_uri) not in {
            str(uri) for uri in client.redirect_uris or []
        }:
            raise AuthorizeError("invalid_request", "Unregistered redirect URI")
        if params.resource != self.resource:
            raise AuthorizeError("invalid_target", "Exact MCP resource required")
        if not re.fullmatch(r"[A-Za-z0-9_-]{43}", params.code_challenge):
            raise AuthorizeError("invalid_request", "S256 PKCE challenge required")
        transaction = self.store.create_login(
            {"client_id": client.client_id, "params": params.model_dump(mode="json")}
        )
        return self.issuer + "/oauth/start?" + urlencode({"transaction": transaction})

    def complete_login(self, transaction, user_id):
        invalid = None
        with self.store.raw.tx() as db:
            login = self.store._get(
                self.store.login_transactions, digest(transaction), db=db, consume=True
            )
            if not login or "params" not in login:
                invalid = "Login expired or already used"
            else:
                generation = db.execute(
                    select(self.store.users.c.generation).where(
                        self.store.users.c.user_id == user_id
                    )
                ).scalar_one_or_none()
                if generation is None or (
                    "consent_generation" in login
                    and (
                        login.get("consent_user_id") != user_id
                        or login["consent_generation"] != generation
                    )
                ):
                    invalid = "Authorization changed; sign in again"
                else:
                    params = AuthorizationParams.model_validate(login["params"])
                    code = secrets.token_urlsafe(32)
                    data = params.model_dump(mode="json")
                    data.update(
                        client_id=login["client_id"],
                        expires_at=self.store.clock.now() + 120,
                        scopes=params.scopes or [],
                        subject=user_id,
                        grant_generation=generation,
                    )
                    data.pop("state", None)
                    self.store._put(
                        self.store.auth_codes, digest(code), data, 120, user_id=user_id, db=db
                    )
        if invalid:
            raise AuthorizeError("invalid_request", invalid)
        parsed = urlsplit(str(params.redirect_uri))
        query = parse_qsl(parsed.query, keep_blank_values=True) + [("code", code)]
        if params.state is not None:
            query.append(("state", params.state))
        return urlunsplit(parsed._replace(query=urlencode(query)))

    async def load_authorization_code(self, client, authorization_code):
        data = self.store._get(self.store.auth_codes, digest(authorization_code))
        if not data or data["client_id"] != client.client_id:
            return None
        return AuthorizationCode(code=authorization_code, **data)

    def _mint(self, db, client_id, user_id, scopes, family=None):
        family = family or secrets.token_urlsafe(24)
        now = self.store.clock.now()
        access, refresh = secrets.token_urlsafe(32), secrets.token_urlsafe(48)
        common = dict(
            client_id=client_id,
            user_id=user_id,
            subject=user_id,
            scopes=scopes,
            resource=self.resource,
            family=family,
        )
        self.store._put(
            self.store.token_families,
            family,
            {"revoked": False},
            30 * 86400,
            db=db,
            user_id=user_id,
        )
        self.store._put(
            self.store.access_tokens,
            digest(access),
            dict(common, expires_at=int(now + 3600)),
            3600,
            db=db,
            user_id=user_id,
        )
        self.store._put(
            self.store.refresh_tokens,
            digest(refresh),
            dict(common, expires_at=int(now + 30 * 86400), used=False),
            30 * 86400,
            db=db,
            user_id=user_id,
        )
        return OAuthToken(
            access_token=access,
            token_type="Bearer",
            expires_in=3600,
            refresh_token=refresh,
            scope=" ".join(scopes),
        )

    async def exchange_authorization_code(self, client, authorization_code):
        result = None
        with self.store.raw.tx() as db:
            data = self.store._get(
                self.store.auth_codes, digest(authorization_code.code), db, consume=True
            )
            if data and data["client_id"] == client.client_id and data["resource"] == self.resource:
                generation = db.execute(
                    select(self.store.users.c.generation).where(
                        self.store.users.c.user_id == data["subject"]
                    )
                ).scalar_one_or_none()
                if generation is not None and generation == data.get("grant_generation"):
                    result = self._mint(db, client.client_id, data["subject"], data["scopes"])
        if result is None:
            raise TokenError("invalid_grant", "Code expired, used, or authorization changed")
        return result

    async def load_refresh_token(self, client, refresh_token):
        data = self.store._get(self.store.refresh_tokens, digest(refresh_token))
        if not data or data["client_id"] != client.client_id:
            return None
        return BoundRefreshToken(token=refresh_token, **data)

    async def exchange_refresh_token(self, client, refresh_token, scopes):
        invalid = False
        result = None
        with self.store.raw.tx() as db:
            data = self.store._get(self.store.refresh_tokens, digest(refresh_token.token), db)
            if not data or data["client_id"] != client.client_id:
                invalid = True
            else:
                family = self.store._get(self.store.token_families, data["family"], db)
                if data["used"] or not family or family["revoked"]:
                    self.store._put(
                        self.store.token_families,
                        data["family"],
                        {"revoked": True},
                        30 * 86400,
                        db=db,
                        user_id=data["user_id"],
                    )
                    invalid = True
                elif data["resource"] != self.resource or not set(scopes).issubset(data["scopes"]):
                    invalid = True
                else:
                    data["used"] = True
                    self.store._put(
                        self.store.refresh_tokens,
                        digest(refresh_token.token),
                        data,
                        max(0, data["expires_at"] - self.store.clock.now()),
                        db=db,
                        user_id=data["user_id"],
                    )
                    result = self._mint(
                        db, client.client_id, data["user_id"], scopes, data["family"]
                    )
        # Raise after transaction commits so reuse revocation cannot be rolled back.
        if invalid:
            raise TokenError("invalid_grant", "Refresh token invalid or reused")
        return result

    async def load_access_token(self, token):
        with self.store.raw.tx() as db:
            data = self.store._get(self.store.access_tokens, digest(token), db)
            if (
                not data
                or data["resource"] != self.resource
                or data["expires_at"] <= self.store.clock.now()
            ):
                return None
            family = self.store._get(self.store.token_families, data["family"], db)
            if not family or family["revoked"]:
                return None
            return VerifiedAccessToken(token=token, **data)

    async def revoke_token(self, token):
        family = getattr(token, "family", None)
        if family:
            self.store._put(
                self.store.token_families,
                family,
                {"revoked": True},
                30 * 86400,
                user_id=getattr(token, "user_id", token.subject),
            )
