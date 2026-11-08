"""Shared fixtures for the trust tests."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture
def keys(tmp_path, monkeypatch):
    """Fresh Ed25519 keys + registry in a temp dir (never touches keys/)."""
    from common import crypto
    monkeypatch.setattr(crypto, "KEYS_DIR", tmp_path / "keys")
    crypto.generate_keys(force=True)
    yield crypto
    crypto.load_private.cache_clear()
    crypto.registry_keys.cache_clear()


class Events:
    """Collects emitted events instead of posting them to the hub."""

    def __init__(self):
        self.items = []

    async def __call__(self, type, data=None, severity="info", source=None):
        self.items.append({"type": type, "data": data or {}, "severity": severity})
        return self.items[-1]

    def of(self, type):
        return [e["data"] for e in self.items if e["type"] == type]


@pytest.fixture
def events():
    return Events()
