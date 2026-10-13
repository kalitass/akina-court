```json
{
  "dispute_ticket": {
    "dispute_id": "DISP-003",
    "trip_id": "TRIP-2026-10023",
    "filed_by": "rider",
    "dispute_type": "fare_dispute",
    "description": "Final fare of $16.50 was charged, but the upfront quote shown at booking was only $12.00. The rider was not informed of any fare change, surge pricing, or price adjustment before or during the trip. The rider requests a refund of the $4.50 difference.",
    "filed_at": "2026-09-14T21:30:00+08:00",
    "status": "open"
  },

  "rider_profile": {
    "rider_id": "R-9001",
    "name": "James Ford",
    "account_age_days": 45,
    "total_trips": 7,
    "avg_rating": 4.5,
    "dispute_history": {
      "total_disputes": 0,
      "upheld": 0,
      "rejected": 0
    },
    "fraud_flags": 0,
    "payment_method": "credit_card"
  },

  "driver_profile": {
    "driver_id": "D-3456",
    "name": "Tan Ah Beng",
    "account_age_days": 450,
    "total_trips": 1567,
    "avg_rating": 4.8,
    "dispute_history": {
      "total_disputes": 2,
      "upheld_against": 0,
      "rejected": 2
    },
    "fraud_flags": 0,
    "vehicle": "Hyundai Elantra (SLM 8890 P)"
  },

  "trip_data": {
    "trip_id": "TRIP-2026-10023",
    "rider_id": "R-9001",
    "driver_id": "D-3456",
    "pickup_location": {
      "name": "Bugis Junction",
      "lat": 1.3000,
      "lng": 103.8556
    },
    "dropoff_location": {
      "name": "Marina Bay Sands",
      "lat": 1.2834,
      "lng": 103.8607
    },
    "start_time": "2026-09-14T21:05:00+08:00",
    "end_time": "2026-09-14T21:18:00+08:00",
    "estimated_duration_min": 13,
    "actual_duration_min": 13,
    "upfront_quote": 12.00,
    "actual_fare": 16.50,
    "fare_difference": 4.50
  },

  "fare_breakdown": {
    "upfront_quote": {
      "surge_multiplier": 1.0,
      "surge_amount": 0.00,
      "total": 12.00,
      "surgeable_subtotal": 9.00
    },
    "actual_fare": {
      "surge_multiplier": 1.5,
      "surge_amount": 4.50,
      "total": 16.50,
      "surgeable_subtotal": 9.00
    },
    "comparison": {
      "surge_multiplier_changed": "1.0x → 1.5x",
      "surge_amount_difference": 4.50,
      "total_difference": 4.50,
      "root_cause": "surge_multiplier_increase",
      "booking_fee_surge_exempt": true
    }
  },

  "gps_telemetry": [
    {
      "timestamp": "2026-09-14T21:05:00+08:00",
      "lat": 1.3000,
      "lng": 103.8556,
      "speed_kmh": 0
    },
    {
      "timestamp": "2026-09-14T21:07:00+08:00",
      "lat": 1.2972,
      "lng": 103.8561,
      "speed_kmh": 25
    },
    {
      "timestamp": "2026-09-14T21:09:00+08:00",
      "lat": 1.2935,
      "lng": 103.8568,
      "speed_kmh": 30
    },
    {
      "timestamp": "2026-09-14T21:11:00+08:00",
      "lat": 1.2901,
      "lng": 103.8582,
      "speed_kmh": 22
    },
    {
      "timestamp": "2026-09-14T21:13:00+08:00",
      "lat": 1.2868,
      "lng": 103.8595,
      "speed_kmh": 28
    },
    {
      "timestamp": "2026-09-14T21:16:00+08:00",
      "lat": 1.2845,
      "lng": 103.8604,
      "speed_kmh": 15
    },
    {
      "timestamp": "2026-09-14T21:18:00+08:00",
      "lat": 1.2834,
      "lng": 103.8607,
      "speed_kmh": 0
    }
  ],

  "chat_logs": [
    {
      "message_id": "MSG-001",
      "sender": "rider",
      "timestamp": "2026-09-14T21:02:15+08:00",
      "message": "Hi, I'm at the taxi stand outside Bugis Junction near the fountain."
    },
    {
      "message_id": "MSG-002",
      "sender": "driver",
      "timestamp": "2026-09-14T21:03:40+08:00",
      "message": "OK, I see you. Pulling up now, white Elantra."
    },
    {
      "message_id": "MSG-003",
      "sender": "rider",
      "timestamp": "2026-09-14T21:18:30+08:00",
      "message": "Thanks for the ride! Just noticed the fare is $16.50 — I thought it was $12?"
    }
  ],

  "surge_pricing_log": {
    "quote_time_surge": 1.0,
    "trip_start_surge": 1.5,
    "surge_activated_at": "2026-09-14T21:04:30+08:00",
    "rider_notified": false,
    "notification_method": null,
    "notification_timestamp": null,
    "reason": "surge_window_activated_between_quote_and_pickup"
  }
}
```
