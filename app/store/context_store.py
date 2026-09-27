"""
Thread-safe, versioned in-memory store for contexts (Category, Merchant, Customer, Trigger).
Enforces:
1. Idempotency and version comparison: strictly higher version replaces prior version.
2. Stale version rejection (409 Conflict if incoming version <= stored version).
3. Real-time count reporting for /v1/healthz.
"""

from datetime import datetime, timezone
import threading
from typing import Dict, Tuple, Optional, Any, List


class ContextStore:
    def __init__(self):
        self._lock = threading.RLock()
        # Storage map: (scope, context_id) -> {"version": int, "payload": dict, "delivered_at": str, "stored_at": str}
        self._store: Dict[Tuple[str, str], Dict[str, Any]] = {}
        # Fast index by scope
        self._scope_indices: Dict[str, set[str]] = {
            "category": set(),
            "merchant": set(),
            "customer": set(),
            "trigger": set(),
        }

    def push(self, scope: str, context_id: str, version: int, payload: Dict[str, Any], delivered_at: str) -> Tuple[bool, Optional[str], Optional[int]]:
        """
        Ingest a context entry with version checking.
        Returns:
            (success, ack_or_reason, current_version_if_conflict)
        """
        with self._lock:
            key = (scope, context_id)
            current = self._store.get(key)
            if current is not None:
                cur_ver = current["version"]
                if version < cur_ver:
                    # Stale version conflict per challenge spec (strictly lower version)
                    return False, "stale_version", cur_ver
                elif version == cur_ver:
                    # Idempotent no-op per challenge spec: return success without duplicating or mutating state
                    ack_id = f"ack_{context_id}_v{version}"
                    return True, ack_id, None

            now_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
            self._store[key] = {
                "version": version,
                "payload": payload,
                "delivered_at": delivered_at,
                "stored_at": now_iso
            }
            if scope in self._scope_indices:
                self._scope_indices[scope].add(context_id)

            ack_id = f"ack_{context_id}_v{version}"
            return True, ack_id, None

    def get_stored_at(self, scope: str, context_id: str) -> Optional[str]:
        with self._lock:
            entry = self._store.get((scope, context_id))
            return entry["stored_at"] if entry else None

    def get(self, scope: str, context_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            entry = self._store.get((scope, context_id))
            return entry["payload"] if entry else None

    def get_version(self, scope: str, context_id: str) -> Optional[int]:
        with self._lock:
            entry = self._store.get((scope, context_id))
            return entry["version"] if entry else None

    def get_category(self, slug: str) -> Optional[Dict[str, Any]]:
        return self.get("category", slug)

    def get_merchant(self, merchant_id: str) -> Optional[Dict[str, Any]]:
        return self.get("merchant", merchant_id)

    def get_customer(self, customer_id: str) -> Optional[Dict[str, Any]]:
        return self.get("customer", customer_id)

    def get_trigger(self, trigger_id: str) -> Optional[Dict[str, Any]]:
        return self.get("trigger", trigger_id)

    def get_counts(self) -> Dict[str, int]:
        with self._lock:
            return {
                "category": len(self._scope_indices.get("category", set())),
                "merchant": len(self._scope_indices.get("merchant", set())),
                "customer": len(self._scope_indices.get("customer", set())),
                "trigger": len(self._scope_indices.get("trigger", set())),
            }

    def clear(self):
        with self._lock:
            self._store.clear()
            for s in self._scope_indices:
                self._scope_indices[s].clear()


# Global singleton store instance
context_store = ContextStore()
