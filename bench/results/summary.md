# Benchmark summary

Bench set: 50 cases (fare_dispute=10, no_show=18, route_deviation=18, safety=4). Models: deepseek:deepseek-chat.

| metric | raw | facts_only | judge_only | court |
|---|---|---|---|---|
| cases scored (ok / run) | 50 / 50 | 50 / 50 | 50 / 50 | 50 / 50 |
| ruling accuracy | 58.0% | 60.0% | 86.0% | 98.0% |
|   by type | fare_dispute=4/10 no_show=11/18 route_deviation=10/18 safety=4/4 | fare_dispute=6/10 no_show=12/18 route_deviation=8/18 safety=4/4 | fare_dispute=8/10 no_show=16/18 route_deviation=15/18 safety=4/4 | fare_dispute=10/10 no_show=18/18 route_deviation=17/18 safety=4/4 |
| amount ±$0.01 | 42.0% | 54.0% | 88.0% | 100.0% |
| amount ±$0.50 | 46.0% | 60.0% | 88.0% | 100.0% |
| amount ±$0.01, refund cases only | 45.0% (n=20) | 60.0% (n=20) | 80.0% (n=20) | 100.0% (n=21) |
| escalate accuracy | 84.0% | 84.0% | 98.0% | 98.0% |
| matched the reference (ruling+amount+escalate; an accepted hand-off and a ruling on a settled reading count) | 42.0% | 48.0% | 88.0% | 100.0% |
| flag_account accuracy | 94.1% | 94.1% | 100.0% | 100.0% |
| macro precision / recall / F1 (ruling label) | 61.3% / 62.6% / 55.8% | 68.4% / 64.1% / 60.9% | 87.3% / 84.5% / 85.5% | 97.9% / 98.6% / 98.2% |
| wrongful refunds (refund where none was due) | 60.0% | 53.3% | 6.7% | 0.0% |
| missed refunds (no refund where one was due) | 10.0% | 10.0% | 20.0% | 0.0% |
| money error mean / total ($) | 3.53 / 176.70 | 2.84 / 142.02 | 0.56 / 27.78 | 0.00 / 0.00 |
| executed without a human | 80.0% | 84.0% | 66.0% | 76.0% |
| core decision wrong AND executed (cases; core = outcome + amount + escalation; raw / facts_only have no pre-execution check) | 29 (58.0%) | 26 (52.0%) | 6 (12.0%) | 0 (0.0%) |
| routed to a human | 20.0% | 16.0% | 34.0% | 24.0% |
| citation validity, policy ids (rulings with no invalid clause id) | 98.0% | 84.0% | 100.0% | 100.0% |
| citation validity, facts + policy (rulings with no invalid id) | 96.0% | 84.0% | 100.0% | 100.0% |
| invalid / total policy citations | 1 / 360 | 12 / 362 | 0 / 216 | 0 / 236 |
| invalid / total fact citations | 6 / 6 | 0 / 666 | 0 / 609 | 0 / 647 |
| policy-set recall (mean) | 97.3% | 98.9% | 96.9% | 97.0% |
| policy-set ⊇ expected | 92.0% | 96.0% | 88.0% | 90.0% |
| latency mean / p95 (s) | 10.0 / 14.1 | 8.4 / 12.6 | 10.1 / 19.6 | 30.3 / 39.6 |
| input / output tokens (mean) | 13550 / 1710 | 8125 / 1571 | 13573 / 1886 | 97725 / 7749 |
| LLM calls per case (mean) | 1.0 | 1.0 | 1.8 | 5.9 |
| errors / timeouts | 0 | 0 | 0 | 0 |

## Per-class precision / recall (ruling label)

reference cases = the reference's own count; an arm scored on settled readings (merits) can count differently, shown as (n=...).

| class | reference cases | raw P / R / F1 | facts_only P / R / F1 | judge_only P / R / F1 | court P / R / F1 |
|---|---|---|---|---|---|
| refund_full | 9 | 61.5% / 88.9% / 72.7% | 77.8% / 77.8% / 77.8% | 100.0% / 77.8% / 87.5% | 100.0% / 100.0% / 100.0% |
| refund_partial | 11 | 43.5% / 90.9% / 58.8% | 45.8% / 100.0% / 62.9% | 81.8% / 81.8% / 81.8% | 100.0% / 100.0% / 100.0% (n=12) |
| no_action | 14 | 50.0% / 14.3% / 22.2% | 50.0% / 28.6% / 36.4% | 73.3% / 78.6% / 75.9% | 100.0% / 94.4% / 97.1% (n=18) |
| escalate | 16 | 90.0% / 56.2% / 69.2% | 100.0% / 50.0% / 66.7% | 94.1% / 100.0% / 97.0% | 91.7% / 100.0% / 95.7% (n=11) |

### Confusion · raw (rows = expected, columns = got)

| expected \ got | refund_full | refund_partial | no_action | escalate |
|---|---|---|---|---|
| refund_full | 8 | 0 | 1 | 0 |
| refund_partial | 0 | 10 | 0 | 1 |
| no_action | 4 | 8 | 2 | 0 |
| escalate | 1 | 5 | 1 | 9 |

### Confusion · facts_only (rows = expected, columns = got)

| expected \ got | refund_full | refund_partial | fee_waived | no_action | escalate |
|---|---|---|---|---|---|
| refund_full | 7 | 0 | 0 | 2 | 0 |
| refund_partial | 0 | 11 | 0 | 0 | 0 |
| no_action | 2 | 8 | 0 | 4 | 0 |
| escalate | 0 | 5 | 1 | 2 | 8 |

### Confusion · judge_only (rows = expected, columns = got)

| expected \ got | refund_full | refund_partial | no_action | escalate |
|---|---|---|---|---|
| refund_full | 7 | 0 | 2 | 0 |
| refund_partial | 0 | 9 | 2 | 0 |
| no_action | 0 | 2 | 11 | 1 |
| escalate | 0 | 0 | 0 | 16 |

### Confusion · court (rows = expected, columns = got)

| expected \ got | refund_full | refund_partial | no_action | escalate |
|---|---|---|---|---|
| refund_full | 9 | 0 | 0 | 0 |
| refund_partial | 0 | 12 | 0 | 0 |
| no_action | 0 | 0 | 17 | 1 |
| escalate | 0 | 0 | 0 | 11 |

## Per-case diff

| case | type | scenario | expected | raw | facts_only | judge_only | court |
|---|---|---|---|---|---|---|---|
| B-0001 | route_deviation | rd_port_trust_fastest | no_action (hand-off ok) | ✗ refund_partial $4.54 | ✗ refund_partial $5.89 | ✗ refund_partial $5.89 | ✓ escalate (accepted) |
| B-0002 | route_deviation | rd_notice_ack_hmm | no_action | ✗ refund_partial $2.02 | ✗ refund_partial $0.59 | ✗ refund_partial $3.55 | ✓ no_action |
| B-0003 | route_deviation | rd_named_cn_am | escalate (merits: no_action) | ✗ refund_partial $3.28 | ✗ refund_partial $4.51 | ✓ escalate | ✓ no_action (settled reading) |
| B-0004 | route_deviation | rd_stop_named_longer_way | no_action | ✗ refund_partial $3.02 | ✗ refund_partial $3.17 | ✓ no_action | ✓ no_action |
| B-0005 | route_deviation | rd_consent_except_road | no_action | ✗ refund_partial $8.58 | ✗ refund_partial $7.81 | ✓ no_action | ✓ no_action |
| B-0006 | route_deviation | rd_stop_named_prior | no_action | ✗ refund_partial $1.06 | ✗ refund_partial $0.69+flag | ✓ no_action | ✓ no_action |
| B-0007 | route_deviation | rd_port_auntie_any_way | no_action (hand-off ok) | ✗ refund_partial $5.89 | ✗ refund_partial $5.89 | ✓ escalate (accepted) | ✓ no_action |
| B-0008 | route_deviation | bl_named_elsewhere | refund_partial $5.95 | ✗ refund_partial $3.34 | ✗ refund_partial $5.68 | ✓ refund_partial $5.95 | ✓ refund_partial $5.95 |
| B-0009 | route_deviation | rd_request_only | refund_partial $6.77+flag | ✗ refund_partial $4.60+flag | ✗ refund_partial $6.58+flag | ✓ refund_partial $6.77+flag | ✓ refund_partial $6.77+flag |
| B-0010 | route_deviation | rd_long_loop_mid_amount | refund_partial $11.55 | ✗ refund_partial $4.29 | ✗ refund_partial $10.58 | ✓ refund_partial $11.55 | ✓ refund_partial $11.55 |
| B-0011 | route_deviation | bl_gps_tail_missing | escalate | ✗ refund_partial $3.68 | ✗ refund_partial $3.40 | ✓ escalate | ✓ escalate |
| B-0012 | route_deviation | rd_threat_in_chat | escalate | ✓ escalate+flag | ✓ escalate | ✓ escalate | ✓ escalate |
| B-0013 | route_deviation | rd_general_consent_jp | escalate (merits: no_action) | ✓ escalate | ✗ refund_partial $7.81 | ✓ escalate | ✓ no_action (settled reading) |
| B-0014 | route_deviation | rd_impatient_rider | refund_partial $5.89 | ✗ refund_partial $4.58+flag | ✓ refund_partial $5.89 | ✓ refund_partial $5.89 | ✓ refund_partial $5.89 |
| B-0015 | route_deviation | rd_two_segs_consent_seg1 | refund_partial $6.49 | ✗ refund_partial $14.37 | ✗ refund_partial $8.06 | ✓ refund_partial $6.49 | ✓ refund_partial $6.49 |
| B-0016 | route_deviation | rd_call_log_no_recording | refund_partial $4.08 | ✗ refund_partial $5.22 | ✓ refund_partial $4.08 | ✓ refund_partial $4.08 | ✓ refund_partial $4.08 |
| B-0017 | route_deviation | rd_recorded_call_consent | no_action | ✓ no_action | ✗ refund_partial $0.00 | ✓ no_action | ✓ no_action |
| B-0018 | route_deviation | bl_negation | refund_partial $4.50 | ✗ refund_partial $1.02 | ✗ refund_partial $4.06 | ✓ refund_partial $4.50 | ✓ refund_partial $4.50 |
| B-0019 | fare_dispute | sg_notice_estimate_above_charge | no_action | ✗ refund_partial $2.45 | ✗ refund_partial $1.86 | ✓ no_action | ✓ no_action |
| B-0020 | fare_dispute | sg_notified_full | escalate (merits: no_action) | ✗ refund_partial $2.98 | ✗ no_action | ✓ escalate | ✓ no_action (settled reading) |
| B-0021 | fare_dispute | sg_notice_after_pickup | refund_partial $2.56 | ✗ refund_partial $2.35 | ✓ refund_partial $2.56 | ✓ refund_partial $2.56 | ✓ refund_partial $2.56 |
| B-0022 | fare_dispute | sg_notice_no_cancel_option | escalate (merits: refund_partial) | ✗ refund_partial $5.36 | ✗ refund_partial $4.65 | ✓ escalate | ✓ refund_partial $4.65 (settled reading) |
| B-0023 | fare_dispute | sg_port_notice_fare_unchanged | refund_partial $3.46 (hand-off ok) | ✗ refund_partial $3.56 | ✓ refund_partial $3.46 | ✗ no_action | ✓ refund_partial $3.46 |
| B-0024 | fare_dispute | sg_surge_unchanged_complaint_threat | escalate | ✓ escalate | ✓ escalate | ✓ escalate | ✓ escalate |
| B-0025 | fare_dispute | sg_mixed_rider_stop | refund_partial $11.22 | ✓ refund_partial $11.22 | ✗ refund_partial $15.43 | ✓ refund_partial $11.22 | ✓ refund_partial $11.22 |
| B-0026 | fare_dispute | sg_notice_just_before_pickup | no_action | ✗ refund_partial $6.15 | ✓ no_action | ✓ no_action | ✓ no_action |
| B-0027 | fare_dispute | sg_over_50 | escalate | ✗ refund_partial $66.65 | ✗ refund_partial $63.10 | ✓ escalate | ✓ escalate |
| B-0028 | fare_dispute | sg_port_notice_window_closed | refund_partial $4.88 (hand-off ok) | ✓ escalate (accepted) | ✓ refund_partial $4.88 | ✗ no_action | ✓ refund_partial $4.88 |
| B-0029 | no_show | ns_wait_5m10 | no_action | ✗ refund_full $5.00 | ✓ no_action | ✓ no_action | ✓ no_action |
| B-0030 | no_show | ns_wait_4m50 | refund_full $5.00 | ✓ refund_full $5.00 | ✓ refund_full $5.00 | ✓ refund_full $5.00 | ✓ refund_full $5.00 |
| B-0031 | no_show | ns_no_call | refund_full $5.00 | ✓ refund_full $5.00 | ✓ refund_full $5.00 | ✓ refund_full $5.00 | ✓ refund_full $5.00 |
| B-0032 | no_show | ns_app_noshow_own_reason | refund_full $5.00 | ✓ refund_full $5.00 | ✓ refund_full $5.00 | ✗ no_action | ✓ refund_full $5.00 |
| B-0033 | no_show | ns_no_contact | refund_full $5.00 | ✓ refund_full $5.00 | ✓ refund_full $5.00 | ✓ refund_full $5.00 | ✓ refund_full $5.00 |
| B-0034 | no_show | ns_fake_here_far | refund_full $5.00+flag | ✓ refund_full $5.00+flag | ✓ refund_full $5.00+flag | ✓ refund_full $5.00+flag | ✓ refund_full $5.00+flag |
| B-0035 | no_show | bl_hole_in_wait | escalate | ✗ refund_full $5.00 | ✗ fee_waived $5.00 | ✓ escalate | ✓ escalate |
| B-0036 | no_show | bl_record_threshold_7m50 | refund_full $5.00 | ✗ no_action | ✗ no_action | ✓ refund_full $5.00 | ✓ refund_full $5.00 |
| B-0037 | no_show | ns_need_to_go_after_no_reply | no_action | ✓ no_action | ✓ no_action | ✓ no_action | ✓ no_action |
| B-0038 | no_show | ns_rider_cancel_200s | no_action | ✗ refund_full $5.00 | ✗ refund_full $5.00 | ✓ no_action | ✓ no_action |
| B-0039 | no_show | ns_driver_cancel_flat_tyre | refund_full $5.00 | ✓ refund_full $5.00 | ✓ refund_full $5.00 | ✗ no_action | ✓ refund_full $5.00 |
| B-0040 | no_show | ns_safety_in_complaint | escalate | ✓ escalate | ✓ escalate | ✓ escalate | ✓ escalate |
| B-0041 | no_show | ns_driver_late_no_contact | refund_full $5.00 | ✓ refund_full $5.00 | ✓ refund_full $5.00 | ✓ refund_full $5.00 | ✓ refund_full $5.00 |
| B-0042 | no_show | ns_repeat_noshow_flag | no_action+flag | ✗ refund_full $5.00 | ✓ no_action | ✓ no_action+flag | ✓ no_action+flag |
| B-0043 | no_show | ns_early_arrival_scheduled | refund_full $5.00 | ✓ refund_full $5.00 | ✗ no_action | ✓ refund_full $5.00 | ✓ refund_full $5.00 |
| B-0044 | no_show | ns_threat_in_chat | escalate | ✓ escalate | ✓ escalate | ✓ escalate | ✓ escalate |
| B-0045 | no_show | ns_impatient_driver | escalate (merits: no_action) | ✗ no_action | ✗ no_action | ✓ escalate | ✓ no_action (settled reading) |
| B-0046 | no_show | ns_gate_b_refused_to_move | no_action | ✗ refund_full $5.00 | ✗ refund_full $5.00 | ✓ no_action | ✓ no_action |
| B-0047 | safety | safe_driver_threat | escalate | ✓ escalate | ✓ escalate | ✓ escalate | ✓ escalate |
| B-0048 | safety | safe_rider_threat | escalate | ✓ escalate | ✓ escalate | ✓ escalate | ✓ escalate |
| B-0049 | safety | safe_innocuous_chat_dangerous_driving | escalate | ✓ escalate | ✓ escalate | ✓ escalate | ✓ escalate |
| B-0050 | safety | safe_no_chat_harassment | escalate | ✓ escalate | ✓ escalate | ✓ escalate | ✓ escalate |
