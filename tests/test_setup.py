import importlib.util
from pathlib import Path

import pytest
from cryptography.fernet import Fernet

from ytintel.config import Settings


def test_bootstrap_creates_private_encryption_key_and_does_not_overwrite(tmp_path):
    spec = importlib.util.spec_from_file_location(
        "bootstrap", Path(__file__).parents[1] / "scripts/bootstrap.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    target = tmp_path / ".env"
    assert module.bootstrap(target)
    original = target.read_bytes()
    assert not module.bootstrap(target) and target.read_bytes() == original
    settings = Settings(_env_file=target)
    # An actual Fernet round trip proves the generated key is usable.
    cipher = Fernet(settings.encryption_key.encode())
    assert cipher.decrypt(cipher.encrypt(b"private")) == b"private"
    assert target.stat().st_mode & 0o777 == 0o600
    assert b"YT_API_KEY=" not in original
    assert b"YT_OWNER_KEY=" not in original
    assert not hasattr(settings, "api_key") and not hasattr(settings, "owner_key")


def test_settings_repr_does_not_expose_encryption_or_google_client_secrets():
    key = Fernet.generate_key().decode()
    settings = Settings(_env_file=None, encryption_key=key, google_client_secret="secret-client")
    assert key not in repr(settings)
    assert "secret-client" not in repr(settings)


@pytest.mark.parametrize(
    "values",
    [
        {"units_per_day": -1},
        {"searches_per_day": -1},
        {"public_base_url": "http://public.example"},
        {"public_base_url": "https://public.example/path"},
    ],
)
def test_unsafe_settings_rejected(values):
    with pytest.raises(ValueError):
        Settings(_env_file=None, encryption_key=Fernet.generate_key().decode(), **values)
