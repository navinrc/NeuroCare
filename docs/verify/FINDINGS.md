# Findings and bugs (running log)

Everything found while building and verifying the phases: bugs (fixed or open), spec gaps, and
decisions made without asking. Newest phase at the bottom. Status: **fixed** · **open** · **decision**
(made a call; review it) · **needs you** (blocked on access, money, or a choice only you can make).

## Phase 1–2 (found while verifying phase 2)

| # | Status | Finding |
|---|---|---|
| 1 | open | `speak` keeps the user's leading capital mid-sentence: "Three things are still open: Send Priya the Q3 deck, Book the dentist". Lower-casing blindly breaks names ("Priya called"), so it needs a proper-noun check against `PERSON#` names. Cosmetic; Alexa reads it the same. |
| 2 | open | `set_preference` speak uses only the last path segment: "Gentle is now 15." Fine for unique leaves, vague for `time.checkin_thresholds.*` (no unit) and `telegram.pushes.*`. |
| 3 | fixed | `ruff check .` flagged import order in `docs/diagrams/aws_architecture.py` (pre-existing). Fixed with `ruff --fix`. |
| 4 | decision | Verification proofs are produced by `scripts/prove.sh <steps.yaml>`: fresh temp DB, server on port 8765 with a static token, steps run over real Streamable HTTP, Markdown output. Your `.data/` DB is never touched. |
