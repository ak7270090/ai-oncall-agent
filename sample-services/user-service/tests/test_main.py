from fastapi.testclient import TestClient

from main import app

client = TestClient(app)


def test_health_reports_service_and_version():
    body = client.get("/health").json()
    assert body["status"] == "ok"
    assert body["service"] == "user-service"


def test_get_existing_user():
    assert client.get("/users/1").json()["name"] == "Asha Rao"


def test_unknown_user_is_404():
    assert client.get("/users/999").status_code == 404
