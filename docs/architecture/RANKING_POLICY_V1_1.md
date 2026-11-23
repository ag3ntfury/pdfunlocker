# PDF Unlocker — Ranking Policy v1.1

**Status:** Approved by project owner — Option B

## Global ranking applies to every batch

Every batch, including batch 1 of every profile, uses the same global
historical rule ranking. A new profile immediately benefits from completed
learning results collected from previous profiles.

## Ranking order

1. Rules with completed history are ranked by PDF-level success rate,
   descending.
2. Ties are resolved by distinct successful PDF count, descending.
3. Remaining ties retain the original active-rule order from the profile's
   YAML rule directory.
4. Rules without qualifying completed history remain after tested rules in
   their original YAML order.
5. Inactive rules are never included.

Success rate is:

`distinct successful PDFs / distinct attempted PDFs`

A PDF is counted as attempted for a rule only when its outcome is `success`
or `exhausted`. Outcomes `error`, `no_candidates`, and `skipped` are excluded
from the denominator. Each SHA-256 PDF identity contributes at most once per
rule globally, even when it appears in multiple profiles or has multiple
outcome records.

Only outcomes belonging to completed learning batches contribute to ranking.
Incomplete batches do not influence ranking.

## Batch validation

The requested batch must exist. Batch numbers must be sequential for that
profile, and all earlier batches must be completed before a later batch can
run. This validation does not prevent batch 1 from using completed global
history belonging to other profiles.

## Compatibility

No SQLite schema change is required. Existing profile data, rule files and
learning history remain in place.
