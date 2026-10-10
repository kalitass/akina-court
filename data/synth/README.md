# Synthetic cases

| file | what it does |
|---|---|
| `build_cases.py` | the six hand-scripted demo cases C-0001..C-0006 (real OneMap routes, scripted detours and chats) -> `data/cases/` |
| `scenarios.py` | the 49 benchmark scenarios (`SCENARIOS`) and the 12 held-out ones (`BLIND_SCENARIOS`, `--blind`) -> `data/bench/`, `data/bench/blind/`; the reference answer of each case is derived (`derive_truth`), never typed |
| `contract.py` | the scenario contract: what a scenario's labels claim about its record, and the checks of a record against them |
| `validate.py` | format and arithmetic checks of a case file (schema, 5 s grid, fare recomputed, bands on the route) |
| `trajectory.py`, `route_provider.py`, `fare.py` | GPS synthesis, OneMap routing with the leg cache, fares from the rate card |

## Adding a scenario

1. Add one `R(...)` / `N(...)` / `S(...)` line to `SCENARIOS` (or `BLIND_SCENARIOS`). Say what the record must hold with the
   conditions (`loops`, `consent`, `stop`, `incident`, `band`, `prior`, `threat`, `weather`; `by`, `park_m`, `wait_s` /
   `within_s`, `here`, `cancel_s`, `driver`, `prior_ns`, `chat`; `gps_hole_s`, `gps_tail_cut_s`, `policy`, `recorded_by`).
   A new condition value needs a branch in the builder AND in `contract.contract_for` (tests fail on an unread key).
2. Write the `hard` label as "what makes it hard -> the expected outcome". The part after the last `->` is read by
   `contract.label_implications`: it must name `escalate` / `a person decides`, `refund`, `no_action` / `fee stands` /
   `no refund`, or `exempt`, and may say `flag` / `no flag`. A label without an outcome is refused.
3. Run `.venv/bin/python data/synth/scenarios.py` (add `--blind` for the held-out set). Legs already in
   `onemap_cache.json` need no network; new loop candidates do, so run with `ONEMAP_TOKEN` (or `ONEMAP_EMAIL` +
   `ONEMAP_PASSWORD`, see the docstring). An offline run prints which scenarios skipped uncached candidates.
4. Rerun `scripts/run_case.py all`, `scripts/run_case.py DISP-002`, `scripts/prerecord_demos.py` and the tests; log any
   moved answer in `data/bench/REFERENCE_CHANGES.md`.

## The contract (what the gate refuses)

`contract_for(spec)` turns the conditions into claims; `check(case, contract)` measures the record with its own
geometry (nothing from `core/`) and returns every claim it misses. `main()` runs it, plus `check_label(hard, truth)`,
on every built case and **does not write** a case that fails: the run prints `<case id> <name> refused: <checks>` and
exits 1. There is no retry that changes the story; fix the scenario or the builder and run again.

What it checks, by condition:

* route: the number of off-route segments equals the number of loops, each adds >= 0.5 km, segments are in time order;
  a loop whose story goes *round* a stretch (`incident` on it, `consent` naming a road or "whichever way", i.e.
  `loop_must_bypass`) bypasses >= `MIN_REPLACED_KM` (1.0 km) of the optimal route and the car drives < 50 % of that
  stretch (an out-and-back spur bypasses nothing); the driver's request is in the chat >= 60 s before the segment
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
