import pytest


@pytest.fixture(autouse=True)
def _no_ambient_vault(monkeypatch):
    """Dev machine sets a real VAULT_PATH; tests must never touch it."""
    monkeypatch.delenv("VAULT_PATH", raising=False)


@pytest.fixture(autouse=True)
def _private_jarvis_db(monkeypatch, tmp_path):
    """Dispatch paths write audit rows; never into the real ~/.jarvis/jarvis.db."""
    monkeypatch.setenv("JARVIS_DB_PATH", str(tmp_path / "jarvis.db"))
