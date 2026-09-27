"""
Tick Engine — Phase 6
=====================
Implements the full POST /v1/tick decision pipeline:

1. Iterate available_triggers list.
2. Resolve each trigger's full context (category + merchant + customer + trigger).
3. Validate temporal expiry, suppression, consent, and cadence cooldowns.
4. Extract grounded signals from validated contexts.
5. Score and rank candidates (max 1 proactive action per merchant per tick, max 20 total).
6. Compose each selected candidate via the DeterministicComposer.
7. Apply guardrail checks and sanitize.
8. Record suppression key and merchant cooldown in the suppression store.
9. Record the sent turn in conversation store (anti-repetition).
10. Return the list of ActionItem dicts.
"""

import logging
from datetime import datetime, timezone, timedelta
from typing import List, Optional

from app.models.api import ActionItem
from app.engine.context_resolver import context_resolver, ResolvedContext
from app.engine.trigger_validator import trigger_validator
from app.engine.signal_extractor import signal_extractor, GroundedSignals
from app.engine.scoring import candidate_selector
from app.engine.composer.deterministic import DeterministicComposer
from app.engine.guardrails import guardrails
from app.store.suppression_store import suppression_store
from app.store.conversation_store import conversation_store
from app.models.conversation import ConversationTurn

logger = logging.getLogger(__name__)

# After dispatching an action we apply a 24-hour cadence cooldown per merchant.
CADENCE_COOLDOWN_HOURS = 24

# Suppression window for repeated trigger keys.
SUPPRESSION_WINDOW_HOURS = 48


class TickEngine:
    """
    Stateless orchestrator.  All state lives in the global stores.
    """

    def __init__(self):
        self._composer = DeterministicComposer()

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def process(self, now_iso: str, available_triggers: List[str]) -> List[ActionItem]:
        """
        Run the full tick decision pipeline and return the list of actions.

        Args:
            now_iso:             ISO-8601 timestamp supplied by the judge.
            available_triggers:  List of trigger IDs the judge says are eligible.

        Returns:
            List of ActionItem objects to be serialised in the TickResponse.
        """
        logger.info("Tick start: now=%s triggers=%d", now_iso, len(available_triggers))

        # ----------------------------------------------------------------
        # STEP 1 — Resolve + validate every trigger, build candidate list
        # ----------------------------------------------------------------
        candidates = []  # List of (ResolvedContext, GroundedSignals)

        for trigger_id in available_triggers:
            resolved = context_resolver.resolve(trigger_id)

            if not resolved.valid:
                logger.debug("Skip %s: %s", trigger_id, resolved.error)
                continue

            is_valid, reason = trigger_validator.validate(resolved, now_iso)
            if not is_valid:
                logger.debug("Skip %s: %s", trigger_id, reason)
                continue

            signals = signal_extractor.extract(resolved)
            candidates.append((resolved, signals))

        logger.info(
            "Candidates after validation: %d / %d",
            len(candidates),
            len(available_triggers),
        )

        # ----------------------------------------------------------------
        # STEP 2 — Score and rank (max 1/merchant, max 20 overall)
        # ----------------------------------------------------------------
        ranked = candidate_selector.rank_and_select(candidates, max_actions=20)
        logger.info("Selected after ranking: %d", len(ranked))

        # ----------------------------------------------------------------
        # STEP 3 — Compose, guardrail, record
        # ----------------------------------------------------------------
        actions: List[ActionItem] = []

        for resolved, signals, score in ranked:
            action_item = self._compose_and_validate(resolved, signals, now_iso, score)
            if action_item is not None:
                actions.append(action_item)

        logger.info("Tick complete: %d actions dispatched", len(actions))
        return actions

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _compose_and_validate(
        self,
        resolved: ResolvedContext,
        signals: GroundedSignals,
        now_iso: str,
        score: int,
    ) -> Optional[ActionItem]:
        """
        Compose a message, run guardrails, record state, and return ActionItem.
        Returns None if guardrails reject the message.
        """
        try:
            output = self._composer.compose(signals)
        except Exception as exc:
            logger.warning("Composer failed for %s: %s", signals.trigger_id, exc)
            return None

        # Guardrail validation + sanitisation
        is_valid, failure_reason, output = guardrails.validate(
            output,
            category=resolved.category,
            merchant=resolved.merchant,
            conversation_id=output.conversation_id,
        )

        if not is_valid:
            logger.warning(
                "Guardrail rejected %s: %s", signals.trigger_id, failure_reason
            )
            return None

        # ----------------------------------------------------------------
        # Record state AFTER successful composition + guardrail pass
        # ----------------------------------------------------------------

        # 1. Record suppression key so the same trigger won't fire again
        #    for SUPPRESSION_WINDOW_HOURS.
        if output.suppression_key:
            supp_expires = self._hours_from_now(now_iso, SUPPRESSION_WINDOW_HOURS)
            suppression_store.record_key(output.suppression_key, supp_expires)

        # 2. Note: per-merchant cadence limiting is handled within each tick
        #    by CandidateSelector.rank_and_select() (max 1 action per merchant
        #    per tick).  No cross-tick blanket cooldown is applied — the spec
        #    only requires dedup by suppression_key and 1-per-(merchant,conv)
        #    per tick.
        #    Additionally, previous 24h cooldown mixed real wall-clock time
        #    with the simulated `now`, which is structurally incompatible with
        #    the Phase 2 60-minute simulated test window.

        # 3. Record the sent message in conversation store for anti-repetition.
        #    Proactive outbound messages always open a new conversation (turn 1).
        turn = ConversationTurn(
            from_role="vera" if output.send_as == "vera" else "merchant_on_behalf",
            body=output.body,
            timestamp=now_iso,
            turn_number=1,
        )
        conversation_store.add_turn(
            output.conversation_id,
            turn,
            merchant_id=signals.merchant_id,
        )

        return ActionItem(
            conversation_id=output.conversation_id,
            merchant_id=output.merchant_id,
            customer_id=output.customer_id,
            send_as=output.send_as,
            trigger_id=output.trigger_id,
            template_name=output.template_name,
            template_params=output.template_params,
            body=output.body,
            cta=output.cta,
            suppression_key=output.suppression_key,
            rationale=output.rationale,
        )

    @staticmethod
    def _hours_from_now(now_iso: str, hours: int) -> str:
        """Return an ISO-8601 timestamp `hours` hours after `now_iso`."""
        try:
            cleaned = now_iso.replace("Z", "+00:00")
            dt = datetime.fromisoformat(cleaned)
        except Exception:
            dt = datetime.now(timezone.utc)
        result = dt + timedelta(hours=hours)
        return result.isoformat().replace("+00:00", "Z")


# Global singleton
tick_engine = TickEngine()
