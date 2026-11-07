import json
import time

import httpx
import pytest

from tests.wire_helpers import call, login, mcp_session, rpc, running_server, tool


async def signed_in_token(wire):
    async with httpx.AsyncClient(base_url=wire.origin, trust_env=False) as browser:
        return (await login(wire, browser, "alice"))["access_token"]


@pytest.fixture(autouse=True)
def capture_app_logs(caplog):
    import logging

    logger = logging.getLogger("ytintel")
    logger.addHandler(caplog.handler)
    yield
    logger.removeHandler(caplog.handler)


def events(caplog):
    return [r.__dict__.get("event_data", {}) for r in caplog.records if r.name == "ytintel"]


async def test_draft_tool_logs_correlated_success_without_private_arguments(tmp_path, caplog):
    with running_server(tmp_path) as wire:
        token = await signed_in_token(wire)
        with caplog.at_level("INFO", logger="ytintel"):
            async with mcp_session(wire, token) as session:
                result = await call(
                    session, "create_playlist_draft", {"topic": "Python secret-topic"}
                )
        assert result["videos"]
        records = events(caplog)
        started = next(e for e in records if e.get("event") == "tool.started")
        finished = next(e for e in records if e.get("event") == "tool.completed")
        assert started["request_id"] == finished["request_id"]
        assert finished["tool"] == "create_playlist_draft" and finished["outcome"] == "success"
        assert "secret-topic" not in json.dumps(records)
        assert any(e.get("event") == "quota.reserved" for e in records)
        assert any(e.get("event") == "playlist.selected" for e in records)


async def test_invalid_language_reports_field_and_logs_no_input_values(tmp_path, caplog):
    with running_server(tmp_path) as wire:
        token = await signed_in_token(wire)
        with caplog.at_level("INFO", logger="ytintel"):
            async with mcp_session(wire, token) as session:
                result = await call(
                    session,
                    "create_playlist_draft",
                    {"topic": "Python", "language": "private-invalid"},
                )
        error = result["error"]
        assert error["code"] == "invalid_input" and error["request_id"]
        assert error["fields"] == ["language"]
        assert "en" in error["message"]
        assert any(
            e.get("event") == "tool.failed" and e.get("error_code") == "invalid_input"
            for e in events(caplog)
        )
        assert "private-invalid" not in json.dumps(events(caplog))
        assert all(not provider.calls for provider in wire.providers.values())


async def test_gate_challenge_is_logged_and_response_has_server_request_id(tmp_path, caplog):
    with running_server(tmp_path) as wire:
        with caplog.at_level("INFO", logger="ytintel"):
            response = await rpc(wire, tool("create_playlist_draft", {"topic": "Python"}))
        assert response.status_code == 401
        assert response.headers["x-request-id"]
        assert any(e.get("event") == "auth.challenge" for e in events(caplog))
        # http.completed is logged after the response is sent, so it can land just after the client returns.
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and not any(
            e.get("event") == "http.completed" and e.get("status") == 401 for e in events(caplog)
        ):
            time.sleep(0.01)
        assert any(
            e.get("event") == "http.completed" and e.get("status") == 401 for e in events(caplog)
        )


async def test_http_logs_never_include_query_secrets_headers_or_dynamic_paths(tmp_path, caplog):
    with running_server(tmp_path) as wire:
        with caplog.at_level("INFO", logger="ytintel"):
            async with httpx.AsyncClient(base_url=wire.origin, trust_env=False) as client:
                await client.get(
                    "/approve/private-draft?code=private-code&key=private-key",
                    headers={
                        "Authorization": "Bearer private-token",
                        "Cookie": "yt_session=private-cookie",
                        "X-Request-ID": "private-injected",
                    },
                )
            time.sleep(0.05)  # allow server thread to flush the completed event
        text = json.dumps(events(caplog))
        assert "http.completed" in text
        for secret in [
            "private-draft",
            "private-code",
            "private-key",
            "private-token",
            "private-cookie",
            "private-injected",
        ]:
            assert secret not in text


async def test_provider_failure_logs_safe_code_status_not_upstream_message(tmp_path, caplog):
    from cryptography.fernet import Fernet

    from ytintel.errors import AppError
    from ytintel.providers.google import GoogleProvider
    from ytintel.quota import Quota
    from ytintel.store import Store

    async def upstream(request):
        return httpx.Response(
            403,
            json={
                "error": {
                    "message": "private-provider-text",
                    "errors": [{"reason": "quotaExceeded"}],
                }
            },
        )

    store = Store(str(tmp_path / "provider.db"), Fernet.generate_key().decode())
    async with httpx.AsyncClient(transport=httpx.MockTransport(upstream)) as client:
        provider = GoogleProvider(client, None, store, public_api_key="private-api-key")
        with caplog.at_level("INFO", logger="ytintel"), Quota(store).reserve(1, 0):
            with pytest.raises(AppError):
                await provider.videos(["aaaaaaaaaaa"])
    rows = events(caplog)
    assert any(
        e.get("event") == "youtube.failed"
        and e.get("error_code") == "quota_exceeded"
        and e.get("status") == 403
        for e in rows
    )
    assert "private-api-key" not in json.dumps(rows) and "private-provider-text" not in json.dumps(
        rows
    )


async def test_sdk_rejects_wrong_argument_type_with_safe_diagnostics(tmp_path, caplog):
    with running_server(tmp_path) as wire:
        token = await signed_in_token(wire)
        with caplog.at_level("INFO", logger="ytintel"):
            async with mcp_session(wire, token) as session:
                result = await call(
                    session, "create_playlist_draft", {"topic": ["private-wrong-type"]}
                )
        assert result["error"]["code"] == "invalid_input"
        assert result["error"]["fields"] == ["topic"]
        assert any(e.get("event") == "tool.failed" for e in events(caplog))
        assert "private-wrong-type" not in json.dumps(events(caplog))
        assert wire.providers == {}


async def test_playlist_tool_schema_explains_language_and_positive_optional_durations():
    from ytintel.mcp_server import build_mcp

    tools = await build_mcp(lambda _: None).list_tools()
    for item in tools:
        if item.name == "create_playlist_draft":
            properties = item.inputSchema["properties"]
            assert "en" in properties["language"]["description"]
            assert "seconds" in properties["total_seconds"]["description"]
            assert properties["topic"]["maxLength"] == 200


async def test_unexpected_http_exception_is_sanitized_and_correlated(tmp_path, caplog):
    with running_server(tmp_path) as wire:

        @wire.app.get("/unexpected")
        async def unexpected():
            raise RuntimeError("private-internal-exception")

        with caplog.at_level("INFO", logger="ytintel"):
            async with httpx.AsyncClient(base_url=wire.origin, trust_env=False) as client:
                response = await client.get("/unexpected")
        assert response.status_code == 500
        assert response.json()["error"]["code"] == "internal_error"
        assert response.json()["error"]["request_id"] == response.headers["x-request-id"]
        assert "private-internal-exception" not in json.dumps(events(caplog))


@pytest.mark.parametrize("completed", [True, False])
async def test_observer_does_not_leak_exception_after_response_started(completed, caplog):
    from ytintel.observability import RequestLogging

    sent = []

    async def app(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        if completed:
            await send({"type": "http.response.body", "body": b"ok", "more_body": False})
        raise RuntimeError("private-after-start")

    async def send(message):
        if completed and len(sent) >= 2:
            raise RuntimeError("response-already-finished")
        if not completed and message["type"] == "http.response.body":
            raise RuntimeError("broken-transport")
        sent.append(message)

    async def receive():
        return {"type": "http.disconnect"}

    with caplog.at_level("INFO", logger="ytintel"):
        await RequestLogging(app)({"type": "http", "path": "/", "method": "GET"}, receive, send)
    assert any(e.get("event") == "http.failed" for e in events(caplog))
    assert "private-after-start" not in json.dumps(events(caplog))
