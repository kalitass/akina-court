# RydeResolve Sample Dataset — DISP-002

**Track:** Tencent Cloud AI Agent Hackathon Singapore 2026 — AI Agent Digital Native Track  
**Use case:** No-Show Charge dispute, ride-hailing (Singapore)  
**Expected ruling:** Cancellation charge **UPHELD** — driver showed up, waited the full free-wait + no-show window, attempted contact; rider has a pattern of late cancellations.

---

## Complete JSON Dataset

```json
{
  "dispute_ticket": {
    "dispute_id": "DISP-002",
    "trip_id": "TRIP-2026-09945",
    "filed_by": "rider",
    "dispute_type": "no_show_charge",
    "description": "I was at the pickup point at Tiong Bahru Plaza on time but the driver never showed up. I waited 10 minutes at the lobby and couldn't find the car. The app charged me a $5.00 cancellation fee for a 'no-show' which is completely unfair — I was there, the driver was not. I want the charge reversed immediately.",
    "filed_at": "2026-09-13T09:20:00+08:00",
    "status": "open"
  },

  "rider_profile": {
    "rider_id": "R-7823",
    "name": "Michael Wong",
    "account_age_days": 210,
    "total_trips": 34,
    "avg_rating": 3.9,
    "dispute_history": {
      "total_disputes": 4,
      "upheld": 1,
      "rejected": 3
    },
    "fraud_flags": 1,
    "fraud_flag_details": "flagged_for_frequent_late_cancellations",
    "payment_method": "e-wallet"
  },

  "driver_profile": {
    "driver_id": "D-2398",
    "name": "Lim Wei Ming",
    "account_age_days": 900,
    "total_trips": 3201,
    "avg_rating": 4.9,
    "dispute_history": {
      "total_disputes": 1,
      "upheld_against": 0,
      "rejected": 1
    },
    "fraud_flags": 0,
    "vehicle": "Honda HR-V (SGP 4521 M)"
  },

  "trip_data": {
    "trip_id": "TRIP-2026-09945",
    "rider_id": "R-7823",
    "driver_id": "D-2398",
    "pickup_location": {
      "name": "Tiong Bahru Plaza",
      "lat": 1.2847,
      "lng": 103.8382
    },
    "dropoff_location": {
      "name": "VivoCity",
      "lat": 1.2648,
      "lng": 103.8223
    },
    "scheduled_time": "2026-09-13T08:45:00+08:00",
    "driver_arrival_time": "2026-09-13T08:43:00+08:00",
    "driver_wait_start": "2026-09-13T08:43:00+08:00",
    "cancellation_time": "2026-09-13T08:51:00+08:00",
    "cancellation_fee": 5.00,
    "cancellation_reason": "rider_no_show"
  },

  "gps_telemetry": [
    {
      "timestamp": "2026-09-13T08:31:00+08:00",
      "lat": 1.2920,
      "lng": 103.8450,
      "speed_kmh": 42,
      "status": "en_route"
    },
    {
      "timestamp": "2026-09-13T08:34:00+08:00",
      "lat": 1.2890,
      "lng": 103.8430,
      "speed_kmh": 38,
      "status": "en_route"
    },
    {
      "timestamp": "2026-09-13T08:38:00+08:00",
      "lat": 1.2865,
      "lng": 103.8400,
      "speed_kmh": 25,
      "status": "en_route"
    },
    {
      "timestamp": "2026-09-13T08:41:00+08:00",
      "lat": 1.2852,
      "lng": 103.8388,
      "speed_kmh": 12,
      "status": "en_route"
    },
    {
      "timestamp": "2026-09-13T08:43:00+08:00",
      "lat": 1.2847,
      "lng": 103.8382,
      "speed_kmh": 0,
      "status": "arrived"
    },
    {
      "timestamp": "2026-09-13T08:45:00+08:00",
      "lat": 1.2847,
      "lng": 103.8382,
      "speed_kmh": 0,
      "status": "waiting"
    },
    {
      "timestamp": "2026-09-13T08:48:00+08:00",
      "lat": 1.2847,
      "lng": 103.8382,
      "speed_kmh": 0,
      "status": "waiting"
    },
    {
      "timestamp": "2026-09-13T08:51:00+08:00",
      "lat": 1.2847,
      "lng": 103.8382,
      "speed_kmh": 0,
      "status": "cancelled"
    }
  ],

  "chat_logs": [
    {
      "timestamp": "2026-09-13T08:43:00+08:00",
      "sender": "driver",
      "type": "message",
      "content": "I've arrived at the pickup point, I'm at the lobby area."
    },
    {
      "timestamp": "2026-09-13T08:45:20+08:00",
      "sender": "driver",
      "type": "message",
      "content": "I'm waiting at the lobby area, white Honda HR-V plate SGP 4521 M."
    },
    {
      "timestamp": "2026-09-13T08:47:05+08:00",
      "sender": "driver",
      "type": "call",
      "content": "Outgoing call to rider — not answered (rang 22s, no response)."
    },
    {
      "timestamp": "2026-09-13T08:49:30+08:00",
      "sender": "driver",
      "type": "message",
      "content": "Hi, are you coming down? I've been waiting a while."
    },
    {
      "timestamp": "2026-09-13T08:50:45+08:00",
      "sender": "driver",
      "type": "message",
      "content": "Please let me know, otherwise I'll have to cancel the trip."
    },
    {
      "timestamp": "2026-09-13T08:51:00+08:00",
      "sender": "system",
      "type": "system",
      "content": "Trip cancelled by driver. Reason: rider_no_show. Cancellation fee of $5.00 applied."
    }
  ],

  "app_events": [
    {
      "timestamp": "2026-09-13T08:30:00+08:00",
      "event_type": "booking_confirmed",
      "details": "Rider R-7823 booked trip TRIP-2026-09945 from Tiong Bahru Plaza to VivoCity. Scheduled pickup 08:45."
    },
    {
      "timestamp": "2026-09-13T08:30:15+08:00",
      "event_type": "driver_assigned",
      "details": "Driver D-2398 (Lim Wei Ming, Honda HR-V SGP 4521 M) assigned. ETA 13 min."
    },
    {
      "timestamp": "2026-09-13T08:30:20+08:00",
      "event_type": "driver_en_route",
      "details": "Driver started navigating to pickup location. Live tracking enabled."
    },
    {
      "timestamp": "2026-09-13T08:43:00+08:00",
      "event_type": "driver_arrived",
      "details": "Driver GPS within 10m of pickup point. Speed 0 km/h. Auto-arrival confirmed."
    },
    {
      "timestamp": "2026-09-13T08:43:05+08:00",
      "event_type": "rider_notified",
      "details": "Push notification + in-app alert sent to rider: 'Your driver has arrived.'"
    },
    {
      "timestamp": "2026-09-13T08:43:10+08:00",
      "event_type": "wait_timer_started",
      "details": "Free wait timer started. 5 min free wait period ends at 08:48."
    },
    {
      "timestamp": "2026-09-13T08:47:05+08:00",
      "event_type": "driver_called_rider",
      "details": "Driver initiated in-app call to rider. Call rang 22s, no answer."
    },
    {
      "timestamp": "2026-09-13T08:48:10+08:00",
      "event_type": "wait_timer_expired",
      "details": "Free 5-min wait period expired. Rider had not boarded. Cancellation fee now applicable per policy."
    },
    {
      "timestamp": "2026-09-13T08:51:00+08:00",
      "event_type": "cancellation_fee_applied",
      "details": "No-show threshold (8 min) reached. $5.00 cancellation fee charged to rider payment method (e-wallet)."
    },
    {
      "timestamp": "2026-09-13T08:51:05+08:00",
      "event_type": "driver_released",
      "details": "Driver D-2398 released from trip. Trip status: cancelled (rider_no_show)."
    }
  ],

  "cancellation_policy": {
    "free_wait_time_min": 5,
    "cancellation_fee_after_wait": 5.00,
    "no_show_threshold_min": 8,
    "fee_goes_to": "driver_compensation"
  }
}
```

---

## Evidence Summary (for hackathon teams)

| Evidence | Supports |
|---|---|
| GPS telemetry shows driver stationary at pickup from 08:43 to 08:51 (8 min) | Driver was physically present |
| Driver sent 4 messages + 1 call; rider sent 0 | Driver attempted contact, rider did not respond |
| App events: driver_arrived, wait_timer_started, wait_timer_expired, fee_applied | Process followed correctly |
| Driver arrived 2 min **early** (08:43 vs scheduled 08:45) | No driver fault |
| Rider: 1 fraud flag, 3/4 prior disputes rejected, 3.9 avg rating | Pattern of disputed no-shows |
| Driver: 0 fraud flags, 4.9 rating, 3201 trips, 0 disputes upheld against | Credible, reliable driver |
| Free wait (5 min) expired at 08:48 → fee properly applied at 08:51 | Policy-compliant charging |

**Expected ruling: Cancellation charge UPHELD.**