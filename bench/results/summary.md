# Benchmark summary

Bench set: 49 cases (no_show=18, route_deviation=26, safety=5). Models: deepseek:deepseek-chat.

| metric | raw | facts_only | judge_only | court |
|---|---|---|---|---|
| cases scored (ok / run) | 49 / 49 | 49 / 49 | 49 / 49 | 49 / 49 |
| ruling accuracy | 75.5% | 67.3% | 93.9% | 98.0% |
|   by type | no_show=14/18 route_deviation=18/26 safety=5/5 | no_show=10/18 route_deviation=18/26 safety=5/5 | no_show=18/18 route_deviation=23/26 safety=5/5 | no_show=18/18 route_deviation=25/26 safety=5/5 |
| amount ±$0.01 | 53.1% | 61.2% | 95.9% | 98.0% |
| amount ±$0.50 | 59.2% | 65.3% | 95.9% | 98.0% |
| amount ±$0.01, refund cases only | 39.1% (n=23) | 78.3% (n=23) | 100.0% (n=23) | 100.0% (n=23) |
| escalate accuracy | 87.8% | 91.8% | 95.9% | 100.0% |
| exact (ruling+amount+escalate) | 53.1% | 59.2% | 93.9% | 98.0% |
| flag_account accuracy | 92.1% | 94.7% | 100.0% | 97.4% |
| macro precision / recall / F1 (ruling label) | 78.1% / 76.2% / 75.6% | 72.0% / 70.1% / 66.0% | 94.4% / 94.4% / 94.2% | 98.2% / 98.3% / 98.2% |
| wrongful refunds (refund where none was due) | 34.6% | 53.8% | 7.7% | 3.8% |
| missed refunds (no refund where one was due) | 8.7% | 4.3% | 0.0% | 0.0% |
| money error mean / total ($) | 1.85 / 90.59 | 1.78 / 87.20 | 0.22 / 10.93 | 0.05 / 2.40 |
| executed without a human | 81.6% | 85.7% | 77.6% | 77.6% |
| core decision wrong AND executed (cases; core = outcome + amount + escalation; raw / facts_only have no gate) | 21 (42.9%) | 20 (40.8%) | 2 (4.1%) | 1 (2.0%) |
| routed to a human | 18.4% | 14.3% | 22.4% | 22.4% |
| citation validity, policy ids (rulings with no invalid clause id) | 89.8% | 100.0% | 100.0% | 100.0% |
| citation validity, facts + policy (rulings with no invalid id) | 89.8% | 100.0% | 100.0% | 100.0% |
| invalid / total policy citations | 11 / 214 | 0 / 235 | 0 / 308 | 0 / 318 |
| invalid / total fact citations | 1 / 1 | 0 / 553 | 0 / 568 | 0 / 632 |
| policy-set recall (mean) | 97.8% | 96.8% | 98.5% | 98.5% |
| policy-set ⊇ expected | 93.9% | 91.8% | 95.9% | 95.9% |
| latency mean / p95 (s) | 6.9 / 11.2 | 6.4 / 8.5 | 8.0 / 11.5 | 24.2 / 30.6 |
| input / output tokens (mean) | 15161 / 1441 | 10114 / 1372 | 13153 / 1617 | 108516 / 7264 |
| LLM calls per case (mean) | 1.0 | 1.0 | 1.8 | 5.8 |
| consistency: same ruling across repeats | – (n=0, N=–) | – (n=0, N=–) | – (n=0, N=–) | – (n=0, N=–) |
| consistency: pass^N (all repeats correct) | – | – | – | – |
| identity-swap invariance | – (n=0) | – (n=0) | – (n=0) | – (n=0) |
| errors / timeouts | 0 | 0 | 0 | 0 |

## Per-class precision / recall (ruling label)

| class | support | raw P / R / F1 | facts_only P / R / F1 | judge_only P / R / F1 | court P / R / F1 |
|---|---|---|---|---|---|
| refund_full | 10 | 69.2% / 90.0% / 78.3% | 56.2% / 90.0% / 69.2% | 100.0% / 100.0% / 100.0% | 100.0% / 100.0% / 100.0% |
| refund_partial | 13 | 64.7% / 84.6% / 73.3% | 65.0% / 100.0% / 78.8% | 86.7% / 100.0% / 92.9% | 92.9% / 100.0% / 96.3% |
| no_action | 15 | 90.9% / 66.7% / 76.9% | 66.7% / 26.7% / 38.1% | 100.0% / 86.7% / 92.9% | 100.0% / 93.3% / 96.6% |
| escalate | 11 | 87.5% / 63.6% / 73.7% | 100.0% / 63.6% / 77.8% | 90.9% / 90.9% / 90.9% | 100.0% / 100.0% / 100.0% |

### Confusion · raw (rows = expected, columns = got)

| expected \ got | refund_full | refund_partial | no_action | escalate |
|---|---|---|---|---|
| refund_full | 9 | 0 | 1 | 0 |
| refund_partial | 1 | 11 | 0 | 1 |
| no_action | 3 | 2 | 10 | 0 |
| escalate | 0 | 4 | 0 | 7 |

### Confusion · facts_only (rows = expected, columns = got)

| expected \ got | refund_full | refund_partial | no_action | escalate |
|---|---|---|---|---|
| refund_full | 9 | 0 | 1 | 0 |
| refund_partial | 0 | 13 | 0 | 0 |
| no_action | 7 | 4 | 4 | 0 |
| escalate | 0 | 3 | 1 | 7 |

### Confusion · judge_only (rows = expected, columns = got)

| expected \ got | refund_full | refund_partial | no_action | escalate |
|---|---|---|---|---|
| refund_full | 10 | 0 | 0 | 0 |
| refund_partial | 0 | 13 | 0 | 0 |
| no_action | 0 | 1 | 13 | 1 |
| escalate | 0 | 1 | 0 | 10 |

### Confusion · court (rows = expected, columns = got)

| expected \ got | refund_full | refund_partial | no_action | escalate |
|---|---|---|---|---|
| refund_full | 10 | 0 | 0 | 0 |
| refund_partial | 0 | 13 | 0 | 0 |
| no_action | 0 | 1 | 14 | 0 |
| escalate | 0 | 0 | 0 | 11 |

## Per-case diff

| case | type | scenario | expected | raw | facts_only | judge_only | court |
|---|---|---|---|---|---|---|---|
| B-0001 | route_deviation | rd_basic | refund_partial $4.33 | ✗ refund_partial $3.24 | ✗ refund_partial $4.51 | ✓ refund_partial $4.33 | ✓ refund_partial $4.33 |
| B-0002 | route_deviation | rd_consent_before | escalate | ✗ refund_partial $0.92 | ✗ refund_partial $4.61 | ✓ escalate | ✓ escalate |
| B-0003 | route_deviation | rd_consent_after | refund_partial $2.74 | ✗ escalate | ✓ refund_partial $2.74 | ✓ refund_partial $2.74 | ✓ refund_partial $2.74 |
| B-0004 | route_deviation | rd_incident_on_stretch | no_action | ✗ refund_partial $3.38 | ✗ refund_partial $7.19 | ✓ no_action | ✓ no_action |
| B-0005 | route_deviation | rd_incident_decoy | refund_partial $2.76 | ✗ refund_partial $3.13 | ✗ refund_partial $3.06 | ✓ refund_partial $2.76 | ✓ refund_partial $2.76 |
| B-0006 | route_deviation | rd_incident_late | refund_partial $3.33 | ✗ refund_partial $4.32 | ✓ refund_partial $3.33 | ✓ refund_partial $3.33 | ✓ refund_partial $3.33 |
| B-0007 | route_deviation | rd_band1_no_incident | refund_partial $2.69 | ✗ refund_partial $4.17 | ✓ refund_partial $2.69 | ✓ refund_partial $2.69 | ✓ refund_partial $2.69 |
| B-0008 | route_deviation | rd_band1_incident | no_action | ✗ refund_partial $3.12 | ✗ refund_partial $3.61 | ✓ no_action | ✓ no_action |
| B-0009 | route_deviation | rd_band2_heavy_rain | refund_partial $7.06 | ✗ refund_partial $7.45 | ✓ refund_partial $7.06 | ✓ refund_partial $7.06 | ✓ refund_partial $7.06 |
| B-0010 | route_deviation | rd_stop_named | no_action | ✓ no_action | ✗ refund_partial $4.91 | ✗ refund_partial $4.19 | ✓ no_action |
| B-0011 | route_deviation | rd_stop_named_prior | no_action | ✓ no_action+flag | ✗ refund_partial $2.40+flag | ✓ no_action | ✗ refund_partial $2.40+flag |
| B-0012 | route_deviation | rd_stop_unnamed | refund_partial $6.90 | ✗ refund_partial $8.60 | ✗ refund_partial $7.71 | ✓ refund_partial $6.90 | ✓ refund_partial $6.90 |
| B-0013 | route_deviation | rd_two_segs_consent_seg1 | escalate | ✗ refund_partial $6.48 | ✗ refund_partial $6.74 | ✗ refund_partial $6.74 | ✓ escalate |
| B-0014 | route_deviation | rd_two_segs_incident_seg1 | refund_partial $4.41 | ✗ refund_partial $15.11 | ✗ refund_partial $5.82 | ✓ refund_partial $4.41 | ✓ refund_partial $4.41 |
| B-0015 | route_deviation | rd_two_segs_plain | refund_partial $8.22 | ✗ refund_partial $7.41 | ✓ refund_partial $8.22 | ✓ refund_partial $8.22 | ✓ refund_partial $8.22 |
| B-0016 | route_deviation | rd_fixed_fare | no_action | ✓ no_action | ✓ no_action | ✓ no_action | ✓ no_action |
| B-0017 | route_deviation | rd_fixed_fare_consent | no_action | ✓ no_action | ✓ no_action | ✗ escalate | ✓ no_action |
| B-0018 | route_deviation | rd_prior_flag | refund_partial $3.00+flag | ✗ refund_full $11.25+flag | ✓ refund_partial $3.00+flag | ✓ refund_partial $3.00+flag | ✓ refund_partial $3.00+flag |
| B-0019 | route_deviation | rd_fixed_fare_prior_flag | no_action+flag | ✓ no_action+flag | ✓ no_action+flag | ✓ no_action+flag | ✓ no_action+flag |
| B-0020 | route_deviation | rd_no_deviation | no_action | ✓ no_action | ✓ no_action | ✓ no_action | ✓ no_action |
| B-0021 | route_deviation | rd_request_only | refund_partial $6.27 | ✗ refund_partial $3.10 | ✓ refund_partial $6.27+flag | ✓ refund_partial $6.27 | ✓ refund_partial $6.27 |
| B-0022 | route_deviation | rd_scope_other | refund_partial $6.43 | ✗ refund_partial $4.12 | ✓ refund_partial $6.43 | ✓ refund_partial $6.43 | ✓ refund_partial $6.43 |
| B-0023 | route_deviation | rd_consent_before_prior | escalate | ✗ refund_partial $7.90+flag | ✗ refund_partial $2.16+flag | ✓ escalate | ✓ escalate |
| B-0024 | route_deviation | rd_threat_in_chat | escalate | ✓ escalate | ✓ escalate | ✓ escalate | ✓ escalate |
| B-0025 | route_deviation | rd_consent_before_light | escalate | ✗ refund_partial $8.18 | ✗ no_action | ✓ escalate | ✓ escalate |
| B-0026 | no_show | ns_fake_here_far | refund_full $6.61+flag | ✓ refund_full $6.61 | ✓ refund_full $6.61+flag | ✓ refund_full $6.61+flag | ✓ refund_full $6.61+flag |
| B-0027 | no_show | ns_wait_2min | refund_full $6.61 | ✓ refund_full $6.61 | ✓ refund_full $6.61 | ✓ refund_full $6.61 | ✓ refund_full $6.61 |
| B-0028 | no_show | ns_wait_4min | no_action | ✓ no_action | ✗ refund_full $6.61 | ✓ no_action | ✓ no_action |
| B-0029 | no_show | ns_rider_cancel_150s | refund_full $6.61 | ✓ refund_full $6.61 | ✓ refund_full $6.61 | ✓ refund_full $6.61 | ✓ refund_full $6.61 |
| B-0030 | no_show | ns_rider_cancel_200s | no_action | ✓ no_action | ✗ refund_full $6.61 | ✓ no_action | ✓ no_action |
| B-0031 | no_show | ns_no_here_tap | refund_full $6.61 | ✓ refund_full $6.61 | ✓ refund_full $6.61 | ✓ refund_full $6.61 | ✓ refund_full $6.61 |
| B-0032 | no_show | ns_fake_here_350m | refund_full $6.61+flag | ✓ refund_full $6.61+flag | ✓ refund_full $6.61+flag | ✓ refund_full $6.61+flag | ✓ refund_full $6.61+flag |
| B-0033 | no_show | ns_wait_185s_edge | no_action | ✗ refund_full $6.61 | ✗ refund_full $6.61 | ✓ no_action | ✓ no_action |
| B-0034 | no_show | ns_wait_175s_edge | refund_full $6.61 | ✓ refund_full $6.61 | ✗ no_action | ✓ refund_full $6.61 | ✓ refund_full $6.61 |
| B-0035 | no_show | ns_rider_cancel_175s | refund_full $6.61 | ✓ refund_full $6.61 | ✓ refund_full $6.61 | ✓ refund_full $6.61 | ✓ refund_full $6.61 |
| B-0036 | no_show | ns_rider_cancel_185s | no_action | ✗ refund_full $6.61 | ✗ refund_full $6.61 | ✓ no_action | ✓ no_action |
| B-0037 | no_show | ns_wait_4min_two_more_minutes | no_action | ✓ no_action | ✗ refund_full $6.61 | ✓ no_action | ✓ no_action |
| B-0038 | no_show | ns_wait_2min_driver_claims_5 | refund_full $6.61 | ✓ refund_full $6.61 | ✓ refund_full $6.61 | ✓ refund_full $6.61 | ✓ refund_full $6.61 |
| B-0039 | no_show | ns_fake_here_1km_long_wait | refund_full $6.61+flag | ✓ refund_full $6.61 | ✓ refund_full $6.61+flag | ✓ refund_full $6.61+flag | ✓ refund_full $6.61+flag |
| B-0040 | no_show | ns_rider_cancel_400s_driver_waiting | no_action | ✓ no_action | ✗ refund_full $6.61 | ✓ no_action | ✓ no_action |
| B-0041 | no_show | ns_threat_in_chat | escalate | ✓ escalate | ✓ escalate | ✓ escalate | ✓ escalate |
| B-0042 | no_show | ns_rider_cancel_100s_bad_profile | refund_full $6.61 | ✗ no_action | ✓ refund_full $6.61 | ✓ refund_full $6.61 | ✓ refund_full $6.61 |
| B-0043 | no_show | ns_wait_4min_180m | no_action | ✗ refund_full $6.61 | ✗ refund_full $6.61 | ✓ no_action | ✓ no_action |
| B-0044 | safety | safe_driver_threat | escalate | ✓ escalate | ✓ escalate | ✓ escalate | ✓ escalate |
| B-0045 | safety | safe_rider_threat | escalate | ✓ escalate | ✓ escalate | ✓ escalate | ✓ escalate |
| B-0046 | safety | safe_innocuous_chat_dangerous_driving | escalate | ✓ escalate | ✓ escalate | ✓ escalate | ✓ escalate |
| B-0047 | safety | safe_no_chat_harassment | escalate | ✓ escalate | ✓ escalate+flag | ✓ escalate | ✓ escalate |
| B-0048 | safety | safe_keyword_only_in_statement | escalate | ✓ escalate+flag | ✓ escalate | ✓ escalate | ✓ escalate |
| B-0049 | route_deviation | rd_keyword_trap_find_you | refund_partial $2.74 | ✗ refund_partial $2.91 | ✓ refund_partial $2.74 | ✓ refund_partial $2.74 | ✓ refund_partial $2.74 |
