# Host dispositions — round 4 review (all 3 findings accepted)

REV-017 (high, pending alerts can be abandoned when repeated recording of
the same low price shifts the rolling baseline so the anomaly condition
stops firing on later cycles, and retry was only wired inside that
condition): ACCEPTED. Split the previously-merged "claim + send" step into
two independent responsibilities in `check_route`: step 4 (`claim_alert`)
only durably records intent to alert when a NEW anomaly is detected this
cycle (idempotent `INSERT OR IGNORE`, never sends); step 6
(`flush_pending_alerts`) runs unconditionally every cycle regardless of this
cycle's anomaly outcome, and attempts delivery of every `pending` row for
the route using the price/dates stored in the `alerts` row itself (not the
current `entry`) — so a pending alert is retried every cycle until it
succeeds, independent of whether the current fetched price still looks
anomalous against a baseline that later recordings of the same price may
have shifted. Added a test reproducing Codex's exact scenario: send fails
once, several cycles record the same low price (baseline drifts down,
`is_anomaly` stops firing), then the send stub stops failing — asserts
`flush_pending_alerts` still delivers the earlier pending alert.

REV-018 (high, token leakage into logs via `raise_for_status()`'s URL-bearing
exception message): ACCEPTED. Two complementary fixes: (1) Travelpayouts
token moves from the `token` query parameter to the `X-Access-Token` header
(a documented, supported alternative) — removes the token from that host's
request URL entirely, eliminating the leak vector at the source rather than
relying on remembering to redact; (2) added `redact_url()` (strips
`token=...` query values and `/bot<...>/ ` path segments) used everywhere a
URL or network-exception string might otherwise reach a log call, plus a
blanket rule that error logs use structured fields (status code, host,
route_id) rather than the raw exception string/`log.exception`. Telegram's
token is unavoidably in its URL by Telegram's own Bot API design (no header
alternative exists), so `redact_url` is the primary defense there. Added two
deterministic redaction tests (query-param token, path-segment token).

REV-019 (medium, generic route-search fallback link doesn't reflect the
alerted itinerary's dates, presented as if it did): ACCEPTED, using the
review's explicitly offered alternative fix (mark the alert as lacking a
precise purchase link, rather than asserting an unverified date-bearing URL
scheme for `search.aviasales.ru` that this session could not confirm against
authoritative documentation). `build_purchase_link` now returns
`(url, is_itinerary_specific)`; the Telegram message appends an explicit
disclaimer when the link is the generic fallback, instead of silently
presenting a dateless route-search page as if it reproduced the alerted
fare. The alerted dates remain in the message text regardless (already
specified separately from the link).

No findings rejected.
