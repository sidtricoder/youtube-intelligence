import importlib.util
from pathlib import Path

import pytest

from ytintel.config import Settings


def test_bootstrap_creates_private_distinct_keys_and_does_not_overwrite(tmp_path):
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
    assert not hasattr(settings, "mode") and settings.api_key != settings.owner_key


@pytest.mark.parametrize(
    "values",
    [
        {"api_key": "short", "owner_key": "o" * 32},
        {"api_key": "a" * 32, "owner_key": "a" * 32},
        {"api_key": "a" * 32, "owner_key": "o" * 32, "units_per_day": -1},
    ],
)
def test_unsafe_settings_rejected(values):
    with pytest.raises(ValueError):
        Settings(_env_file=None, encryption_key="unused", **values)
