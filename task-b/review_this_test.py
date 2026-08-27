"""The tests that shipped with PR #412. They pass."""

from fastapi.testclient import TestClient
from .main import app

client = TestClient(app)
HEADERS = {"token": "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0."}


def test_export_returns_responses():
    r = client.get("/api/surveys/1/export", headers=HEADERS)
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_close_survey_increments_close_count():
    r = client.post("/api/surveys/1/close", headers=HEADERS)
    assert r.status_code == 200


def test_delete_survey():
    r = client.delete("/api/surveys/999", headers=HEADERS)
    assert r.status_code == 200
