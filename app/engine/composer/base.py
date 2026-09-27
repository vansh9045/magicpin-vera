"""
Base types and interfaces for message composition.
"""

from typing import Optional, List, Literal, Dict, Any
from dataclasses import dataclass, field


@dataclass
class ComposedOutput:
    conversation_id: str
    merchant_id: str
    customer_id: Optional[str]
    send_as: Literal["vera", "merchant_on_behalf"]
    trigger_id: str
    template_name: str
    template_params: List[str]
    body: str
    cta: str
    suppression_key: str
    rationale: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "conversation_id": self.conversation_id,
            "merchant_id": self.merchant_id,
            "customer_id": self.customer_id,
            "send_as": self.send_as,
            "trigger_id": self.trigger_id,
            "template_name": self.template_name,
            "template_params": self.template_params,
            "body": self.body,
            "cta": self.cta,
            "suppression_key": self.suppression_key,
            "rationale": self.rationale,
        }
