# Ryde Dispute Resolution Policy — Akina Court edition

The official documents take priority; where they are silent, this system sets the rule.

- **[Official]**: stated in an official document.
- **[Official + system detail]**: the rule is official; how this system applies it to the records is ours or from a Ryde help-centre page.
- **[System rule]**: not in the official documents; quoted from a Ryde help-centre page where one states it.
- **system rule** in a Source line = set by this system; neither the official documents nor Ryde's public pages specify it.

Source codes refer to `policy/sources.md`.

| Code | File | Content |
|---|---|---|
| O1 | `Document 2 — Ryde Dispute Resolution Policy v2.1 (Markdown).md` | Ryde Dispute Resolution Policy v2.1, effective 2026-01-01 |
| O2 | `RydeResolve Route Deviation Dataset — DISP-001.md` | Route-deviation sample; official ruling `partial_refund` $3.44 |
| O3 | `RydeResolve Sample Dataset — DISP-002 No-Show Charge Dispute (SG).md` | No-show sample; official ruling: fee upheld |
| O4 | `Document 1 — Fare Dispute Sample Data (JSON).md` | Surge sample (DISP-003); 1.0x → 1.5x without notice, rider asks for $4.50 |

---

## 0. Fare

**FARE-0** — Fare build-up [Official + system detail]
Actual fare = (base + distance + time fare) × surge multiplier at trip start + booking fee (not surged) + tolls / ERP (at cost) + published add-on fees. All service types.
<sub>Source: O1 Appendix A "calculated using actual distance, actual time, and the surge multiplier in effect at trip start"; O1 §3.5 "Booking fee" surge-exempt; O2 "Tolls are passed through at cost." Add-on fees: A9 "a $3.00 add/edit destination fee will apply".</sub>

---

## 1. RD — Route deviation

**RD-1** — Distance and tolerance [Official + system detail]
Deviation = actual distance − recommended distance. ≤ 1 km → no refund.
System detail: the code splits the trip into off-route segments (times, roads, extra km) so each can be checked under RD-3, RD-4, RD-5. Departures under 0.2 km are map-matching noise.
<sub>Source: O1 §1.4 "actual_route_distance − recommended_route_distance"; §1.3 "deviation ≤ 1km … No refund (within tolerance)". Segments, 0.2 km: system rule.</sub>

**RD-2** — Refund matrix [Official + system detail]
Deviation over 1 km:

| Situation | Outcome |
|---|---|
| Traffic reason, rider informed and agreed | `no_action` |
| Traffic reason, rider **not** informed | Refund excess distance fare, `refund_partial` |
| **No** traffic reason | Refund excess distance fare, `refund_partial`; record a driver violation |

Amount = refundable km × this trip's per-km distance fare (or `excess_distance_fare` if given). Tolls, time fare and surge are not refunded.
System detail: refundable km = deviation − km of segments exempt under RD-3 / RD-5.
<sub>Source: O1 §1.3 "rider informed and agrees … No refund", "rider not informed … Partial refund of excess distance fare", "without traffic justification … Full refund of excess distance fare"; O2 "calculated at $0.80/km … $3.44", "Only the excess distance fare is refunded." Exempt km: system rule.</sub>

**RD-3** — Rider-requested stops or routes [System rule]
Rider named a place or route in chat and the driver accepted, or an in-app destination change / added stop was accepted → that segment is not a deviation. Driver chose an off-route place the rider did not name, without saying so beforehand → not exempt. Stop time is charged as time fare. An accepted destination change adds $3.00.
<sub>Source: A7 "reach a mutual agreement before you go"; A9 "If the driver accepts your edit destination request, a $3.00 … fee will apply". Driver-chosen places, stop time: system rule.</sub>

**RD-4** — Traffic reason [Official + system detail]
A reroute needs traffic data showing closure, incident or congestion on the replaced part of the recommended route at trip time.
System detail: a segment has a traffic reason if (a) a traffic event (accident, closure, fire, roadworks, heavy congestion) is on the recommended route — within 300 m, or on a road the route uses — started before the segment and was still active; or (b) the route's speed band there is 1 or 2 (under 9 / 10–19 km/h) during the segment. Otherwise none.
<sub>Source: O1 §1.1 "in response to real-time traffic conditions, road closures, or congestion"; §1.4 "verified via historical traffic API data for the route segment"; B7 "1 – indicates speed range from 0 < 9 2 – … 10 < 19". 300 m, road names, bands 1–2: system rule.</sub>

**RD-5** — Notice and consent [Official + system detail]
The driver must tell the rider before or at the point of deviation, by in-app chat or phone; a brief reason is enough. Chat or call recording shows the rider acknowledged → agreed.
System detail:
- Notice after the segment began does not count, nor does an explanation given only after the rider asks (DISP-001).
- Verbal notice needs a call recording; the driver's word alone does not count.
- Rider agreed to "go via X" → the code checks X against the roads driven on that segment: present → covered; absent → not covered. No road names in the record → escalate.
- Driver proposed a reroute with no traffic reason and the rider clearly agreed beforehand → treated as the rider's route (RD-3), no refund.
<sub>Source: O1 §1.2 "MUST inform the rider … via in-app chat or verbally (with the trip call recording as evidence) before or at the point of deviation"; §1.4 "call recording confirms rider acknowledgment, the deviation is considered agreed"; A7 "reach a mutual agreement before you go". Late notice, road-name check: system rule.</sub>

**RD-6** — Repeat deviations [System rule]
Upheld against the driver, and the driver had an upheld deviation in the last 90 days → add `flag_account`. The profile never decides the current case.
<sub>Source: A10 "Repeated or severe breaches may lead to permanent suspension". 90 days: system rule.</sub>

**RD-7** — Reminder after uninformed reroute [Official]
Refund for not informing the rider → also send the driver a notification-duty reminder and log it on the driver's route compliance record; no formal warning for a first such incident.
<sub>Source: O2 actions "Issue a reminder to the driver … No formal warning given as this is a first notification-related incident", "Log the notification failure".</sub>

---

## 2. NS — No-show and cancellation

**NS-0** — Which clause [System rule]
Driver cancelled for rider no-show → NS-1 / NS-2; driver cancelled for another reason → NS-3; rider cancelled → NS-4; driver did not arrive → NS-8.
<sub>Source: system rule.</sub>

**NS-1** — No-show fee stands [Official + system detail]
Driver cancels for rider no-show: the **$5.00 fee** stands (paid to the driver) only if all hold:
(i) driver arrived: pressed "I'm Here" or arrival was auto-confirmed, with GPS within 200 m of the pickup point;
(ii) the **5-minute free wait** passed, counted from the later of scheduled pickup time and arrival; a no-show threshold in the record (DISP-002: 8 min) applies instead;
(iii) before cancelling, the driver sent **≥ 1 in-app message and made ≥ 1 in-app call**;
(iv) the driver stayed at the pickup point throughout; a GPS gap that leaves this unproven → escalate.
<sub>Source: O1 §2.1 "free wait time of 5 minutes from the scheduled pickup time"; §2.2 "$5.00 … transferred to the driver"; §2.3 "At least 1 in-app chat message, AND … At least 1 phone call"; A3 "at the pick-up location according to GPS data"; O3 "Auto-arrival confirmed", "no_show_threshold_min": 8. 200 m, later-of-two, continuous presence, GPS gap: system rule.</sub>

**NS-2** — No-show fee voided [Official + system detail]
Any NS-1 condition fails → `refund_full` of $5.00. Driver marked arrival while GPS was not at the pickup point → also `flag_account`.
<sub>Source: O1 §2.3 "the cancellation fee is voided and the rider is not charged"; A10 "Fraudulent behavior … 8. Abuse of Cancellation and Waiting Fee Policy".</sub>

**NS-3** — Driver cancelled for another reason [System rule]
→ No fee; if charged, `refund_full`.
<sub>Source: A1 lists the only chargeable cases: "Rider cancels after 3 minutes of matching OR The driver presses "I'm Here", waits … and cancels the trip (Rider NO SHOW …)".</sub>

**NS-4** — Rider cancelled [System rule]
Within 3 minutes of matching → free; later → $5.00 fee (Ryde's help centre says $6.61; this system uses the official $5.00).
<sub>Source: A1 "within 3 minutes of matching are not chargeable"; O1 §2.2 "cancellation fee of $5.00".</sub>

**NS-8** — Driver did not arrive [Official]
Driver not at pickup by scheduled time + 5 min → rider may cancel free; a fee charged → `refund_full`. Driver also made no contact attempt → add $5.00 `goodwill_credit`.
<sub>Source: O1 §2.4 "scheduled pickup time + 5 minutes), the rider may cancel at no charge", "fails to attempt contact … $5.00 goodwill credit".</sub>

**NS-9** — Repeat rider no-shows [Official]
≥ 3 no-show cancellations in a rolling 30 days → `flag_account` (upfront payment; suspension pending Trust & Safety review). The profile never decides the current case.
<sub>Source: O1 §2.5 "3 or more no-show cancellations within a 30-day rolling window … flagged".</sub>

---

## 3. SURGE — Surge pricing

**SURGE-1** — Quote lock and notice [Official]
The quote is binding at the multiplier when quoted. Multiplier rises before trip start → in-app notice before or at pickup stating the new multiplier, the revised estimated fare, and free cancellation. Missing any item → not notified.
<sub>Source: O1 §3.1 "binding at the surge multiplier in effect at quote time"; §3.2 "new surge multiplier … revised estimated fare … option to cancel without penalty".</sub>

**SURGE-2** — Surge refund [Official]

| Situation | Outcome |
|---|---|
| Surge rose, rider notified, rode | `no_action` |
| Surge rose, rider **not** notified | Refund full surge differential, `refund_partial` |
| Surge fell | Lower fare applies |
| Unchanged | Quoted fare applies |

<sub>Source: O1 §3.3 "rider not notified … Full refund of the surge differential"; O4 "rider_notified": false.</sub>

**SURGE-3** — Differential [Official + system detail]
Differential = actual fare − quote, when the whole difference comes from surge.
System detail: if other causes (e.g. a deviation) are mixed in, refund only (trip multiplier − quote multiplier) × surgeable subtotal (booking fee excluded); the rest goes to RD or other clauses.
<sub>Source: O1 §3.4 "actual_fare − upfront_quote … attributable solely to a surge multiplier change"; O4 "surgeable_subtotal": 9.00. Mixed causes: system rule.</sub>

---

## 4. DMG — Vehicle damage

**DMG-1** — Claims [Official]
Driver may claim cleaning or repair for rider-caused damage: spills, vomit, stains; interior damage (seats, doors, windows); exterior damage while boarding or alighting.
<sub>Source: O1 §4.1 "cleaning or repair fees resulting from rider-caused damage".</sub>

**DMG-2** — Evidence [Official]
Photos within 24 hours of trip end, taken and auto-timestamped in the Ryde driver app (no external uploads), linked to the trip by GPS and trip time.
<sub>Source: O1 §4.2 "within 24 hours", "built-in camera, not external uploads", "via GPS telemetry and trip timestamp".</sub>

**DMG-3** — Amounts [Official]
Cleaning up to $50.00 on photos alone. Repair at cost, with a certified workshop's written quote within 7 days.
<sub>Source: O1 §4.3 "Up to $50.00", "written quote from a certified workshop; quote must be submitted within 7 days".</sub>

**DMG-4** — Insufficient evidence [Official]
No timestamp, external photo, or not linked to the trip → claim rejected, `fee_waived`. Rider disputes the damage → see TH-2.
<sub>Source: O1 §4.4 "If evidence is insufficient … the claim is rejected".</sub>

---

## 5. SAFE — Safety

**SAFE-1** — Safety screen [Official + system detail]
Any case, whatever type was filed: chat, complaint or appeal describes dangerous driving, harassment, assault or threats, inappropriate conduct, an accident, or someone feeling unsafe → `escalate`.
System detail: the court decides by reading the text; the code only highlights hint-word sentences. Every case is screened, hint words or not.
<sub>Source: O1 §5.2 "flag any dispute that contains safety-related keywords or indicators for immediate human escalation, regardless of the dispute type". Court reading: system rule.</sub>

**SAFE-2** — Accident and injury [Official + system detail]
Accident, injury or dangerous driving → `escalate`; the summary lists 995, the driver's commercial motor insurance and RydeHELP.
<sub>Source: O1 §5.1 "Traffic accidents during the trip"; A14 "call 995 … driver's commercial motor insurance … via RydeHELP".</sub>

**SAFE-3** — AI limits in safety cases [Official]
The AI may only gather evidence, summarise accounts and prepare the case file; it may not rule, assign fault or recommend an outcome.
<sub>Source: O1 §5.2 "CANNOT issue rulings, determine fault, or recommend resolutions on safety incidents".</sub>

**SAFE-4** — Interim measures [Official]
After escalation the system may suspend the accused party (no trip acceptance / no booking) until human review; lifted if no violation is found. Action `interim_suspension`.
<sub>Source: O1 §5.3 "Temporary suspension of the accused party's account", "lifted if the human reviewer determines no safety violation occurred".</sub>

---

## 6. TH — System decision or human review

**TH-1** — By amount [Official]

| Amount | Path |
|---|---|
| Under $10 | System ruling final |
| $10–$50 | System rules at confidence ≥ 80%, else escalate |
| Over $50 | Human review; system prepares the case file |

<sub>Source: O1 §6.1 table.</sub>

**TH-2** — By category [Official]
Safety → human. No-show / cancellation → system final ($5.00 fixed). Fare → TH-1. Route deviation → by amount as TH-1, following DISP-001 (section 9, C1). Damage → cleaning ≤ $50 with verifiable photos: system; repair over $50: human.
<sub>Source: O1 §6.2 table; O2 "assigned_to": "RydeResolve_Auto_Resolution".</sub>

**TH-3** — Confidence [Official + system detail]
Based on evidence completeness, policy clarity, precedent alignment, party credibility. Any party with fraud flag ≥ 1 → threshold 95%, any amount.
System detail: the code computes it; the AI does not score itself. Complete = needed records present (GPS coverage, timestamped messages, who cancelled); clear = exactly one rule row applies; aligned = a similar precedent reached the same outcome; credibility = both profiles.
<sub>Source: O1 §6.3 "evidence completeness, policy clarity, precedent alignment, and party credibility", "fraud flag ≥ 1 … raised to 95%". Computation: system rule.</sub>

**TH-4** — Missing records [System rule]
A missing or broken GPS track, untimestamped messages, no record of who cancelled, etc. leaves an outcome-relevant condition undecidable → escalate, stating what is missing. Missing records favour neither party.
<sub>Source: system rule.</sub>

---

## 7. PREC — Precedents

**PREC-1** — Citing precedents [Official + system detail]
Search precedents by dispute type and key facts and cite them in the reasons. Loaded: DISP-2026-0089 (uninformed reroute, $3.20), DISP-2026-0142 (surge without notice, $3.20), DISP-2026-0211 (no-show cancel, zero contact, $5.00).
System detail: human-confirmed rulings join the store.
<sub>Source: O1 §7 "search precedent rulings by dispute type and key facts, and cite the relevant precedent". Store: system rule.</sub>

---

## 8. Ruling actions

| Action | Meaning |
|---|---|
| `refund_full` | Refund the disputed item in full |
| `refund_partial` | Refund only the overcharge, with the calculation |
| `fee_waived` | Fee or claim voided |
| `no_action` | Not upheld; charge stands |
| `escalate` | Human review with the case file |
| `flag_account` | Add-on: account review (fraud, repeat violations) |
| `goodwill_credit` | Add-on: $5.00 rider credit (NS-8) |
| `interim_suspension` | Add-on: suspension until human review (SAFE-4) |

Refunds go to the original payment method, in SGD. Every ruling cites its clause IDs with the official section (e.g. RD-2 / §1.3).
<sub>Source: O2 "method": "original_payment_method"; O1 closing note "must cite the applicable policy section".</sub>

---

## 9. Contradictions in the official documents

| # | Contradiction | This system |
|---|---|---|
| C1 | §6.2 sends deviations over 2 km to human review, but DISP-001 (4.3 km) is resolved automatically with $3.44; §6.1 makes rulings under $10 final. | Follows DISP-001: under $10 the system decides (TH-1, TH-2). |
| C2 | §4.4 sends disputed damage claims to human review; §6.2 lets the system decide cleaning ≤ $50 with verifiable photos. | Follows §6.2 (more specific). |
| C3 | §1.3 calls the refund "partial" with a traffic reason but no notice, "full" with no traffic reason; both are the excess distance fare (DISP-001's "partial" is all of it). | Same amount; no traffic reason also records a violation (RD-2). |
| C4 | §2.1 counts the free wait from scheduled time; DISP-002 counts from arrival (2 min early) and adds an 8-min threshold. | Later of the two; a record threshold applies (NS-1). DISP-002 is upheld either way. |
| C5 | §6.3 raises the threshold to 95% on a fraud flag; §6.2 makes no-show rulings final. DISP-002's rider has one flag. | The flag only raises the threshold; the system still decides at ≥ 95% (TH-3). |
| C6 | DISP-001 cites "Driver Policy §4.2"; v2.1 has it at §1.2. | Cite v2.1 §1.2. |

---

## 10. Rules Ryde has not specified (system defaults)

| Topic | Default | Clause |
|---|---|---|
| "At the pickup point" radius | 200 m | NS-1 |
| "Repeat" driver deviation | One upheld deviation in 90 days | RD-6 |
| Per-km refund rate | Trip's distance fare ÷ distance (DISP-001: $0.80/km) | RD-2 |
| Missing or broken records | Escalate, no presumption | TH-4 |
| Agreed route, no road names in record | Escalate | RD-5 |
