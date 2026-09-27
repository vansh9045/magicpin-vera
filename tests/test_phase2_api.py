"""
Integration tests for Phase 2 endpoints:
- GET /v1/healthz
- GET /v1/metadata
- POST /v1/context
"""

import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.store.context_store import context_store

client = TestClient(app)


@pytest.fixture(autouse=True)
def clean_store():
    """Ensure clean store before each test."""
    context_store.clear()


def test_healthz_initial():
    response = client.get("/v1/healthz")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["uptime_seconds"] >= 0
    assert data["contexts_loaded"] == {
        "category": 0,
        "merchant": 0,
        "customer": 0,
        "trigger": 0
    }


def test_metadata():
    response = client.get("/v1/metadata")
    assert response.status_code == 200
    data = response.json()
    assert data["team_name"] == "Team Vera Elite"
    assert "deterministic" in data["approach"]
    assert "version" in data
    assert "submitted_at" in data


def test_context_push_lifecycle():
    # 1. Valid Category push v1
    cat_payload = {
        "slug": "dentists",
        "voice": {"tone": "peer_clinical"},
        "offer_catalog": []
    }
    resp1 = client.post("/v1/context", json={
        "scope": "category",
        "context_id": "dentists",
        "version": 1,
        "delivered_at": "2026-04-26T09:45:00Z",
        "payload": cat_payload
    })
    assert resp1.status_code == 200
    data1 = resp1.json()
    assert data1["accepted"] is True
    assert data1["ack_id"] == "ack_dentists_v1"
    assert "stored_at" in data1

    # 2. Idempotency test: Re-pushing same version v1 returns 200 OK (no-op, does not duplicate state)
    resp2 = client.post("/v1/context", json={
        "scope": "category",
        "context_id": "dentists",
        "version": 1,
        "delivered_at": "2026-04-26T09:46:00Z",
        "payload": cat_payload
    })
    assert resp2.status_code == 200
    data2 = resp2.json()
    assert data2["accepted"] is True
    assert data2["ack_id"] == "ack_dentists_v1"
    # State not duplicated in counts
    assert context_store.get_counts()["category"] == 1

    # 3. Lower version v0 returns 409
    resp3 = client.post("/v1/context", json={
        "scope": "category",
        "context_id": "dentists",
        "version": 0,
        "delivered_at": "2026-04-26T09:46:00Z",
        "payload": cat_payload
    })
    assert resp3.status_code == 409
    assert resp3.json()["current_version"] == 1

    # 4. Version bump to v2 returns 200 and replaces prior version
    cat_payload_v2 = dict(cat_payload)
    cat_payload_v2["updated"] = True
    resp4 = client.post("/v1/context", json={
        "scope": "category",
        "context_id": "dentists",
        "version": 2,
        "delivered_at": "2026-04-26T10:00:00Z",
        "payload": cat_payload_v2
    })
    assert resp4.status_code == 200
    assert resp4.json()["ack_id"] == "ack_dentists_v2"
    assert context_store.get_category("dentists")["updated"] is True


def test_context_healthz_counts():
    # Push merchant
    client.post("/v1/context", json={
        "scope": "merchant",
        "context_id": "m_001_drmeera",
        "version": 1,
        "delivered_at": "2026-04-26T10:00:00Z",
        "payload": {"merchant_id": "m_001_drmeera", "name": "Dr. Meera"}
    })

    # Push customer
    client.post("/v1/context", json={
        "scope": "customer",
        "context_id": "c_001_priya",
        "version": 1,
        "delivered_at": "2026-04-26T10:00:00Z",
        "payload": {"customer_id": "c_001_priya", "name": "Priya"}
    })

    # Push trigger
    client.post("/v1/context", json={
        "scope": "trigger",
        "context_id": "trg_001",
        "version": 1,
        "delivered_at": "2026-04-26T10:00:00Z",
        "payload": {"id": "trg_001", "kind": "research_digest"}
    })

    resp = client.get("/v1/healthz")
    assert resp.status_code == 200
    counts = resp.json()["contexts_loaded"]
    assert counts["merchant"] == 1
    assert counts["customer"] == 1
    assert counts["trigger"] == 1
    assert counts["category"] == 0


def test_context_validation_errors():
    # Invalid scope
    r1 = client.post("/v1/context", json={
        "scope": "invalid_scope",
        "context_id": "test",
        "version": 1,
        "payload": {}
    })
    assert r1.status_code == 400
    assert r1.json()["reason"] == "invalid_scope"

    # Missing context_id
    r2 = client.post("/v1/context", json={
        "scope": "merchant",
        "context_id": "",
        "version": 1,
        "payload": {}
    })
    assert r2.status_code == 400
    assert r2.json()["reason"] == "missing_context_id"

    # Invalid payload (not a dict)
    r3 = client.post("/v1/context", json={
        "scope": "merchant",
        "context_id": "m_001",
        "version": 1,
        "payload": "not_a_dict"
    })
    assert r3.status_code == 400
    assert r3.json()["reason"] == "invalid_payload"
