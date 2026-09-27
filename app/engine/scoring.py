"""
Deterministic Signal Scoring and Ranking Engine
Scores candidate triggers based on urgency, fact availability, and merchant alignment.
Ensures maximum leverage actions are prioritized without non-deterministic randomness.
"""

from typing import List, Tuple
from app.engine.context_resolver import ResolvedContext
from app.engine.signal_extractor import GroundedSignals, signal_extractor


class CandidateScorer:
    @staticmethod
    def score(signals: GroundedSignals) -> int:
        """
        Compute deterministic relevance score (0 - 150) for a candidate trigger.
        """
        score = 0

        # 1. Base Urgency Weight (20 - 100 points)
        score += signals.urgency * 20

        # 2. Fact Richness & Grounding Evidence (0 - 30 points)
        kind = signals.trigger_kind
        if kind in ("research_digest", "cde_opportunity", "regulation_change"):
            if signals.digest_item and signals.digest_item.get("source"):
                score += 20
        elif kind in ("perf_dip", "perf_spike", "seasonal_perf_dip"):
            if signals.perf_calls is not None or signals.perf_views is not None:
                score += 15
            if signals.delta_calls_pct is not None or signals.delta_views_pct is not None:
                score += 10
        elif kind in ("recall_due", "chronic_refill_due", "trial_followup", "wedding_package_followup"):
            if signals.customer_name:
                score += 15
            if signals.preferred_slots or signals.payload.get("available_slots"):
                score += 10
        elif kind in ("supply_alert",):
            if signals.payload.get("affected_batches"):
                score += 25
        elif kind in ("ipl_match_today", "festival_upcoming"):
            if signals.payload.get("match") or signals.payload.get("festival"):
                score += 15

        # Bonus if merchant has active service offers
        if signals.active_offers:
            score += 5

        # 3. Merchant Alignment & Relevance (0 - 20 points)
        # Check if derived signals in MerchantContext match trigger topic
        merchant_sigs = signals.merchant_signals
        if any("high_risk" in s for s in merchant_sigs) and "fluoride" in str(signals.payload):
            score += 15
        if any("ctr_below" in s for s in merchant_sigs) and kind == "perf_dip":
            score += 15
        if any("stale_posts" in s for s in merchant_sigs) and kind in ("curious_ask_due", "milestone_reached"):
            score += 10
        if any("renewal" in s for s in merchant_sigs) and kind == "renewal_due":
            score += 20
        if any("winback" in s for s in merchant_sigs) and kind == "winback_eligible":
            score += 20

        # Subscription active bonus
        if signals.subscription_status == "active":
            score += 5

        return score


class CandidateSelector:
    @staticmethod
    def rank_and_select(candidates: List[Tuple[ResolvedContext, GroundedSignals]], max_actions: int = 20) -> List[Tuple[ResolvedContext, GroundedSignals, int]]:
        """
        Rank candidates and select top candidates with constraints:
        - Max 1 action per merchant per tick.
        - Max 20 actions overall.
        """
        scored_candidates = []
        for resolved, signals in candidates:
            sc = CandidateScorer.score(signals)
            scored_candidates.append((resolved, signals, sc))

        # Sort descending by score; secondary sort by trigger_id for strict determinism
        scored_candidates.sort(key=lambda x: (x[2], x[1].trigger_id), reverse=True)

        selected = []
        seen_merchants = set()

        for item in scored_candidates:
            resolved, signals, sc = item
            mid = signals.merchant_id
            if mid in seen_merchants:
                continue  # Max 1 proactive action per merchant per tick
            seen_merchants.add(mid)
            selected.append(item)
            if len(selected) >= max_actions:
                break

        return selected


candidate_scorer = CandidateScorer()
candidate_selector = CandidateSelector()
