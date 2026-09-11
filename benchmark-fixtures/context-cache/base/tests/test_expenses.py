from fastapi.testclient import TestClient

from app.main import DATABASE, app


def test_create_and_list_expense():
    DATABASE.unlink(missing_ok=True)
    client = TestClient(app)
    response = client.post("/expenses", json={
        "amount": 12.5, "category": "food", "description": "lunch", "date": "2026-01-10"})
    assert response.status_code == 201
    assert client.get("/expenses").json()[0]["category"] == "food"
