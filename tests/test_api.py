from fastapi.testclient import TestClient

from app.main import create_app
from app.settings import Settings
from app.store import MemoryLeadStore


def seed(name: str, phone: str, score: int = 80) -> dict:
    return {
        "id": name.lower().replace(" ", "-"),
        "name": name,
        "area": "Bangalore",
        "city": "Bangalore",
        "score": score,
        "status": "Found",
        "contact_channels": [{"type": "phone", "value": phone, "public_business": True}],
    }


def client() -> TestClient:
    settings = Settings(database_url="memory://", portal_shared_secret="test-secret", city="Bangalore", batch_size=2, daily_limit=10)
    app = create_app(settings=settings, store=MemoryLeadStore([seed("Alpha", "98765 00001"), seed("Beta", "98765 00002"), seed("Gamma", "98765 00003")], batch_size=2))
    return TestClient(app)


def headers(user: str = "caller-1") -> dict[str, str]:
    return {"x-portal-secret": "test-secret", "x-portal-user": user}


def test_health_is_public_but_caller_routes_require_the_netlify_secret() -> None:
    test_client = client()
    assert test_client.get("/v1/health").json() == {"ok": True}
    assert test_client.get("/v1/caller/current").status_code == 403


def test_refresh_assigns_a_non_overlapping_batch_to_each_caller() -> None:
    test_client = client()
    first = test_client.post("/v1/caller/refresh", headers=headers("first")).json()
    second = test_client.post("/v1/caller/refresh", headers=headers("second")).json()
    assert len(first["leads"]) == 2
    assert len(second["leads"]) == 1
    assert {lead["id"] for lead in first["leads"]}.isdisjoint({lead["id"] for lead in second["leads"]})


def test_import_requires_the_shared_secret_and_ignores_non_callable_records() -> None:
    test_client = client()
    payload = {"leads": [seed("Delta", "98765 00004"), {"name": "No Phone", "contact_channels": []}]}
    assert test_client.post("/v1/internal/import", json=payload).status_code == 403
    response = test_client.post("/v1/internal/import", headers={"x-portal-secret": "test-secret"}, json=payload)
    assert response.status_code == 200
    assert response.json()["imported"] == 1
