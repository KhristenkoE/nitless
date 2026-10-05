from sqlalchemy import create_engine

from app.core.db import get_engine
from app.main import app


def test_live(client):
    response = client.get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_ready_when_database_is_reachable(client):
    app.dependency_overrides[get_engine] = lambda: create_engine("sqlite://")

    response = client.get("/health/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_ready_returns_503_when_database_is_down(client, tmp_path):
    broken = create_engine(f"sqlite:///{tmp_path}/missing-dir/orders.db")
    app.dependency_overrides[get_engine] = lambda: broken

    response = client.get("/health/ready")

    assert response.status_code == 503
    assert response.json() == {"status": "unavailable"}
