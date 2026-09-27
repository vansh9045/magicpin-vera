"""
Pydantic API request and response models.
Strictly conforms to the challenge-testing-brief and API call examples.
"""

from typing import Literal, Optional, Any, Dict, List
from pydantic import BaseModel, Field


# -----------------------------------------------------------------------------
# GET /v1/healthz
# -----------------------------------------------------------------------------

class ContextsLoadedCount(BaseModel):
    category: int = 0
    merchant: int = 0
    customer: int = 0
    trigger: int = 0


class HealthzResponse(BaseModel):
    status: str = "ok"
    uptime_seconds: int
    contexts_loaded: ContextsLoadedCount


# -----------------------------------------------------------------------------
# GET /v1/metadata
# -----------------------------------------------------------------------------

class MetadataResponse(BaseModel):
    team_name: str
    team_members: List[str]
    model: str
    approach: str
    contact_email: str
    version: str
    submitted_at: str


# -----------------------------------------------------------------------------
# POST /v1/context
# -----------------------------------------------------------------------------

ContextScope = Literal["category", "merchant", "customer", "trigger"]


class ContextPushRequest(BaseModel):
    scope: str
    context_id: str
    version: int
    payload: Dict[str, Any]
    delivered_at: str


class ContextPushSuccessResponse(BaseModel):
    accepted: Literal[True] = True
    ack_id: str
    stored_at: str


class ContextPushConflictResponse(BaseModel):
    accepted: Literal[False] = False
    reason: str = "stale_version"
    current_version: int


class ContextPushErrorResponse(BaseModel):
    accepted: Literal[False] = False
    reason: str
    details: Optional[str] = None


# -----------------------------------------------------------------------------
# POST /v1/tick
# -----------------------------------------------------------------------------

class TickRequest(BaseModel):
    now: str
    available_triggers: List[str] = Field(default_factory=list)


class ActionItem(BaseModel):
    conversation_id: str
    merchant_id: str
    customer_id: Optional[str] = None
    send_as: Literal["vera", "merchant_on_behalf"]
    trigger_id: str
    template_name: str
    template_params: List[str] = Field(default_factory=list)
    body: str
    cta: str
    suppression_key: str
    rationale: str


class TickResponse(BaseModel):
    actions: List[ActionItem] = Field(default_factory=list)


# -----------------------------------------------------------------------------
# POST /v1/reply
# -----------------------------------------------------------------------------

class ReplyRequest(BaseModel):
    conversation_id: str
    merchant_id: Optional[str] = None
    customer_id: Optional[str] = None
    from_role: str
    message: str
    received_at: str
    turn_number: int


class ReplyResponse(BaseModel):
    action: Literal["send", "wait", "end"]
    body: Optional[str] = None
    cta: Optional[str] = None
    wait_seconds: Optional[int] = None
    rationale: str
