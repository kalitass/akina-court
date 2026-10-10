# Reference answers: change log

The reference answer of every benchmark case is derived by `data/synth/scenarios.py` from the scenario's own labels
(what was injected: consent, stops, incidents, waits) and the evidence rules in `policy/policy.md`, never from a
model's output. The version string lives in `data/bench/manifest.json` (`reference_version`). Every answer that a
rule change moves is listed here with the gap and why it moves the outcome.

## 2026-10-10 v3 — agreement to a named road needs a record tying the driven segment to it (G13)

Rule: a rider's agreement to "go via X" covers driving on X only. The record carries no road names for the driven
path, so unless a stop on X, a message placing the car on X or a road name in a fact ties the segment to X, the
finding is undetermined; when that finding changes the amount or the flag, a person decides. Timing alone is a lead.
Case files are unchanged; 4 of 49 answers move, all from an automatic outcome to a hand-off.

| case | scenario | before | after | evidence gap | why it changes the outcome |
|---|---|---|---|---|---|
| B-0002 | rd_consent_before | no_action | escalate | no record ties segment F3 to Sims Avenue, the road the rider agreed to | metered trip: the finding decides the RD-2 amount |
| B-0013 | rd_two_segs_consent_seg1 | refund_partial $6.74 | escalate | no record ties segment F3 (loop 1) to Kranji Expressway, the road the rider agreed to | metered trip: loop 1's finding decides part of the amount (loop 2 counts either way) |
| B-0023 | rd_consent_before_prior | no_action | escalate | no record ties segment F3 to Bedok South Avenue 3, the road the rider agreed to | metered trip, and the driver's prior makes the RD-6 flag depend on the finding |
| B-0025 | rd_consent_before_light | no_action | escalate | no record ties segment F3 to Prince George's Park, the road the rider agreed to | metered trip; the decoy incident is far from the route and does not settle the segment under RD-4 |

Not moved although it holds the same kind of agreement: B-0017 (rd_fixed_fare_consent) — a fixed-fare trip with no
prior: the finding changes neither the amount nor the flag, so the segment may stay undetermined and the answer stays
no_action. B-0008 (incident on the replaced stretch) stays exempt under RD-4, which code settles.

## 2026-10-09 v2 — the court reads the chat; keyword labels removed

B-0049 (rd_keyword_trap_find_you): escalate → refund_partial $1.09. "I'll find you at the lobby" is a pickup
arrangement, not a threat; the old answer encoded a keyword rule. B-0003 / B-0021 (rd_consent_after, rd_request_only):
RD-5 added to the cited clauses (the chat holds a route exchange the judge had to read).

## 2026-09-28 v1 — initial set (49 cases, seed in the manifest)

## 2026-10-10 v3b — incident scenarios regenerated so the loop really bypasses the incident

A reviewer found that the loops of the incident scenarios left and rejoined the optimal route at almost the same point
(an out-and-back spur replacing 30–40 m of route), so the accident placed mid-stretch was not on the stretch the
driver bypassed and RD-4 failed although the scenario said "accident on the replaced stretch → exempt". The generator
now requires an incident scenario's loop to bypass at least 1.0 km of the optimal route (`MIN_REPLACED_KM`); four case
files changed, the rules did not.

| case | scenario | before | after | why |
|---|---|---|---|---|
| B-0004 | rd_incident_on_stretch | refund_partial $2.44 (RD-4 failed: incident off the 30 m stretch) | no_action | the loop now bypasses 2.1 km containing the accident, reported 12 min before pickup → RD-4 exempts it |
| B-0006 | rd_incident_late | refund_partial $6.82 | refund_partial $4.34 | same geometry fix; the accident is on the bypassed stretch but reported after the detour began → still not exempt, amount follows the new segment |
| B-0008 | rd_band1_incident | no_action | no_action | geometry fixed (bypasses 1.5 km instead of 0.2 km); outcome unchanged |
| B-0014 | rd_two_segs_incident_seg1 | refund_partial $15.21 (both segments) | refund_partial $4.89 (segment 2 only) | segment 1 now bypasses the accident → exempt under RD-4; segment 2 unexplained → counts |

## 2026-10-10 v3c — contract gate: every loop that claims a bypass must bypass ≥ 1.0 km

`data/synth/contract.py` now derives, from each scenario's conditions, the facts its label implies and the generator
refuses to write a case that fails them. Regenerated with real bypass geometry: B-0013 (loop 1), B-0017, B-0023, B-0025,
X-0005, X-0006, X-0007 (named-road loops that were out-and-back spurs); B-0030, B-0042 (an "en route" driver now really
approaches the pickup); B-0016, B-0019 (fixed-fare statements no longer talk about a meter); X-0004 (a 10 km loop
replaced by a 1.2 km bypass). Reference outcomes unchanged except the two blind amounts below.

| case | scenario | before | after | why |
|---|---|---|---|---|
| X-0004 | bl_negation | refund_partial $14.14 | refund_partial $3.27 | same rule (rider refused, driver went anyway: counts); the loop is now a realistic bypass, so the extra km and the amount changed |
| X-0007 | bl_named_elsewhere | refund_partial $2.44 | refund_partial $2.21 | same rule (driver's own account puts the car on another road: counts); loop regenerated as a real bypass |
