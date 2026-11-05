from ytintel.ui import approval_page, consent_page, error_page


def draft():
    return {
        "id": "synthetic",
        "status": "pending",
        "constraints": {"topic": "Python", "total_seconds": None, "max_seconds": None},
        "videos": [
            {
                "id": "aaaaaaaaaaa",
                "title": "<script>bad()</script>",
                "channel_title": "Fixture",
                "seconds": 600,
            }
        ],
        "total_seconds": 600,
    }


def test_consent_uses_browser_confirm_and_no_custom_dialog():
    response = consent_page("<script>bad()</script>", "https://claude.ai/callback", "csrf", "tx")
    body = response.body.decode()
    assert "window.confirm(" in body and "<dialog" not in body
    assert "<script>bad()</script>" not in body
    assert "nonce-" in response.headers["content-security-policy"]
    assert 'value="deny"' in body and 'name="csrf"' in body


def test_approval_uses_typed_browser_prompt_and_fetch_alert_not_navigation():
    response = approval_page(draft(), "csrf", True)
    body = response.body.decode()
    assert "window.prompt(" in body and "fetch(" in body and "window.alert(" in body
    assert "<script>bad()</script>" not in body
    assert "connect-src" in response.headers["content-security-policy"]
    assert "CREATE" in body and 'name="csrf" value="csrf"' in body


def test_browser_error_fallback_is_plain_and_retains_http_status():
    response = error_page("Google quota exceeded", 429)
    assert response.status_code == 429
    assert "Google quota exceeded" in response.body.decode()
    assert "Let’s get you back on track" not in response.body.decode()
