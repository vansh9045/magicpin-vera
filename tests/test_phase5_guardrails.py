"""
Unit tests for Phase 5: Guardrails Engine.
Tests URL blocking, category taboos, internal jargon, expired offers, and repetition prevention.
"""

import pytest
from app.engine.composer.base import ComposedOutput
from app.engine.guardrails import guardrails
from app.store.conversation_store import conversation_store
from app.models.conversation import ConversationTurn


@pytest.fixture(autouse=True)
def clean():
    conversation_store.clear()


def make_output(body: str, cta: str = "binary_yes_no") -> ComposedOutput:
    return ComposedOutput(
        conversation_id="conv_guard_1",
        merchant_id="m_001",
        customer_id=None,
        send_as="vera",
        trigger_id="trg_1",
        template_name="tmpl_1",
        template_params=["Dr. Meera"],
        body=body,
        cta=cta,
        suppression_key="supp_1",
        rationale="Guardrail test"
    )


def test_url_blocking_and_sanitization():
    out = make_output("Check this out at https://magicpin.com/blog now! Want me to send the abstract?")
    valid, reason, sanitized = guardrails.validate(out)
    assert valid is True
    assert "https://" not in sanitized.body
    assert "magicpin.com" not in sanitized.body


def test_category_taboo_blocking():
    category = {
        "slug": "dentists",
        "voice": {"vocab_taboo": ["completely cure", "guaranteed", "100% safe"]}
    }
    out = make_output("We offer a completely cure treatment for caries. Want me to draft a post?")
    valid, reason, sanitized = guardrails.validate(out, category=category)
    assert "completely cure" not in sanitized.body.lower()


def test_internal_jargon_blocking():
    out = make_output("Processing payload for triggercontext trg_001. Want me to help?")
    valid, reason, _ = guardrails.validate(out)
    assert valid is False
    assert "jargon" in reason


def test_expired_offer_blocking():
    merchant = {
        "merchant_id": "m_001",
        "offers": [
            {"title": "Dental Cleaning @ ₹299", "status": "active"},
            {"title": "Deep Cleaning @ ₹499", "status": "expired"}
        ]
    }
    out = make_output("Pushing Deep Cleaning @ ₹499 special this week. Want me to draft it?")
    valid, reason, _ = guardrails.validate(out, merchant=merchant)
    assert valid is False
    assert "expired offer" in reason


def test_anti_repetition_blocking():
    conv_id = "conv_guard_rep"
    body = "Dr. Meera, JIDA's Oct issue landed with a 2,100-patient trial. Want to review?"

    turn = ConversationTurn(
        from_role="vera",
        body=body,
        timestamp="2026-04-26T10:00:00Z",
        turn_number=1
    )
    conversation_store.add_turn(conv_id, turn, merchant_id="m_001")

    out = make_output(body)
    out.conversation_id = conv_id
    valid, reason, _ = guardrails.validate(out, conversation_id=conv_id)
    assert valid is False
    assert "repetition" in reason


def test_valid_message_passes():
    out = make_output("Dr. Meera, JIDA Oct issue landed with a 2,100-patient trial. Want me to pull the abstract?")
    valid, reason, _ = guardrails.validate(out)
    assert valid is True
    assert reason == "Passed all guardrails"
