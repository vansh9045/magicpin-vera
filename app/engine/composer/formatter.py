"""
Formatting and personalization utilities for message composition.
Enforces domain salutations, language code-mix rules, and conversation IDs.
"""

from typing import Optional
from app.engine.signal_extractor import GroundedSignals

CATEGORY_EMOJIS = {
    "dentists": "🦷",
    "salons": "✨",
    "gyms": "👋",
    "restaurants": "🍕",
    "pharmacies": "💊",
}


class MessageFormatter:
    @staticmethod
    def get_salutation(signals: GroundedSignals, customer_facing: bool = False) -> str:
        """Derive respectful, domain-appropriate salutation."""
        if customer_facing:
            cname = signals.customer_name or "there"
            emoji = CATEGORY_EMOJIS.get(signals.category_slug, "")
            clang = (signals.customer_lang or "").lower()
            if "hi" in clang and signals.category_slug == "pharmacies":
                return f"Namaste — {signals.merchant_name} yahan."
            return f"Hi {cname} {emoji}".strip()

        # Merchant-facing salutations
        owner = signals.owner_name or signals.merchant_name.split()[0]
        cat = signals.category_slug

        if cat == "dentists":
            if not owner.lower().startswith("dr"):
                return f"Dr. {owner}"
            return owner
        elif cat == "gyms":
            return f"{owner}"
        else:
            return f"{owner}"

    @staticmethod
    def format_conversation_id(signals: GroundedSignals) -> str:
        """Generate human-readable, unique conversation ID."""
        clean_trg = signals.trigger_id.replace("trg_", "").replace("-", "_")
        if signals.customer_id:
            return f"conv_{signals.customer_id}_{signals.trigger_kind}"
        return f"conv_{signals.merchant_id}_{clean_trg}"

    @staticmethod
    def format_pct(val: Optional[float]) -> str:
        """Format decimal to signed percentage string."""
        if val is None:
            return ""
        pct = round(val * 100)
        return f"+{pct}%" if pct > 0 else f"{pct}%"


message_formatter = MessageFormatter()
