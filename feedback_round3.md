# Host dispositions — round 3 review (all 5 findings accepted)

REV-012 (high, at-least-once contradicts acceptance criterion 2's unconditional
"no repeat"): ACCEPTED, resolved by making acceptance criterion 2's wording
match the already-justified mechanism rather than switching mechanisms.
Round 2 chose at-least-once (pending/sent) deliberately, to avoid losing an
alert permanently on an ordinary transient Telegram send failure — the worse
failure mode for this use case. Criterion 2 in PLAN.md now states this
precisely: no repeat during ordinary operation or after a clean crash/restart
recovery, with the one named, accepted exception being a process crash in
the sub-second window between a confirmed Telegram send and the local
`status='sent'` commit. No hidden contradiction remains — it's now an
explicit, scoped guarantee instead of an absolute one.

REV-013 (medium, alert-send failure skips record_price for that cycle):
ACCEPTED. The alert-claim/send/mark-sent block is now specified as wrapped
in its own local try/except inside `check_route`, so any exception raised
during the alert attempt is caught and logged right there and does NOT
propagate past step 5 (`record_price`, always run when `fetch_cheapest`
returned a non-None entry). A new deterministic test asserts this directly:
a `send_telegram_alert` stub that raises still results in `record_price`
being called.

REV-014 (high, no request timeouts, daemon can hang forever): ACCEPTED.
Added `REQUEST_TIMEOUT_SECONDS=10` to config.py and specified that every
`requests.get`/`requests.post` call (both Travelpayouts and Telegram) passes
`timeout=REQUEST_TIMEOUT_SECONDS`. `requests.Timeout` is a `RequestException`
subclass so it's caught by the already-specified error handling without new
code paths.

REV-015 (medium, `startswith("http")` link check is spoofable): ACCEPTED.
Replaced with `urllib.parse.urlparse` + an explicit allowlist of trusted
Aviasales hosts (`aviasales.com`, `www.aviasales.com`, `aviasales.ru`,
`www.aviasales.ru`, `search.aviasales.ru`), requiring `scheme == "https"`.
A value with no scheme/netloc is treated as a relative code/path and
prefixed with the documented search base (`https://www.aviasales.com` +
`/search/<code>` when it isn't already a `/`-rooted path). Any absolute URL
that isn't on the allowlist falls through to the safe generated search-page
fallback instead of being trusted. Four deterministic test cases specified:
bare relative code, `/`-rooted relative path, trusted absolute URL (passed
through), untrusted absolute URL (must NOT be passed through — must produce
the fallback).

REV-016 (medium, unrecognized schema silently produces a daemon that runs
"successfully" while finding nothing): ACCEPTED, implemented as a loud
distinguishable failure signal rather than a hard crash (a crash would
violate the 24/7-resilience requirement, which is more important here — this
endpoint's exact response schema still couldn't be independently confirmed
in this session; support.travelpayouts.com remained unreachable, DNS
failure). `fetch_cheapest` now distinguishes "API returned empty data"
(quiet, info-level, routine) from "API returned non-empty data but no
recognizable price field" (ERROR-level, one line per route per cycle,
includes the actual response keys seen) — impossible to miss in
systemd/journalctl logs, without stopping the process. README explicitly
tells the operator that an ERROR log line here means "stop and fix the field
names," reinforcing the mandatory first-live-run verification step already
in the plan (verification step 1).

No findings rejected.
