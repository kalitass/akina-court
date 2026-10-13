# Synthetic cases

| file | what it does |
|---|---|
| `build_cases.py` | the six hand-scripted demo cases C-0001..C-0006 (real OneMap routes, scripted detours and chats) -> `data/cases/` |
| `scenarios.py` | the 50 benchmark scenarios (`SCENARIOS`: 18 route, 10 surge, 18 no-show, 4 safety) -> `data/bench/`; the reference answer of each case is derived (`reference.py`), never typed, and the engine must agree |
| `reference.py` | the policy (`policy/policy.md`) as code, without the engine: the reference answer from the record and the scenario's interpretive labels |
| `contract.py` | the scenario contract: what a scenario's labels claim about its record, and the checks of a record against them |
| `validate.py` | format and arithmetic checks of a case file (schema, 5 s grid, fare recomputed, bands on the route) |
| `trajectory.py`, `route_provider.py`, `fare.py` | GPS synthesis, OneMap routing with the leg cache, fares from the rate card (surge quote and breakdown, the policy's $5.00 fee) |

The generator works on the internal `Case` dict and writes official-plus files: the organisers' RydeResolve field names
plus our own fields (`core/case_format.py`, `build_cases.dump`). Code that reads a committed file as a dict uses
`core.case_format.read_case`; `Case.model_validate` takes either shape.

## The stories the generator can tell (one line each; copy the nearest and change what differs)

| story | conditions | example |
|---|---|---|
| detour, no explanation (driver's own choice) | `R(... loops=[{"frac": (a, b)}])` | `rd_basic` |
| detour round an accident on the route (exempt, RD-4) | `incident="on_stretch"` (+ `band=1` for a jam on the feed) | `rd_incident_on_stretch`, `rd_band1_incident` |
| detour with an accident elsewhere / reported too late | `incident="decoy_far"` / `incident="late"` | `rd_incident_decoy`, `rd_incident_late` |
| detour blamed on weather or a slow road (not exempt) | `band=2, weather="heavy"` / `band=1` | `rd_band2_heavy_rain`, `rd_band1_no_incident` |
| rider agreed to a named road before / after / never replied / said no | `consent="before" / "after" / "request_only" / "negation"` | `rd_consent_before`, `rd_consent_after`, ... |
| rider gave a general "any faster way" (English / Chinese) | `consent="general" / "general_cn"` | `bl_general_consent` |
| rider asked for a stop at a named place / "a 7-Eleven" | `loops=[{"place": "Paya Lebar Square"}], stop="named"` / `stop="unnamed"` | `rd_stop_named`, `rd_stop_unnamed` |
| driver's own errand inside a loop | `stop="driver_errand"` | `bl_general_errand` |
| two detours, consent covers only the first | `loops=[{...}, {...}], consent="before_seg1"` | `rd_two_segs_consent_seg1` |
| repeat offender (RD-6 flag) / fixed-fare trip (no km refund) | `prior=2` / `service="RydeX"` | `rd_prior_flag`, `rd_fixed_fare` |
| intimidating driver line during a detour (safety screen) | `threat="driver"` | `rd_threat_in_chat` |
| trace ends early / no detour at all | `gps_tail_cut_s=240` / `loops=[]` | `bl_gps_tail_missing`, `rd_no_deviation` |
| a short detour inside the 1 km tolerance | `target=0.5, min_extra_km=0.25, max_excess_km=0.9`, small `offsets` on the loop | `rd_within_tolerance` |
| rider says "can, but not via Y" and the car takes Y | `consent="qualified"` | `bl_negation` |
| agreement in a recorded call before pickup / a spoken "ok" the driver only claims | `consent="recorded_call"` / `consent="verbal_unrecorded"` | `rd_recorded_call_consent`, `rd_verbal_consent_no_recording` |
| impatient but not a safety matter | `threat="impatient"` (route), `chat="impatient"` (no-show) | `rd_impatient_rider`, `ns_impatient_driver` |
| a safety allegation in the complaint of another dispute type | `complaint_safety=True` | `sg_surge_unchanged_complaint_threat`, `ns_safety_in_complaint` |
| the rider's acknowledgement in other words | `yes="Ok can."` | `rd_two_segs_consent_seg1` |
| why the driver cancelled: the app's reason vs his own words (NS-0 / NS-3) | `app_reason=None` (none picked), `cancel_text="..."`, `reason_reading="no_show" / "own_reason"` | `ns_driver_cancel_flat_tyre`, `ns_app_noshow_own_reason`, `ns_impatient_driver` |
| a trace cut short just after the rider asked for another road | `gps_tail_cut_s=240, tail_request=True` | `bl_gps_tail_missing` |
| dangerous driving the trace corroborates | `S(..., speeding=True)` (~98 km/h on the expressway, two hard brakings) | `safe_innocuous_chat_dangerous_driving` |
| a fraud flag on a party (TH-3) | `fraud={"rider": "flagged_for_..."}` | `rd_general_consent_jp`, `sg_fraud_flag_rider` |
| reuse another scenario's pinned loop under a new story | `geometry_from="old_name"` | `rd_long_loop_mid_amount` |
| driver no-show: real wait / too short / tapped far away / no tap | `N(... by="driver", park_m, wait_s or within_s, here=True/False)` | `ns_wait_5m10`, `ns_wait_4m50`, `ns_fake_here_far` |
| driver's contact attempts before cancelling (NS-1 (iii)) | `contact="both" / "message_only" / "call_only" / "none"` (calls go to the call log only) | `ns_no_call`, `ns_no_message`, `ns_no_contact` |
| a booking for a set time: driver early / driver late (NS-8) | `scheduled_after_tap_s=120` / `by="rider", driver="late", scheduled_after_accept_s=300` | `ns_early_arrival_scheduled`, `ns_driver_late_*` |
| driver cancels on the way for his own reason (NS-3) | `by="driver_other", cancel_s=` | `ns_driver_cancel_flat_tyre` |
| rider's no-shows in 30 days (NS-9) / a claim the record contradicts | `no_shows_30d=2` / `claim="never_called"` | `ns_repeat_noshow_flag`, `ns_wait_5m10` |
| driver no-show with a hole in the trace / record-stated threshold / unknown canceller | `gps_hole_s=`, `policy={...}`, `recorded_by=None` | `bl_hole_in_wait`, `bl_record_threshold_*`, `bl_cancelled_by_missing` |
| rider cancels inside / after the grace period, driver en route / at the pin | `by="rider", cancel_s=, driver="en_route" / "at_pickup"` | `ns_rider_cancel_*` |
| safety complaint with / without a threat in the chat, keyword traps | `S(... chat="driver_threat" / "rider_threat" / "innocuous")` | `safe_*` |
| surge (fare dispute): quote at m0 on the route estimate, trip at m1, the notice's own words | `G(name, pair, m0, m1, notice="none" / "full" / "no_cancel" / "no_fare" / "no_multiplier" / "cancel_fee" / "after_pickup" / "sms" / "missing")` | `sg_*` |
| surge plus a longer trip (SURGE-3 mixed causes) | `G(..., loops=[{"place": ...}], stop="named")` | `sg_mixed_rider_stop` |

Every case carries a real OneMap route, a 5 s GPS trace on real roads (each sample names its road, from the OneMap legs
the car drove; speeds by road class: expressways ~70 km/h, highways ~55, arterials ~46, local streets ~32, 10% faster at
night, a standing car wanders a metre or so), LTA-style speed bands and incidents, a weather record, a fare from the rate card and a chat; the replay
page plays any of them (`/replay.html?case=B-0001`). The 50 are chosen so that each comparison of the four systems is
exercised: arithmetic and timing a model must do from raw data (detour km, waits around 5 min, calls only in the call
log, the surge part, scheduled times, statements the record contradicts), precise conditions that are easy to misapply
(tolerance after exemptions, late notice, unrecorded verbal consent, NS-8, NS-9, fraud threshold, $10-50), and readings
both sides can argue (Chinese / qualified consent, named road driven or not, named vs driver-chosen stop, two segments).

## Adding a scenario

1. Append one `R(...)` / `N(...)` / `G(...)` / `S(...)` line to the END of `SCENARIOS`. A case's id (`B-0051`), date
   and trip id come from its position, and `tests/test_synth_pipeline.py` fails if the manifest and the list disagree.
   Its random streams (where the car starts, the wording, the GPS jitter) come from the scenario's NAME (`identity()`;
   `ns="blind"` keeps the streams of a case ported from the earlier set), so nothing else changes when a scenario is added.
2. Say what the record must hold with the conditions (`loops`, `consent`, `stop`, `incident`, `band`, `prior`, `threat`,
   `weather`; `by`, `park_m`, `wait_s` / `within_s`, `here`, `cancel_s`, `driver`, `prior_ns`, `chat`; `gps_hole_s`,
   `gps_tail_cut_s`, `policy`, `recorded_by`). A new condition value needs a branch in the builder AND in
   `contract.contract_for` (tests fail on an unread key).
3. Write `expect={"ruling": ..., "flag": ...}` — the typed promise the reference must keep (checked, never fed) — and the
   `hard` sentence for the reader ("what makes it hard -> the expected outcome").
4. Build only that scenario:
   ```
   set -a; . ./.env; set +a                                            # OneMap account, only for legs not yet cached
   .venv/bin/python data/synth/scenarios.py --case rd_new              # -> data/bench/{cases,expected}/B-00NN.json + its manifest entry
   SYNTH_SKIP_ENGINE_CHECK=1 .venv/bin/python data/synth/scenarios.py  # publish on reference.py alone (while the engine is being changed)
   ```
   The case is built in memory and published only after every gate passed: the contract (the record tells the story),
   `reference.py` (the published answer) and the engine reaching the same ruling, amount, flag and goodwill credit
   (skipped with `SYNTH_SKIP_ENGINE_CHECK=1`), `expect`, `validate.py` (format and arithmetic) and `lint.py` (the rules a
   reader checks by eye). A failed build changes nothing on disk and exits 1.
   The chosen loop geometry is pinned in the manifest entry (`plan`): a later rebuild never searches again and
   reproduces the file byte for byte from the cache (`tests/test_synth_pipeline.py` proves it for every case).
   `--replan` throws the pinned plan away and searches afresh (needs the network; the amount may move).
5. Run the tests, `scripts/run_case.py all` is NOT needed (demo cases only), run the new case through the arms
   (`bench/run_bench.py --cases B-00NN`), then `scripts/after_batch.sh`. Log any moved answer of an EXISTING case in
   `data/bench/REFERENCE_CHANGES.md`.

Loops: a `frac` loop is searched among corridor candidates (two via points on a road parallel to the stretch, so the
car cannot be routed back onto the stretch between them) and single-via candidates; every valid plan (replaces
>= `MIN_REPLACED_KM` / `MIN_REPLACED_PLAIN_KM`, adds >= `MIN_EXTRA_KM`, re-drives <= `RETRACE_MAX` of the stretch,
drives <= `RATIO_HARD` x it) is scored by the distance of its refundable extra km from the case's target amount
(`TARGET_REFUNDS`, picked by the scenario's identity), plus a penalty above `RATIO_SOFT` and for retracing; two-loop
cases are chosen jointly (the best `TOP_FIRST` loop-1 plans each tried with every loop-2 candidate). The search stops
as soon as a plan lands within `GOOD_ENOUGH` km of the target.

## What the builders do for the story (not checked by the contract, but a reader would notice)

* **Nobody types while driving.** Every driver line sent during a trip (a route request, the petrol ask, "Ok" to a stop,
  a threat) is timed inside a `PAUSE_S` (25 s) halt of the car at a junction — `_try_trace(pauses_km=...)` on the driven
  polyline, `pause_stops()` for a plain trajectory, `approach_trace(pauses=...)` for the pickup chatter; the safety scripts
  put the halt on a surface road (`surface_km`), never on an expressway. A halt is far below the 120 s that makes a stop
  fact; it is billed as metered waiting like any red light. `build_route` asserts the car is below 5 km/h at every driver line.
* **A loop goes somewhere.** A `frac` loop must replace >= `MIN_REPLACED_KM` (1.0 km) of the optimal route when its story
  goes round a stretch (`loop_must_bypass`: an incident on it, an agreement to a named road, "whichever way"), else
  >= `MIN_REPLACED_PLAIN_KM` (0.5 km), and drive at most `MAX_DETOUR_RATIO` (4x) the stretch it replaces; among the
  candidates that qualify the smallest extra km (>= `MIN_EXTRA_KM`) wins, so an out-and-back spur or a 7 km loop round
  1.5 km of road is not written. A loop through a named place keeps the first candidate that measures cleanly: that stop
  is the rider's own request. A scenario for which the real road network offers no such loop keeps its previously
  committed record (the run reports it; `main()` writes nothing for it).
* **A claim of traffic has traffic behind it.** Consent scenarios set `band=2` on the stretch the driver names, backed by a
  15 km/h crawl before the turn-off (and `CRAWL_PAST_KM` into the slip road); the no-loop scenario in heavy rain drives
  at a speed that puts the trip over the estimate, so "traffic was slow" and "the fare was higher" are both true.
* **Incidents read like DataMall.** `EXPRESSWAY_DIR` gives the direction label of each expressway from the way the route
  runs ("(towards TPE)"), never the trip's destination; a `late` incident is listed 10 min after the driver turned off.
* **Wording varies.** Chat lines, cars, outfits and the stock statements come from small pools chosen by the case's own
  rng (`PICKUP_LINES`, `ASK_LINES`, `CANCEL_LINES`, ...); the pickup line names the spot a rider waits at (`PICKUP_SPOT`).
  Paraphrases keep the words the contract reads ("on X is building", "go round via", "Sure", "Accident on X (").
* **Dates.** Two cases a day from 2026-09-01 (bench) / 2026-10-03 (cases ported from the earlier set): every case is dated before the sets were built.

## The gates (what a build must pass before it is published)

* `contract.contract_for(spec)` turns the conditions into claims; `contract.check(case, contract)` measures the record
  with its own geometry (nothing from `core/`) and returns every claim it misses.
* `reference.derive_reference(case, conditions, kind)` derives the whole expected answer from the raw record and the
  labels without the engine; `engine_answer` (the engine's certificate, its interpretive route slots filled from the
  reference's findings, and its TH gate) must agree on ruling, amount, flag and goodwill credit.
* `contract.check_expect(expect, truth)`: the typed promise holds.
* `validate.check_case`: schema, 5 s grid, fare recomputed, bands on the route, expected-answer vocabulary.
* `lint.lint_case`: the universal rules — no driver line while the car moves (by displacement, 10 s before the
  message), pins within 100 m of the road, no out-and-back spur without a stop in it, no re-driving more than half
  of a left stretch, speed bands equal to what `lint.band_level` measures from the trace, timestamps in order, no
  date after 2026-10-09, no bulletin naming the trip's destination. `tests/test_lint.py` runs it over every committed
  file, demos and the organisers' sample included.

What it checks, by condition:

* route: the number of off-route segments equals the number of loops, each adds >= 0.5 km, segments are in time order;
  a loop whose story goes *round* a stretch (`incident` on it, `consent` naming a road or "whichever way") bypasses
  >= `MIN_REPLACED_KM` (1.0 km) of the optimal route and the car drives < 50 % of that stretch (an out-and-back spur
  bypasses nothing; the builder itself demands this of every `frac` loop); the driver's request is in the chat >= 60 s before the segment
  (`after`: >= 60 s after), the rider's reply before (or after) it as labelled, `negation` is a refusal,
  `request_only` has no reply, `scope_other` has no stop; the road the driver names as jammed is the main road of
  the bypassed stretch; a `named` stop is inside the segment within 150 m of the place the rider named before the
  segment, an `unnamed` stop is >= 500 m off the route, `driver_errand` has no rider request, `none` has no stop at
  all; an `on_stretch` / `seg1` / `late` incident lies on the bypassed stretch (RD-4 tolerance 0.3 km) and is
  reported before pickup (`late`: >= 60 s after the segment start), `seg1` is not also on segment 2, `decoy_far`
  is >= 2 km from every stretch; a `band` record sits on the stretch's main road, ends by the segment start and the
  GPS crawled in that band for the 150 s before the detour; `prior` equals the driver's upheld route disputes; the
  threat line is present only when scripted; a fixed-fare statement does not talk about the meter; quoted km match.
* no-show: `cancelled_by`, the tap exists only when `here`, the car is `park_m` (± 25 m) from the pickup at the tap,
  the continuous seconds inside 200 m after the tap equal `within_s` or fall in `wait_s − 30..−15`, a `park_m > 200`
  trace never enters the radius, `cancel_s` is exact, an `en_route` driver gets closer to the pickup without
  stopping or arriving, an `at_pickup` driver stands within 60 m for >= 180 s after the tap, `gps_hole_s` is the only
  hole and sits inside the wait, `policy` parameters are on the record, `prior_ns` and the fee in the statement.
* safety: the scripted line and `filed_by`, `innocuous` carries no hint word, the insult only when `statement_threat`, no detour, no stop.
* surge: the log's multipliers, the notice (in-app / SMS, before / after pickup, which of the three items it states, or
  no record of it), the fare recomputed at the trip multiplier, the surgeable subtotal and booking fee in the breakdown,
  the quote total priced from its subtotal, the same subtotal in quote and trip unless the story adds a stop; the threat.
* every case: no 5 s step over 125 m (140 m where the complaint alleges speeding), no detour that comes back over its own
  path (out-and-back, U-turn, closed loop) unless a stop is in it (`lint.py` LOOPBACK); the candidate search rejects them.
* readings: what a reader must decide (the rider's agreement, a named stop, the notice text, the driver's reason, the
  safety screen) is never a boolean in the case file; the manifest's `readings` lists each element with the scenario's label.
* named roads: the road the rider agreed to is among the segment's GPS road names (or, for `named_elsewhere`, nowhere
  in the trace; for `qualified`, the excluded road is driven); a recorded call carries the request and the yes.
* no-show contact: messages and calls before the cancellation as `contact` says; scheduled time a whole minute where the
  story puts it; a late driver never inside 200 m and cancelled on after scheduled + 5 min; `no_shows_30d` and fraud flags.
* every case: 5 s grid (unless a hole is the story), increasing timestamps, `+08:00`, Singapore bounds, estimate ==
  route, fare recomputed from the trace / rate card (unless the tail is cut), chat inside the trip, the weather record.

`tests/test_contract.py` runs the same checks over every committed case (`KNOWN_PENDING` lists the records that still
fail; fixing one must remove its entry), checks every label against the reference, and re-derives every reference
answer from the raw record and the labels without the engine.
