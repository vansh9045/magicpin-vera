"""
Unit tests for Phase 1: Models and in-memory stores.
"""

import pytest
from app.config import METADATA, BOT_START_TIME
from app.models.api import (
    HealthzResponse, MetadataResponse, ContextPushRequest,
    TickRequest, ActionItem, TickResponse, ReplyRequest, ReplyResponse
)
from app.models.context import CategoryContext, MerchantContext, CustomerContext, TriggerContext
from app.models.conversation import ConversationState, ConversationTurn
from app.store.context_store import context_store
from app.store.conversation_store import conversation_store
from app.store.suppression_store import suppression_store


def test_models_instantiation():
    health = HealthzResponse(
        status="ok",
        uptime_seconds=10,
        contexts_loaded={"category": 5, "merchant": 50, "customer": 200, "trigger": 0}
    )
    assert health.status == "ok"
    assert health.contexts_loaded.merchant == 50

    meta = MetadataResponse(**METADATA)
    assert meta.team_name == "Vansh"

    action = ActionItem(
        conversation_id="conv_1",
        merchant_id="m_001",
        send_as="vera",
        trigger_id="trg_1",
        template_name="tmpl_1",
        body="Test message",
        cta="open_ended",
        suppression_key="key_1",
        rationale="Test rationale"
    )
    assert action.send_as == "vera"


def test_context_store_versioning():
    context_store.clear()

    # Initial push v1 -> success
    ok, ack, ver = context_store.push("merchant", "m_001", 1, {"name": "Meera"}, "2026-04-26T00:00:00Z")
    assert ok is True
    assert ack == "ack_m_001_v1"
    assert context_store.get_counts()["merchant"] == 1

    # Idempotent push v1 again -> success (no-op, does not duplicate state)
    ok, ack, ver = context_store.push("merchant", "m_001", 1, {"name": "Meera"}, "2026-04-26T00:00:00Z")
    assert ok is True
    assert ack == "ack_m_001_v1"
    assert context_store.get_counts()["merchant"] == 1
    assert context_store.get_merchant("m_001")["name"] == "Meera"

    # Stale push lower version 0 -> conflict
    ok, reason, cur_ver = context_store.push("merchant", "m_001", 0, {"name": "Meera"}, "2026-04-26T00:00:00Z")
    assert ok is False
    assert reason == "stale_version"
    assert cur_ver == 1

    # Higher version v2 -> success and atomic replacement
    ok, ack, ver = context_store.push("merchant", "m_001", 2, {"name": "Meera Updated"}, "2026-04-26T01:00:00Z")
    assert ok is True
    assert ack == "ack_m_001_v2"
    assert context_store.get_merchant("m_001")["name"] == "Meera Updated"
    assert context_store.get_version("merchant", "m_001") == 2


def test_conversation_and_suppression():
    conversation_store.clear()
    suppression_store.clear()

    conv = conversation_store.get_or_create("conv_test", merchant_id="m_001")
    assert conv.conversation_id == "conv_test"

    turn = ConversationTurn(
        from_role="vera",
        body="Dr. Meera, JIDA Oct issue landed...",
        timestamp="2026-04-26T10:00:00Z",
        turn_number=1,
        cta="open_ended",
        rationale="initial hook"
    )
    conversation_store.add_turn("conv_test", turn, merchant_id="m_001")

    # Anti-repetition check
    assert conversation_store.has_sent_body("conv_test", "Dr. Meera, JIDA Oct issue landed...") is True
    assert conversation_store.has_sent_body("conv_test", "Different message") is False

    # Suppression key test
    suppression_store.record_key("key:123", "2026-05-01T00:00:00Z")
    assert suppression_store.is_key_suppressed("key:123", "2026-04-26T10:00:00Z") is True
    assert suppression_store.is_key_suppressed("key:123", "2026-05-02T00:00:00Z") is False
