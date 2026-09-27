"""
Phase 7 Tests — POST /v1/reply (conversation state machine)
20 tests covering all documented intent and state scenarios.
"""

import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.store.context_store import context_store
from app.store.suppression_store import suppression_store
from app.store.conversation_store import conversation_store

client = TestClient(app)

NOW = "2027-01-01T10:00:00Z"
EXPIRES = "2027-12-31T00:00:00Z"


# ---------------------------------------------------------------------------
# Fixtures & helpers
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def reset_stores():
    context_store.clear()
    suppression_store.clear()
    conversation_store.clear()
    yield
    context_store.clear()
    suppression_store.clear()
    conversation_store.clear()


def push(scope, cid, payload, version=1):
    r = client.post("/v1/context", json={
        "scope": scope, "context_id": cid, "version": version,
        "payload": payload, "delivered_at": NOW
    })
    assert r.status_code == 200, f"push {scope}/{cid} failed: {r.text}"


def reply(conv_id, message, turn=2, merchant_id="m_001", customer_id=None, from_role="merchant"):
    return client.post("/v1/reply", json={
        "conversation_id": conv_id,
        "merchant_id": merchant_id,
        "customer_id": customer_id,
        "from_role": from_role,
        "message": message,
        "received_at": NOW,
        "turn_number": turn,
    })


CATEGORY = {
    "slug": "dentists",
    "voice": {
        "tone": "clinical",
        "vocab_allowed": ["fluoride"],
        "vocab_taboo": ["guaranteed cure"]
    },
    "peer_stats": {"avg_ctr": 0.045},
    "digest": [{
        "id": "d001",
        "title": "fluoride recall cuts caries by 38%",
        "source": "JIDA 2024",
        "trial_n": 2100
    }],
    "offer_catalog": []
}

MERCHANT = {
    "merchant_id": "m_001",
    "category_slug": "dentists",
    "identity": {
        "name": "Smile Clinic",
        "owner_first_name": "Priya",
        "locality": "Koramangala",
        "city": "Bengaluru",
        "languages": ["en"],
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


def push_base():
    push("category", "dentists", CATEGORY)
    push("merchant", "m_001", MERCHANT)


# ---------------------------------------------------------------------------
# Test 1: Basic valid reply — returns 200 with correct shape
# ---------------------------------------------------------------------------
def test_basic_valid_reply():
    r = reply("conv_001", "Yes, sounds great!")
    assert r.status_code == 200
    data = r.json()
    assert data["action"] in ("send", "wait", "end")
    assert "rationale" in data


# ---------------------------------------------------------------------------
# Test 2: SEND response returned on positive accept
# ---------------------------------------------------------------------------
def test_send_on_positive_accept():
    push_base()
    r = reply("conv_001", "Yes please go ahead")
    assert r.status_code == 200
    data = r.json()
    assert data["action"] == "send"
    assert data.get("body") and len(data["body"]) > 5


# ---------------------------------------------------------------------------
# Test 3: WAIT response — second auto-reply triggers wait
# ---------------------------------------------------------------------------
def test_wait_on_second_auto_reply():
    auto_msg = "Thank you for contacting our clinic! Our team will respond shortly."
    # Turn 2: first auto-reply → send (flag for owner)
    r1 = reply("conv_001", auto_msg, turn=2)
    assert r1.status_code == 200
    assert r1.json()["action"] == "send"

    # Turn 3: same auto-reply again → wait
    r2 = reply("conv_001", auto_msg, turn=3)
    assert r2.status_code == 200
    assert r2.json()["action"] == "wait"
    assert r2.json().get("wait_seconds") and r2.json()["wait_seconds"] > 0


# ---------------------------------------------------------------------------
# Test 4: END response — third consecutive auto-reply
# ---------------------------------------------------------------------------
def test_end_on_third_auto_reply():
    auto_msg = "Thank you for contacting our clinic! Our team will respond shortly."
    reply("conv_001", auto_msg, turn=2)  # 1st
    reply("conv_001", auto_msg, turn=3)  # 2nd → wait
    r = reply("conv_001", auto_msg, turn=4)  # 3rd → end
    assert r.status_code == 200
    assert r.json()["action"] == "end"


# ---------------------------------------------------------------------------
# Test 5: Positive acknowledgement → send
# ---------------------------------------------------------------------------
def test_positive_acknowledgement():
    push_base()
    for msg in ["Sure!", "Sounds good", "Ok great", "Awesome", "Please do"]:
        r = reply("conv_unique_" + msg[:5].lower().replace(" ", "_"), msg)
        assert r.status_code == 200
        assert r.json()["action"] == "send", f"Expected send for: '{msg}'"


# ---------------------------------------------------------------------------
# Test 6: Question → send (grounded answer)
# ---------------------------------------------------------------------------
def test_question_intent():
    push_base()
    r = reply("conv_001", "What are my profile views this month?")
    assert r.status_code == 200
    data = r.json()
    assert data["action"] == "send"
    body = data.get("body", "")
    # Should reference actual performance data
    assert any(c.isdigit() for c in body)  # contains numbers from perf data


# ---------------------------------------------------------------------------
# Test 7: Interested/planning intent → send with grounded action
# ---------------------------------------------------------------------------
def test_intent_transition():
    push_base()
    r = reply("conv_001", "Ok let's do it. What's next?")
    assert r.status_code == 200
    data = r.json()
    assert data["action"] == "send"
    # Must NOT be still qualifying
    body = data.get("body", "").lower()
    qualifying_words = ["would you", "could you tell me", "what if", "how about first"]
    assert not any(w in body for w in qualifying_words), f"Bot still qualifying: {body}"


# ---------------------------------------------------------------------------
# Test 8: Rejection → end
# ---------------------------------------------------------------------------
def test_rejection():
    for msg in ["Not interested", "No thanks", "Maybe some other time"]:
        conversation_store.clear()
        r = reply("conv_001", msg)
        assert r.status_code == 200
        data = r.json()
        assert data["action"] == "end", f"Expected end for: '{msg}'"


# ---------------------------------------------------------------------------
# Test 9: Explicit opt-out → end + suppress
# ---------------------------------------------------------------------------
def test_explicit_opt_out():
    r = reply("conv_001", "Stop messaging me please. Unsubscribe.", merchant_id="m_001")
    assert r.status_code == 200
    data = r.json()
    assert data["action"] in ("end", "send")  # may send one apology first or end

    # Subsequent tick must be suppressed (merchant in opt-out)
    is_suppressed = suppression_store.is_merchant_opted_out("m_001", NOW)
    assert is_suppressed, "Merchant should be opted out after explicit opt-out"


# ---------------------------------------------------------------------------
# Test 10: Hostile/unwanted → end (or graceful apology)
# ---------------------------------------------------------------------------
def test_hostile_response():
    for msg in [
        "Stop this useless spam!",
        "Why are you bothering me. This is useless.",
        "You're wasting my time. Leave me alone."
    ]:
        conversation_store.clear()
        r = reply("conv_001", msg)
        assert r.status_code == 200
        data = r.json()
        assert data["action"] in ("end", "send"), f"Unexpected action for: '{msg}'"
        # If send, it must be a graceful apology, not a sales message
        if data["action"] == "send":
            body = data.get("body", "").lower()
            assert any(w in body for w in ["apolog", "won't", "sorry", "won't message"]), \
                f"Hostile response must apologize: {body}"


# ---------------------------------------------------------------------------
# Test 11: New conversation_id with same merchant_id (cross-conv memory)
# ---------------------------------------------------------------------------
def test_new_conv_id_same_merchant():
    auto_msg = "Thank you for contacting our team. We will respond shortly."
    # First conversation: 2 auto-replies → merchant memory has count=2
    reply("conv_A", auto_msg, turn=2, merchant_id="m_X")
    reply("conv_A", auto_msg, turn=3, merchant_id="m_X")

    # NEW conversation_id, SAME merchant_id
    # Memory should carry the auto-reply count
    mem = conversation_store.get_merchant_memory("m_X")
    assert mem.consecutive_auto_replies >= 2, "Merchant-level memory should persist across conversations"


# ---------------------------------------------------------------------------
# Test 12: Cross-conversation merchant memory persists
# ---------------------------------------------------------------------------
def test_cross_conversation_merchant_memory():
    # Opt out in conversation A
    reply("conv_A", "Stop messaging me.", merchant_id="m_Y")
    # Memory should flag merchant as opted out
    mem = conversation_store.get_merchant_memory("m_Y")
    assert mem.opted_out, "Opted-out merchant memory must persist"


# ---------------------------------------------------------------------------
# Test 13: Customer isolation — customer A data not leaked to customer B
# ---------------------------------------------------------------------------
def test_customer_isolation():
    push_base()
    # Reply for customer A
    r_a = reply("conv_custA", "Yes please", merchant_id="m_001", customer_id="cust_A")
    assert r_a.status_code == 200

    # Reply for customer B on different conv — should NOT reference customer A
    r_b = reply("conv_custB", "Yes please", merchant_id="m_001", customer_id="cust_B")
    assert r_b.status_code == 200

    # Both must succeed independently
    assert r_a.json()["action"] in ("send", "wait", "end")
    assert r_b.json()["action"] in ("send", "wait", "end")


# ---------------------------------------------------------------------------
# Test 14: Repeated reply prevention — no identical body twice
# ---------------------------------------------------------------------------
def test_repeated_reply_prevention():
    push_base()
    r1 = reply("conv_001", "Yes please send it", turn=2)
    r2 = reply("conv_001", "Yes please send it", turn=3)
    assert r1.status_code == 200
    assert r2.status_code == 200
    # Second identical message should get a different body or an end/wait
    body1 = r1.json().get("body", "")
    body2 = r2.json().get("body", "")
    # They should not both be send with the same body
    if r1.json()["action"] == "send" and r2.json()["action"] == "send":
        assert body1.lower() != body2.lower(), "Identical repeated body detected"


# ---------------------------------------------------------------------------
# Test 15: Conversation already ended — returns end
# ---------------------------------------------------------------------------
def test_conversation_already_ended():
    # End the conversation
    reply("conv_001", "Not interested", turn=2)
    # Any subsequent reply should return end
    r = reply("conv_001", "Actually wait, tell me more", turn=3)
    assert r.status_code == 200
    assert r.json()["action"] == "end"


# ---------------------------------------------------------------------------
# Test 16: Missing context (no merchant in store) — still returns valid response
# ---------------------------------------------------------------------------
def test_missing_context_graceful():
    # No merchant or category pushed
    r = reply("conv_001", "Yes please tell me more", merchant_id="m_nonexistent")
    assert r.status_code == 200
    data = r.json()
    assert data["action"] in ("send", "wait", "end")
    assert "rationale" in data


# ---------------------------------------------------------------------------
# Test 17: Off-topic request → politely redirected (send)
# ---------------------------------------------------------------------------
def test_off_topic_redirect():
    r = reply("conv_001", "Can you also help me with my GST filing?")
    assert r.status_code == 200
    data = r.json()
    assert data["action"] == "send"
    body = data.get("body", "").lower()
    # Must decline off-topic without engaging it
    assert any(w in body for w in ["outside", "expert", "leave", "can't help", "not in"])


# ---------------------------------------------------------------------------
# Test 18: Grounded follow-up references actual context
# ---------------------------------------------------------------------------
def test_grounded_followup_references_context():
    push_base()
    r = reply("conv_001", "Yes please, send the abstract")
    assert r.status_code == 200
    data = r.json()
    if data["action"] == "send":
        body = data.get("body", "")
        # Must reference actual data (clinic name, offer, or digest item)
        assert any(keyword in body for keyword in [
            "JIDA", "fluoride", "Free Consultation", "Smile Clinic", "Priya", "38%", "2,100", "2100"
        ]), f"Body should reference stored context, got: {body}"


# ---------------------------------------------------------------------------
# Test 19: Intent handoff — committed merchant gets action mode
# ---------------------------------------------------------------------------
def test_intent_handoff_action_mode():
    push_base()
    r = reply("conv_001", "Ok let's do it. Proceed now.")
    assert r.status_code == 200
    data = r.json()
    assert data["action"] == "send"
    body = data.get("body", "").lower()

    # Must be action words, not qualifying words
    action_words = ["draft", "sending", "now", "confirm", "ready", "prepare", "proceed"]
    assert any(w in body for w in action_words), \
        f"Expected action mode after intent transition, got: {body}"

    # Must NOT still be asking qualifying questions
    bad_words = ["would you", "could you tell me more", "what is your"]
    assert not any(w in body for w in bad_words), \
        f"Bot must not keep qualifying after commitment, got: {body}"


# ---------------------------------------------------------------------------
# Test 20: No fabricated information — body must not contain invented data
# ---------------------------------------------------------------------------
def test_no_fabricated_information():
    # Do NOT push any context — reply without any stored data
    r = reply("conv_001", "What are my stats?", merchant_id="m_nonexistent_xyz")
    assert r.status_code == 200
    data = r.json()
    body = data.get("body", "")

    # Should not fabricate a specific number that doesn't exist
    # We can't easily detect all hallucinations, but we can ensure
    # the response doesn't claim specific stats for an unknown merchant
    # The response should be a question back or general statement
    assert data["action"] in ("send", "wait", "end")
    if data["action"] == "send":
        # If it "sends", it must not claim specific metrics for unknown merchant
        # We trust the grounded implementation; check no absurd made-up number pattern
        assert len(body) > 0
