# Synthetic cases

| file | what it does |
|---|---|
| `build_cases.py` | the six hand-scripted demo cases C-0001..C-0006 (real OneMap routes, scripted detours and chats) -> `data/cases/` |
| `scenarios.py` | the 49 benchmark scenarios (`SCENARIOS`) and the 12 held-out ones (`BLIND_SCENARIOS`, `--blind`) -> `data/bench/`, `data/bench/blind/`; the reference answer of each case is derived (`derive_truth`), never typed |
| `contract.py` | the scenario contract: what a scenario's labels claim about its record, and the checks of a record against them |
| `validate.py` | format and arithmetic checks of a case file (schema, 5 s grid, fare recomputed, bands on the route) |
| `trajectory.py`, `route_provider.py`, `fare.py` | GPS synthesis, OneMap routing with the leg cache, fares from the rate card |

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
| driver no-show: real wait / too short / tapped far away / no tap | `N(... by="driver", park_m, wait_s or within_s, here=True/False)` | `ns_driver_wait_*`, `ns_fake_here_*`, `ns_no_tap` |
| driver no-show with a hole in the trace / record-stated threshold / unknown canceller | `gps_hole_s=`, `policy={...}`, `recorded_by=None` | `bl_hole_in_wait`, `bl_record_threshold_*`, `bl_cancelled_by_missing` |
| rider cancels inside / after the grace period, driver en route / at the pin | `by="rider", cancel_s=, driver="en_route" / "at_pickup"` | `ns_rider_cancel_*` |
| safety complaint with / without a threat in the chat, keyword traps | `S(... chat="driver_threat" / "rider_threat" / "innocuous")` | `safe_*` |

Every case carries a real OneMap route, a 5 s GPS trace on real roads, LTA-style speed bands and incidents, a weather
record, a fare from the rate card and a chat; the replay page plays any of them (`/replay.html?case=B-0001`).

## Adding a scenario

1. Append one `R(...)` / `N(...)` / `S(...)` line to the END of `SCENARIOS` (or `BLIND_SCENARIOS`). The list is
   append-only: a case's id (`B-0050`), date and trip id come from its position, and `tests/test_synth_pipeline.py`
   fails if an existing scenario moves. Its random streams (where the car starts, the wording, the GPS jitter) come from
   the scenario's NAME (`identity()`), so nothing else changes when a scenario is added.
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
   .venv/bin/python data/synth/scenarios.py --case bl_new --blind       # held-out set
   ```
   The case is built in memory and published only after every gate passed: the contract (the record tells the story),
   `reference.py` (an engine-free derivation agrees with the engine's reading), `expect`, `validate.py` (format and
   arithmetic) and `lint.py` (the rules a reader checks by eye). A failed build changes nothing on disk and exits 1.
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
* **Dates.** Two cases a day from 2026-09-01 (bench) / 2026-10-03 (held-out): every case is dated before the sets were built.

## The gates (what a build must pass before it is published)

* `contract.contract_for(spec)` turns the conditions into claims; `contract.check(case, contract)` measures the record
  with its own geometry (nothing from `core/`) and returns every claim it misses.
* `reference.derive_reference(case, conditions, kind)` derives the answer from the raw record and the labels without
  the engine; `derive_truth` (engine) must agree on ruling, amount and flag.
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
* every case: 5 s grid (unless a hole is the story), increasing timestamps, `+08:00`, Singapore bounds, estimate ==
  route, fare recomputed from the trace / rate card (unless the tail is cut), chat inside the trip, the weather record.

`tests/test_contract.py` runs the same checks over every committed case (`KNOWN_PENDING` lists the records that still
fail; fixing one must remove its entry), checks every label against the reference, and re-derives every reference
answer from the raw record and the labels without the engine.
