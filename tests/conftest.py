"""Tests must not inherit the developer's real source credentials."""
import pytest


@pytest.fixture(autouse=True)
def clear_source_credentials(monkeypatch):
    monkeypatch.delenv('CONSULTANT_LOGIN', raising=False)
    monkeypatch.delenv('CONSULTANT_PASSWORD', raising=False)
