# Reference answers: change log

The reference answer of every benchmark case is derived by `data/synth/reference.py` from the generated record and the
scenario's interpretive labels (what the rider's words mean), under the rules in `policy/policy.md`, never from a
model's output; `data/synth/scenarios.py` publishes a case only when the engine reaches the same answer. The version
string lives in `data/bench/manifest.json` (`reference_version`). Every answer that a rule change moves is listed here.

## 2026-10-14 v5e — four cases validated against the live models, ported verbatim

Rules unchanged. Four cases built by hand (a bench case copied, texts edited) and validated against the live models were ported through
the generator: each is its base scenario's record (same trip, GPS, fare and date) with the validated texts laid over it, verbatim
(PORT_TEXT in scenarios.py). B-0001 and B-0007 share B-0014's trip; B-0023 shares B-0020's (without the fraud flag); B-0028 keeps its own.
Every expected answer carries escalate_ok.

| case | scenario | before (v5d) | after | why |
|---|---|---|---|---|
| B-0001 | rd_port_trust_fastest | no_action (rd_cte_consent_connector) | no_action | ported R-0014: "Whatever road you think is fastest, I trust you, don't need to follow the app." |
| B-0007 | rd_port_auntie_any_way | refund_partial $7.73 (rd_stop_unnamed) | no_action | ported R-0016: "Any way also can, you decide, just bring me to NUS to see my grandson." |
| B-0023 | sg_port_notice_fare_unchanged | no_action (sg_surge_fell) | refund_partial $3.46 | ported M-0011: "Your fare stays at the quoted $12.71." (no revised fare) |
| B-0028 | sg_port_notice_window_closed | no_action (sg_rider_denies_notice) | refund_partial $4.88 | ported M-0008: "Free cancellation until 17:13." received at 17:14:45 (the window had closed) |

## 2026-10-13 v5d — six cases where each side is partly right

Rules unchanged. Six more near-duplicates were replaced by cases a careful reading after argument settles.

| case | scenario | before (v5c) | after | why |
|---|---|---|---|---|
| B-0002 | rd_notice_ack_hmm | no_action (rd_within_tolerance) | no_action | acknowledged notice: 'Jam ahead on Ayer Rajah Expressway, I'm going via Clementi Avenue 2.' / 'hmm ok lor'; complaint 'I just said hmm' |
| B-0005 | rd_consent_except_road | refund_partial $3.61 (rd_consent_after) | no_action | consent with an exclusion not driven: '可以，不要走 Clementi Avenue 2。' |
| B-0015 | rd_two_segs_consent_seg1 | refund_partial $6.49 (rd_two_segs_consent_seg1) | refund_partial $6.49 | reworked: 'can go via Upper Bukit Timah Road?' / 'ok'; complaint wants the whole excess, driver 'She agreed to my route.' |
| B-0025 | sg_mixed_rider_stop | refund_partial $14.88 (sg_mixed_rider_stop) | refund_partial $11.22 | shorter trip; 'Can stop at Paya Lebar Square for 5 min?' / 'Ok'; driver 'No refund is due...'; only the surge part is refunded |
| B-0026 | sg_notice_just_before_pickup | refund_partial $21.54 (sg_mid_amount) | no_action | complete notice 20 s before pickup; complaint 'only popped up as I was getting into the car' |
| B-0046 | ns_gate_b_refused_to_move | no_action (ns_parked_180m_rider_says_absent) | no_action | Gate A / Gate B: 'Cannot stop at Gate A, double yellow line, please come to Gate B.'; complaint 'refused to come to me' |

## 2026-10-13 v5c — six cases where reading the text exactly as the policy writes it is the whole question

Rules unchanged. Six near-duplicate cases were replaced by cases built around a realistic distractor that invites a stricter or looser
reading than the policy text; the benefiting party has an obvious argument. The fraud flag of the replaced B-0028 moved to B-0021.

| case | scenario | before (v5b) | after | why |
|---|---|---|---|---|
| B-0001 | rd_cte_consent_connector | refund_partial $6.42 (rd_basic) | no_action | distractor: agreed road driven together with its connector roads |
| B-0004 | rd_stop_named_longer_way | refund_partial $4.65 (rd_incident_on_stretch) | no_action | distractor: the driver's own 'the way to the market was a bit longer because of one-way streets' |
| B-0016 | rd_call_log_no_recording | refund_partial $4.08 (rd_verbal_consent_no_recording) | refund_partial $4.08 | distractor: an answered 25 s call in the call log, with no recording or transcript |
| B-0019 | sg_notice_estimate_above_charge | refund_partial $3.47 (sg_not_notified) | no_action | distractor: the notice's estimate ($12.65) is above the fare charged ($11.88), and the rider calls it misleading (replaces the arguable time-limited free cancel) |
| B-0028 | sg_rider_denies_notice | refund_partial $1.85 (sg_fraud_flag_rider) | refund_partial $4.88 | distractor: the rider's 'I never received any notice about surge pricing' |
| B-0037 | ns_need_to_go_after_no_reply | refund_full $5.00 (ns_rider_cancel_150s) | no_action | distractor: 'No reply from you, I need to go already, cancelling.' |
| B-0021 | sg_notice_after_pickup | refund_partial $2.56 (sg_notice_after_pickup) | refund_partial $2.56 | distractor: fraud flag moved here from the replaced B-0028: timing is code-settled (97% >= 95%) |

## 2026-10-13 v5b — reviewers' round: one arrival time, readings as text, realistic speeds

Rules unchanged. Records changed after a hand audit: (1) a no-show's recorded arrival is the arrival confirmation, the car parks at it, so
arrival, parking and the tap coincide; (2) what a reader must decide is text, never a boolean in the file: the surge notice is its verbatim
`notification_text`, every cancellation carries `cancellation_reason` (the canceller's claim) and the driver's own words; (3) speeds follow the
road class (expressways ~70 km/h, 10% faster at night), the trace standing still wanders a metre, the last sample of a moving car keeps its
speed; (4) surge trips are RydeX with the quote priced on the route estimate and FARE-0 fares (waiting folded into time); (5) a jam band covers
the whole detour; (6) TH-* never in cited_policy (the thresholds are named in the rationale); a TH-3 escalation carries `merits`;
(7) safety rationales are factual summaries; SAFE-2 only for dangerous driving. Amounts move with the new timings and loops.

| case | scenario | before (v5) | after | why |
|---|---|---|---|---|
| B-0001 | rd_basic | refund_partial $4.51 (rd_basic) | no_action | new loop position (the old one only had out-and-back candidates) |
| B-0003 | rd_named_cn_am | no_action (rd_named_cn_am) | escalate (merits: no_action) | fraud flag added on the rider: a lone reading of the clear text (87%) is under TH-3's 95%; merits = the policy's answer once both sides read it alike |
| B-0004 | rd_incident_on_stretch | refund_partial $7.19 (rd_incident_on_stretch) | no_action | loop rebuilt without the U-turn; accident text no longer names a guessed exit |
| B-0005 | rd_consent_after | refund_partial $3.06 (rd_consent_after) | no_action | new timings (road-class speeds, arrival = confirmation, estimate-priced quote) |
| B-0007 | rd_stop_unnamed | refund_partial $7.71 (rd_stop_unnamed) | no_action | new timings (road-class speeds, arrival = confirmation, estimate-priced quote) |
| B-0008 | bl_named_elsewhere | refund_partial $7.50 (bl_named_elsewhere) | refund_partial $5.95 | loop rebuilt without the U-turn |
| B-0009 | rd_request_only | refund_partial $7.47 + flag_account (rd_request_only) | refund_partial $6.77 + flag_account | Beach Station pin moved to the real station; loop rebuilt |
| B-0010 | rd_long_loop_mid_amount | refund_partial $11.58 (rd_long_loop_mid_amount) | refund_partial $11.55 | new timings (road-class speeds, arrival = confirmation, estimate-priced quote) |
| B-0013 | rd_general_consent_jp | escalate (rd_general_consent_jp) | escalate (merits: no_action) | merits added: no_action once the reading is settled |
| B-0014 | rd_impatient_rider | refund_partial $3.44 (rd_rude_rider) | refund_partial $5.89 | now an objection ('No... stay on') plus plain impatience, not an insult |
| B-0015 | rd_two_segs_consent_seg1 | refund_partial $6.66 (rd_two_segs_consent_seg1) | refund_partial $6.49 | loop 2 rebuilt; the rider's yes is 'Ok can.'; RD-3 cited |
| B-0016 | rd_verbal_consent_no_recording | refund_partial $7.53 (rd_verbal_consent_no_recording) | refund_partial $4.08 | loop rebuilt |
| B-0018 | bl_negation | refund_partial $6.53 (bl_negation) | refund_partial $4.50 | new loop position (0.20-0.40) |
| B-0019 | sg_notice_estimate_above_charge | refund_partial $4.34 (sg_not_notified) | no_action | new timings (road-class speeds, arrival = confirmation, estimate-priced quote) |
| B-0021 | sg_notice_after_pickup | refund_partial $3.48 (sg_notice_after_pickup) | refund_partial $2.56 | new timings (road-class speeds, arrival = confirmation, estimate-priced quote) |
| B-0022 | sg_notice_no_cancel_option | refund_partial $5.41 (sg_notice_no_cancel_option) | escalate (merits: refund_partial $4.65) | fraud flag added on the rider: a lone reading of the clear text (87%) is under TH-3's 95%; merits = the policy's answer once both sides read it alike |
| B-0020 | sg_notified_full | no_action (sg_notified_full) | escalate (merits: no_action) | fraud flag added on the rider: a lone reading of the clear text (87%) is under TH-3's 95%; merits = the policy's answer once both sides read it alike |
| B-0024 | sg_surge_unchanged_complaint_threat | escalate (sg_surge_unchanged_threat) | escalate | the safety allegation is in the complaint of a fare dispute |
| B-0025 | sg_mixed_rider_stop | refund_partial $15.71 (sg_mixed_rider_stop) | refund_partial $11.22 | new timings (road-class speeds, arrival = confirmation, estimate-priced quote) |
| B-0026 | sg_mid_amount | refund_partial $25.89 (sg_mid_amount) | no_action | the notice says only 'prices are higher than usual' (a reading) |
| B-0027 | sg_over_50 | escalate (sg_over_50) | escalate | the notice says 'cancellation fees may apply' (a reading) |
| B-0028 | sg_fraud_flag_rider | refund_partial $2.95 (sg_fraud_flag_rider) | refund_partial $4.88 | new timings (road-class speeds, arrival = confirmation, estimate-priced quote) |
| B-0032 | ns_app_noshow_own_reason | refund_full $5.00 (ns_no_message) | refund_full $5.00 | app says rider_no_show, the driver's own words give his reason (NS-3) |
| B-0039 | ns_driver_cancel_flat_tyre | refund_full $5.00 (ns_driver_cancel_flat_tyre) | refund_full $5.00 | driver arrived and waited; no reason picked; 'car got problem' (NS-3) |
| B-0040 | ns_safety_in_complaint | refund_full $5.00 (ns_driver_late_contacted) | escalate | a no-show charge whose complaint alleges harassment (SAFE-1) |
| B-0041 | ns_driver_late_no_contact | refund_full $5.00 (ns_driver_late_no_contact) | refund_full $5.00 + goodwill_credit $5.00 | new timings (road-class speeds, arrival = confirmation, estimate-priced quote) |
| B-0045 | ns_impatient_driver | no_action (ns_rude_driver) | escalate (merits: no_action) | fraud flag added on the rider: a lone reading of the clear text (87%) is under TH-3's 95%; merits = the policy's answer once both sides read it alike |

## 2026-10-13 v5 — the organisers' policy; a new 50-case set

The benchmark was rebuilt on the organisers' Dispute Resolution Policy v2.1 (`policy/policy.md` v3): 18 route
deviation, 18 no-show, 10 surge (fare dispute), 4 safety. It replaces the earlier set: 34 cases are rebuilt from one
of its scenarios (same name, pair and pinned loop plan where the story still holds; `reused_from` in the manifest names
the earlier id), 16 are new. Every case file was regenerated (official-plus format, GPS samples carry the
road name, $5.00 fees, call logs, surge logs).

Rules that move answers, compared with v4:

* RD-1 / RD-2: every fare is distance-based (no fixed-fare branch). Deviation = billed distance − optimal route; the 1 km
  tolerance applies to what is left once exempt segments are taken out; refund = that × the trip's per-km distance fare.
* RD-4: a traffic reason (incident on the replaced stretch reported before the segment, or speed band 1–2) no longer
  exempts a segment; it decides whether a driver violation is recorded, and an uninformed reroute with a reason gets the
  RD-7 reminder. Only the rider's agreement before the segment (RD-5) or a rider-named stop (RD-3) exempts.
* RD-5: a rider's agreement to "go via X" is checked against the road names of the GPS samples of the segment (X driven
  -> exempt, not driven -> counts); a recorded call whose transcript holds the rider's yes counts as agreement, a driver's
  account of a spoken yes without a recording does not. Named-road agreements no longer escalate (v4 G13).
* NS-1: $5.00; 5-minute free wait (inclusive) from the later of arrival and scheduled time (a record-stated threshold is
  counted from arrival); the driver needs at least one in-app message AND one call before cancelling. NS-8 (driver late
  past scheduled + 5 min: free cancel, $5.00 goodwill credit without any contact attempt) and NS-9 (third no-show in 30
  days: flag) are new.
* SURGE-1..3 (new): refund (trip multiplier − quote multiplier) × surgeable subtotal unless the rider got an in-app
  notice before pickup stating the new multiplier, the revised fare and free cancellation; the booking fee is not surged.
* TH-1..4: over $50 a person decides; $10–50 needs code confidence ≥ 80%; a fraud flag raises it to 95% (a judge reading
  of the rider's words gives 90%, a fraud flag ×97%); missing or broken records escalate.

| case | scenario | before (v4 case it was built from) | after | why |
|---|---|---|---|---|
| B-0001 | rd_port_trust_fastest | validated by hand (R-0014) | no_action | the rider, before the detour: 'Whatever road you think is fastest, I trust you, don't need to follow the app.'; no traffic reason, and the complaint says the driver abused that trust: a general route choice covers a way round to the destination (RD-5), and what is left is within the 1 km tolerance -> no refund |
| B-0002 | rd_notice_ack_hmm | v4 case 0003 (rd_consent_after): refund_partial $2.74 | no_action | the driver told the rider (a statement, not a question) he was going via a named road because of the jam, the rider answered 'hmm ok lor' before the turn-off, and the GPS shows that road; the complaint says 'I just said hmm': an acknowledged notice is agreement (RD-5) -> no refund |
| B-0003 | rd_named_cn_am | v4 case 0056 (rd_named_cn_am): escalate | escalate (merits: no_action) | traffic on the stretch; the driver asked to go via a named road and the rider agreed in Chinese before the turn-off, and the GPS road names show that road: informed and agreed (merits: no refund); the rider carries a fraud flag, so a lone reading (87%) is under 95% -> escalate unless both sides read the yes alike |
| B-0004 | rd_stop_named_longer_way | new | no_action | the rider named Tiong Bahru Market before the turn-off and the car stopped there; the driver himself says the way there was longer because of one-way streets, but RD-3 exempts the whole segment to a rider-named stop, and what is left is within the 1 km tolerance -> no refund |
| B-0005 | rd_consent_except_road | v4 case 0050 (rd_general_consent_jp): no_action | no_action | 'Jam ahead, shall I take another way?' answered '可以，不要走 Y' (ok, don't use Y): consent with an exclusion; the GPS road names show Y was not driven, so the consent covers the loop (RD-5); the complaint says the rider put conditions -> no refund |
| B-0006 | rd_stop_named_prior | v4 case 0011 (rd_stop_named_prior): no_action | no_action | RD-3: the rider named Clementi Mall; with that loop exempt, what is left of the deviation is under the 1 km tolerance, and the driver's 2 priors trigger no RD-6 flag -> no refund, no flag |
| B-0007 | rd_port_auntie_any_way | validated by hand (R-0016) | no_action | the 72-year-old rider, before the detour: 'Any way also can, you decide, just bring me to NUS'; the complaint asks for sympathy: a general route choice covers the way round (RD-5), the rest is within tolerance -> no refund |
| B-0008 | bl_named_elsewhere | earlier-set case 0007 (bl_named_elsewhere): refund_partial $7.11 | refund_partial $5.95 | the rider agreed to go via a named road, but the GPS road names show the segment never used it (RD-5) -> the agreement does not cover it, refund |
| B-0009 | rd_request_only | v4 case 0021 (rd_request_only): refund_partial $6.27 | refund_partial $6.77 + flag_account | the driver asked about another road and the rider never answered: no agreement (RD-5); the driver has 2 upheld route disputes in 90 days -> refund + flag_account (RD-6) |
| B-0010 | rd_long_loop_mid_amount | v4 case 0052 (rd_general_consent_cn_cp): no_action | refund_partial $11.55 | a long loop round a crawling stretch, rider not informed: the refund is in the $10-50 band (TH-1) and code settles it -> refund, the system decides |
| B-0011 | bl_gps_tail_missing | earlier-set case 0008 (bl_gps_tail_missing): escalate | escalate | the trace ends 4 min before drop-off, and just before that the rider asked for another road and drop-off point: whether the car went there (the rider's own route, RD-3) cannot be measured (TH-4) -> escalate |
| B-0012 | rd_threat_in_chat | v4 case 0024 (rd_threat_in_chat): escalate | escalate | route dispute whose chat holds an intimidating driver message -> the safety screen (SAFE-1) overrides: escalate |
| B-0013 | rd_general_consent_jp | v4 case 0050 (rd_general_consent_jp): no_action | escalate (merits: no_action) | 'whichever way is faster' would exempt the loop, but that rests on reading the rider's words and the rider carries a fraud flag: 90% x 97% is under the 95% TH-3 needs -> escalate |
| B-0014 | rd_impatient_rider | v4 case 0049 (rd_keyword_trap_find_you): refund_partial $2.74 | refund_partial $5.89 | the driver asked to go round and the rider said no, stay on the main road; he went anyway, and the rider wrote 'Why you go this way?? I said stay. I'm late already': an objection (no agreement, RD-5) and frustration, not a safety matter -> refund |
| B-0015 | rd_two_segs_consent_seg1 | v4 case 0013 (rd_two_segs_consent_seg1): escalate | refund_partial $6.49 | two segments: before the first the driver asked 'can go via' a road and the rider said 'ok', and the GPS shows it driven (exempt; no traffic reason, so the rider's own route, RD-3); the second is a later loop with no message before it (counts); the rider wants all of it back, the driver says she agreed to his route -> refund the second segment's share only |
| B-0016 | rd_call_log_no_recording | v4 case 0009 (rd_band2_heavy_rain): refund_partial $7.06 | refund_partial $4.08 | the driver says 'I called her before the turn and she said ok', and the call log shows an answered 25 s call, but no recording and no transcript: a logged call is not the rider's agreement (RD-5: verbal notice needs the recording) -> refund |
| B-0017 | rd_recorded_call_consent | v4 case 0008 (rd_band1_incident): no_action | no_action | an accident on the stretch, and the recorded call before pickup has the rider agreeing to go via the road the GPS shows -> informed and agreed (RD-5 with a recording), no refund |
| B-0018 | bl_negation | earlier-set case 0004 (bl_negation): refund_partial $5.41 | refund_partial $4.50 | 'Can lah, but not via Y' and the GPS shows the segment on Y: the agreement excluded the road the driver took -> counts, refund |
| B-0019 | sg_notice_estimate_above_charge | new | no_action | the in-app notice before pickup states 1.3x, a new estimated fare and 'You can cancel for free'; the estimate is above what was charged and the rider calls it misleading, but SURGE-1 asks the notice to state a revised fare, not to predict it -> no refund |
| B-0020 | sg_notified_full | new | escalate (merits: no_action) | surge rose and the rider got an in-app notice before pickup with the new multiplier, the revised fare and free cancellation, then rode (merits: no refund); the rider carries a fraud flag, so a lone reading of the notice (87%) is under 95% -> escalate unless both sides read it alike |
| B-0021 | sg_notice_after_pickup | new | refund_partial $2.56 | a complete notice, but sent after pickup (SURGE-1 needs it before or at pickup); the rider carries a fraud flag, but the timing is settled by code (97% >= 95%, TH-3) -> refund the surge part |
| B-0022 | sg_notice_no_cancel_option | new | escalate (merits: refund_partial $4.65) | the log says rider_notified, but the notice never offers free cancellation: no SURGE-1 notice (merits: refund the surge part); the rider carries a fraud flag, so a lone reading (87%) is under 95% -> escalate unless both sides read it alike |
| B-0023 | sg_port_notice_fare_unchanged | validated by hand (M-0011) | refund_partial $3.46 | the timely notice says 'Your fare stays at the quoted $12.71': it states no revised estimated fare, so SURGE-1 is not met although the multiplier and free cancellation are there -> refund the surge part (capped at actual - quote) |
| B-0024 | sg_surge_unchanged_complaint_threat | new | escalate | filed as a fare dispute: the 1.3x surge was in the quote and unchanged (no refund on the fare), but the complaint says the driver told the rider he knows where she lives -> safety screen (SAFE-1): escalate |
| B-0025 | sg_mixed_rider_stop | new | refund_partial $11.22 | no notice of a 1.4x surge, and the rider also asked for a stop that lengthened the trip; she wants the whole difference over the quote, he says nothing is due because of the stop -> refund only the surge part, (1.4 - 1.0) x surgeable subtotal (SURGE-3); the stop's share is hers (RD-3) |
| B-0026 | sg_notice_just_before_pickup | new | no_action | a complete in-app notice timestamped 20 s before pickup; the rider says it only popped up as she got into the car, with no real chance to cancel; SURGE-1 asks for it before or at the point of pickup -> no refund |
| B-0027 | sg_over_50 | new | escalate | the notice names 2.0x and the new fare but says 'cancellation fees may apply' (the opposite of a free-cancel option): not a SURGE-1 notice, and the surge part is over $50 (TH-1) -> escalate, the system prepares the case file |
| B-0028 | sg_port_notice_window_closed | validated by hand (M-0008) | refund_partial $4.88 | the notice says 'Free cancellation until 17:13.' but reached the rider at 17:14:45, after that window had closed: no free-cancel option was open to her, so SURGE-1 is not met -> refund the surge part (capped at actual - quote) |
| B-0029 | ns_wait_5m10 | v4 case 0033 (ns_wait_185s_edge): no_action | no_action | 5 min 10 s at the pickup after the arrival tap, two messages, and one unanswered call that is only in the call log; the rider says he never called -> every NS-1 condition holds, fee stands |
| B-0030 | ns_wait_4m50 | v4 case 0034 (ns_wait_175s_edge): refund_full $6.61 | refund_full $5.00 | 4 min 50 s at the pickup, then cancelled: short of the 5-minute free wait (NS-1 (ii)) -> refund |
| B-0031 | ns_no_call | v4 case 0028 (ns_wait_4min): no_action | refund_full $5.00 | waited 5+ min and messaged, but never called (NS-1 (iii) needs both); the rider's 2 earlier no-shows count for nothing when this one is not upheld -> refund, no flag |
| B-0032 | ns_app_noshow_own_reason | v4 case 0027 (ns_wait_2min): refund_full $6.61 | refund_full $5.00 | the app reason says rider_no_show and every NS-1 element holds, but the driver's own cancel message says he left for a family matter: the reason is his, not a no-show (NS-0, NS-3) -> refund |
| B-0033 | ns_no_contact | v4 case 0031 (ns_no_here_tap): refund_full $6.61 | refund_full $5.00 | Precedent 7.3 pattern: a long wait at the pin but zero contact attempts -> refund the $5.00 |
| B-0034 | ns_fake_here_far | v4 case 0026 (ns_fake_here_far): refund_full $6.61 + flag_account | refund_full $5.00 + flag_account | NS-2: arrival tapped 600 m away, never within 200 m -> refund + flag_account |
| B-0035 | bl_hole_in_wait | earlier-set case 0011 (bl_hole_in_wait): escalate | escalate | 6 min from the arrival tap to the cancel, a message and a call: the fee would stand if the car stayed, but a 200 s hole in the trace leaves that unproven (NS-1 (iv), TH-4) -> escalate |
| B-0036 | bl_record_threshold_7m50 | earlier-set case 0009 (bl_record_threshold_7m50): refund_full $5.00 | refund_full $5.00 | the record states an 8-min no-show threshold; 7:50 passes the 5-min default but not the record's own -> refund |
| B-0037 | ns_need_to_go_after_no_reply | v4 case 0029 (ns_rider_cancel_150s): refund_full $6.61 | no_action | no reason picked in the app; after 6 min, two messages and a call the driver wrote 'No reply from you, I need to go already, cancelling': he leaves because the rider did not come (a no-show, NS-0), not for a reason of his own; NS-1 holds -> fee stands |
| B-0038 | ns_rider_cancel_200s | v4 case 0030 (ns_rider_cancel_200s): no_action | no_action | NS-4: 200 s after matching -> fee stands; the driver being on the way is not a ground (no scheduled time, NS-8 cannot apply) |
| B-0039 | ns_driver_cancel_flat_tyre | new | refund_full $5.00 | no reason picked in the app; the driver arrived, waited 5+ min, messaged and called, then wrote 'tyre puncture, car got problem, have to cancel': his own reason, not a no-show (NS-0, NS-3) -> refund |
| B-0040 | ns_safety_in_complaint | new | escalate | filed as a no-show charge and the no-show facts favour the driver, but the complaint says he kept making comments about her body and asked where she lives -> safety screen (SAFE-1): escalate |
| B-0041 | ns_driver_late_no_contact | new | refund_full $5.00 + goodwill_credit $5.00 | NS-8: late driver who never messaged or called -> refund + $5.00 goodwill credit |
| B-0042 | ns_repeat_noshow_flag | v4 case 0042 (ns_rider_cancel_100s_bad_profile): refund_full $6.61 | no_action + flag_account | every NS-1 condition holds and the driver's 'waited more than 5 min, cancelling' is a no-show cancel; this is the rider's third no-show in 30 days -> fee stands + flag_account (NS-9) |
| B-0043 | ns_early_arrival_scheduled | new | refund_full $5.00 | the driver arrived about 2 min before the scheduled pickup and cancelled 4 min after it (6 min after arriving): the free wait runs from the scheduled time, 4 min is short of 5 -> refund |
| B-0044 | ns_threat_in_chat | v4 case 0041 (ns_threat_in_chat): escalate | escalate | the no-show facts favour the driver, but his chat holds 'I will find you and you will regret it' -> safety screen (SAFE-1): escalate |
| B-0045 | ns_impatient_driver | new | escalate (merits: no_action) | no reason picked in the app, but 'Waited 5 min already, you never come, cancelling' is a no-show cancel and NS-1 holds (merits: fee stands); 'Still waiting ah, so slow' is impatience, not a safety matter; the rider carries a fraud flag, so a lone reading (87%) is under 95% -> escalate unless both sides read it alike |
| B-0046 | ns_gate_b_refused_to_move | v4 case 0043 (ns_wait_4min_180m): no_action | no_action | the driver tapped at Gate B, 150 m from the pin, and told the rider he could not stop at Gate A (double yellow line); he called once, waited 6 min and cancelled; the rider says he refused to come to her: NS-1 holds within 200 m and he cancelled because she did not come (NS-0) -> fee stands |
| B-0047 | safe_driver_threat | v4 case 0044 (safe_driver_threat): escalate | escalate | SAFE-1: driver threatens to lock the rider in -> escalate |
| B-0048 | safe_rider_threat | v4 case 0045 (safe_rider_threat): escalate | escalate | SAFE-1: rider threatens the driver; the driver filed -> escalate, no refund |
| B-0049 | safe_innocuous_chat_dangerous_driving | v4 case 0046 (safe_innocuous_chat_dangerous_driving): escalate | escalate | innocuous chat; the complaint alleges speeding and hard braking, and the trace shows ~98 km/h on the expressway with two sharp decelerations -> SAFE-2 escalate |
| B-0050 | safe_no_chat_harassment | v4 case 0047 (safe_no_chat_harassment): escalate | escalate | no chat at all; harassment alleged in the statement -> escalate (SAFE-1 via type) |
