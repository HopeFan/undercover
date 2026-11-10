import time

import pytest
from fastapi.testclient import TestClient

from agent import tools
from backend.main import app
from backend.tests.conftest import client, database

__all__ = ["client", "database"]


@pytest.fixture(autouse=True)
def backend(monkeypatch):
    """Send the agent's requests to the test backend."""
    monkeypatch.setattr(tools, "backend", lambda: TestClient(app))


@pytest.fixture(autouse=True)
def no_waiting(monkeypatch):
    """Let the retry middleware retry at once instead of waiting."""
    monkeypatch.setattr(time, "sleep", lambda seconds: None)
