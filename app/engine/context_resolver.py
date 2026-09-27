"""
Context Resolver
Fetches and associates the 4 contexts (Category, Merchant, Customer, Trigger)
from the in-memory store for a given trigger ID.
"""

from typing import Optional, Dict, Any
from dataclasses import dataclass
from app.store.context_store import context_store


@dataclass
class ResolvedContext:
    trigger_id: str
    trigger: Dict[str, Any]
    merchant: Optional[Dict[str, Any]] = None
    category: Optional[Dict[str, Any]] = None
    customer: Optional[Dict[str, Any]] = None
    valid: bool = False
    error: Optional[str] = None


class ContextResolver:
    @staticmethod
    def resolve(trigger_id: str) -> ResolvedContext:
        """
        Resolve Category, Merchant, Customer, and Trigger contexts for a trigger.
        Returns a ResolvedContext with valid=True if all required contexts exist.
        """
        trigger = context_store.get_trigger(trigger_id)
        if not trigger:
            return ResolvedContext(
                trigger_id=trigger_id,
                trigger={},
                valid=False,
                error=f"Trigger '{trigger_id}' not found in store"
            )

        # 1. Resolve merchant_id
        merchant_id = trigger.get("merchant_id")
        if not merchant_id:
            merchant_id = trigger.get("payload", {}).get("merchant_id")

        if not merchant_id:
            return ResolvedContext(
                trigger_id=trigger_id,
                trigger=trigger,
                valid=False,
                error=f"Trigger '{trigger_id}' has no merchant_id"
            )

        merchant = context_store.get_merchant(merchant_id)
        if not merchant:
            return ResolvedContext(
                trigger_id=trigger_id,
                trigger=trigger,
                valid=False,
                error=f"Merchant '{merchant_id}' referenced by trigger not found"
            )

        # 2. Resolve category
        category_slug = merchant.get("category_slug")
        if not category_slug:
            category_slug = trigger.get("payload", {}).get("category")

        category = context_store.get_category(category_slug) if category_slug else None
        if not category:
            return ResolvedContext(
                trigger_id=trigger_id,
                trigger=trigger,
                merchant=merchant,
                valid=False,
                error=f"Category '{category_slug}' for merchant '{merchant_id}' not found"
            )

        # 3. Resolve customer if scoped
        customer = None
        customer_id = trigger.get("customer_id")
        if not customer_id:
            customer_id = trigger.get("payload", {}).get("customer_id") or trigger.get("payload", {}).get("patient_id")

        if customer_id:
            customer = context_store.get_customer(customer_id)

        return ResolvedContext(
            trigger_id=trigger_id,
            trigger=trigger,
            merchant=merchant,
            category=category,
            customer=customer,
            valid=True
        )


context_resolver = ContextResolver()
