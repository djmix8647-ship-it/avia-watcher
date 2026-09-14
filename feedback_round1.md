# Host dispositions — round 1 review (all 6 findings accepted)

REV-001 (high, API selection): ACCEPTED. Independently re-verified empirically:
`GET /aviasales/v3/prices_for_dates?token=invalid` → HTTP 401 (path exists,
just needs a valid token), vs a deliberately made-up path on the same host →
HTTP 404. This confirms the endpoint is real; my round-1 rejection was based
on an incomplete third-party GitHub mirror of the docs that simply doesn't
include this method. PLAN.md "Источник данных" section rewritten to use
`/aviasales/v3/prices_for_dates` with per-route `departure_at`/`return_at`,
and to consume the response's own ticket link (with a documented fallback
when the exact response field names can't be verified without a live token —
see "Assumptions and sources" and Verification step 1, now a mandatory
first-real-run field-name check before production use).

REV-002 (high, one_way/currency not propagated / route identity): ACCEPTED.
PLAN.md now specifies `one_way`, `direct`, `sorting`, `unique`, `currency` as
real query parameters of `fetch_cheapest`, and `route_id` now includes
`origin, destination, departure_at, return_at, one_way, currency` so
different trip types/currencies never share a price history/median.

REV-003 (high, no alert dedup/cooldown): ACCEPTED. Added a durable `alerts`
SQLite table with `UNIQUE(route_id, price, depart_date, return_date)`,
checked before sending and written after a successful send in the same
check_route call, surviving process restart. Marked as a ponytail-flagged
simplification (exact-match dedup, not a time-based cooldown) with a named
upgrade path if needed later.

REV-004 (medium, acceptance criterion 3 / verification contradiction):
ACCEPTED. Replaced the live-token "must alert within one cycle" acceptance
criterion with a deterministic unit test in test_watcher.py that mocks
fetch_cheapest and proves the full check_route → anomaly → alert → dedup
path without live network/market dependency. The real-token threshold test
is now explicitly labeled observational, not a pass/fail acceptance gate.

REV-005 (medium, no rate-limit/429 handling): ACCEPTED. Added
`MAX_REQUESTS_PER_MINUTE` config with a startup warning if configured routes
× poll frequency would exceed it, and explicit handling of HTTP 429 in
`fetch_cheapest` (logged distinctly from generic errors, honors
`Retry-After` if present) instead of falling into the generic exception
path.

REV-006 (medium, no `actual` filtering / link doesn't reflect alerted
itinerary): ACCEPTED. `fetch_cheapest` now skips entries where `actual` is
present and `false`. `build_purchase_link` now prefers the API response's
own itinerary link (once its real field name is confirmed on first live run,
per REV-001 disposition) and only falls back to the generic route-search URL
when no itinerary-specific link is available — documented explicitly as a
fallback rather than the primary mechanism.

No findings rejected. Two related residual risks are now explicit in PLAN.md
rather than resolved by further guessing, since they could not be confirmed
without a real API token or working access to support.travelpayouts.com from
this session (DNS failure when attempting to fetch it): (a) the exact
response field names of `prices_for_dates`, especially the ticket-link field
name, and (b) the exact numeric rate limit for this specific endpoint. Both
are mitigated with defensive code (graceful `None`-return on unrecognized
schema instead of a crash or silent bad data, conservative configurable
request budget) and an explicit mandatory first-live-run verification step
rather than left as silent assumptions.
