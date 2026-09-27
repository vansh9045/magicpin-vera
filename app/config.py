"""
Application Configuration
Contains bot identity metadata, runtime timeouts, and default operational thresholds.
"""

from datetime import datetime, timezone
import time

BOT_START_TIME = time.time()

# Team & Metadata information per GET /v1/metadata specification
METADATA = {
    "team_name": "Team Vera Elite",
    "team_members": ["Architect"],
    "model": "deterministic-engine-v1",
    "approach": "deterministic provenance-bound signal prioritization, structured grounded composition, strict category taboos, and zero-hallucination guardrails",
    "contact_email": "team@example.com",
    "version": "1.0.0",
    "submitted_at": "2026-04-26T08:00:00Z"
}

# Operational limits from challenge-testing-brief.md
MAX_ACTIONS_PER_TICK = 20
MAX_ACTIONS_PER_MERCHANT_PER_TICK = 1
DEFAULT_REPLY_TIMEOUT_SECONDS = 30
AUTO_REPLY_WAIT_SECONDS = 86400  # 24 hours backoff on repeated auto-replies
HOSTILE_SUPPRESSION_DAYS = 30
MERCHANT_CADENCE_HOURS = 24  # Standard cooldown between proactive non-urgent messages
