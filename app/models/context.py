"""
Domain context models representing the 4-context architecture:
1. CategoryContext
2. MerchantContext
3. CustomerContext
4. TriggerContext
"""

from typing import Optional, Dict, Any, List
from pydantic import BaseModel, Field


class CategoryContext(BaseModel):
    slug: str
    display_name: Optional[str] = None
    voice: Dict[str, Any] = Field(default_factory=dict)
    offer_catalog: List[Dict[str, Any]] = Field(default_factory=list)
    peer_stats: Dict[str, Any] = Field(default_factory=dict)
    digest: List[Dict[str, Any]] = Field(default_factory=list)
    patient_content_library: List[Dict[str, Any]] = Field(default_factory=list)
    seasonal_beats: List[Dict[str, Any]] = Field(default_factory=list)
    trend_signals: List[Dict[str, Any]] = Field(default_factory=list)


class MerchantContext(BaseModel):
    merchant_id: str
    category_slug: str
    identity: Dict[str, Any] = Field(default_factory=dict)
    subscription: Dict[str, Any] = Field(default_factory=dict)
    performance: Dict[str, Any] = Field(default_factory=dict)
    offers: List[Dict[str, Any]] = Field(default_factory=list)
    conversation_history: List[Dict[str, Any]] = Field(default_factory=list)
    customer_aggregate: Dict[str, Any] = Field(default_factory=dict)
    signals: List[str] = Field(default_factory=list)
    review_themes: List[Dict[str, Any]] = Field(default_factory=list)


class CustomerContext(BaseModel):
    customer_id: str
    merchant_id: str
    identity: Dict[str, Any] = Field(default_factory=dict)
    relationship: Dict[str, Any] = Field(default_factory=dict)
    state: str = "new"
    preferences: Dict[str, Any] = Field(default_factory=dict)
    consent: Dict[str, Any] = Field(default_factory=dict)


class TriggerContext(BaseModel):
    id: str
    scope: str
    kind: str
    source: str
    merchant_id: str
    customer_id: Optional[str] = None
    payload: Dict[str, Any] = Field(default_factory=dict)
    urgency: int = 1
    suppression_key: str
    expires_at: str
