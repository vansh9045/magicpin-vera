"""
Intent Detector — Phase 7
==========================
Classifies incoming merchant/customer reply messages into deterministic
intent categories using only lexical pattern matching.

No LLM. No external calls. No hallucination.

Intent taxonomy (drawn directly from challenge materials):
- auto_reply         : WA Business canned auto-reply
- hostile            : abuse / "stop this" / "spam"
- opt_out            : explicit stop / unsubscribe
- rejection          : polite "no" / "not interested"
- positive_accept    : yes / please send / go ahead
- intent_transition  : "ok let's do it" / "proceed" / "confirm"
- question           : "?" / "what/how/when/which"
- off_topic          : unrelated request (GST, competitor, etc.)
- unclear            : none of the above
"""

import re
from typing import Optional

# ---------------------------------------------------------------------------
# Intent labels (match exactly what the state machine uses)
# ---------------------------------------------------------------------------

INTENT_AUTO_REPLY = "auto_reply"
INTENT_HOSTILE = "hostile"
INTENT_OPT_OUT = "opt_out"
INTENT_REJECTION = "rejection"
INTENT_POSITIVE = "positive_accept"
INTENT_TRANSITION = "intent_transition"
INTENT_QUESTION = "question"
INTENT_OFF_TOPIC = "off_topic"
INTENT_UNCLEAR = "unclear"


# ---------------------------------------------------------------------------
# Pattern banks
# ---------------------------------------------------------------------------

_AUTO_REPLY_PATTERNS = [
    r"thank you for contact",
    r"our team will respond",
    r"we will get back",
    r"auto.?reply",
    r"out of office",
    r"away from (my |the )?phone",
    r"automatically generated",
    r"we have received your",
    r"will respond shortly",
    r"response time is",
    r"business hours",
    r"currently unavailable",
]

_HOSTILE_PATTERNS = [
    r"\bspam\b",
    r"\buseless\b",
    r"\bannoying\b",
    r"\bhate\b",
    r"\bidiot\b",
    r"\bfool\b",
    r"\bshut up\b",
    r"\bgo away\b",
    r"\bleave me alone\b",
    r"bothering me",
    r"waste of (my )?time",
    r"why are you",
    r"don['\u2019]?t (ever )?contact",
    r"never (contact|message|text|call)",
]

_OPT_OUT_PATTERNS = [
    r"\bstop\b",
    r"\bunsubscribe\b",
    r"\bopt.?out\b",
    r"\bremove me\b",
    r"don['\u2019]?t (send|message|text|contact)",
    r"\bblock\b",
    r"\bdo not (send|message|contact|disturb)\b",
    r"\bdnd\b",
    r"not interested.*don['\u2019]?t",
]

_REJECTION_PATTERNS = [
    r"\bnot interested\b",
    r"\bno thanks?\b",
    r"\bnope\b",
    r"\bnah\b",
    r"\bcan['\u2019]?t (afford|use|do)\b",
    r"\bmaybe later\b",
    r"\bsome other time\b",
    r"\bbusy\b.*\bcan['\u2019]?t\b",
    r"\bpas[s]?\b",
]

_POSITIVE_PATTERNS = [
    r"\byes\b",
    r"\bya\b",
    r"\byeah\b",
    r"\byup\b",
    r"\bsure\b",
    r"\bplease\b",
    r"\bsend (it|me|the)\b",
    r"\bgo ahead\b",
    r"\bdo it\b",
    r"\bshare (it|the)\b",
    r"\bproceed\b",
    r"\bconfirm\b",
    r"\bsounds good\b",
    r"\bgreat\b",
    r"\bawesome\b",
    r"\bperfect\b",
    r"\bok[ay]?\b",
    r"\bwould love\b",
    r"\binterested\b",
]

_TRANSITION_PATTERNS = [
    r"\blet['\u2019]?s do it\b",
    r"\blet['\u2019]?s go\b",
    r"\bwhat['\u2019]?s next\b",
    r"\bwhat do (i|we) do next\b",
    r"\bok lets?\b.*\bdo\b",
    r"\bready\b",
    r"\bproceed\b",
    r"\bcommit\b",
    r"\bfinaliz",
    r"\bgo for it\b",
    r"\bdo this\b",
]

_OFF_TOPIC_PATTERNS = [
    r"\bgst\b",
    r"\btax\b",
    r"\bca\b.{0,20}\bfiling\b",
    r"\baccounting\b",
    r"\bcompetitor\b",
    r"\bother (app|platform|service)\b",
    r"\bjustdial\b",
    r"\bpracto\b",
    r"\bgoogle ad\b",
    r"\bseo\b",
    r"\bwebsite\b",
    r"\binstagram\b",
    r"\bfacebook\b",
    r"\bhire\b.*\bstaff\b",
    r"\bstaff\b.*\bhire\b",
    r"\brent\b",
    r"\blegal\b",
]


def _matches(text: str, patterns: list) -> bool:
    """Case-insensitive match against any pattern in the list."""
    t = text.lower()
    return any(re.search(p, t) for p in patterns)


def detect_intent(message: str, auto_reply_count: int = 0) -> str:
    """
    Classify the reply message into one intent label.

    Priority order (higher priority wins):
    1. auto_reply
    2. hostile
    3. opt_out
    4. rejection
    5. intent_transition  (must come before positive, since "ok let's do it" has positive words)
    6. positive_accept
    7. question
    8. off_topic
    9. unclear
    """
    msg = message.strip()
    if not msg:
        return INTENT_UNCLEAR

    if _matches(msg, _AUTO_REPLY_PATTERNS):
        return INTENT_AUTO_REPLY

    if _matches(msg, _HOSTILE_PATTERNS):
        return INTENT_HOSTILE

    if _matches(msg, _OPT_OUT_PATTERNS):
        return INTENT_OPT_OUT

    if _matches(msg, _REJECTION_PATTERNS):
        return INTENT_REJECTION

    # Intent transition must come before positive (transition phrases contain positive words)
    if _matches(msg, _TRANSITION_PATTERNS):
        return INTENT_TRANSITION

    if _matches(msg, _POSITIVE_PATTERNS):
        return INTENT_POSITIVE

    # WHY: Off-topic detection takes precedence over generic question detection (presence of '?')
    # because requests like "Can you also help me with my GST filing?" or competitor comparisons
    # are grammatically questions, but substantively out-of-domain. Detecting off-topic first ensures
    # the bot politely declines and redirects back to core context instead of trying to hallucinate
    # domain answers from merchant stats.
    if _matches(msg, _OFF_TOPIC_PATTERNS):
        return INTENT_OFF_TOPIC

    if "?" in msg:
        return INTENT_QUESTION

    return INTENT_UNCLEAR

