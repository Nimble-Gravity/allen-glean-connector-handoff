"""The /health probe must return 200 WITHOUT a bearer key (platform calls it)."""

import pytest
from fastapi.testclient import TestClient

import main as api_main
from notifications.events import ErrorEvent
from notifications.senders.base import Notifier


class _RecordingNotifier(Notifier):
    name = "recording"

    def __init__(self):
        self.events: list[ErrorEvent] = []

    def send(self, event: ErrorEvent) -> None:
        self.events.append(event)


@pytest.fixture
def _recorder(monkeypatch) -> _RecordingNotifier:
    rec = _RecordingNotifier()
    monkeypatch.setattr(api_main, "build_api_notifier", lambda: rec)
    monkeypatch.setattr(api_main, "load_api_key", lambda: "test-key")
    return rec


def test_health_no_auth_returns_200(_recorder):
    with TestClient(api_main.app) as client:
        resp = client.get("/health")  # no Authorization header
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_protected_route_still_requires_bearer(_recorder):
    with TestClient(api_main.app) as client:
        resp = client.get(
            "/metadata", params={"user_email": "a@b.com", "show_all_views": "true"}
        )
    assert resp.status_code == 401
