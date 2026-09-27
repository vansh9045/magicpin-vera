"""
In-memory store for conversations and merchant-level cross-conversation memory.
Tracks:
1. Active conversation states and turn history.
2. Anti-repetition message history.
3. Merchant-level auto-reply memory across conversation IDs.
4. Merchant-level opt-out/hostility flags.
"""

import threading
from typing import Dict, Optional, List, Set, Any
from app.models.conversation import ConversationState, ConversationTurn


class MerchantMemory:
    """Persistent state per merchant_id that survives conversation_id changes."""
    def __init__(self, merchant_id: str):
        self.merchant_id = merchant_id
        self.opted_out = False
        self.is_hostile = False
        self.consecutive_auto_replies = 0
        self.last_canned_text: Optional[str] = None
        self.sent_body_hashes: Set[int] = set()
        self.last_contact_ts: Optional[str] = None


class ConversationStore:
    def __init__(self):
        self._lock = threading.RLock()
        self._conversations: Dict[str, ConversationState] = {}
        self._merchant_memories: Dict[str, MerchantMemory] = {}

    def get_or_create(self, conversation_id: str, merchant_id: Optional[str] = None, customer_id: Optional[str] = None) -> ConversationState:
        with self._lock:
            state = self._conversations.get(conversation_id)
            if state is None:
                state = ConversationState(
                    conversation_id=conversation_id,
                    merchant_id=merchant_id,
                    customer_id=customer_id
                )
                self._conversations[conversation_id] = state
            else:
                if merchant_id and not state.merchant_id:
                    state.merchant_id = merchant_id
                if customer_id and not state.customer_id:
                    state.customer_id = customer_id
            return state

    def get(self, conversation_id: str) -> Optional[ConversationState]:
        with self._lock:
            return self._conversations.get(conversation_id)

    def add_turn(self, conversation_id: str, turn: ConversationTurn, merchant_id: Optional[str] = None) -> None:
        with self._lock:
            state = self.get_or_create(conversation_id, merchant_id)
            state.turns.append(turn)
            mid = merchant_id or state.merchant_id
            if mid and turn.from_role in ("vera", "merchant_on_behalf"):
                mem = self.get_merchant_memory(mid)
                mem.sent_body_hashes.add(hash(turn.body.strip()))
                mem.last_contact_ts = turn.timestamp

    def has_sent_body(self, conversation_id: str, body: str) -> bool:
        """Anti-repetition check within the specific conversation."""
        with self._lock:
            state = self._conversations.get(conversation_id)
            if not state:
                return False
            normalized = body.strip().lower()
            for t in state.turns:
                if t.from_role in ("vera", "merchant_on_behalf"):
                    if t.body.strip().lower() == normalized:
                        return True
            return False

    def has_sent_body_to_merchant(self, merchant_id: str, body: str) -> bool:
        """Cross-conversation anti-repetition check for a merchant."""
        with self._lock:
            mem = self._merchant_memories.get(merchant_id)
            if not mem:
                return False
            return hash(body.strip()) in mem.sent_body_hashes

    def get_merchant_memory(self, merchant_id: str) -> MerchantMemory:
        with self._lock:
            if merchant_id not in self._merchant_memories:
                self._merchant_memories[merchant_id] = MerchantMemory(merchant_id)
            return self._merchant_memories[merchant_id]

    def clear(self):
        with self._lock:
            self._conversations.clear()
            self._merchant_memories.clear()


conversation_store = ConversationStore()
