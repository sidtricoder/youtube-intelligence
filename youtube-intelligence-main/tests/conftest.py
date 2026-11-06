"""Offline tests must not inherit production application credentials or Render settings."""

import os

import pytest


@pytest.fixture(autouse=True)
def isolate_application_environment(monkeypatch):
    for name in tuple(os.environ):
        if name.startswith("YT_") or name in {
            "DATABASE_URL",
            "DATABASE_URL_POOLED",
            "RENDER_EXTERNAL_URL",
            "PORT",
            "FORWARDED_ALLOW_IPS",
        }:
            monkeypatch.delenv(name, raising=False)
    # TEST_DATABASE_URL is deliberately retained only for explicit PostgreSQL tests.
