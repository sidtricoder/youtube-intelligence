"""Browser-bound Google login, client consent and per-account draft approval routes."""

import hashlib
import html
import json
import re
import secrets

from fastapi import Request
from fastapi.responses import HTMLResponse, RedirectResponse

from .context import UserContext
from .errors import AppError
from .identity import WRITE_SCOPE
from .tenant_quota import TenantQuota


def install_browser_routes(
    app, *, security, auth, idp, credentials, service_factory, raw, s, issuer
):
    secure = issuer.startswith("https://")

    def binding_name(transaction):
        return "yt_login_" + hashlib.sha256(transaction.encode()).hexdigest()[:16]

    def set_session(response, user_id, generation):
        opaque, _ = security.create_session(user_id, expected_generation=generation)
        response.set_cookie(
            "yt_session",
            opaque,
            max_age=43200,
            httponly=True,
            secure=secure,
            samesite="lax",
            path="/",
        )

    def browser_session(request):
        session = security.session(request.cookies.get("yt_session", ""))
        if not session:
            raise AppError("browser_sign_in_required", "Sign in with Google in this browser", 401)
        return session

    async def csrf_form(request):
        session = browser_session(request)
        if request.headers.get("origin") not in (None, issuer):
            raise AppError("origin_denied", "Request origin refused", 403)
        form = await request.form()
        if not secrets.compare_digest(str(form.get("csrf", "")), session["csrf"]):
            raise AppError("csrf_denied", "Request verification failed", 403)
        return session, form

    def own_service(session):
        user_id = session["user_id"]
        q = TenantQuota(
            raw,
            user_id,
            units=s.units_per_day,
            searches=s.searches_per_day,
            user_units=s.user_units_per_day,
            anonymous_units=s.anonymous_units_per_day,
        )
        return service_factory(
            UserContext(user_id, lambda: credentials.access(user_id), q, session["generation"])
        )

    @app.get("/login")
    async def browser_login(draft: str):
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", draft):
            raise AppError("invalid_input", "Invalid draft reference", 400)
        transaction = security.create_login({"return_path": "/approve/" + draft, "write": False})
        return RedirectResponse("/oauth/start?transaction=" + transaction, 302)

    @app.get("/oauth/start")
    async def google_start(transaction: str):
        pending = security.get_login(transaction)
        if not pending or pending.get("started"):
            raise AppError("invalid_login", "Login expired or already started", 400)
        binding = secrets.token_urlsafe(32)
        pending.update(
            started=True,
            binding=hashlib.sha256(binding.encode()).hexdigest(),
            nonce=secrets.token_urlsafe(32),
            verifier=secrets.token_urlsafe(48),
        )
        security.update_login(transaction, pending)
        response = RedirectResponse(
            idp.authorization_url(
                transaction, pending["nonce"], pending["verifier"], pending.get("write", False)
            ),
            302,
        )
        response.set_cookie(
            binding_name(transaction),
            binding,
            max_age=600,
            httponly=True,
            secure=secure,
            samesite="lax",
            path="/oauth",
        )
        return response

    @app.get("/oauth/callback")
    async def google_callback(request: Request, state: str, code: str = ""):
        pending = security.get_login(state)
        binding = request.cookies.get(binding_name(state), "")
        if (
            not pending
            or not pending.get("started")
            or not binding
            or not secrets.compare_digest(
                hashlib.sha256(binding.encode()).hexdigest(), pending.get("binding", "")
            )
        ):
            raise AppError("invalid_login", "Login expired or browser verification failed", 400)
        if not code or len(code) > 4096:
            security.take_login(state)
            raise AppError("invalid_login", "Google sign-in was not completed", 400)
        # Consume the browser-bound upstream exchange before making any remote request.
        pending = security.take_login(state)
        if not pending:
            raise AppError("invalid_login", "Login already used", 400)
        identity = await idp.exchange(code, pending["verifier"], pending["nonce"])
        user_id = security.upsert_user(identity.sub)
        if pending.get("expected_user_id") and pending["expected_user_id"] != user_id:
            raise AppError(
                "account_mismatch", "Use the same Google account that owns this draft", 403
            )
        if pending.get("expected_user_id") and pending.get(
            "expected_generation"
        ) != security.generation(user_id):
            raise AppError("invalid_login", "Authorization changed; sign in again", 401)
        tokens = security.google(user_id) or {}
        tokens.update({k: v for k, v in identity.tokens.items() if v is not None and v != ""})
        expected_generation = pending.get("expected_generation", security.generation(user_id))
        if not security.save_google(user_id, tokens, expected_generation=expected_generation):
            raise AppError("invalid_login", "Authorization changed; sign in again", 401)
        if "params" in pending:
            pending["consent_user_id"] = user_id
            pending["consent_generation"] = expected_generation + 1
            pending["consent_csrf"] = secrets.token_urlsafe(32)
            transaction = security.create_login(pending)
            response = RedirectResponse("/oauth/consent?transaction=" + transaction, 302)
        else:
            response = RedirectResponse(pending.get("return_path", "/"), 302)
        set_session(response, user_id, expected_generation + 1)
        response.delete_cookie(binding_name(state), path="/oauth")
        return response

    @app.get("/oauth/consent", response_class=HTMLResponse)
    async def client_consent(request: Request, transaction: str):
        session = browser_session(request)
        pending = security.get_login(transaction)
        if (
            not pending
            or pending.get("consent_user_id") != session["user_id"]
            or pending.get("consent_generation") != security.generation(session["user_id"])
        ):
            raise AppError("invalid_login", "Login expired", 400)
        client_info = await auth.get_client(pending["client_id"])
        name = html.escape(client_info.client_name or "this AI client")
        return (
            "<h1>Connect AI client</h1><p>Allow "
            + name
            + ' to read your YouTube profile and propose drafts? It cannot approve or create playlists.</p><form method="post"><input type="hidden" name="csrf" value="'
            + html.escape(session["csrf"])
            + '"><input type="hidden" name="transaction" value="'
            + html.escape(transaction)
            + '"><button>Allow this client</button></form>'
        )

    @app.post("/oauth/consent")
    async def complete_client_consent(request: Request):
        session, form = await csrf_form(request)
        transaction = str(form.get("transaction", request.query_params.get("transaction", "")))
        pending = security.get_login(transaction)
        if (
            not pending
            or pending.get("consent_user_id") != session["user_id"]
            or pending.get("consent_generation") != security.generation(session["user_id"])
        ):
            raise AppError("invalid_login", "Login expired", 400)
        return RedirectResponse(auth.complete_login(transaction, session["user_id"]), 302)

    @app.get("/approve/{ident}", response_class=HTMLResponse)
    async def approval_page(ident: str, request: Request):
        session = security.session(request.cookies.get("yt_session", ""))
        if not session:
            return RedirectResponse("/login?draft=" + ident, 302)
        draft = own_service(session).draft(ident)
        csrf = html.escape(session["csrf"])
        content = (
            "<h1>Review your playlist</h1><p>Metadata below is untrusted. Review every video before confirming.</p><pre>"
            + html.escape(json.dumps(draft, indent=2, ensure_ascii=False))
            + "</pre>"
        )
        tokens = security.google(session["user_id"]) or {}
        if WRITE_SCOPE not in tokens.get("scope", "").split():
            return (
                content
                + '<form method="post" action="/approve/'
                + html.escape(ident)
                + '/enable-writes"><input type="hidden" name="csrf" value="'
                + csrf
                + '"><button>Enable playlist writes with the same Google account</button></form>'
            )
        phrase = "RESUME" if draft["status"] == "partial" else "CREATE"
        return (
            content
            + '<form method="post"><input type="hidden" name="csrf" value="'
            + csrf
            + '"><label>Type '
            + phrase
            + ' to confirm these exact videos <input name="confirmation" autocomplete="off"></label><button>Confirm playlist in my account</button></form>'
        )

    @app.post("/approve/{ident}/enable-writes")
    async def enable_writes(ident: str, request: Request):
        session, _ = await csrf_form(request)
        own_service(session).draft(ident)
        transaction = security.create_login(
            {
                "expected_user_id": session["user_id"],
                "expected_generation": security.generation(session["user_id"]),
                "return_path": "/approve/" + ident,
                "write": True,
            }
        )
        return RedirectResponse("/oauth/start?transaction=" + transaction, 302)

    @app.post("/approve/{ident}")
    async def approve(ident: str, request: Request):
        session, form = await csrf_form(request)
        service = own_service(session)
        draft = service.draft(ident)
        confirmation = str(form.get("confirmation", ""))
        phrase = "RESUME" if draft["status"] == "partial" else "CREATE"
        if confirmation != phrase:
            raise AppError("confirmation_required", "Type the displayed confirmation phrase", 403)
        credentials.require_write(session["user_id"])
        await credentials.access(session["user_id"])
        return await (
            service.resume(ident, confirmation)
            if phrase == "RESUME"
            else service.approve(ident, confirmation)
        )
