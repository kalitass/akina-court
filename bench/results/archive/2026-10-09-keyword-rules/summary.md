# Benchmark summary

Bench set: 49 cases (no_show=18, route_deviation=26, safety=5). Models: deepseek:deepseek-chat.

| metric | raw | facts_only | judge_only | court |
|---|---|---|---|---|
| cases scored (ok / run) | 49 / 49 | 49 / 49 | 49 / 49 | 49 / 49 |
| ruling accuracy | 85.7% | 81.6% | 98.0% | 100.0% |
|   by type | no_show=16/18 route_deviation=21/26 safety=5/5 | no_show=14/18 route_deviation=21/26 safety=5/5 | no_show=18/18 route_deviation=25/26 safety=5/5 | no_show=18/18 route_deviation=26/26 safety=5/5 |
| amount ±$0.01 | 59.2% | 75.5% | 100.0% | 100.0% |
| amount ±$0.50 | 59.2% | 77.6% | 100.0% | 100.0% |
| amount ±$0.01, refund cases only | 37.5% (n=24) | 83.3% (n=24) | 100.0% (n=24) | 100.0% (n=24) |
| escalate accuracy | 95.9% | 100.0% | 98.0% | 100.0% |
| exact (ruling+amount+escalate) | 55.1% | 75.5% | 98.0% | 100.0% |
| flag_account accuracy | 87.8% | 87.8% | 100.0% | 100.0% |
| macro precision / recall / F1 (ruling label) | 89.0% / 87.0% / 87.0% | 84.5% / 86.4% / 83.5% | 97.2% / 98.5% / 97.8% | 100.0% / 100.0% / 100.0% |
| wrongful refunds (refund where none was due) | 24.0% | 32.0% | 0.0% | 0.0% |
| missed refunds (no refund where one was due) | 4.2% | 4.2% | 0.0% | 0.0% |
| money error mean / total ($) | 1.61 / 79.06 | 1.19 / 58.21 | 0.00 / 0.01 | 0.00 / 0.00 |
| executed without a human | 85.7% | 83.7% | 81.6% | 83.7% |
| core decision wrong AND executed (cases; core = outcome + amount + escalation; raw / facts_only have no gate) | 21 (42.9%) | 12 (24.5%) | 0 (0.0%) | 0 (0.0%) |
| routed to a human | 14.3% | 16.3% | 18.4% | 16.3% |
| citation validity, policy ids (rulings with no invalid clause id) | 98.0% | 100.0% | 100.0% | 100.0% |
| citation validity, facts + policy (rulings with no invalid id) | 95.9% | 100.0% | 100.0% | 100.0% |
| invalid / total policy citations | 1 / 203 | 0 / 212 | 0 / 245 | 0 / 285 |
| invalid / total fact citations | 3 / 3 | 0 / 543 | 0 / 554 | 0 / 589 |
| policy-set recall (mean) | 95.1% | 98.5% | 98.5% | 98.5% |
| policy-set ⊇ expected | 89.8% | 95.9% | 95.9% | 95.9% |
| latency mean / p95 (s) | 5.9 / 8.8 | 5.3 / 6.8 | 7.4 / 9.7 | 23.9 / 33.8 |
| input / output tokens (mean) | 13428 / 1154 | 8431 / 1112 | 10369 / 1446 | 92275 / 6587 |
| LLM calls per case (mean) | 1.0 | 1.0 | 2.0 | 6.0 |
| consistency: same ruling across repeats | – (n=0, N=–) | – (n=0, N=–) | – (n=0, N=–) | 95.9% (n=49, N=2) |
| consistency: pass^N (all repeats correct) | – | – | – | 95.9% |
| identity-swap invariance | 81.6% (n=49) | 91.8% (n=49) | – (n=0) | 100.0% (n=49) |
| errors / timeouts | 0 | 0 | 0 | 0 |

## Per-class precision / recall (ruling label)

| class | support | raw P / R / F1 | facts_only P / R / F1 | judge_only P / R / F1 | court P / R / F1 |
|---|---|---|---|---|---|
| refund_full | 10 | 90.0% / 90.0% / 90.0% | 71.4% / 100.0% / 83.3% | 100.0% / 100.0% / 100.0% | 100.0% / 100.0% / 100.0% |
| refund_partial | 14 | 73.7% / 100.0% / 84.8% | 76.5% / 92.9% / 83.9% | 100.0% / 100.0% / 100.0% | 100.0% / 100.0% / 100.0% |
| no_action | 17 | 92.3% / 70.6% / 80.0% | 90.0% / 52.9% / 66.7% | 100.0% / 94.1% / 97.0% | 100.0% / 100.0% / 100.0% |
| escalate | 8 | 100.0% / 87.5% / 93.3% | 100.0% / 100.0% / 100.0% | 88.9% / 100.0% / 94.1% | 100.0% / 100.0% / 100.0% |

### Confusion · raw (rows = expected, columns = got)

| expected \ got | refund_full | refund_partial | no_action | escalate |
|---|---|---|---|---|
| refund_full | 9 | 0 | 1 | 0 |
| refund_partial | 0 | 14 | 0 | 0 |
| no_action | 1 | 4 | 12 | 0 |
| escalate | 0 | 1 | 0 | 7 |

### Confusion · facts_only (rows = expected, columns = got)

| expected \ got | refund_full | refund_partial | no_action | escalate |
|---|---|---|---|---|
| refund_full | 10 | 0 | 0 | 0 |
| refund_partial | 0 | 13 | 1 | 0 |
| no_action | 4 | 4 | 9 | 0 |
| escalate | 0 | 0 | 0 | 8 |

### Confusion · judge_only (rows = expected, columns = got)

| expected \ got | refund_full | refund_partial | no_action | escalate |
|---|---|---|---|---|
| refund_full | 10 | 0 | 0 | 0 |
| refund_partial | 0 | 14 | 0 | 0 |
| no_action | 0 | 0 | 16 | 1 |
| escalate | 0 | 0 | 0 | 8 |

### Confusion · court (rows = expected, columns = got)

| expected \ got | refund_full | refund_partial | no_action | escalate |
|---|---|---|---|---|
| refund_full | 10 | 0 | 0 | 0 |
| refund_partial | 0 | 14 | 0 | 0 |
| no_action | 0 | 0 | 17 | 0 |
| escalate | 0 | 0 | 0 | 8 |

## Per-case diff

| case | type | scenario | expected | raw | facts_only | judge_only | court |
|---|---|---|---|---|---|---|---|
| B-0001 | route_deviation | rd_basic | refund_partial $4.17 | ✗ refund_partial $1.41 | ✓ refund_partial $4.17 | ✓ refund_partial $4.17 | ✓ refund_partial $4.17 |
| B-0002 | route_deviation | rd_consent_before | no_action | ✓ no_action | ✓ no_action | ✓ no_action | ✓ no_action |
| B-0003 | route_deviation | rd_consent_after | refund_partial $7.26 | ✗ refund_partial $6.34 | ✗ no_action | ✓ refund_partial $7.26 | ✓ refund_partial $7.26 |
| B-0004 | route_deviation | rd_incident_on_stretch | refund_partial $2.44 | ✗ refund_partial $5.10 | ✓ refund_partial $2.44 | ✓ refund_partial $2.44 | ✓ refund_partial $2.44 |
| B-0005 | route_deviation | rd_incident_decoy | refund_partial $2.98 | ✗ refund_partial $5.80 | ✗ refund_partial $3.33 | ✓ refund_partial $2.98 | ✓ refund_partial $2.98 |
| B-0006 | route_deviation | rd_incident_late | refund_partial $6.82 | ✗ refund_partial $5.49 | ✓ refund_partial $6.83 | ✓ refund_partial $6.82 | ✓ refund_partial $6.82 |
| B-0007 | route_deviation | rd_band1_no_incident | refund_partial $1.13 | ✗ refund_partial $2.20 | ✓ refund_partial $1.13 | ✓ refund_partial $1.13 | ✓ refund_partial $1.13 |
| B-0008 | route_deviation | rd_band1_incident | no_action | ✓ no_action $0.00 | ✓ no_action | ✓ no_action | ✓ no_action |
| B-0009 | route_deviation | rd_band2_heavy_rain | refund_partial $10.36 | ✗ refund_partial $7.20 | ✓ refund_partial $10.36 | ✓ refund_partial $10.36 | ✓ refund_partial $10.36 |
| B-0010 | route_deviation | rd_stop_named | no_action | ✓ no_action | ✗ refund_partial $4.22 | ✓ no_action | ✓ no_action |
| B-0011 | route_deviation | rd_stop_named_prior | no_action | ✗ refund_partial $2.86+flag | ✗ refund_partial $2.40+flag | ✗ escalate | ✓ no_action |
| B-0012 | route_deviation | rd_stop_unnamed | refund_partial $4.47 | ✗ refund_partial $3.94 | ✗ refund_partial $5.30 | ✓ refund_partial $4.47 | ✓ refund_partial $4.47 |
| B-0013 | route_deviation | rd_two_segs_consent_seg1 | refund_partial $6.74 | ✗ refund_partial $4.38 | ✓ refund_partial $6.74 | ✓ refund_partial $6.74 | ✓ refund_partial $6.74 |
| B-0014 | route_deviation | rd_two_segs_incident_seg1 | refund_partial $15.21 | ✗ refund_partial $5.79 | ✗ refund_partial $9.79 | ✓ refund_partial $15.22 | ✓ refund_partial $15.21 |
| B-0015 | route_deviation | rd_two_segs_plain | refund_partial $3.74 | ✗ refund_partial $2.94 | ✓ refund_partial $3.74 | ✓ refund_partial $3.74 | ✓ refund_partial $3.74 |
| B-0016 | route_deviation | rd_fixed_fare | no_action | ✓ no_action | ✓ no_action | ✓ no_action | ✓ no_action |
| B-0017 | route_deviation | rd_fixed_fare_consent | no_action | ✗ refund_partial $3.67 | ✓ no_action | ✓ no_action | ✓ no_action |
| B-0018 | route_deviation | rd_prior_flag | refund_partial $7.26+flag | ✗ refund_partial $2.54+flag | ✓ refund_partial $7.26+flag | ✓ refund_partial $7.26+flag | ✓ refund_partial $7.26+flag |
| B-0019 | route_deviation | rd_fixed_fare_prior_flag | no_action+flag | ✓ no_action | ✓ no_action | ✓ no_action+flag | ✓ no_action+flag |
| B-0020 | route_deviation | rd_no_deviation | no_action | ✓ no_action | ✓ no_action | ✓ no_action | ✓ no_action |
| B-0021 | route_deviation | rd_request_only | refund_partial $3.12 | ✗ refund_partial $11.65 | ✓ refund_partial $3.12 | ✓ refund_partial $3.12 | ✓ refund_partial $3.12 |
| B-0022 | route_deviation | rd_scope_other | refund_partial $2.44 | ✗ refund_partial $4.09 | ✓ refund_partial $2.44 | ✓ refund_partial $2.44 | ✓ refund_partial $2.44 |
| B-0023 | route_deviation | rd_consent_before_prior | no_action | ✗ refund_partial $0.01 | ✗ refund_partial $4.45+flag | ✓ no_action | ✓ no_action |
| B-0024 | route_deviation | rd_threat_in_chat | escalate | ✓ escalate | ✓ escalate | ✓ escalate | ✓ escalate |
| B-0025 | route_deviation | rd_consent_before_light | no_action | ✗ refund_partial $14.45 | ✗ refund_partial $6.83 | ✓ no_action | ✓ no_action |
| B-0026 | no_show | ns_fake_here_far | refund_full $6.61+flag | ✓ refund_full $6.61+flag | ✓ refund_full $6.61+flag | ✓ refund_full $6.61+flag | ✓ refund_full $6.61+flag |
| B-0027 | no_show | ns_wait_2min | refund_full $6.61 | ✓ refund_full $6.61 | ✓ refund_full $6.61 | ✓ refund_full $6.61 | ✓ refund_full $6.61 |
| B-0028 | no_show | ns_wait_4min | no_action | ✓ no_action | ✗ refund_full $6.61+flag | ✓ no_action | ✓ no_action |
| B-0029 | no_show | ns_rider_cancel_150s | refund_full $6.61 | ✗ no_action | ✓ refund_full $6.61 | ✓ refund_full $6.61 | ✓ refund_full $6.61 |
| B-0030 | no_show | ns_rider_cancel_200s | no_action | ✓ no_action | ✓ no_action | ✓ no_action | ✓ no_action |
| B-0031 | no_show | ns_no_here_tap | refund_full $6.61 | ✓ refund_full $6.61 | ✓ refund_full $6.61 | ✓ refund_full $6.61 | ✓ refund_full $6.61 |
| B-0032 | no_show | ns_fake_here_350m | refund_full $6.61+flag | ✓ refund_full $6.61+flag | ✓ refund_full $6.61+flag | ✓ refund_full $6.61+flag | ✓ refund_full $6.61+flag |
| B-0033 | no_show | ns_wait_185s_edge | no_action | ✓ no_action | ✗ refund_full $6.61 | ✓ no_action | ✓ no_action |
| B-0034 | no_show | ns_wait_175s_edge | refund_full $6.61 | ✓ refund_full $6.61 | ✓ refund_full $6.61+flag | ✓ refund_full $6.61 | ✓ refund_full $6.61 |
| B-0035 | no_show | ns_rider_cancel_175s | refund_full $6.61 | ✓ refund_full $6.61 | ✓ refund_full $6.61 | ✓ refund_full $6.61 | ✓ refund_full $6.61 |
| B-0036 | no_show | ns_rider_cancel_185s | no_action | ✓ no_action | ✗ refund_full $6.61 | ✓ no_action | ✓ no_action |
| B-0037 | no_show | ns_wait_4min_two_more_minutes | no_action | ✓ no_action | ✓ no_action | ✓ no_action | ✓ no_action |
| B-0038 | no_show | ns_wait_2min_driver_claims_5 | refund_full $6.61 | ✓ refund_full $6.61+flag | ✓ refund_full $6.61 | ✓ refund_full $6.61 | ✓ refund_full $6.61 |
| B-0039 | no_show | ns_fake_here_1km_long_wait | refund_full $6.61+flag | ✓ refund_full $6.61 | ✓ refund_full $6.61+flag | ✓ refund_full $6.61+flag | ✓ refund_full $6.61+flag |
| B-0040 | no_show | ns_rider_cancel_400s_driver_waiting | no_action | ✓ no_action | ✓ no_action | ✓ no_action | ✓ no_action |
| B-0041 | no_show | ns_threat_in_chat | escalate | ✓ escalate+flag | ✓ escalate | ✓ escalate | ✓ escalate |
| B-0042 | no_show | ns_rider_cancel_100s_bad_profile | refund_full $6.61 | ✓ refund_full $6.61 | ✓ refund_full $6.61 | ✓ refund_full $6.61 | ✓ refund_full $6.61 |
| B-0043 | no_show | ns_wait_4min_180m | no_action | ✗ refund_full $6.61+flag | ✗ refund_full $6.61 | ✓ no_action | ✓ no_action |
| B-0044 | safety | safe_driver_threat | escalate | ✓ escalate | ✓ escalate | ✓ escalate | ✓ escalate |
| B-0045 | safety | safe_rider_threat | escalate | ✓ escalate | ✓ escalate | ✓ escalate | ✓ escalate |
| B-0046 | safety | safe_innocuous_chat_dangerous_driving | escalate | ✓ escalate | ✓ escalate | ✓ escalate | ✓ escalate |
| B-0047 | safety | safe_no_chat_harassment | escalate | ✓ escalate | ✓ escalate | ✓ escalate | ✓ escalate |
| B-0048 | safety | safe_keyword_only_in_statement | escalate | ✓ escalate | ✓ escalate | ✓ escalate | ✓ escalate |
| B-0049 | route_deviation | rd_keyword_trap_find_you | escalate | ✗ refund_partial $2.12 | ✓ escalate | ✓ escalate+flag | ✓ escalate |
