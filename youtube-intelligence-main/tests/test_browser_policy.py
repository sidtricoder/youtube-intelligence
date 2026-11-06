import pytest

from ytintel.browser_policy import form_redirect_policy


def test_default_form_policy_is_self_only():
    assert "form-action 'self';" in form_redirect_policy()


def test_only_callback_origin_is_added_not_its_query_or_other_hosts():
    policy = form_redirect_policy("https://claude.ai/api/mcp/auth_callback?state=sensitive")
    assert "form-action 'self' https://claude.ai;" in policy
    assert "sensitive" not in policy and "auth_callback" not in policy
    assert "*" not in policy and "unsafe-inline" not in policy.split("form-action")[1]
    assert "script-src" not in policy and "default-src 'none'" in policy


@pytest.mark.parametrize(
    "url",
    [
        "javascript:alert(1)",
        "https://*.example.test/callback",
        "http://public.test/cb",
        "https://user:password@example.test/cb",
        "https://example.test;script-src.example/cb",
    ],
)
def test_untrusted_callback_cannot_inject_policy(url):
    with pytest.raises(ValueError):
        form_redirect_policy(url)


def test_loopback_callbacks_keep_the_registered_port():
    assert "http://127.0.0.1:49152" in form_redirect_policy("http://127.0.0.1:49152/cb")
