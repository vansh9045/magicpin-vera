"""
Signal Extractor
Extracts grounded, provenance-traceable facts from the 4 contexts.
Ensures zero-hallucination fact binding for downstream message composition.
"""

from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
from app.engine.context_resolver import ResolvedContext


@dataclass
class GroundedSignals:
    # Context Provenance
    category_slug: str
    merchant_id: str
    customer_id: Optional[str]
    trigger_id: str
    trigger_kind: str
    urgency: int
    suppression_key: str

    # Category Grounding
    voice_tone: str
    allowed_vocab: List[str]
    taboo_vocab: List[str]
    peer_avg_ctr: Optional[float]
    peer_avg_rating: Optional[float]
    peer_avg_reviews: Optional[int]
    digest_item: Optional[Dict[str, Any]]
    catalog_offers: List[Dict[str, Any]]

    # Merchant Grounding
    merchant_name: str
    owner_name: str
    locality: str
    city: str
    languages: List[str]
    is_verified: bool
    subscription_status: str
    days_remaining: Optional[int]
    days_since_expiry: Optional[int]
    perf_views: Optional[int]
    perf_calls: Optional[int]
    perf_directions: Optional[int]
    perf_ctr: Optional[float]
    delta_views_pct: Optional[float]
    delta_calls_pct: Optional[float]
    active_offers: List[Dict[str, Any]]
    customer_aggregate: Dict[str, Any]
    merchant_signals: List[str]

    # Customer Grounding (if customer-scoped)
    customer_name: Optional[str] = None
    customer_lang: Optional[str] = None
    customer_state: Optional[str] = None
    preferred_slots: Optional[str] = None
    visits_total: Optional[int] = None
    last_visit: Optional[str] = None
    services_received: List[str] = field(default_factory=list)

    # Trigger-Specific Facts
    payload: Dict[str, Any] = field(default_factory=dict)


class SignalExtractor:
    @staticmethod
    def extract(resolved: ResolvedContext) -> GroundedSignals:
        """Extract grounded signals from resolved context tuple."""
        cat = resolved.category or {}
        m = resolved.merchant or {}
        trg = resolved.trigger or {}
        cust = resolved.customer or {}

        # Category Extraction
        voice = cat.get("voice", {})
        peer_stats = cat.get("peer_stats", {})
        digest_list = cat.get("digest", [])
        digest_map = {d.get("id"): d for d in digest_list if "id" in d}

        # Resolve referenced digest item
        top_item_id = trg.get("payload", {}).get("top_item_id") or trg.get("payload", {}).get("digest_item_id")
        digest_item = digest_map.get(top_item_id) if top_item_id else (digest_list[0] if digest_list else None)

        # Merchant Extraction
        ident = m.get("identity", {})
        sub = m.get("subscription", {})
        perf = m.get("performance", {})
        delta = perf.get("delta_7d", {})
        m_offers = m.get("offers", [])
        active_offers = [o for o in m_offers if o.get("status") == "active"]

        # Owner name resolution (fallback to title prefix like "Dr. Meera" if dentist)
        owner_name = ident.get("owner_first_name", "")
        if not owner_name:
            owner_name = ident.get("name", "").split("'")[0].strip()

        # Customer Extraction
        cust_ident = cust.get("identity", {}) if cust else {}
        cust_rel = cust.get("relationship", {}) if cust else {}
        cust_pref = cust.get("preferences", {}) if cust else {}

        return GroundedSignals(
            category_slug=cat.get("slug", m.get("category_slug", "")),
            merchant_id=m.get("merchant_id", ""),
            customer_id=cust.get("customer_id") if cust else None,
            trigger_id=trg.get("id", ""),
            trigger_kind=trg.get("kind", ""),
            urgency=trg.get("urgency", 1),
            suppression_key=trg.get("suppression_key", ""),

            voice_tone=voice.get("tone", "conversational"),
            allowed_vocab=voice.get("vocab_allowed", []),
            taboo_vocab=voice.get("vocab_taboo", []),
            peer_avg_ctr=peer_stats.get("avg_ctr"),
            peer_avg_rating=peer_stats.get("avg_rating"),
            peer_avg_reviews=peer_stats.get("avg_review_count"),
            digest_item=digest_item,
            catalog_offers=cat.get("offer_catalog", []),

            merchant_name=ident.get("name", "Your Business"),
            owner_name=owner_name,
            locality=ident.get("locality", ""),
            city=ident.get("city", ""),
            languages=ident.get("languages", ["en"]),
            is_verified=ident.get("verified", False),
            subscription_status=sub.get("status", "active"),
            days_remaining=sub.get("days_remaining"),
            days_since_expiry=sub.get("days_since_expiry"),
            perf_views=perf.get("views"),
            perf_calls=perf.get("calls"),
            perf_directions=perf.get("directions"),
            perf_ctr=perf.get("ctr"),
            delta_views_pct=delta.get("views_pct"),
            delta_calls_pct=delta.get("calls_pct"),
            active_offers=active_offers,
            customer_aggregate=m.get("customer_aggregate", {}),
            merchant_signals=m.get("signals", []),

            customer_name=cust_ident.get("name"),
            customer_lang=cust_ident.get("language_pref", "en"),
            customer_state=cust.get("state"),
            preferred_slots=cust_pref.get("preferred_slots"),
            visits_total=cust_rel.get("visits_total"),
            last_visit=cust_rel.get("last_visit"),
            services_received=cust_rel.get("services_received", []),

            payload=trg.get("payload", {})
        )


signal_extractor = SignalExtractor()
