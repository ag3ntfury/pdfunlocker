# PDF Unlocker — Ranking Policy v1.1

**Status:** Proposed revision; requires review before merge.

- First batch of each profile retains original active YAML rule order.
- Before 100 unique completed PDFs globally, rank tested rules by distinct successful PDF count, descending.
- At 100 or more unique completed PDFs globally, rank tested rules by success rate, descending.
- The global count is shared across profiles; duplicate SHA-256 values count once.
- Untested rules remain last in original YAML order.
- Before threshold, ties retain original YAML order.
- After threshold, ties use successful PDF count, then original YAML order.

Success rate = distinct PDFs with a completed `success` outcome divided by
distinct PDFs with a completed `success` or `exhausted` outcome for that rule.

Engine `error`, `no_candidates`, and `skipped` outcomes are excluded from the
per-rule denominator. Each PDF contributes at most once per rule globally.

The global threshold counts distinct PDFs in completed learning batches with
terminal file state (`unlocked`, `locked`, `skipped`, or `failed`).

This is a v1.1 proposal, not the approved v1 baseline. No SQLite schema change
is required by this implementation.
