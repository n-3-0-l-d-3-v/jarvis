import pytest


@pytest.fixture(autouse=True)
def _no_ambient_vault(monkeypatch):
    """Dev machine sets a real VAULT_PATH; tests must never touch it."""
    monkeypatch.delenv("VAULT_PATH", raising=False)
