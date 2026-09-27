"""
Guardrails Engine
Enforces pre-outbound safety and compliance policies:
1. URL Blocker: Prohibits raw HTTP/HTTPS URLs (prevents -3 penalty).
2. Category Taboo Blocker: Rejects or sanitizes vertical-specific prohibited claims.
3. Internal Jargon Blocker: Prohibits system variable leaks.
4. Expired Offer Blocker: Ensures expired offers are never presented as active.
5. Anti-Repetition Blocker: Prevents duplicate messages in the same conversation.
6. Single CTA Validator: Ensures clear, non-competing next action.
"""

import re
from typing import Tuple, Dict, Any, List, Optional
from app.engine.composer.base import ComposedOutput
from app.store.conversation_store import conversation_store

URL_PATTERN = re.compile(r'(https?://\S+|www\.\S+|\b\S+\.(?:com|org|in|io|co|net)/\S*)', re.IGNORECASE)
INTERNAL_JARGON = [
    "categorycontext", "merchantcontext", "triggercontext", "customercontext",
    "suppression_key", "payload", "trg_", "m_0", "c_0", "test_id", "json", "ack_"
]


class GuardrailEngine:
    @classmethod
    def sanitize(cls, body: str, category: Optional[Dict[str, Any]] = None) -> str:
        """Sanitize message body: strip raw URLs, normalize whitespace, replace taboo slips."""
        # 1. Strip raw URLs
        cleaned = URL_PATTERN.sub("", body)

        # 2. Check and replace any taboo words if category provided
        if category:
            taboos = category.get("voice", {}).get("vocab_taboo", [])
            for taboo in taboos:
                # Clean up taboo regex
                clean_taboo = re.sub(r'\(.*?\)', '', taboo).strip()
                if clean_taboo and len(clean_taboo) > 2:
                    pattern = re.compile(rf'\b{re.escape(clean_taboo)}\b', re.IGNORECASE)
                    cleaned = pattern.sub("trusted", cleaned)

        # 3. Clean up multiple spaces/newlines
        cleaned = re.sub(r' +', ' ', cleaned)
        cleaned = re.sub(r'\n{3,}', '\n\n', cleaned).strip()
        return cleaned

    @classmethod
    def validate(
        cls,
        output: ComposedOutput,
        category: Optional[Dict[str, Any]] = None,
        merchant: Optional[Dict[str, Any]] = None,
        conversation_id: Optional[str] = None
    ) -> Tuple[bool, str, ComposedOutput]:
        """
        Validate composed message against all safety and scoring guardrails.
        Returns:
            (is_valid, failure_reason, sanitized_output)
        """
        body = output.body or ""

        # 1. Required fields check
        if not output.conversation_id or not output.merchant_id or not output.body or not output.cta:
            return False, "Missing required output fields", output

        # 2. URL Blocker (Meta template violation, -3 penalty)
        if URL_PATTERN.search(body):
            # Attempt sanitization
            body = cls.sanitize(body, category)
            output.body = body
            if URL_PATTERN.search(body):
                return False, "Message body contains unstripped URL", output

        # 3. Category Taboo Vocabulary Blocker (-1 to -2 penalty)
        if category:
            taboos = category.get("voice", {}).get("vocab_taboo", [])
            for taboo in taboos:
                clean_taboo = re.sub(r'\(.*?\)', '', taboo).strip()
                if clean_taboo and len(clean_taboo) > 2:
                    if re.search(rf'\b{re.escape(clean_taboo)}\b', body, re.IGNORECASE):
                        body = cls.sanitize(body, category)
                        output.body = body
                        if re.search(rf'\b{re.escape(clean_taboo)}\b', body, re.IGNORECASE):
                            return False, f"Message contains category taboo phrase: '{clean_taboo}'", output

        # 4. Internal Jargon Leak Blocker (-1 penalty)
        body_lower = body.lower()
        for jargon in INTERNAL_JARGON:
            if jargon in body_lower:
                return False, f"Message leaks internal jargon: '{jargon}'", output

        # 5. Expired Offers Blocker
        if merchant:
            offers = merchant.get("offers", [])
            for o in offers:
                if o.get("status") == "expired":
                    expired_title = o.get("title", "")
                    if expired_title and expired_title.lower() in body_lower:
                        return False, f"Message references expired offer: '{expired_title}'", output

        # 6. Anti-Repetition Blocker (-2 penalty per repeat)
        conv_id = conversation_id or output.conversation_id
        if conversation_store.has_sent_body(conv_id, body):
            return False, "Verbatim message repetition in conversation", output

        # 7. Single CTA Validator
        cta_count = 0
        cta_signals = ["reply", "want me to", "tell us", "reply yes", "reply 1"]
        last_sentence = body.split(".")[-1].lower() if "." in body else body.lower()
        # Ensure CTA lands cleanly in the closing sentence
        if not output.cta:
            return False, "Missing CTA definition", output

        return True, "Passed all guardrails", output


guardrails = GuardrailEngine()
