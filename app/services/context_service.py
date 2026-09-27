"""
Context Service
Handles validation, ingestion, and retrieval of Category, Merchant, Customer, and Trigger contexts.
"""

from typing import Tuple, Dict, Any
from app.store.context_store import context_store

VALID_SCOPES = {"category", "merchant", "customer", "trigger"}


class ContextService:
    @staticmethod
    def ingest_context(body: Dict[str, Any]) -> Tuple[int, Dict[str, Any]]:
        """
        Validate and ingest incoming context push.
        Returns:
            (status_code, response_body)
        """
        scope = body.get("scope")
        if not scope or scope not in VALID_SCOPES:
            return 400, {
                "accepted": False,
                "reason": "invalid_scope",
                "details": f"Scope '{scope}' is invalid. Must be one of: {sorted(list(VALID_SCOPES))}"
            }

        context_id = body.get("context_id")
        if not context_id or not isinstance(context_id, str):
            return 400, {
                "accepted": False,
                "reason": "missing_context_id",
                "details": "context_id must be a non-empty string"
            }

        version = body.get("version")
        if version is None or not isinstance(version, int):
            return 400, {
                "accepted": False,
                "reason": "invalid_version",
                "details": "version must be an integer"
            }

        payload = body.get("payload")
        if payload is None or not isinstance(payload, dict):
            return 400, {
                "accepted": False,
                "reason": "invalid_payload",
                "details": "payload must be a JSON object"
            }

        delivered_at = body.get("delivered_at", "")

        # Atomic push into context store
        success, result, cur_ver = context_store.push(
            scope=scope,
            context_id=context_id,
            version=version,
            payload=payload,
            delivered_at=delivered_at
        )

        if not success:
            # 409 Conflict: stale or duplicate version
            return 409, {
                "accepted": False,
                "reason": result,
                "current_version": cur_ver
            }

        stored_at = context_store.get_stored_at(scope, context_id)
        return 200, {
            "accepted": True,
            "ack_id": result,
            "stored_at": stored_at
        }


context_service = ContextService()
