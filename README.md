# magicpin AI Challenge Bot

## Dev Notes

**Trigger expiry in local testing:** The `judge_simulator.py` uses real-time `datetime.utcnow()` for tick timestamps, while the seed triggers in `dataset/triggers_seed.json` have `expires_at` dates set in spring/autumn 2026. When running locally after those dates have passed, triggers will appear expired — this is a local testing artifact of the date mismatch, not a bot defect. For dev testing, the seed dates have been extended to keep triggers valid.
