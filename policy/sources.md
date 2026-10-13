# Policy sources

Only sources that `policy/policy.md` still cites. A source is kept only when a verbatim sentence from it states the rule of the clause that cites it. Excerpts are verbatim (English), never paraphrased.

Ryde help-centre excerpts were taken on 2026-09-28 through the public Zendesk JSON API (`https://help.rydesharing.com/api/v2/help_center/en-us/articles/<id>.json`; the web pages return 403 to plain fetches) and re-checked in a browser on 2026-10-09. Entry codes (A1, A3 …, B7) are kept from the earlier register; the gaps are the removed entries listed at the end.

## O. Official documents (sent by the organisers, 2026-10-13)

These take priority over everything else.

### O1. Ryde Dispute Resolution Policy v2.1
- File: `Document 2 — Ryde Dispute Resolution Policy v2.1 (Markdown).md`
- What it is: the official policy, effective 1 January 2026. Sections 1–7 (route deviation, no-show, fare and surge, property damage, safety, ruling thresholds, precedents), Appendix A glossary.
- Cited by: FARE-0, RD-1, RD-2, RD-4, RD-5, NS-1, NS-2, NS-4 (amount), NS-8, NS-9, SURGE-1, SURGE-2, SURGE-3, DMG-1–4, SAFE-1–4, TH-1–3, PREC-1, section 8.

### O2. DISP-001 route-deviation sample
- File: `RydeResolve Route Deviation Dataset — DISP-001.md`
- What it is: full case record (trip, GPS, recommended route, chat, traffic events) with the official ruling `partial_refund` $3.44 and its breakdown and actions.
- Cited by: FARE-0, RD-2, RD-7, TH-2, section 8.

### O3. DISP-002 no-show sample
- File: `RydeResolve Sample Dataset — DISP-002 No-Show Charge Dispute (SG).md` (local copy carries a " (1)" download suffix)
- What it is: full case record (GPS, chat, app events, cancellation policy) with the official ruling: cancellation fee upheld.
- Cited by: NS-1.

### O4. DISP-003 surge sample
- File: `Document 1 — Fare Dispute Sample Data (JSON).md`
- What it is: case record for a surge dispute: quote $12.00 at 1.0x, actual $16.50 at 1.5x, `rider_notified: false`; the rider asks for the $4.50 difference.
- Cited by: SURGE-2, SURGE-3.

## A. Ryde help centre (first-hand)

### A1. Cancellation and Waiting Fee (rider side)
- URL: https://help.rydesharing.com/hc/en-us/articles/23534478435353-Cancellation-and-Waiting-Fee (updated 2026-02-26, accessed 2026-09-28)
- Excerpt: "All cancellations made within 3 minutes of matching are not chargeable. Rider will be charged a Cancellation Fee of $6.61* if: Rider cancels after 3 minutes of matching OR The driver presses "I'm Here", waits for > 3 minutes for the rider to arrive at the pick-up point and cancels the trip (Rider NO SHOW and no trip completion)"
- Cited by: NS-3 (only these cases are chargeable), NS-4 (3-minute free window).

### A3. What if my driver hasn't arrived, but has indicated that he/she arrived?
- URL: https://help.rydesharing.com/hc/en-us/articles/4407754403353 (updated 2026-02-26, accessed 2026-09-28)
- Excerpt: "Drivers are only allowed to indicate arrival and impose the Waiting Time Fee only if he/she: Is at the pick-up location according to GPS data AND Has waited for more than 3 mins"
- Cited by: NS-1 (arrival must be at the pickup point by GPS).

### A7. Can I suggest my preferred route to the driver?
- URL: https://help.rydesharing.com/hc/en-us/articles/4412121982745 (updated 2024-10-01, accessed 2026-09-28)
- Excerpt: "If you have a preferred route, you may recommend this to your driver and reach a mutual agreement before you go."
- Cited by: RD-3 (rider's own route), RD-5 (prior rider agreement).

### A9. Edit destination fee
- URL: https://help.rydesharing.com/hc/en-us/articles/51399796192921 ; https://help.rydesharing.com/hc/en-us/articles/51400229761177 (both updated 2025-10-10, accessed 2026-09-28)
- Excerpt: "Yes. If the driver accepts your edit destination request, a $3.00 add/edit destination fee will apply. This fee will be reflected in your receipt once the trip is completed."
- Cited by: RD-3 ($3.00 fee for an accepted destination change), FARE-0 (published add-on fees).

### A10. Driver Performance and Community Standards
- URL: https://help.rydesharing.com/hc/en-us/articles/33362721809049 (updated 2026-04-10, accessed 2026-09-28)
- Excerpts: "Fraudulent behavior may take many forms. This includes, but is not limited to: 1. Overcharging riders or manipulating fares 2. Completing trips without the rider onboard … 5. Remaining stationary and uncontactable after accepting a ride to trigger cancellation or waiting fees … 8. Abuse of Cancellation and Waiting Fee Policy" / "Repeated or severe breaches may lead to permanent suspension from the Ryde platform."
- Cited by: RD-6 (repeat breaches), NS-2 (false arrival → `flag_account`).

### A14. Report a safety issue / I was involved in an accident
- URL: https://help.rydesharing.com/hc/en-us/articles/51354502165913 ; https://help.rydesharing.com/hc/en-us/articles/900003838306 ; https://help.rydesharing.com/hc/en-us/articles/18230876398105 (all updated 2026-09-25, accessed 2026-09-28)
- Excerpt: "If you're in need of medical assistance, please call 995 … You may file a medical claim through your driver's commercial motor insurance. Report to us swiftly via RydeHELP."
- Cited by: SAFE-2 (reporting routes).

## B. Data definitions

### B7. LTA DataMall API User Guide & Documentation (Traffic Speed Bands)
- URL: https://datamall.lta.gov.sg/content/dam/datamall/datasets/LTA_DataMall_API_User_Guide.pdf (v6.9 when accessed 2026-09-28; v6.10 on 2026-10-09, same text)
- Excerpt: "SpeedBand Speed Bands Information. Total: 8 1 – indicates speed range from 0 < 9 2 – indicates speed range from 10 < 19 3 – indicates speed range from 20 < 29 …"
- Cited by: RD-4 (meaning of speed bands 1 and 2). This defines the data field only; treating bands 1–2 as congestion is a system rule.

## Removed sources

| Entry | Why removed |
|---|---|
| A2 Ryde driver-side cancellation policy | $4.50 driver payout; the official $5.00 fee replaces it |
| A4 Fee waiver request | Only cited by NS-7 (30-day window, vouchers), which is deleted; refunds now go to the original payment method per O1/O2 |
| A5 How the cancellation / waiting fee works | Only cited by NS-6 (waiting fee), which is deleted |
| A6 Service fee / platform fee | Platform-fee tiers; no clause states a platform-fee amount |
| A8 ERP / toll and surcharges | Only supported the old flat-fare model and FARE-1/FARE-2, all removed; FARE-0 tolls now cite O2 |
| A11 Irregular trip behaviour SMS | Same point as A10; one source is enough |
| A12 Completed a trip without the rider | Only cited by SAFE-5, which is deleted; did not state the refund rule directly |
| A13 Code of Conduct | Safety categories now come from O1 §5.1; not a direct source for NS-3 |
| A15 My Rider Made a Mess | $40 / $120 / $200 cleaning tiers replaced by O1 §4.3 |
| A16 Terms of Use | General terms; no sentence states any current clause |
| A17 Ratings moderation policy | Only background for a code-side procedure rule |
| A18 Other Ryde facts (scope, RydeTAXI meter, distance pricing) | Supported the old flat-fare / meter split, which O1 replaces |
| B1 PSV conduct rules r.23 / r.25 | Statute for taxi drivers; used only to support an inference about routes |
| B2 LTA demerit points | Penalties for drivers; analogy only |
| B3 LTA PDVL / TDVL offences | Penalties for drivers; analogy only |
| B4 LTA enforcement news release | Second-hand enforcement news; analogy only |
| B5 LTA taxi fares | Meter rates; not used by any clause |
| B6 PTC point-to-point fares | Only cited by FARE-1, which is deleted; FARE-0 add-on fees now cite A9 |
| B8 Small Claims Tribunals | Background on legal remedies; not a rule source |
| C1 Grab cancellation policy | Other operator; analogy only, not a direct source |
| C2 Grab driver code of conduct | Other operator; analogy only |
| C3 Gojek cancellation and waiting fees | Other operator; analogy only (NS-8 now cites O1 §2.4) |
| C4 CDG Zig help centre (routes) | Other operator; analogy only |
| C5 ComfortDelGro cancellation policy | Other operator; analogy only |
| C6 ComfortDelGro fares | Other operator; analogy only |
| C7 Tada (via Mothership) | Second-hand news about another operator |
| D1 NYC TLC rules | Foreign regulator; analogy only |
| D2 TfL taxi driver handbook | Foreign regulator; analogy only |
| D3 Uber upfront price | Other operator; analogy only |
| D4 Uber wait time fees | Other operator; analogy only |
| D5 GPS.gov accuracy | Technical background for the 200 m radius; the radius is a system rule |
| E System design documents | Not a source; system rules are now marked "system rule" in the policy |
