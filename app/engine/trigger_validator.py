"""
Trigger Validator
Enforces temporal validity, customer consent, scope integrity, and suppression checks.
"""

from typing import Tuple
from app.engine.context_resolver import ResolvedContext
from app.store.suppression_store import suppression_store, parse_iso


class TriggerValidator:
    @staticmethod
    def validate(resolved: ResolvedContext, now_iso: str) -> Tuple[bool, str]:
        """
        Validate whether this resolved trigger is eligible for proactive outbound action.
        Returns:
            (is_valid, reason)
        """
        if not resolved.valid:
            return False, resolved.error or "Context incomplete"

        trg = resolved.trigger
        merchant = resolved.merchant
        customer = resolved.customer

        # 1. Temporal Expiry Check
        expires_at = trg.get("expires_at")
        if expires_at:
            exp_dt = parse_iso(expires_at)
            now_dt = parse_iso(now_iso)
            if now_dt >= exp_dt:
                return False, f"Trigger expired at {expires_at} (current: {now_iso})"

        # 2. Suppression Key Check
        supp_key = trg.get("suppression_key")
        if supp_key and suppression_store.is_key_suppressed(supp_key, now_iso):
            return False, f"Suppression key '{supp_key}' is active"

        # 3. Merchant Opt-Out & Hostility Check
        mid = merchant.get("merchant_id", "")
        if suppression_store.is_merchant_opted_out(mid, now_iso):
            return False, f"Merchant '{mid}' is currently opted out"

        # 4. Per-merchant cadence: 1-per-merchant-per-tick is enforced at the
        #    ranking/selection layer (CandidateSelector).  No blanket cross-tick
        #    cooldown is applied per spec.

        # 5. Customer Scope Integrity & Consent Check
        scope = trg.get("scope", "merchant")
        if scope == "customer":
            if not customer:
                return False, f"Customer context missing for customer-scoped trigger '{trg.get('id')}'"

            # Check customer belongs to merchant
            if customer.get("merchant_id") != mid:
                return False, f"Customer merchant mismatch: {customer.get('merchant_id')} != {mid}"

            # Check consent
            consent = customer.get("consent", {})
            if not consent.get("opted_in_at"):
                return False, f"Customer '{customer.get('customer_id')}' has not opted in"

            # Check preferences opt-in flag
            prefs = customer.get("preferences", {})
            if prefs.get("reminder_opt_in") is False:
                return False, f"Customer '{customer.get('customer_id')}' explicitly opted out of reminders"

            # Check communication scope
            allowed_scopes = consent.get("scope", [])
            kind = trg.get("kind", "")
            # Verify kind matches consent scope if specified
            if allowed_scopes:
                kind_scope_map = {
                    "recall_due": ["recall_reminders", "appointment_reminders"],
                    "chronic_refill_due": ["recall_reminders", "promotional_offers", "refill_reminders"],
                    "customer_lapsed_soft": ["promotional_offers", "winback_offers"],
                    "customer_lapsed_hard": ["promotional_offers", "winback_offers"],
                    "wedding_package_followup": ["bridal_package_followup", "appointment_reminders", "promotional_offers"],
                    "trial_followup": ["appointment_reminders", "program_updates", "kids_program_updates"],
                    "appointment_tomorrow": ["appointment_reminders"]
                }
                needed = kind_scope_map.get(kind, [])
                if needed and not any(s in allowed_scopes for s in needed):
                    return False, f"Trigger kind '{kind}' not in customer consent scopes: {allowed_scopes}"

        return True, "Valid"


trigger_validator = TriggerValidator()
