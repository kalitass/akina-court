# Ryde Dispute Resolution Policy v2.1

**Effective Date:** 1 January 2026  
**Document Owner:** Ryde Operations — Dispute Resolution Team  
**Classification:** Internal — Agent Training Reference  
**Applies To:** All AI dispute resolution agents (Rider Advocate, Driver Advocate, Judge) and human reviewers in the RydeResolve system.

---

## Section 1: Route Deviation Policy

### 1.1 General Principle

Drivers are permitted to reroute from the GPS-recommended path in response to real-time traffic conditions, road closures, or congestion. However, the rider must be informed of any deviation.

### 1.2 Notification Requirement

- The driver **MUST** inform the rider of a route deviation via **in-app chat** or **verbally** (with the trip call recording as evidence) **before or at the point of deviation**.
- A brief reason (e.g., "traffic jam ahead onNicoll Highway, taking alternate route") is sufficient.

### 1.3 Refund Eligibility Matrix

| Scenario | Rider Informed? | Deviation > 1km? | Refund |
|---|---|---|---|
| Driver reroutes for traffic, rider informed and agrees | Yes | Yes | No refund |
| Driver reroutes for traffic, rider **not** informed | No | Yes | Partial refund of excess distance fare |
| Driver reroutes for traffic, rider not informed | No | No (≤ 1km) | No refund (within tolerance) |
| Driver reroutes **without** traffic justification (no evidence of congestion) | N/A | Yes | **Full refund** of excess distance fare |
| Driver reroutes without justification, deviation ≤ 1km | N/A | No | No refund (within tolerance) |

### 1.4 Evidence Requirements

- Traffic justification is verified via **historical traffic API data** for the route segment at the trip time.
- Route deviation distance is calculated as: `actual_route_distance − recommended_route_distance`.
- If the driver's in-app chat or call recording confirms rider acknowledgment, the deviation is considered agreed.

---

## Section 2: No-Show & Cancellation Policy

### 2.1 Free Wait Time

- The driver must wait at the pickup location for a **free wait time of 5 minutes** from the scheduled pickup time.
- After 5 minutes, the driver may cancel the trip as a "rider no-show."

### 2.2 Cancellation Fee

- A **no-show cancellation fee of $5.00** is charged to the rider when the driver cancels after the free wait period.
- The cancellation fee is transferred to the driver as compensation for time and fuel.

### 2.3 Driver Contact Obligation

Before cancelling for no-show, the driver **MUST** attempt to contact the rider with:

1. **At least 1 in-app chat message**, AND
2. **At least 1 phone call** (via the in-app calling system).

If the driver fails to meet both contact obligations, the cancellation fee is **voided** and the rider is not charged.

### 2.4 Driver No-Show

- If the driver **fails to arrive at the pickup location** within a reasonable time (defined as scheduled pickup time + 5 minutes), the rider may cancel at no charge.
- If the driver fails to arrive **and** fails to attempt contact, the rider is eligible for a **$5.00 goodwill credit**.

### 2.5 Repeat No-Show Flagging

- If a rider accumulates **3 or more no-show cancellations within a 30-day rolling window**, the rider's account is **flagged** for review.
- Flagged accounts are subject to:
  - Mandatory upfront payment for future bookings.
  - Temporary suspension pending review by the Trust & Safety team.

---

## Section 3: Fare & Surge Pricing Policy

### 3.1 Upfront Quote Binding

- The upfront quote presented to the rider at booking is **binding at the surge multiplier in effect at quote time** (typically 1.0x in normal conditions).
- The quoted fare includes: base fare, distance fare, time fare, booking fee, and any applicable surge.

### 3.2 Surge Change Notification

- If the surge multiplier **increases** between the time of quote and the time of trip start, the rider **MUST be notified** via an **in-app notification** before or at the point of pickup.
- The notification must clearly state:
  - The new surge multiplier.
  - The revised estimated fare.
  - An option to cancel without penalty.

### 3.3 Refund Eligibility

| Scenario | Rider Notified? | Refund |
|---|---|---|
| Surge increases, rider notified, rider proceeds | Yes | No refund — higher fare applies |
| Surge increases, rider **not** notified | No | **Full refund of the surge differential** (actual fare − quoted fare) |
| Surge decreases between quote and trip start | N/A | Lower fare applies automatically (rider benefits) |
| Surge unchanged | N/A | Quoted fare applies |

### 3.4 Surge Differential Calculation

```
surge_differential = actual_fare − upfront_quote
```

Where the difference is attributable solely to a surge multiplier change (all other fare components unchanged), the full differential is refundable if the rider was not notified.

### 3.5 Surge-Exempt Components

The following fare components are **exempt** from surge pricing and remain fixed regardless of multiplier:

- Booking fee

All other components (base fare, distance fare, time fare) are subject to the surge multiplier.

---

## Section 4: Property Damage Policy

### 4.1 Driver Claim Rights

Drivers may file claims for cleaning or repair fees resulting from **rider-caused damage** to the vehicle, including but not limited to:

- Spills, vomiting, or food/beverage stains.
- Physical damage to interior (seats, doors, windows).
- Damage to exterior caused by rider behavior during boarding/alighting.

### 4.2 Evidence Requirements

| Requirement | Details |
|---|---|
| Photo evidence | Must be submitted **within 24 hours** of trip completion |
| Timestamps | Photos must be automatically timestamped by the in-app camera |
| Verifiability | Photos must be verifiable — taken through the Ryde driver app's built-in camera, not external uploads |
| Trip association | Damage must be linked to the specific trip via GPS telemetry and trip timestamp |

### 4.3 Fee Structure

| Damage Type | Maximum Fee | Conditions |
|---|---|---|
| Cleaning fee | Up to **$50.00** | Photo evidence of soiling/stain; no external quote required |
| Repair fee | Cost of repair | Requires a **written quote from a certified workshop**; quote must be submitted within 7 days |

### 4.4 Dispute Handling

- If the rider disputes the damage claim, the dispute is routed to human review.
- The driver's photo evidence and the rider's account are both reviewed.
- If evidence is insufficient (no timestamp, external photo, or damage not linked to trip), the claim is **rejected**.

---

## Section 5: Safety Incident Policy

### 5.1 Automatic Escalation

Any dispute flagged as **safety-related** is **automatically escalated to human review**. Safety-related disputes include but are not limited to:

- Reckless or dangerous driving.
- Physical or verbal harassment.
- Assault or threat of assault.
- Inappropriate behavior or conduct.
- Traffic accidents during the trip.
- Rider or driver feeling unsafe during the trip.

### 5.2 AI Agent Limitations

- AI agents (Rider Advocate, Driver Advocate, Judge) **MAY** gather evidence, summarize accounts, and prepare case files for human reviewers.
- AI agents **CANNOT** issue rulings, determine fault, or recommend resolutions on safety incidents.
- AI agents **MUST** flag any dispute that contains safety-related keywords or indicators for immediate human escalation, regardless of the dispute type selected by the filer.

### 5.3 Interim Measures

Upon escalation, the system may apply interim measures pending human review:

- Temporary suspension of the accused party's account.
- Prevention of new trip acceptance (for drivers) or booking (for riders).
- These measures are lifted if the human reviewer determines no safety violation occurred.

---

## Section 6: Ruling Thresholds

### 6.1 Monetary Thresholds

| Dispute Value | Ruling Path | Agent Confidence Requirement |
|---|---|---|
| Under $10 | AI agent ruling is **final** | Any confidence level |
| $10 – $50 | AI agent ruling with **80%+ confidence** | If confidence < 80%, escalate to human review |
| Above $50 | **Always human review** | N/A — AI agent prepares case file only |

### 6.2 Category Thresholds

| Dispute Category | Ruling Path |
|---|---|
| Safety incident | **Always human review** (see Section 5) |
| Fare dispute < $10 | AI agent ruling is final |
| Fare dispute $10 – $50 | AI agent ruling if confidence ≥ 80%, else escalate |
| Fare dispute > $50 | Always human review |
| Route deviation | AI agent ruling if confidence ≥ 80% and deviation ≤ 2km, else escalate |
| Property damage (cleaning ≤ $50) | AI agent ruling if photo evidence is verifiable |
| Property damage (repair > $50) | Always human review |
| No-show / cancellation | AI agent ruling is final (fee is fixed at $5.00) |

### 6.3 Confidence Calibration

- Agent confidence is calculated based on: evidence completeness, policy clarity, precedent alignment, and party credibility scores.
- If any party has a fraud flag ≥ 1, the confidence threshold is raised to 95% regardless of dispute value.

---

## Section 7: Precedent Rulings

Past rulings on similar cases should be referenced for consistency. Agents should search precedent rulings by dispute type and key facts, and cite the relevant precedent in their ruling rationale.

### Precedent 7.1: Route Deviation Without Notification

| Field | Value |
|---|---|
| **Case ID** | DISP-2026-0089 |
| **Date** | 2026-02-12 |
| **Dispute Type** | route_deviation |
| **Facts** | Driver rerouted from Geylang to Orchard via Nicoll Highway due to traffic. Deviation was 1.8km beyond recommended route. Rider was not informed. GPS telemetry confirmed traffic congestion on original route. |
| **Ruling** | Partial refund of excess distance fare. Rationale: Driver had valid traffic justification (confirmed via traffic API), but failed to notify rider per Section 1.2. Refund applies only to the excess distance fare, not the entire trip. |
| **Refund Amount** | $3.20 |
| **Confidence** | 91% |

### Precedent 7.2: Surge Pricing Without Rider Notification

| Field | Value |
|---|---|
| **Case ID** | DISP-2026-0142 |
| **Date** | 2026-04-03 |
| **Dispute Type** | fare_dispute |
| **Facts** | Rider received upfront quote of $9.50 at 1.0x surge. Surge increased to 1.4x between quote and pickup. Rider was not notified. Actual fare was $12.70 — a difference of $3.20 entirely attributable to surge differential. |
| **Ruling** | Full refund of surge differential. Rationale: Per Section 3.3, if surge increases between quote and trip start and rider is not notified, rider is eligible for full refund of the surge differential. The $3.20 difference was solely attributable to surge multiplier change. |
| **Refund Amount** | $3.20 |
| **Confidence** | 96% |

### Precedent 7.3: No-Show Cancellation Without Contact Attempt

| Field | Value |
|---|---|
| **Case ID** | DISP-2026-0211 |
| **Date** | 2026-05-18 |
| **Dispute Type** | cancellation_fee |
| **Facts** | Driver arrived at pickup, waited 6 minutes, and cancelled as no-show. $5.00 fee charged to rider. Review of chat logs and call records showed the driver sent zero messages and made zero calls before cancelling. Rider arrived at the pickup point 1 minute after cancellation. |
| **Ruling** | Cancellation fee voided. Rationale: Per Section 2.3, the driver must attempt at least 1 in-app message and 1 call before cancelling for no-show. The driver failed to meet both contact obligations. The $5.00 fee is reversed and refunded to the rider. |
| **Refund Amount** | $5.00 |
| **Confidence** | 98% |

---

## Appendix A: Glossary

| Term | Definition |
|---|---|
| **Upfront Quote** | The fare estimate shown to the rider at the time of booking, binding at the surge multiplier in effect at that moment |
| **Actual Fare** | The final fare charged after trip completion, calculated using actual distance, actual time, and the surge multiplier in effect at trip start |
| **Surge Differential** | The difference between the actual fare and the upfront quote, attributable solely to a change in surge multiplier |
| **Surge-Exempt** | Fare components that are not multiplied by the surge multiplier (e.g., booking fee) |
| **No-Show** | A cancellation initiated by the driver after the free wait period because the rider did not appear at the pickup location |
| **AI Agent Ruling** | A dispute resolution decision issued by the RydeResolve AI system without human intervention |
| **Human Review** | A dispute resolution decision requiring human reviewer involvement |

---

## Appendix B: Revision History

| Version | Date | Changes |
|---|---|---|
| 1.0 | 2025-06-01 | Initial policy |
| 2.0 | 2025-11-15 | Added surge pricing notification requirements; introduced AI agent ruling thresholds |
| 2.1 | 2026-01-01 | Added precedent rulings framework; expanded property damage evidence requirements; added interim safety measures |

---

*This document is a reference for the RydeResolve multi-agent dispute resolution system. All AI agents must cite the applicable policy section in their ruling rationale.*