"""
Phase 6 Tests — POST /v1/tick (full decision pipeline)
"""

import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.store.context_store import context_store
from app.store.suppression_store import suppression_store
from app.store.conversation_store import conversation_store

client = TestClient(app)

NOW_ISO = "2027-01-01T10:00:00Z"
EXPIRES_FUTURE = "2027-06-01T00:00:00Z"


@pytest.fixture(autouse=True)
def reset_stores():
    """Clear all stores before each test."""
    context_store.clear()
    suppression_store.clear()
    conversation_store.clear()
    yield
    context_store.clear()
    suppression_store.clear()
    conversation_store.clear()


# -----------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------

def push(scope: str, cid: str, payload: dict, version: int = 1):
    r = client.post("/v1/context", json={
        "scope": scope, "context_id": cid, "version": version,
        "payload": payload, "delivered_at": NOW_ISO
    })
    assert r.status_code == 200, f"push {scope}/{cid} failed: {r.text}"


def tick(trigger_ids: list, now: str = NOW_ISO):
    return client.post("/v1/tick", json={"now": now, "available_triggers": trigger_ids})


CATEGORY_DENTISTS = {
    "slug": "dentists",
    "voice": {
        "tone": "clinical",
        "vocab_allowed": ["evidence-based", "peer-reviewed"],
        "vocab_taboo": ["guaranteed cure", "miracle"]
    },
    "peer_stats": {"avg_ctr": 0.045, "avg_rating": 4.2, "avg_review_count": 87},
    "digest": [
        {
            "id": "dig_001",
            "title": "fluoride varnish reduces caries by 43%",
            "source": "JADA 2024",
            "trial_n": 1200
        }
    ],
    "offer_catalog": []
}

MERCHANT_DENTIST = {
    "merchant_id": "m_001",
    "category_slug": "dentists",
    "identity": {
        "name": "Smile Clinic",
        "owner_first_name": "Priya",
        "locality": "Koramangala",
        "city": "Bengaluru",
        "languages": ["en", "kn"],
        "verified": True
    },
    "subscription": {"status": "active", "days_remaining": 45},
    "performance": {
        "views": 320, "calls": 18, "directions": 5, "ctr": 0.056,
        "delta_7d": {"views_pct": -0.12, "calls_pct": -0.08}
    },
    "offers": [{"title": "Free Consultation", "status": "active"}],
    "signals": ["ctr_below_peers"],
    "customer_aggregate": {"high_risk_adult_count": 34}
}

TRIGGER_RESEARCH = {
    "id": "trg_001",
    "kind": "research_digest",
    "merchant_id": "m_001",
    "scope": "merchant",
    "urgency": 3,
    "suppression_key": "research_digest_m_001",
    "expires_at": EXPIRES_FUTURE,
    "payload": {"top_item_id": "dig_001"}
}


# -----------------------------------------------------------------------
# Test 1: Empty trigger list returns empty actions
# -----------------------------------------------------------------------
def test_tick_empty_triggers():
    r = tick([])
    assert r.status_code == 200
    body = r.json()
    assert "actions" in body
    assert body["actions"] == []


# -----------------------------------------------------------------------
# Test 2: Unknown trigger IDs produce no actions (not in store)
# -----------------------------------------------------------------------
def test_tick_unknown_triggers():
    r = tick(["trg_nonexistent_1", "trg_nonexistent_2"])
    assert r.status_code == 200
    assert r.json()["actions"] == []


# -----------------------------------------------------------------------
# Test 3: Trigger present but no merchant context → no action
# -----------------------------------------------------------------------
def test_tick_trigger_no_merchant():
    push("trigger", "trg_001", TRIGGER_RESEARCH)
    r = tick(["trg_001"])
    assert r.status_code == 200
    assert r.json()["actions"] == []


# -----------------------------------------------------------------------
# Test 4: Full happy-path — all context present → action returned
# -----------------------------------------------------------------------
def test_tick_full_happy_path():
    push("category", "dentists", CATEGORY_DENTISTS)
    push("merchant", "m_001", MERCHANT_DENTIST)
    push("trigger", "trg_001", TRIGGER_RESEARCH)

    r = tick(["trg_001"])
    assert r.status_code == 200
    data = r.json()
    actions = data["actions"]
    assert len(actions) == 1

    a = actions[0]
    # Required fields
    assert a["merchant_id"] == "m_001"
    assert a["trigger_id"] == "trg_001"
    assert a["send_as"] in ("vera", "merchant_on_behalf")
    assert len(a["body"]) > 10
    assert a["cta"] != ""
    assert a["suppression_key"] != ""
    assert a["rationale"] != ""
    assert isinstance(a["template_params"], list)


# -----------------------------------------------------------------------
# Test 5: Max 1 action per merchant per tick
# -----------------------------------------------------------------------
def test_tick_max_one_per_merchant():
    push("category", "dentists", CATEGORY_DENTISTS)
    push("merchant", "m_001", MERCHANT_DENTIST)

    # Push two triggers for the same merchant
    push("trigger", "trg_001", TRIGGER_RESEARCH)
    push("trigger", "trg_002", {
        "id": "trg_002",
        "kind": "perf_dip",
        "merchant_id": "m_001",
        "scope": "merchant",
        "urgency": 2,
        "suppression_key": "perf_dip_m_001",
        "expires_at": EXPIRES_FUTURE,
        "payload": {}
    })

    r = tick(["trg_001", "trg_002"])
    assert r.status_code == 200
    actions = r.json()["actions"]
    # Must have at most 1 action for m_001
    m001_actions = [a for a in actions if a["merchant_id"] == "m_001"]
    assert len(m001_actions) <= 1


# -----------------------------------------------------------------------
# Test 6: Suppressed trigger produces no action
# -----------------------------------------------------------------------
def test_tick_suppressed_trigger():
    push("category", "dentists", CATEGORY_DENTISTS)
    push("merchant", "m_001", MERCHANT_DENTIST)
    push("trigger", "trg_001", TRIGGER_RESEARCH)

    # Pre-suppress the key
    suppression_store.record_key("research_digest_m_001", EXPIRES_FUTURE)

    r = tick(["trg_001"])
    assert r.status_code == 200
    assert r.json()["actions"] == []


# -----------------------------------------------------------------------
# Test 7: Expired trigger produces no action
# -----------------------------------------------------------------------
def test_tick_expired_trigger():
    push("category", "dentists", CATEGORY_DENTISTS)
    push("merchant", "m_001", MERCHANT_DENTIST)
    push("trigger", "trg_001", {
        **TRIGGER_RESEARCH,
        "expires_at": "2020-01-01T00:00:00Z"  # definitely expired
    })

    r = tick(["trg_001"])
    assert r.status_code == 200
    assert r.json()["actions"] == []


# -----------------------------------------------------------------------
# Test 8: Post-tick suppression is recorded
# -----------------------------------------------------------------------
def test_tick_records_suppression():
    push("category", "dentists", CATEGORY_DENTISTS)
    push("merchant", "m_001", MERCHANT_DENTIST)
    push("trigger", "trg_001", TRIGGER_RESEARCH)

    r = tick(["trg_001"])
    actions = r.json()["actions"]
    assert len(actions) == 1

    # Second tick with the same trigger must yield no actions (suppressed)
    r2 = tick(["trg_001"])
    assert r2.json()["actions"] == []


# -----------------------------------------------------------------------
# Test 9: Different trigger for same merchant in a separate tick is allowed
#         (spec only requires 1-per-merchant-per-tick, not 24h blanket cooldown)
# -----------------------------------------------------------------------
def test_tick_no_cross_tick_merchant_cooldown():
    push("category", "dentists", CATEGORY_DENTISTS)
    push("merchant", "m_001", MERCHANT_DENTIST)
    push("trigger", "trg_001", TRIGGER_RESEARCH)

    r = tick(["trg_001"])
    assert r.json()["actions"]  # got at least 1 action

    # Push a different trigger for same merchant (different suppression_key)
    push("trigger", "trg_002", {
        "id": "trg_002",
        "kind": "perf_dip",
        "merchant_id": "m_001",
        "scope": "merchant",
        "urgency": 2,
        "suppression_key": "perf_dip_m_001_different",
        "expires_at": EXPIRES_FUTURE,
        "payload": {}
    }, version=1)

    # Second tick: different trigger with different suppression_key should be allowed
    r2 = tick(["trg_002"])
    assert len(r2.json()["actions"]) >= 1, "Different trigger in separate tick should not be blocked"


# -----------------------------------------------------------------------
# Test 10: Action response shape matches API contract exactly
# -----------------------------------------------------------------------
def test_tick_response_shape():
    push("category", "dentists", CATEGORY_DENTISTS)
    push("merchant", "m_001", MERCHANT_DENTIST)
    push("trigger", "trg_001", TRIGGER_RESEARCH)

    r = tick(["trg_001"])
    assert r.status_code == 200

    actions = r.json()["actions"]
    if not actions:
        pytest.skip("No actions returned; composition or guardrails filtered this trigger")

    a = actions[0]
    required_fields = [
        "conversation_id", "merchant_id", "send_as", "trigger_id",
        "template_name", "template_params", "body", "cta",
        "suppression_key", "rationale"
    ]
    for field in required_fields:
        assert field in a, f"Missing field: {field}"

    assert a["send_as"] in ("vera", "merchant_on_behalf")
    assert isinstance(a["template_params"], list)
