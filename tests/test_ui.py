import httpx
import pytest
from sqlalchemy import func, select

from tests.wire_helpers import csrf, login, query, running_server


def test_consent_is_an_accessible_dialog_with_nonce_and_escaped_client_name():
    from ytintel.ui import consent_page

    response = consent_page("<script>bad()</script>", "https://claude.ai/callback", "csrf", "tx")
    body = response.body.decode()
    assert "<dialog" in body and 'aria-labelledby="consent-title"' in body
    assert ".showModal()" in body and 'name="decision" value="deny"' in body
    assert "&lt;script&gt;bad()&lt;/script&gt;" in body
    assert "script-src 'nonce-" in response.headers["content-security-policy"]
    assert "form-action 'self' https://claude.ai" in response.headers["content-security-policy"]
    assert 'name="csrf" value="csrf"' in body


def test_home_has_responsive_layout_and_safe_connector_url():
    from ytintel.ui import home_page

    response = home_page("https://example.test")
    body = response.body.decode()
    assert 'name="viewport"' in body
    assert "<main" in body and "https://example.test/mcp/" in body
    assert "Public discovery" in body and "Sign In Now" in body


@pytest.fixture
def server(tmp_path):
    with running_server(tmp_path) as wire:
        yield wire


async def test_cancel_consent_returns_access_denied_without_minting_code(server):
    async with httpx.AsyncClient(base_url=server.origin, trust_env=False) as browser:
        await login(server, browser, "alice")
        security = server.app.state.security
        user = security.upsert_user("alice")
        client = (
            await browser.post(
                "/register",
                json={
                    "client_name": "New client",
                    "redirect_uris": ["http://127.0.0.1:9876/cb"],
                    "token_endpoint_auth_method": "none",
                    "scope": "youtube:read",
                },
            )
        ).json()
        tx = security.create_login(
            {
                "client_id": client["client_id"],
                "consent_user_id": user,
                "consent_generation": security.generation(user),
                "params": {
                    "state": "cancel-state",
                    "scopes": ["youtube:read"],
                    "code_challenge": "a" * 43,
                    "redirect_uri": "http://127.0.0.1:9876/cb",
                    "redirect_uri_provided_explicitly": True,
                    "resource": server.origin + "/mcp/",
                },
            }
        )
        page = await browser.get("/oauth/consent", params={"transaction": tx})
        with security.raw.tx() as db:
            before = db.execute(select(func.count()).select_from(security.auth_codes)).scalar_one()
        response = await browser.post(
            "/oauth/consent", data={"csrf": csrf(page), "transaction": tx, "decision": "deny"}
        )
        values = query(response.headers["location"])
        assert values.get("error") == "access_denied" and "code" not in values
        assert values["state"] == "cancel-state"
        assert security.get_login(tx) is None
        with security.raw.tx() as db:
            assert (
                db.execute(select(func.count()).select_from(security.auth_codes)).scalar_one()
                == before
            )


async def test_browser_errors_are_styled_but_api_errors_stay_json(server):
    async with httpx.AsyncClient(base_url=server.origin, trust_env=False) as browser:
        page = await browser.get(
            "/oauth/consent?transaction=expired", headers={"Accept": "text/html"}
        )
        assert page.status_code == 401 and "text/html" in page.headers["content-type"]
        assert "<main" in page.text and "Sign-in" in page.text
        api = await browser.get("/oauth/consent?transaction=expired")
        assert api.status_code == 401 and api.json()["error"]["code"] == "browser_sign_in_required"


@pytest.mark.parametrize("path,status", [("/missing-page", 404), ("/login", 422)])
async def test_browser_missing_or_invalid_pages_are_styled(server, path, status):
    async with httpx.AsyncClient(base_url=server.origin, trust_env=False) as browser:
        response = await browser.get(path, headers={"Accept": "text/html"})
        assert response.status_code == status and "text/html" in response.headers["content-type"]
        assert "<main" in response.text


@pytest.mark.parametrize(
    "accept",
    ["application/json, text/html;q=0", "application/json, text/html;q=0.5"],
)
async def test_json_preference_is_respected_for_browser_errors(server, accept):
    async with httpx.AsyncClient(base_url=server.origin, trust_env=False) as browser:
        response = await browser.get(
            "/oauth/consent?transaction=expired", headers={"Accept": accept}
        )
        assert response.status_code == 401
        assert response.headers["content-type"].startswith("application/json")
