"""
Unit tests for Phase 3:
- Context resolution
- Trigger validation
- Signal extraction
- Scoring and candidate selection
"""

import pytest
from app.store.context_store import context_store
from app.store.suppression_store import suppression_store
from app.engine.context_resolver import context_resolver
from app.engine.trigger_validator import trigger_validator
from app.engine.signal_extractor import signal_extractor
from app.engine.scoring import candidate_scorer, candidate_selector


@pytest.fixture(autouse=True)
def clean_stores():
    context_store.clear()
    suppression_store.clear()


def test_context_resolver_success():
    # Setup Category, Merchant, Customer, Trigger
    context_store.push("category", "dentists", 1, {"slug": "dentists", "display_name": "Dentists"}, "2026-04-26T00:00:00Z")
    context_store.push("merchant", "m_001", 1, {"merchant_id": "m_001", "category_slug": "dentists", "identity": {"name": "Dr. Meera"}}, "2026-04-26T00:00:00Z")
    context_store.push("customer", "c_001", 1, {"customer_id": "c_001", "merchant_id": "m_001", "identity": {"name": "Priya"}}, "2026-04-26T00:00:00Z")
    context_store.push("trigger", "trg_001", 1, {
        "id": "trg_001", "scope": "customer", "merchant_id": "m_001", "customer_id": "c_001",
        "kind": "recall_due", "urgency": 3, "expires_at": "2026-05-30T00:00:00Z"
    }, "2026-04-26T00:00:00Z")

    resolved = context_resolver.resolve("trg_001")
    assert resolved.valid is True
    assert resolved.merchant["identity"]["name"] == "Dr. Meera"
    assert resolved.category["slug"] == "dentists"
    assert resolved.customer["identity"]["name"] == "Priya"


def test_context_resolver_missing_merchant():
    context_store.push("trigger", "trg_002", 1, {
        "id": "trg_002", "scope": "merchant", "merchant_id": "m_nonexistent",
        "kind": "perf_dip", "urgency": 4
    }, "2026-04-26T00:00:00Z")

    resolved = context_resolver.resolve("trg_002")
    assert resolved.valid is False
    assert "not found" in resolved.error


def test_trigger_validator():
    context_store.push("category", "dentists", 1, {"slug": "dentists"}, "2026-04-26T00:00:00Z")
    context_store.push("merchant", "m_001", 1, {"merchant_id": "m_001", "category_slug": "dentists", "identity": {"name": "Meera"}}, "2026-04-26T00:00:00Z")
    
    # 1. Expired trigger
    context_store.push("trigger", "trg_exp", 1, {
        "id": "trg_exp", "scope": "merchant", "merchant_id": "m_001",
        "kind": "research_digest", "expires_at": "2026-04-20T00:00:00Z"
    }, "2026-04-26T00:00:00Z")
    resolved = context_resolver.resolve("trg_exp")
    valid, reason = trigger_validator.validate(resolved, now_iso="2026-04-26T10:00:00Z")
    assert valid is False
    assert "expired" in reason

    # 2. Suppressed trigger
    context_store.push("trigger", "trg_supp", 1, {
        "id": "trg_supp", "scope": "merchant", "merchant_id": "m_001",
        "kind": "research_digest", "suppression_key": "supp:key:1", "expires_at": "2026-05-20T00:00:00Z"
    }, "2026-04-26T00:00:00Z")
    suppression_store.record_key("supp:key:1", "2026-05-01T00:00:00Z")
    resolved = context_resolver.resolve("trg_supp")
    valid, reason = trigger_validator.validate(resolved, now_iso="2026-04-26T10:00:00Z")
    assert valid is False
    assert "Suppression key" in reason


def test_signal_extraction_and_scoring():
    cat = {
        "slug": "dentists",
        "digest": [{"id": "d_1", "title": "Fluoride Study", "source": "JIDA Oct 2026, p.14"}],
        "voice": {"tone": "peer_clinical", "vocab_taboo": ["cure"]}
    }
    merchant = {
        "merchant_id": "m_001",
        "category_slug": "dentists",
        "identity": {"name": "Dr. Meera's Clinic", "owner_first_name": "Meera", "locality": "Lajpat Nagar"},
        "subscription": {"status": "active"},
        "performance": {"views": 2400, "calls": 18, "delta_7d": {"calls_pct": -0.5}},
        "signals": ["high_risk_adult_cohort"]
    }
    trigger = {
        "id": "trg_1", "scope": "merchant", "merchant_id": "m_001",
        "kind": "research_digest", "urgency": 2, "suppression_key": "supp_1",
        "expires_at": "2026-05-30T00:00:00Z",
        "payload": {"top_item_id": "d_1", "fluoride_info": "fluoride study"}
    }

    context_store.push("category", "dentists", 1, cat, "2026-04-26T00:00:00Z")
    context_store.push("merchant", "m_001", 1, merchant, "2026-04-26T00:00:00Z")
    context_store.push("trigger", "trg_1", 1, trigger, "2026-04-26T00:00:00Z")

    resolved = context_resolver.resolve("trg_1")
    signals = signal_extractor.extract(resolved)

    assert signals.owner_name == "Meera"
    assert signals.digest_item["source"] == "JIDA Oct 2026, p.14"
    assert signals.delta_calls_pct == -0.5

    # Scoring
    score = candidate_scorer.score(signals)
    assert score > 50  # Urgency 40 + study 20 + signals 15 + sub 5

    # Selection constraint test
    candidates = [(resolved, signals)]
    selected = candidate_selector.rank_and_select(candidates, max_actions=20)
    assert len(selected) == 1
    assert selected[0][1].merchant_id == "m_001"
