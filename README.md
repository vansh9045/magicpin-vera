# Vera Message Engine — Submission

A deterministic message-composition bot built for magicpin's Vera AI Challenge.

## Approach

The composer is **rule-based and deterministic**, not LLM-based. The challenge
brief requires same-input-same-output behavior, which rules out a
generative-model composer at inference time — an LLM is used only in local
development, as the *judge* (`judge_simulator.py`), never inside the bot's
own request path.

Given `category + merchant + trigger (+ optional customer)` context, the
composer:

1. Validates the trigger against consent scope and cadence rules
   (`trigger_validator.py`)
2. Ranks eligible triggers per merchant per tick
   (`candidate_selector.py` → `CandidateScorer.score()`)
3. Renders a grounded message + single CTA + suppression key
   (`composer/deterministic.py`)

### Ranking formula

```
score = urgency * 20                    (up to 100)
      + fact_richness_bonus              (up to +30)
      + active_offer_bonus               (+5)
      + merchant_signal_alignment_bonus  (up to +20)
      + active_subscription_bonus        (+5)
```

Only one action is dispatched per `(merchant_id, conversation_id)` per tick,
and a max of 20 actions per tick, per the testing brief. In the current
25-trigger seed set this produces 13–14 dispatched actions per full
evaluation run, with the remainder losing rank contention (`RANK_FILTER`) —
not blocked by consent or cooldown.

## Model / tooling choice

- **Bot runtime:** no model calls — pure deterministic Python (FastAPI).
- **Local judge (dev-only):** OpenRouter, `meta-llama/llama-3.1-8b-instruct`,
  used to dry-run the rubric scorer against the 30 canonical test pairs before
  submission.

## Key fixes made during development

1. **Idempotent context push** — re-posting the same context version now
   returns `200` no-op per spec §2.1, instead of a `409`.
2. **Removed an out-of-spec 24h merchant cooldown** — it used wall-clock time
   against a simulated test window, which is structurally incompatible with
   the harness's simulated `now`. The spec only requires: max 20 actions/tick,
   suppression-key dedup, and 1 action per (merchant, conversation) per tick.
3. **Widened consent-scope taxonomy** — two trigger kinds
   (`trial_followup`, `chronic_refill_due`) were being rejected because their
   customers used differently-named but equivalent consent scopes. Fixed as a
   general taxonomy mapping, not a customer-specific patch.
4. **CTA tightening for low-engagement trigger kinds** — compliance/alert-style
   messages (regulation changes, review-theme alerts, supply alerts)
   originally ended on vague or open-ended asks. CTAs were rewritten to a
   single, low-effort, grounded yes/no action (e.g. *"Reply YES to receive
   the checklist"*), matching the pattern already working well in
   proactive/good-news trigger kinds.

## Local evaluation results

Latest clean `full_evaluation` run against the real LLM judge (13 messages
scored, zero fallback/WARN lines):

| Dimension | Score |
|---|---|
| Specificity | 8/10 |
| Category Fit | 9/10 |
| Merchant Fit | 8/10 |
| Decision Quality | 7/10 |
| Engagement | 6/10 |
| **Average** | **38/50 (76%)** |

53/53 local pytest suite passing, no regressions from the CTA changes.

## Known limitations / tradeoffs

- Composite ranking bonuses (fact-richness, merchant-signal-alignment, etc.)
  have not yet been observed to flip a winner versus urgency-only ranking on
  the current seed set — they're in place for when the trigger mix requires
  them, but not yet validated as decisive.
- Decision Quality and Engagement remain the lowest-scoring rubric
  dimensions; CTA tightening was applied to the trigger kinds that were
  clearly underperforming, not a full rewrite of the message templates.
- Not all seed triggers dispatch in a given tick by design — 1-per-merchant
  cap and rank contention filter most of them out; this is expected, not a
  bug.

## Endpoints

`POST /v1/context` · `POST /v1/tick` · `POST /v1/reply` ·
`GET /v1/healthz` · `GET /v1/metadata`