"""
Unit tests for Phase 4: Deterministic message composition.
Tests provenance binding, category voice, and CTA validity across trigger kinds.
"""

import pytest
from app.engine.signal_extractor import GroundedSignals
from app.engine.composer.deterministic import deterministic_composer


def create_mock_signals(kind: str, category_slug: str = "dentists", **overrides) -> GroundedSignals:
    defaults = {
        "category_slug": category_slug,
        "merchant_id": "m_001_drmeera",
        "customer_id": None,
        "trigger_id": f"trg_{kind}_001",
        "trigger_kind": kind,
        "urgency": 2,
        "suppression_key": f"supp:{kind}:1",
        "voice_tone": "peer_clinical",
        "allowed_vocab": ["fluoride", "scaling"],
        "taboo_vocab": ["cure", "guaranteed"],
        "peer_avg_ctr": 0.030,
        "peer_avg_rating": 4.4,
        "peer_avg_reviews": 62,
        "digest_item": {
            "id": "d_1",
            "title": "3-month fluoride recall cuts caries 38% better",
            "source": "JIDA Oct 2026, p.14",
            "trial_n": 2100
        },
        "catalog_offers": [{"title": "Dental Cleaning @ ₹299"}],
        "merchant_name": "Dr. Meera's Dental Clinic",
        "owner_name": "Meera",
        "locality": "Lajpat Nagar",
        "city": "Delhi",
        "languages": ["en", "hi"],
        "is_verified": True,
        "subscription_status": "active",
        "days_remaining": 82,
        "days_since_expiry": None,
        "perf_views": 2410,
        "perf_calls": 18,
        "perf_directions": 45,
        "perf_ctr": 0.021,
        "delta_views_pct": 0.18,
        "delta_calls_pct": -0.05,
        "active_offers": [{"title": "Dental Cleaning @ ₹299", "status": "active"}],
        "customer_aggregate": {"high_risk_adult_count": 124, "total_unique_ytd": 540},
        "merchant_signals": ["high_risk_adult_cohort"],
        "payload": {}
    }
    defaults.update(overrides)
    return GroundedSignals(**defaults)


def test_research_digest_composition():
    s = create_mock_signals("research_digest")
    out = deterministic_composer.compose(s)

    assert out.send_as == "vera"
    assert "Dr. Meera" in out.body
    assert "JIDA Oct 2026, p.14" in out.body
    assert "2,100-patient trial" in out.body
    assert "124 high-risk adult patients" in out.body
    assert out.cta == "open_ended"
    assert "https://" not in out.body
    assert "cure" not in out.body.lower()


def test_recall_due_composition():
    s = create_mock_signals(
        "recall_due",
        customer_id="c_001_priya",
        customer_name="Priya",
        customer_lang="hi-en mix",
        payload={
            "available_slots": [
                {"label": "Wed 5 Nov, 6pm"},
                {"label": "Thu 6 Nov, 5pm"}
            ]
        }
    )
    out = deterministic_composer.compose(s)

    assert out.send_as == "merchant_on_behalf"
    assert "Hi Priya" in out.body
    assert "Wed 5 Nov, 6pm" in out.body
    assert "Thu 6 Nov, 5pm" in out.body
    assert "₹299" in out.body
    assert out.cta == "multi_choice_slot"


def test_perf_dip_composition():
    s = create_mock_signals(
        "perf_dip",
        payload={"metric": "calls", "delta_pct": -0.50, "vs_baseline": 12}
    )
    out = deterministic_composer.compose(s)

    assert out.send_as == "vera"
    assert "50%" in out.body
    assert "12" in out.body
    assert out.cta == "binary_yes_no"


def test_ipl_match_composition():
    s = create_mock_signals(
        "ipl_match_today",
        category_slug="restaurants",
        merchant_name="SK Pizza Junction",
        owner_name="Suresh",
        active_offers=[{"title": "Buy 1 Pizza Get 1 Free (Tue-Thu)"}],
        payload={"match": "DC vs MI", "venue": "Arun Jaitley Stadium", "is_weeknight": False}
    )
    out = deterministic_composer.compose(s)

    assert out.send_as == "vera"
    assert "Suresh" in out.body
    assert "DC vs MI" in out.body
    assert "-12%" in out.body
    assert "delivery" in out.body.lower()
    assert out.cta == "binary_yes_no"


def test_supply_alert_composition():
    s = create_mock_signals(
        "supply_alert",
        category_slug="pharmacies",
        merchant_name="Apollo Health Plus",
        owner_name="Ramesh",
        customer_aggregate={"chronic_rx_count": 22},
        payload={
            "molecule": "atorvastatin",
            "affected_batches": ["AT2024-1102", "AT2024-1108"],
            "manufacturer": "Mfr Z"
        }
    )
    out = deterministic_composer.compose(s)

    assert out.send_as == "vera"
    assert "Ramesh" in out.body
    assert "AT2024-1102" in out.body
    assert "22 of your chronic patients" in out.body
    assert out.cta == "binary_yes_no"
