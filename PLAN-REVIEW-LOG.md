# Plan review log — avia-watcher

## Setup

- Host: Claude Code (this session) — requirements owner, coordinator, default builder.
- Plan reviewer: Codex (fresh session per round).
- Builder: host (Claude), default — user asked to build the project directly.
- Final inspector: fresh Codex session (inspects code host did not have reviewed by Codex before writing).
- Plan file: `PLAN.md`
- Rounds: MAX_ROUNDS=5, MAX_FIX_ROUNDS=2, MAX_INSPECTION_ROUNDS=2, inspect=on.
- Research: web (already performed — official Travelpayouts API docs, see PLAN.md "Assumptions and sources").
- Scope: greenfield project, not a git repo yet → review with `--skip-git-repo-check`.
- Authorization: user's original request is to build a working project end-to-end
  (README, systemd instructions, DoD with real test run) — plan + implementation
  both authorized by the task itself.
- Model/effort: not explicitly pinned by user; using CLI defaults for both
  reviewer (Codex) and inspector (Codex) calls.

## Rounds

### Round 1 — REVISE

Reviewer: Codex (codex-cli 0.154.0), CLI default model. session_id
01a0a199-67ea-7e60-94d5-fc3359ad088f. plan_sha256
6730c49126e051653c7f1d0c988251b74967ed3d1e40ce401e40ec148e4380c6.
Result artifact: C:\Users\UNUSUA~1\AppData\Local\Temp\claudex-x6qkjj_l\result.json

Verdict: REVISE. 6 findings (3 high: REV-001 API selection, REV-002
one_way/currency not propagated into requests/route identity, REV-003 no
alert dedup; 3 medium: REV-004 acceptance-criterion contradiction, REV-005
no rate-limit/429 handling, REV-006 no `actual` filtering / itinerary-link
mismatch).

Host arbitration: independently re-verified REV-001 empirically (live HTTP
probe: `aviasales/v3/prices_for_dates` → 401 vs a made-up path on the same
host → 404, confirming the endpoint is real; my round-1 research relied on
an incomplete GitHub mirror of the docs). All 6 findings accepted, no
findings rejected. Full disposition: `feedback_round1.md`. PLAN.md revised
accordingly (new plan_sha256 to be recorded after round 2 submission).

Two residual risks recorded as explicit open assumptions rather than
resolved by guessing further: exact response field names of
`prices_for_dates` (esp. the ticket-link field) and the endpoint's exact
rate limit — support.travelpayouts.com was unreachable from this session
(DNS failure). Both mitigated with defensive code + a mandatory first-live-run
verification step in the plan.

### Round 2 — REVISE

Reviewer: Codex (codex-cli 0.154.0). session_id (resumed)
01a0a199-67ea-7e60-94d5-fc3359ad088f. plan_sha256
4b0a925e8bd832ac3d8b37abf99488e2ff692d5d4b845f9a59a5ede62d6ed7cf.
Result artifact: C:\Users\UNUSUA~1\AppData\Local\Temp\claudex-3w10szwc\result.json

Verdict: REVISE. 5 findings (1 high: REV-007 alert dedup not crash-safe /
false atomicity claim; 4 medium: REV-008 rate limit advisory-only + 429
sleep blocks other routes, REV-009 non-actual entries silently dropped
instead of persisted per acceptance criterion 2, REV-010 undefined link
normalization, REV-011 ambiguous fetch/record/decide ordering with a
self-suppression risk).

Host arbitration: all 5 accepted, no rejections. REV-007 implemented as
at-least-once (pending/sent status column) rather than the plan's suggested
at-most-once, to avoid silently losing an alert on an ordinary transient
Telegram send failure — documented as a deliberate choice, with the residual
duplicate-on-crash edge case named explicitly rather than hidden. Full
disposition: `feedback_round2.md`. PLAN.md revised: new "Порядок решения",
persisted-`actual`-column, pending/sent dedup, enforced `EFFECTIVE_INTERVAL`
+ non-blocking 429 handling, and one canonical link-normalization rule, all
spelled out mechanically rather than left as prose intent.

Also folded in (not a review finding): user requested multi-origin coverage
(several regional departure airports against one or more destinations) and
asked for the tool to clearly outperform Aviasales' own tracker. Reflected
as a config.py-only convenience (`ROUTES` generated from an `ORIGINS ×
DESTINATIONS` comprehension) — no change to watcher.py's contract, schema,
or any of the mechanics reviewed above.

Separately, user asked whether the agent could scrape "absolutely all
aggregators," not just Aviasales — directly contradicting a constraint the
user's own original brief stated explicitly (no mass scraping of OTA sites:
ToS/IP-ban risk). Explained the tradeoffs (no free official APIs exist for
other major Russian OTAs; Aviasales is itself a meta-search aggregating many
agencies under the hood already) and asked the user to choose via
AskUserQuestion. User chose to keep Aviasales/Travelpayouts API only — no
scope change, plan unaffected.

### Round 3 — REVISE

Reviewer: Codex (codex-cli 0.154.0). session_id (resumed)
01a0a199-67ea-7e60-94d5-fc3359ad088f. plan_sha256
0c6aeb1dc4328f0b960fa8112e9c42809737bd552424d63c997a2edab389b258.
Result artifact: C:\Users\UNUSUA~1\AppData\Local\Temp\claudex-_42a8pq3\result.json

Verdict: REVISE. 5 findings (2 high: REV-012 at-least-once dedup
contradicts criterion 2's unconditional "no repeat" wording, REV-014 no
request timeouts → daemon can hang forever on a stalled connection; 3
medium: REV-013 alert-send failure skips record_price for that cycle,
REV-015 spoofable `startswith("http")` link trust check, REV-016 unrecognized
API schema silently produces a daemon that runs "successfully" while finding
nothing).

Host arbitration: all 5 accepted, no rejections. REV-012 resolved by making
acceptance criterion 2's wording explicitly scoped (matches the already-
justified round-2 at-least-once mechanism) rather than switching to
at-most-once. REV-016 resolved with a loud ERROR-level distinguishable log
signal rather than a hard crash (crashing would violate the 24/7-resilience
requirement). Full disposition: `feedback_round3.md`. PLAN.md revised:
acceptance criterion 2 reworded, alert-send wrapped in a local try/except so
`record_price` always runs, `REQUEST_TIMEOUT_SECONDS` added to every HTTP
call, `build_purchase_link` rewritten with `urlparse` + host allowlist,
`fetch_cheapest` distinguishes empty-vs-unrecognized-schema responses.

### Round 4 — REVISE

Reviewer: Codex (codex-cli 0.154.0). session_id (resumed)
01a0a199-67ea-7e60-94d5-fc3359ad088f. plan_sha256
be4066008412f99b59e8eed0dd4c6d0b28aa1ff2e21eb61ecbc6e081322dfebf.
Result artifact: C:\Users\UNUSUA~1\AppData\Local\Temp\claudex-oorxnns6\result.json

Verdict: REVISE. 3 findings (2 high: REV-017 pending alerts can be
permanently abandoned once repeated recording of the same low price shifts
the rolling median so the fresh-anomaly condition that previously gated
retry stops firing, REV-018 `raise_for_status()`'s URL-bearing exception
message can leak the Travelpayouts/Telegram tokens into systemd/journal
logs; 1 medium: REV-019 the no-link fallback silently presents a dateless
generic route-search page as if it reproduced the alerted itinerary).

Host arbitration: all 3 accepted, no rejections. REV-017 resolved by
splitting `check_route`'s alert handling into an idempotent `claim_alert`
(only runs on a fresh anomaly) and an unconditional-every-cycle
`flush_pending_alerts` (retries any undelivered pending row regardless of
this cycle's anomaly decision) — decoupling delivery-retry from
fresh-anomaly-detection as the finding required. REV-018 resolved by moving
the Travelpayouts token to the `X-Access-Token` header (removing it from
that URL entirely) plus a `redact_url` helper and a structured-fields-only
logging rule for both hosts. REV-019 resolved via the review's own offered
alternative (mark the fallback as non-itinerary-specific in the message
rather than assert an unconfirmed date-bearing URL scheme). Full
disposition: `feedback_round4.md`.

Round budget: this was round 4 of MAX_ROUNDS=5. Submitting round 5 next: if
still REVISE, per protocol the host stops and presents unresolved findings
plus its own position rather than manufacturing convergence or burning past
the configured budget.

### Round 5 — REVISE (final round within MAX_ROUNDS=5; not resubmitted)

Reviewer: Codex (codex-cli 0.154.0). session_id (resumed)
01a0a199-67ea-7e60-94d5-fc3359ad088f. plan_sha256
af2b1625f15ade476f25f0b68395ac1733605dd852dacb55cc767159d1d1d87d.
Result artifact: C:\Users\UNUSUA~1\AppData\Local\Temp\claudex-wq_1zdbe\result.json

Verdict: REVISE. 3 findings (2 high: REV-020 `flush_pending_alerts` was
nested under "entry is not None" despite being described as unconditional —
a Travelpayouts outage/429 also silently blocked delivery of already-pending
Telegram alerts; REV-021 the round-4 claim/flush split lost the API's
itinerary link, since neither `purchase_url` nor `is_itinerary_specific` was
persisted at claim time, forcing every delivery through the generic
fallback; 1 medium: REV-022 no backoff/expiry for repeatedly-failing pending
alerts).

Host arbitration: all 3 accepted — both high findings are literal
self-introduced bugs (a step-ordering contradiction and a data-loss
regression from the round-4 claim/flush split), not external-fact disputes,
so the host applied them directly rather than requiring further adversarial
verification. `check_route` restructured so `flush_pending_alerts` runs
unconditionally as the true last step, outside the "entry is not None"
branch; `alerts` gains `purchase_url`, `is_itinerary_specific`,
`attempt_count`, `next_attempt_at`; `claim_alert` now persists the computed
purchase link immutably at claim time; `flush_pending_alerts` applies capped
exponential backoff (honoring Telegram `Retry-After` on 429) and a new
`ALERT_MAX_AGE_SECONDS` (3600s) expiry so a long-pending alert is marked
`expired` with a WARNING log instead of being sent stale. Full disposition:
`feedback_round5.md`.

**STOPPING HERE per protocol**: this was round 5 of `MAX_ROUNDS=5`. No 6th
round is submitted. Host's position: PLAN.md is now believed sound and
ready for implementation; round 5's changes are confined to `check_route`'s
step ordering and the `alerts` schema and do not reopen any round 1-4
finding. 22 findings total were raised and accepted across 5 rounds (0
rejected) — proceeding to Phase 3 (build), implementation already authorized
by the original task ("write a working project... README... systemd...
tested end-to-end").

## Phase 3 — Build (host = builder, per default role)

Base commit for inspection: `0f36e21` (empty baseline, created with user's
explicit authorization to `git init` + commit locally so a fresh Codex
session could diff-inspect real code, not just the plan — repo-local git
identity set for this, not global). Implementation committed as `308d5b0`.

### Inspection attempt 1 — INVALIDATED (host process error, not a code finding)

`inspect --base 0f36e21 ...` with the runner's own stdout redirected to
`inspect_round1.log` *inside* the inspected repo — the file grew while the
run was in flight, which changed the tracked/untracked snapshot mid-inspection
and the runner correctly refused: `"error": "Code changed during inspection;
inspect the final code again."`, `"status": "failed"`. This is the runtime
guidance ("keep artifacts outside the target checkout") that the host failed
to follow on the first attempt — not a defect in avia-watcher.

Despite the invalidated wrapper status, the embedded Codex response was a
real, evidence-based REVISE with 3 findings (session 01a0a1b5...):
REV-023 (medium, Telegram 429 Retry-After discarded, generic backoff used
instead), REV-024 (medium, N route requests fired as an instantaneous burst
at cycle start rather than paced — average rate within budget, instantaneous
rate not), REV-025 (medium, a successful-but-malformed JSON shape, e.g. a
top-level list, would raise AttributeError inside fetch_cheapest, escaping
check_route before the unconditional flush_pending_alerts step). Host
accepted all 3, fixed watcher.py (TelegramRateLimited exception carrying
retry_after; per-route request pacing via compute_request_spacing +
itertools.cycle in main(); defensive isinstance() validation of payload/data/
item shapes in fetch_cheapest), added deterministic tests, committed as
`e772619`.

### Inspection attempt 2 — COMPLETED, REVISE (2 findings)

Rerun with the runner's stdout kept outside the repo (session scratchpad).
`"status": "completed"`, session 01a0a1ba... Verdict REVISE, 2 new findings
(did not re-flag REV-023/024/025 — confirms those fixes held up under a
fresh read): REV-026 (medium, the pacing loop let a slow request's delay
accumulate — `next_at += spacing` unconditionally meant a one-time backlog
could still produce a burst of unpaced requests while catching up), REV-027
(medium, `float(price)` on a non-numeric/NaN/Infinity value would raise and
escape the same way REV-025 did, just via a different code path — numeric
parsing rather than shape validation). Host accepted both, fixed watcher.py
(`next_schedule_time()` rebases from `now` instead of the stale schedule when
behind; price parsing wrapped in try/except with an `isfinite` check, skips
to the next item instead of raising), added deterministic tests including a
pure-function test for the pacing fix, committed as `d5b0091`.

### Inspection attempt 3 — FAILED (external: Codex account usage limit)

`"status": "failed"`, `exit_code: 1`, elapsed 12.5s (no actual review ran).
Raw Codex CLI output: `"You've hit your usage limit. Upgrade to Plus to
continue using Codex ..., or try again at Oct 13th, 2026 4:45 PM."` This is
an account-level quota exhaustion, external to this session and to
avia-watcher's code — not a code finding, not a process mistake by the host
this time (artifacts were correctly kept outside the repo).

**STOPPING HERE**: `MAX_INSPECTION_ROUNDS=2` (initial + one after fixes) is
exhausted by the two *valid* rounds above (attempt 1's invalid wrapper status
doesn't consume budget by protocol, but its real findings were fixed anyway
before attempt 2, which is the genuine "initial" content-bearing round;
attempt 2's fixes make attempt 3 the "after fixes" round the budget allows —
which then failed for an external reason, not a content reason). Further
independent Codex inspection is unavailable until the quota resets
(Oct 13, 2026 per the CLI's own message).

**Host's position**: REV-026 and REV-027 were independently re-traced by the
host (not just accepted on faith) and are correctly diagnosed, proportionate
fixes — each has a dedicated deterministic test in `test_watcher.py`
(`test_pacing_does_not_burst_after_a_slow_request`, and the extended
malformed-price cases in `test_fetch_cheapest_handles_malformed_shapes_without_raising`)
that fails without the fix and passes with it. All 13 tests in
`test_watcher.py` pass (`python test_watcher.py`, exit 0). No further Codex
confirmation of this specific round was obtained due to the quota limit —
this is disclosed here rather than implied as approved. The code has NOT
been independently re-inspected after the REV-026/REV-027 fixes; a fresh
Codex `inspect` pass after Oct 13, 2026 would be the way to close that gap
if the user wants it.

25 total findings raised across plan review (22) and code inspection (3
distinct issues across 2 valid rounds: REV-023/024/025, then REV-026/027),
all accepted and fixed, 0 rejected. Final commit: `d5b0091`.
