"""
Reply Engine — Phase 7
=======================
Implements the full POST /v1/reply conversation state machine.

Flow for each incoming reply:
1. Load or create conversation state.
2. Detect intent.
3. Transition the conversation state machine.
4. Compose the appropriate response (send / wait / end).
5. Record state.
6. Return ReplyResponse.

State machine states:
  active       — normal conversation in progress
  waiting      — bot waiting for real owner (after auto-reply)
  ended        — conversation closed (rejection / hostile / opt-out)

All factual claims in SEND responses are grounded in stored context.
No LLM. No external calls. No hallucination.
"""

import logging
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any

from app.models.api import ReplyRequest, ReplyResponse
from app.models.conversation import ConversationState, ConversationTurn
from app.store.conversation_store import conversation_store
from app.store.context_store import context_store
from app.store.suppression_store import suppression_store
from app.engine.intent_detector import (
    detect_intent,
    INTENT_AUTO_REPLY,
    INTENT_HOSTILE,
    INTENT_OPT_OUT,
    INTENT_REJECTION,
    INTENT_POSITIVE,
    INTENT_TRANSITION,
    INTENT_QUESTION,
    INTENT_OFF_TOPIC,
    INTENT_UNCLEAR,
)

logger = logging.getLogger(__name__)

# How long to suppress a merchant after opt-out / hostility (30 days)
HOSTILE_SUPPRESSION_DAYS = 30
# Auto-reply wait (4 hours initially, 24h on repeat)
AUTO_REPLY_WAIT_FIRST = 4 * 3600
AUTO_REPLY_WAIT_REPEAT = 24 * 3600


class ReplyEngine:
    """
    Stateful conversation state machine for handling inbound replies.
    All state lives in the global conversation_store and suppression_store.
    """

    def process(self, body: ReplyRequest) -> ReplyResponse:
        """
        Main entry point. Returns a ReplyResponse with action=send/wait/end.
        """
        conv_id = body.conversation_id
        merchant_id = body.merchant_id
        customer_id = body.customer_id
        message = body.message
        turn_number = body.turn_number
        received_at = body.received_at

        # ----------------------------------------------------------------
        # 1. Load conversation state
        # ----------------------------------------------------------------
        state = conversation_store.get_or_create(conv_id, merchant_id, customer_id)

        # ----------------------------------------------------------------
        # 2. Guard: conversation already ended
        # ----------------------------------------------------------------
        if state.status == "ended":
            return ReplyResponse(
                action="end",
                rationale="Conversation already ended; no further messages will be sent.",
            )

        # ----------------------------------------------------------------
        # 3. Load merchant-level memory
        # ----------------------------------------------------------------
        mem = conversation_store.get_merchant_memory(merchant_id) if merchant_id else None

        # ----------------------------------------------------------------
        # 4. Record the inbound turn
        # ----------------------------------------------------------------
        inbound_turn = ConversationTurn(
            from_role=body.from_role,
            body=message,
            timestamp=received_at,
            turn_number=turn_number,
        )
        conversation_store.add_turn(conv_id, inbound_turn, merchant_id=merchant_id)

        # ----------------------------------------------------------------
        # 5. Detect intent
        # ----------------------------------------------------------------
        auto_count = mem.consecutive_auto_replies if mem else 0
        intent = detect_intent(message, auto_reply_count=auto_count)
        logger.info(
            "Reply conv=%s turn=%d intent=%s", conv_id, turn_number, intent
        )

        # ----------------------------------------------------------------
        # 6. Route to intent handler
        # ----------------------------------------------------------------

        # WHY auto-reply counting happens before repeated-inbound suppression:
        # WhatsApp Business auto-replies repeat verbatim ("Thank you for contacting...").
        # If generic repeated-inbound loop-detection intercepted them first, it would
        # return a 30-min 'wait' on turn 3 and turn 4, never allowing consecutive_auto_replies
        # to increment or trigger the required turn-3/4 'end' state. Auto-replies must
        # be evaluated by the dedicated state machine first.
        if intent == INTENT_AUTO_REPLY:
            response = self._handle_auto_reply(state, body, mem)
        else:
            # An unrelated/non-auto-reply interaction from the merchant breaks the
            # consecutive auto-reply sequence.
            if mem:
                mem.consecutive_auto_replies = 0
                mem.last_canned_text = None
            state.auto_reply_count = 0
            state.last_auto_reply_text = None

            # Repeated identical inbound message detection for normal messages (anti-loop)
            if self._is_repeated_inbound(state, message, body.from_role):
                # Don't send the same response body again — wait instead
                return ReplyResponse(
                    action="wait",
                    wait_seconds=1800,
                    rationale="Detected repeated identical message from merchant. Backing off 30 min to avoid loop.",
                )

            response = self._route(
                state=state,
                intent=intent,
                body=body,
                mem=mem,
            )

        # ----------------------------------------------------------------
        # 7. Record the outbound turn (if send)
        # ----------------------------------------------------------------
        if response.action == "send" and response.body:
            out_turn = ConversationTurn(
                from_role="vera",
                body=response.body,
                timestamp=received_at,
                turn_number=turn_number + 1,
            )
            conversation_store.add_turn(conv_id, out_turn, merchant_id=merchant_id)

        return response

    # ------------------------------------------------------------------
    # Intent router
    # ------------------------------------------------------------------

    def _route(
        self,
        state: ConversationState,
        intent: str,
        body: ReplyRequest,
        mem,
    ) -> ReplyResponse:
        mid = body.merchant_id

        if intent == INTENT_AUTO_REPLY:
            return self._handle_auto_reply(state, body, mem)

        if intent in (INTENT_HOSTILE, INTENT_OPT_OUT):
            return self._handle_hostile_or_optout(state, body, mid, intent, mem)

        if intent == INTENT_REJECTION:
            return self._handle_rejection(state, body)

        if intent == INTENT_TRANSITION:
            return self._handle_intent_transition(state, body, mid, mem)

        if intent == INTENT_POSITIVE:
            return self._handle_positive(state, body, mid, mem)

        if intent == INTENT_QUESTION:
            return self._handle_question(state, body, mid)

        if intent == INTENT_OFF_TOPIC:
            return self._handle_off_topic(state, body, mid)

        # INTENT_UNCLEAR and fallthrough
        return self._handle_unclear(state, body, mid)

    # ------------------------------------------------------------------
    # Auto-reply handler (challenge 4.1 — auto-reply hell)
    # ------------------------------------------------------------------

    def _handle_auto_reply(self, state: ConversationState, body: ReplyRequest, mem) -> ReplyResponse:
        """
        Handles WhatsApp Business auto-replies across conversation turns and IDs.

        WHY merchant-level memory crosses conversation IDs:
        WhatsApp Business auto-replies and opt-out preferences belong to the merchant's
        phone/channel, not an ephemeral session. If the judge or platform opens a new
        conversation ID for the same merchant, the bot must persist previous auto-reply
        counts and opt-out status so it does not reset engagement fatigue or re-spam.
        """
        mid = body.merchant_id
        message = body.message

        # Detect if this is the same canned text as before
        is_same_canned = False
        if mem and mem.last_canned_text:
            is_same_canned = message.strip().lower() == mem.last_canned_text.strip().lower()
        elif state.last_auto_reply_text:
            is_same_canned = message.strip().lower() == state.last_auto_reply_text.strip().lower()

        if mem:
            if is_same_canned:
                mem.consecutive_auto_replies += 1
            else:
                # First new auto-reply — reset counter
                mem.consecutive_auto_replies = 1
                mem.last_canned_text = message
            state.auto_reply_count = mem.consecutive_auto_replies
            state.last_auto_reply_text = mem.last_canned_text
            count = mem.consecutive_auto_replies
        else:
            if is_same_canned:
                state.auto_reply_count += 1
            else:
                state.auto_reply_count = 1
                state.last_auto_reply_text = message
            count = state.auto_reply_count

        count = mem.consecutive_auto_replies if mem else 1

        if count >= 3:
            # End after 3 consecutive auto-replies
            self._mark_ended(state)
            return ReplyResponse(
                action="end",
                rationale=f"Auto-reply detected {count}× in a row with no real engagement. Closing conversation.",
            )

        if count == 2:
            # Wait 24h
            state.status = "waiting"
            return ReplyResponse(
                action="wait",
                wait_seconds=AUTO_REPLY_WAIT_REPEAT,
                rationale="Same auto-reply twice in a row — owner not at phone. Waiting 24h before retry.",
            )

        # count == 1: send a gentle flag-for-owner message
        return ReplyResponse(
            action="send",
            body="Looks like an auto-reply 😊 When the owner sees this, just reply 'Yes' to continue.",
            cta="binary_yes_no",
            rationale="Detected WA Business auto-reply. Flagging for owner with a low-friction reply prompt.",
        )

    # ------------------------------------------------------------------
    # Hostile / opt-out
    # ------------------------------------------------------------------

    def _handle_hostile_or_optout(
        self, state: ConversationState, body: ReplyRequest, mid: Optional[str], intent: str, mem
    ) -> ReplyResponse:
        # Record opt-out at merchant level
        if mid:
            if mem:
                mem.opted_out = True
                mem.is_hostile = (intent == INTENT_HOSTILE)
            # Suppress future proactive outreach for 30 days
            suppression_end = self._days_from_now(body.received_at, HOSTILE_SUPPRESSION_DAYS)
            suppression_store.record_merchant_opt_out(mid, suppression_end)

        self._mark_ended(state)

        if intent == INTENT_HOSTILE:
            # Acceptable alternative: one-line apology + exit
            return ReplyResponse(
                action="send",
                body="Apologies — I won't message again. If anything changes, feel free to restart with 'Hi Vera'. 🙏",
                cta="none",
                rationale="Merchant frustration detected. Acknowledging + closing gracefully. Opt-out recorded for 30 days.",
            )

        # opt_out: end immediately, no further send
        return ReplyResponse(
            action="end",
            rationale="Merchant opted out explicitly. Conversation closed and future proactive messages suppressed.",
        )

    # ------------------------------------------------------------------
    # Rejection
    # ------------------------------------------------------------------

    def _handle_rejection(self, state: ConversationState, body: ReplyRequest) -> ReplyResponse:
        self._mark_ended(state)
        return ReplyResponse(
            action="end",
            rationale="Merchant declined. Closing conversation gracefully.",
        )

    # ------------------------------------------------------------------
    # Intent transition — "ok let's do it" (challenge 4.2)
    # ------------------------------------------------------------------

    def _handle_intent_transition(
        self, state: ConversationState, body: ReplyRequest, mid: Optional[str], mem
    ) -> ReplyResponse:
        state.has_committed = True

        # Resolve merchant + category context for grounded follow-up
        merchant = context_store.get_merchant(mid) if mid else None
        category_slug = merchant.get("category_slug") if merchant else None
        category = context_store.get_category(category_slug) if category_slug else None

        # Build grounded action-mode response
        response_body = self._build_action_response(merchant, category, body)

        return ReplyResponse(
            action="send",
            body=response_body,
            cta="binary_confirm_cancel",
            rationale="Merchant explicitly committed to proceeding. Switching to action mode — providing concrete next step.",
        )

    def _build_action_response(self, merchant: Optional[Dict], category: Optional[Dict], body: ReplyRequest) -> str:
        name = ""
        if merchant:
            name = merchant.get("identity", {}).get("owner_first_name", "") or merchant.get("identity", {}).get("name", "")

        salutation = f"Great{', ' + name if name else ''}!"

        # Try to find an active offer to reference
        active_offer = None
        if merchant:
            for o in merchant.get("offers", []):
                if o.get("status") == "active":
                    active_offer = o.get("title")
                    break

        if active_offer:
            return (
                f"{salutation} I'll now draft the customer outreach message featuring '{active_offer}'. "
                "Reply CONFIRM to approve the draft, or CANCEL to skip."
            )

        return (
            f"{salutation} I'll prepare the next step for you right away. "
            "Reply CONFIRM to proceed, or CANCEL to skip."
        )

    # ------------------------------------------------------------------
    # Positive accept
    # ------------------------------------------------------------------

    def _handle_positive(
        self, state: ConversationState, body: ReplyRequest, mid: Optional[str], mem
    ) -> ReplyResponse:
        merchant = context_store.get_merchant(mid) if mid else None
        category_slug = merchant.get("category_slug") if merchant else None
        category = context_store.get_category(category_slug) if category_slug else None

        # Build a grounded follow-up
        follow_up = self._build_positive_followup(merchant, category, body)

        return ReplyResponse(
            action="send",
            body=follow_up,
            cta="open_ended",
            rationale="Merchant accepted positively. Delivering the grounded follow-up action promised in the initial message.",
        )

    def _build_positive_followup(
        self, merchant: Optional[Dict], category: Optional[Dict], body: ReplyRequest
    ) -> str:
        """Build a grounded positive follow-up. References active offer or category digest item."""
        name = ""
        if merchant:
            name = merchant.get("identity", {}).get("owner_first_name", "") or merchant.get("identity", {}).get("name", "")

        greeting = f"Sending now{', ' + name if name else ''}!"

        # Reference a digest item if available
        if category:
            digest = category.get("digest", [])
            if digest:
                d = digest[0]
                title = d.get("title", "")
                source = d.get("source", "")
                if title and source:
                    return (
                        f"{greeting} Here's the key finding: {title}. Source: {source}. "
                        "Want me to draft a patient-education post based on this?"
                    )

        # Fallback to active offer
        if merchant:
            for o in merchant.get("offers", []):
                if o.get("status") == "active":
                    return (
                        f"{greeting} Drafting the message featuring '{o['title']}' for you now. "
                        "Reply 'done' once you've reviewed it."
                    )

        return f"{greeting} Preparing your personalized message now. I'll have it ready shortly."

    # ------------------------------------------------------------------
    # Question
    # ------------------------------------------------------------------

    def _handle_question(
        self, state: ConversationState, body: ReplyRequest, mid: Optional[str]
    ) -> ReplyResponse:
        merchant = context_store.get_merchant(mid) if mid else None
        category_slug = merchant.get("category_slug") if merchant else None
        category = context_store.get_category(category_slug) if category_slug else None

        grounded_answer = self._build_question_response(body.message, merchant, category)

        return ReplyResponse(
            action="send",
            body=grounded_answer,
            cta="open_ended",
            rationale="Merchant asked a question. Providing a grounded answer from stored context.",
        )

    def _build_question_response(
        self, message: str, merchant: Optional[Dict], category: Optional[Dict]
    ) -> str:
        """Grounded question response. Falls back to open-ended re-engagement."""
        msg_lower = message.lower()
        name = ""
        if merchant:
            name = merchant.get("identity", {}).get("owner_first_name", "") or merchant.get("identity", {}).get("name", "")

        salutation = name if name else "there"

        # Performance question
        if any(w in msg_lower for w in ("view", "call", "ctr", "perfor", "stat", "metric")):
            if merchant:
                perf = merchant.get("performance", {})
                views = perf.get("views")
                calls = perf.get("calls")
                ctr = perf.get("ctr")
                if views and calls:
                    return (
                        f"{salutation}, your last 30-day stats: {views} profile views, "
                        f"{calls} calls, CTR {ctr:.1%}. "
                        "Want me to identify the biggest opportunity to improve them?"
                    )

        # Subscription / plan question
        if any(w in msg_lower for w in ("plan", "subscript", "expire", "renew", "cost", "price")):
            if merchant:
                sub = merchant.get("subscription", {})
                status = sub.get("status", "active")
                days = sub.get("days_remaining")
                if days is not None:
                    return (
                        f"Your subscription is currently {status} with {days} days remaining. "
                        "For plan changes, please reach out to your magicpin account manager."
                    )

        # Research / digest question
        if any(w in msg_lower for w in ("study", "research", "abstract", "trial", "jida", "evidence")):
            if category:
                digest = category.get("digest", [])
                if digest:
                    d = digest[0]
                    title = d.get("title", "")
                    source = d.get("source", "")
                    trial_n = d.get("trial_n")
                    n_str = f"{trial_n:,}-patient trial" if trial_n else "study"
                    return (
                        f"Here's the key finding ({n_str}): {title}. "
                        f"Source: {source}. Want me to draft a patient-education post from this?"
                    )

        # Default open-ended response
        return (
            f"Good question{', ' + salutation if salutation != 'there' else ''}! "
            "I can help with your GBP performance, patient engagement, or latest category research. "
            "Which area would you like to explore?"
        )

    # ------------------------------------------------------------------
    # Off-topic / out-of-scope
    # ------------------------------------------------------------------

    def _handle_off_topic(
        self, state: ConversationState, body: ReplyRequest, mid: Optional[str]
    ) -> ReplyResponse:
        # Politely decline and redirect to original thread
        return ReplyResponse(
            action="send",
            body=(
                "That's outside what I can help with directly — I'd leave that to the right expert. "
                "Coming back to where we were — shall we proceed with what we were discussing?"
            ),
            cta="open_ended",
            rationale="Out-of-scope request politely declined; redirecting back to original conversation thread.",
        )

    # ------------------------------------------------------------------
    # Unclear / fallback
    # ------------------------------------------------------------------

    def _handle_unclear(
        self, state: ConversationState, body: ReplyRequest, mid: Optional[str]
    ) -> ReplyResponse:
        # After max 2 unclear turns, wait rather than spam
        unclear_count = sum(
            1 for t in state.turns
            if t.from_role == "vera" and "didn't quite catch" in (t.body or "").lower()
        )
        if unclear_count >= 1:
            return ReplyResponse(
                action="wait",
                wait_seconds=3600,
                rationale="Response unclear again. Backing off for 1 hour to avoid message spam.",
            )

        return ReplyResponse(
            action="send",
            body="Apologies, I didn't quite catch that. Could you reply with 'Yes' to continue, or let me know how I can help?",
            cta="open_ended",
            rationale="Reply unclear; gentle re-ask to maintain conversation without assuming intent.",
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _mark_ended(state: ConversationState) -> None:
        state.status = "ended"

    @staticmethod
    def _days_from_now(now_iso: str, days: int) -> str:
        try:
            cleaned = now_iso.replace("Z", "+00:00")
            dt = datetime.fromisoformat(cleaned)
        except Exception:
            dt = datetime.now(timezone.utc)
        result = dt + timedelta(days=days)
        return result.isoformat().replace("+00:00", "Z")

    @staticmethod
    def _is_repeated_inbound(state: ConversationState, message: str, from_role: str) -> bool:
        """
        Return True if this exact message has already been sent by the same role
        in this conversation. Used to break send loops.
        """
        normalized = message.strip().lower()
        matches = [
            t for t in state.turns
            if t.from_role == from_role and t.body.strip().lower() == normalized
        ]
        # If seen more than once (the current turn was already appended before calling this)
        return len(matches) > 1


# Global singleton
reply_engine = ReplyEngine()

