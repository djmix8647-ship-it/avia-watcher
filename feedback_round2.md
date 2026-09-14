# Host dispositions — round 2 review (all 5 findings accepted)

REV-007 (high, dedup not crash-safe / false atomicity claim): ACCEPTED, with
an at-least-once design rather than the plan's suggested at-most-once, to
avoid the worse failure mode (permanently losing an alert on an ordinary
transient Telegram send error, not just a process crash). `alerts` gains a
`status` column ('pending'/'sent'). Row is inserted+committed as 'pending'
before the send attempt (durable, not claimed atomic with the HTTP call);
only promoted to 'sent' after a confirmed successful send. An ordinary send
exception leaves the row 'pending' and the outer per-route exception handler
retries next cycle — no lost alert on a normal failure. Only a true
process-crash in the narrow window between a successful send and the
follow-up UPDATE can produce one duplicate message, which is explicitly
documented as an accepted, rare, low-harm tradeoff (not silent, not claimed
to be transactional). PLAN.md "Дедупликация и порядок доставки" section
rewritten with this exact mechanic.

REV-008 (medium, rate limit advisory only, 429 sleep blocks other routes):
ACCEPTED. Replaced the "warn only" approach with an actually-enforced
`EFFECTIVE_INTERVAL = max(POLL_INTERVAL_SECONDS, ceil(len(ROUTES) * 60 /
MAX_REQUESTS_PER_MINUTE))` used as the real sleep between cycles — the
configured budget can no longer be exceeded by construction, no token-bucket
needed. 429 handling no longer sleeps synchronously inside the per-route
call (which would block later routes in the same cycle): `fetch_cheapest`
returns `None` immediately on 429, and `check_route` records an in-memory
per-route `next_allowed_at` (monotonic) from the `Retry-After` header (or a
default) so only that route is skipped on subsequent cycles until it
expires — other routes in the same cycle are unaffected.

REV-009 (medium, non-actual entries silently dropped instead of persisted):
ACCEPTED. `prices` gains an `actual` column and `record_price` now always
inserts every fetched entry, satisfying "every observation is persisted"
literally. Only `get_recent_prices` (used for the anomaly baseline) filters
to `actual IS NULL OR actual = 1` — non-actual entries are stored for
audit/debugging but excluded from the median.

REV-010 (medium, undefined link normalization): ACCEPTED. One canonical
rule specified: `entry["link"]` returned as-is when it already starts with
`http`, otherwise treated as a relative path and prefixed with
`https://www.aviasales.com`; falls back to the generic search URL only when
no `link` is present at all. Three deterministic test cases added (absolute,
relative, missing).

REV-011 (medium, ambiguous fetch/record/decide ordering, self-suppression
risk): ACCEPTED. `check_route`'s order is now spelled out explicitly and
unambiguously in PLAN.md: fetch → read prior-only history (current entry not
yet inserted) → decide (skip if `actual is False` or insufficient prior
samples) → record last, always. The mocked `test_watcher.py` test now
explicitly asserts the `MIN_HISTORY_SAMPLES - 1` vs `MIN_HISTORY_SAMPLES`
boundary.

No findings rejected.

Unrelated to the review findings: the user added a concrete use case mid-session
(monitor several origin airports in one region — e.g. Nalchik, Mineralnye
Vody, Vladikavkaz, Grozny — against one or more destinations) and asked for
the tool to be meaningfully more capable than Aviasales' own tracker, not
"slightly better." This does not change `watcher.py`'s contract (it already
just consumes a flat list of route dicts) — reflected as a `config.py`
convenience: `ROUTES` built from an `ORIGINS × DESTINATIONS` comprehension
instead of hand-duplicated entries. Noted here for the record since it
touched the "Файлы" section of PLAN.md; it is not a new finding requiring
separate review, just a config-generation detail with no effect on
watcher.py's logic, schema, or the mechanics above.
