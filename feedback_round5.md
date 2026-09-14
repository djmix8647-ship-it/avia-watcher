# Host dispositions — round 5 review (all 3 findings accepted; not resubmitted, MAX_ROUNDS=5 reached)

REV-020 (high, `flush_pending_alerts` described as unconditional but nested
under "entry is not None", so a Travelpayouts outage/429 silently also
blocked delivery of already-pending Telegram alerts): ACCEPTED. This was a
genuine self-introduced contradiction between step 1 (early return on
`entry is None`) and step 6 (claimed unconditional). `check_route`
restructured: steps 2-5 (history/decide/claim/record) only run when
`entry is not None`; step 6 (`flush_pending_alerts`) is now explicitly
outside that condition and always runs as the final action of `check_route`,
regardless of step 1's outcome.

REV-021 (high, claim/flush split lost the API-provided itinerary link since
neither `purchase_url` nor `is_itinerary_specific` was persisted at claim
time): ACCEPTED. `alerts` gains `purchase_url` and `is_itinerary_specific`
columns, computed via `build_purchase_link(route, entry)` at claim time
(while the original `entry` is still available) and persisted immutably.
`flush_pending_alerts` sends from these stored fields, never recomputing
from a possibly-absent current `entry`.

REV-022 (medium, no backoff/expiry for repeatedly-failing pending alerts —
risk of hammering Telegram forever on a permanently broken chat_id, and of
eventually delivering a stale/expired fare after a long outage): ACCEPTED.
`alerts` gains `attempt_count` and `next_attempt_at`; a failed send applies
capped exponential backoff (or honors Telegram's `Retry-After` on 429).
New `ALERT_MAX_AGE_SECONDS` config (default 3600s) — a pending row older
than this is marked `expired` with a WARNING log instead of being sent,
rather than delivering a "great price!" alert for a fare that's likely long
gone.

No findings rejected.

## Round budget note

This was round 5 of the configured `MAX_ROUNDS=5`. Per the claudex-loop
protocol ("Stop at MAX_ROUNDS. Present unresolved findings and the host's
position instead of manufacturing convergence"), a 6th round is not being
submitted. All three round-5 findings were applied to PLAN.md on the host's
own engineering judgment rather than independently re-verified by a further
Codex round — they are the kind of finding (a literal step-ordering
contradiction, a literal data-loss bug, and a bounded-retry/expiry gap) that
don't hinge on any external fact requiring adversarial verification, unlike
earlier rounds' API-existence and endpoint-shape questions. The host's
position: PLAN.md as it now stands is believed sound and ready for
implementation; the change from round 4 to round 5 is confined to
`check_route`'s exact step ordering and the `alerts` table's columns, and
does not touch or reopen any of the round 1-4 findings, which remain
resolved as previously disposed. Implementation proceeds under the original
task's plan-and-implement authorization.
