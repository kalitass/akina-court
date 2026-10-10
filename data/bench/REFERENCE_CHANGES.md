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
| B-0006 | rd_incident_late | refund_partial $6.82 | refund_partial $4.34 (now $1.90, see v3d) | same geometry fix; the accident is on the bypassed stretch but reported after the detour began → still not exempt, amount follows the new segment |
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

## 2026-10-10 v3d — story realism: loops that go somewhere, halts for every driver message, no case dated after the build

A reader's audit of the case files found things no rule checks: drivers typing route requests at 40 km/h on an expressway,
LTA bulletins naming the trip's destination mall, out-and-back spurs excused as "GPS rerouted me", a "jam" the record's
own speed bands denied, airport trips crawling the ECP at 30 km/h, and a bench whose last eight disputes were dated after
the submission deadline. `data/synth/scenarios.py` now (a) times every driver line inside a 25 s halt of the car (a
junction), (b) requires a `frac` loop to replace >= 1.0 km of the route when its story goes round a stretch (0.5 km
otherwise) and to drive at most 4x the stretch it replaces, keeping the candidate with the smallest extra km, (c) backs
every "traffic ahead on X" with a band-2 crawl on X, (d) writes incidents with DataMall direction labels, (e) treats the
ECP/highways as expressway class for cruising speed, (f) varies the stock wording, (g) dates the bench from 2026-09-01.
The rules did not change: no ruling, flag or escalation moved; 10 bench amounts and 2 held-out amounts follow the new,
smaller loops. Four bench scenarios and one held-out scenario found no loop that meets (b) on their road network and keep
their previously committed record unchanged (dates included): B-0013, B-0014, B-0015, B-0022, X-0004.

| case | scenario | before | after | why |
|---|---|---|---|---|
| B-0001 | rd_basic | refund_partial $4.17 | refund_partial $1.57 | the 2.96 km out-and-back spur on the ECP is replaced by a loop that bypasses a real stretch |
| B-0003 | rd_consent_after | refund_partial $7.26 | refund_partial $2.28 | smallest qualifying loop (was a 6.5 km loop round 1.3 km of AYE) |
| B-0005 | rd_incident_decoy | refund_partial $2.98 | refund_partial $1.49 | smallest qualifying loop; the decoy breakdown stays 2+ km from it |
| B-0006 | rd_incident_late | refund_partial $4.34 | refund_partial $1.90 | smallest qualifying loop; the accident is still listed after the turn-off (now 10 min after, not 90 s) |
| B-0007 | rd_band1_no_incident | refund_partial $1.13 | refund_partial $0.99 | smallest qualifying loop; band 1 alone still does not exempt |
| B-0009 | rd_band2_heavy_rain | refund_partial $10.36 | refund_partial $1.09 | the 9.4 km loop round 2 km of AYE is gone; same rule (band 2 + rain do not exempt) |
| B-0012 | rd_stop_unnamed | refund_partial $4.47 | refund_partial $2.93 | smallest qualifying loop; the 7-Eleven is still >= 500 m off the route |
| B-0018 | rd_prior_flag | refund_partial $7.26 + flag_account | refund_partial $2.02 + flag_account | smallest qualifying loop; RD-6 flag unchanged |
| B-0021 | rd_request_only | refund_partial $3.12 | refund_partial $1.49 | smallest qualifying loop; no reply, RD-5 still fails |
| B-0049 | rd_keyword_trap_find_you | refund_partial $1.09 | refund_partial $1.07 | re-sampled trace with the pickup halt; same loop |
| X-0003 | bl_general_errand | refund_partial $5.60 | refund_partial $1.33 | new pair (AMK Hub → VivoCity); the driver's own 4-min stop inside the loop still makes it count |
| X-0007 | bl_named_elsewhere | refund_partial $2.21 | refund_partial $0.85 | new pair (Compass One → Kallang Wave Mall); the driver's account still puts the car on another road |

Held-out pairs no longer repeat a bench route: X-0002 Toa Payoh HDB Hub → Changi City Point, X-0003 AMK Hub → VivoCity,
X-0005 Pasir Ris MRT → Suntec City, X-0006 Hougang Mall → Changi Airport T3, X-0007 Compass One → Kallang Wave Mall,
X-0009 Junction 8 → Jurong Point, X-0010 NEX Serangoon → VivoCity, X-0011 Buona Vista MRT → Suntec City, X-0012 Toa Payoh
HDB Hub → Pasir Ris MRT (outcomes unchanged).
