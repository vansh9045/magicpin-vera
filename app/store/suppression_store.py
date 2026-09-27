"""
Suppression Store
Manages:
1. Trigger suppression keys with expiration.
2. Merchant proactive cadence cooldowns.
3. Merchant opt-out / hostility blacklist.
"""

from datetime import datetime, timezone
import threading
from typing import Dict, Optional


def parse_iso(ts_str: str) -> datetime:
    """Safely parse ISO timestamp string into timezone-aware datetime."""
    try:
        # Normalize trailing Z to +00:00 for fromisoformat compatibility
        cleaned = ts_str.replace("Z", "+00:00")
        return datetime.fromisoformat(cleaned)
    except Exception:
        return datetime.now(timezone.utc)


class SuppressionStore:
    def __init__(self):
        self._lock = threading.RLock()
        # suppression_key -> expires_at ISO str
        self._keys: Dict[str, str] = {}
        # merchant_id -> cooldown_until ISO str
        self._merchant_cooldowns: Dict[str, str] = {}
        # merchant_id -> opted_out_until ISO str
        self._merchant_opt_outs: Dict[str, str] = {}

    def is_key_suppressed(self, key: str, now_iso: str) -> bool:
        """Check if trigger suppression_key is currently active."""
        if not key:
            return False
        with self._lock:
            exp = self._keys.get(key)
            if not exp:
                return False
            now_dt = parse_iso(now_iso)
            exp_dt = parse_iso(exp)
            if now_dt < exp_dt:
                return True
            # Key has expired; clean up
            del self._keys[key]
            return False

    def record_key(self, key: str, expires_at: str) -> None:
        if not key:
            return
        with self._lock:
            self._keys[key] = expires_at

    def is_merchant_in_cooldown(self, merchant_id: str, now_iso: str) -> bool:
        """Check if merchant has received a proactive message within the cadence window."""
        with self._lock:
            cd = self._merchant_cooldowns.get(merchant_id)
            if not cd:
                return False
            now_dt = parse_iso(now_iso)
            cd_dt = parse_iso(cd)
            if now_dt < cd_dt:
                return True
            del self._merchant_cooldowns[merchant_id]
            return False

    def record_merchant_cooldown(self, merchant_id: str, cooldown_until_iso: str) -> None:
        with self._lock:
            self._merchant_cooldowns[merchant_id] = cooldown_until_iso

    def is_merchant_opted_out(self, merchant_id: str, now_iso: str) -> bool:
        """Check if merchant has opted out or flagged as hostile."""
        with self._lock:
            oo = self._merchant_opt_outs.get(merchant_id)
            if not oo:
                return False
            now_dt = parse_iso(now_iso)
            oo_dt = parse_iso(oo)
            if now_dt < oo_dt:
                return True
            del self._merchant_opt_outs[merchant_id]
            return False

    def record_merchant_opt_out(self, merchant_id: str, opt_out_until_iso: str) -> None:
        with self._lock:
            self._merchant_opt_outs[merchant_id] = opt_out_until_iso

    def clear(self):
        with self._lock:
            self._keys.clear()
            self._merchant_cooldowns.clear()
            self._merchant_opt_outs.clear()


suppression_store = SuppressionStore()
