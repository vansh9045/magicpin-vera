"""
Conversation models representing multi-turn conversation states and turns.
"""

from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field


class ConversationTurn(BaseModel):
    from_role: str
    body: str
    timestamp: str
    turn_number: int
    action: Optional[str] = None
    cta: Optional[str] = None
    rationale: Optional[str] = None


class ConversationState(BaseModel):
    conversation_id: str
    merchant_id: Optional[str] = None
    customer_id: Optional[str] = None
    status: str = "active"  # "active", "waiting", "ended"
    turns: List[ConversationTurn] = Field(default_factory=list)
    auto_reply_count: int = 0
    last_auto_reply_text: Optional[str] = None
    wait_until: Optional[str] = None
    is_hostile: bool = False
    has_committed: bool = False
    context_keys: Dict[str, Any] = Field(default_factory=dict)
