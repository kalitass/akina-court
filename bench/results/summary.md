# Benchmark summary

Bench set: 49 cases (no_show=18, route_deviation=26, safety=5). Models: deepseek:deepseek-chat.

| metric | raw | facts_only | judge_only | court |
|---|---|---|---|---|
| cases scored (ok / run) | 49 / 49 | 49 / 49 | 49 / 49 | 49 / 49 |
| ruling accuracy | 77.6% | 81.6% | 100.0% | 100.0% |
|   by type | no_show=15/18 route_deviation=18/26 safety=5/5 | no_show=15/18 route_deviation=20/26 safety=5/5 | no_show=18/18 route_deviation=26/26 safety=5/5 | no_show=18/18 route_deviation=26/26 safety=5/5 |
| amount ±$0.01 | 57.1% | 83.7% | 100.0% | 100.0% |
| amount ±$0.50 | 63.3% | 83.7% | 100.0% | 100.0% |
| amount ±$0.01, refund cases only | 40.0% (n=25) | 100.0% (n=25) | 100.0% (n=25) | 100.0% (n=25) |
| escalate accuracy | 95.9% | 100.0% | 100.0% | 100.0% |
| exact (ruling+amount+escalate) | 55.1% | 81.6% | 100.0% | 100.0% |
| flag_account accuracy | 97.6% | 90.5% | 100.0% | 100.0% |
| macro precision / recall / F1 (ruling label) | 77.7% / 83.0% / 78.2% | 87.1% / 86.8% / 83.6% | 100.0% / 100.0% / 100.0% | 100.0% / 100.0% / 100.0% |
| wrongful refunds (refund where none was due) | 25.0% | 37.5% | 0.0% | 0.0% |
| missed refunds (no refund where one was due) | 12.0% | 0.0% | 0.0% | 0.0% |
| money error mean / total ($) | 1.99 / 97.36 | 0.77 / 37.58 | 0.00 / 0.01 | 0.00 / 0.00 |
| executed without a human | 79.6% | 85.7% | 85.7% | 85.7% |
| core decision wrong AND executed (cases; core = outcome + amount + escalation; raw / facts_only have no gate) | 19 (38.8%) | 9 (18.4%) | 0 (0.0%) | 0 (0.0%) |
| routed to a human | 20.4% | 14.3% | 14.3% | 14.3% |
| citation validity, policy ids (rulings with no invalid clause id) | 100.0% | 98.0% | 100.0% | 100.0% |
| citation validity, facts + policy (rulings with no invalid id) | 89.8% | 98.0% | 100.0% | 100.0% |
| invalid / total policy citations | 0 / 204 | 1 / 224 | 0 / 301 | 0 / 334 |
| invalid / total fact citations | 16 / 16 | 0 / 578 | 0 / 591 | 0 / 627 |
| policy-set recall (mean) | 97.8% | 97.8% | 99.5% | 99.5% |
| policy-set ⊇ expected | 93.9% | 93.9% | 98.0% | 98.0% |
| latency mean / p95 (s) | 6.7 / 10.2 | 5.8 / 8.4 | 8.8 / 16.7 | 23.0 / 30.0 |
| input / output tokens (mean) | 13787 / 1394 | 9253 / 1281 | 14335 / 1870 | 99109 / 6927 |
| LLM calls per case (mean) | 1.0 | 1.0 | 2.1 | 6.0 |
| consistency: same ruling across repeats | – (n=0, N=–) | – (n=0, N=–) | – (n=0, N=–) | – (n=0, N=–) |
| consistency: pass^N (all repeats correct) | – | – | – | – |
| identity-swap invariance | – (n=0) | – (n=0) | – (n=0) | – (n=0) |
| errors / timeouts | 0 | 0 | 0 | 0 |

## Per-class precision / recall (ruling label)

| class | support | raw P / R / F1 | facts_only P / R / F1 | judge_only P / R / F1 | court P / R / F1 |
|---|---|---|---|---|---|
| refund_full | 10 | 71.4% / 100.0% / 83.3% | 76.9% / 100.0% / 87.0% | 100.0% / 100.0% / 100.0% | 100.0% / 100.0% / 100.0% |
| refund_partial | 15 | 78.6% / 73.3% / 75.9% | 71.4% / 100.0% / 83.3% | 100.0% / 100.0% / 100.0% | 100.0% / 100.0% / 100.0% |
| no_action | 17 | 90.9% / 58.8% / 71.4% | 100.0% / 47.1% / 64.0% | 100.0% / 100.0% / 100.0% | 100.0% / 100.0% / 100.0% |
| escalate | 7 | 70.0% / 100.0% / 82.4% | 100.0% / 100.0% / 100.0% | 100.0% / 100.0% / 100.0% | 100.0% / 100.0% / 100.0% |

### Confusion · raw (rows = expected, columns = got)

| expected \ got | refund_full | refund_partial | no_action | escalate |
|---|---|---|---|---|
| refund_full | 10 | 0 | 0 | 0 |
| refund_partial | 1 | 11 | 1 | 2 |
| no_action | 3 | 3 | 10 | 1 |
| escalate | 0 | 0 | 0 | 7 |

### Confusion · facts_only (rows = expected, columns = got)

| expected \ got | refund_full | refund_partial | no_action | escalate |
|---|---|---|---|---|
| refund_full | 10 | 0 | 0 | 0 |
| refund_partial | 0 | 15 | 0 | 0 |
| no_action | 3 | 6 | 8 | 0 |
| escalate | 0 | 0 | 0 | 7 |

### Confusion · judge_only (rows = expected, columns = got)

| expected \ got | refund_full | refund_partial | no_action | escalate |
|---|---|---|---|---|
| refund_full | 10 | 0 | 0 | 0 |
| refund_partial | 0 | 15 | 0 | 0 |
| no_action | 0 | 0 | 17 | 0 |
| escalate | 0 | 0 | 0 | 7 |

### Confusion · court (rows = expected, columns = got)

| expected \ got | refund_full | refund_partial | no_action | escalate |
|---|---|---|---|---|
| refund_full | 10 | 0 | 0 | 0 |
| refund_partial | 0 | 15 | 0 | 0 |
| no_action | 0 | 0 | 17 | 0 |
| escalate | 0 | 0 | 0 | 7 |

## Per-case diff

| case | type | scenario | expected | raw | facts_only | judge_only | court |
|---|---|---|---|---|---|---|---|
| B-0001 | route_deviation | rd_basic | refund_partial $4.17 | ✗ refund_partial $4.44 | ✓ refund_partial $4.17 | ✓ refund_partial $4.17 | ✓ refund_partial $4.17 |
| B-0002 | route_deviation | rd_consent_before | no_action | ✓ no_action | ✗ refund_partial $4.47 | ✓ no_action | ✓ no_action |
| B-0003 | route_deviation | rd_consent_after | refund_partial $7.26 | ✗ no_action | ✓ refund_partial $7.26 | ✓ refund_partial $7.26 | ✓ refund_partial $7.26 |
| B-0004 | route_deviation | rd_incident_on_stretch | refund_partial $2.44 | ✗ escalate | ✓ refund_partial $2.44 | ✓ refund_partial $2.44 | ✓ refund_partial $2.44 |
| B-0005 | route_deviation | rd_incident_decoy | refund_partial $2.98 | ✗ refund_partial $1.44 | ✓ refund_partial $2.98 | ✓ refund_partial $2.98 | ✓ refund_partial $2.98 |
| B-0006 | route_deviation | rd_incident_late | refund_partial $6.82 | ✗ refund_partial $8.03 | ✓ refund_partial $6.83 | ✓ refund_partial $6.82 | ✓ refund_partial $6.82 |
| B-0007 | route_deviation | rd_band1_no_incident | refund_partial $1.13 | ✗ refund_full $28.48 | ✓ refund_partial $1.13 | ✓ refund_partial $1.13 | ✓ refund_partial $1.13 |
| B-0008 | route_deviation | rd_band1_incident | no_action | ✓ no_action | ✗ refund_partial $2.48 | ✓ no_action | ✓ no_action |
| B-0009 | route_deviation | rd_band2_heavy_rain | refund_partial $10.36 | ✗ refund_partial $10.40 | ✓ refund_partial $10.36 | ✓ refund_partial $10.36 | ✓ refund_partial $10.36 |
| B-0010 | route_deviation | rd_stop_named | no_action | ✗ refund_partial $1.04 | ✗ refund_partial $4.22 | ✓ no_action | ✓ no_action |
| B-0011 | route_deviation | rd_stop_named_prior | no_action | ✗ escalate | ✗ refund_partial $2.40+flag | ✓ no_action | ✓ no_action |
| B-0012 | route_deviation | rd_stop_unnamed | refund_partial $4.47 | ✗ refund_partial $10.67 | ✓ refund_partial $4.47 | ✓ refund_partial $4.47 | ✓ refund_partial $4.47 |
| B-0013 | route_deviation | rd_two_segs_consent_seg1 | refund_partial $6.74 | ✗ escalate | ✓ refund_partial $6.74 | ✓ refund_partial $6.74 | ✓ refund_partial $6.74 |
| B-0014 | route_deviation | rd_two_segs_incident_seg1 | refund_partial $15.21 | ✗ refund_partial $17.62 | ✓ refund_partial $15.21 | ✓ refund_partial $15.20 | ✓ refund_partial $15.21 |
| B-0015 | route_deviation | rd_two_segs_plain | refund_partial $3.74 | ✗ refund_partial $4.02 | ✓ refund_partial $3.74 | ✓ refund_partial $3.74 | ✓ refund_partial $3.74 |
| B-0016 | route_deviation | rd_fixed_fare | no_action | ✓ no_action | ✗ refund_partial $0.00 | ✓ no_action | ✓ no_action |
| B-0017 | route_deviation | rd_fixed_fare_consent | no_action | ✗ refund_partial $1.83 | ✓ no_action | ✓ no_action | ✓ no_action |
| B-0018 | route_deviation | rd_prior_flag | refund_partial $7.26+flag | ✗ refund_partial $4.71+flag | ✓ refund_partial $7.26+flag | ✓ refund_partial $7.26+flag | ✓ refund_partial $7.26+flag |
| B-0019 | route_deviation | rd_fixed_fare_prior_flag | no_action+flag | ✓ no_action+flag | ✓ no_action | ✓ no_action+flag | ✓ no_action+flag |
| B-0020 | route_deviation | rd_no_deviation | no_action | ✓ no_action | ✓ no_action | ✓ no_action | ✓ no_action |
| B-0021 | route_deviation | rd_request_only | refund_partial $3.12 | ✗ refund_partial $8.03 | ✓ refund_partial $3.12 | ✓ refund_partial $3.12 | ✓ refund_partial $3.12 |
| B-0022 | route_deviation | rd_scope_other | refund_partial $2.44 | ✗ refund_partial $6.32 | ✓ refund_partial $2.44 | ✓ refund_partial $2.44 | ✓ refund_partial $2.44 |
| B-0023 | route_deviation | rd_consent_before_prior | no_action | ✓ no_action | ✗ refund_partial $4.17 | ✓ no_action | ✓ no_action |
| B-0024 | route_deviation | rd_threat_in_chat | escalate | ✓ escalate | ✓ escalate | ✓ escalate | ✓ escalate |
| B-0025 | route_deviation | rd_consent_before_light | no_action | ✗ refund_partial $6.40 | ✓ no_action | ✓ no_action | ✓ no_action |
| B-0026 | no_show | ns_fake_here_far | refund_full $6.61+flag | ✓ refund_full $6.61+flag | ✓ refund_full $6.61+flag | ✓ refund_full $6.61+flag | ✓ refund_full $6.61+flag |
| B-0027 | no_show | ns_wait_2min | refund_full $6.61 | ✓ refund_full $6.61 | ✓ refund_full $6.61 | ✓ refund_full $6.61 | ✓ refund_full $6.61 |
| B-0028 | no_show | ns_wait_4min | no_action | ✓ no_action | ✓ no_action | ✓ no_action | ✓ no_action |
| B-0029 | no_show | ns_rider_cancel_150s | refund_full $6.61 | ✓ refund_full $6.61+flag | ✓ refund_full $6.61 | ✓ refund_full $6.61 | ✓ refund_full $6.61 |
| B-0030 | no_show | ns_rider_cancel_200s | no_action | ✓ no_action | ✓ no_action | ✓ no_action | ✓ no_action |
| B-0031 | no_show | ns_no_here_tap | refund_full $6.61 | ✓ refund_full $6.61 | ✓ refund_full $6.61 | ✓ refund_full $6.61 | ✓ refund_full $6.61 |
| B-0032 | no_show | ns_fake_here_350m | refund_full $6.61+flag | ✓ refund_full $6.61+flag | ✓ refund_full $6.61+flag | ✓ refund_full $6.61+flag | ✓ refund_full $6.61+flag |
| B-0033 | no_show | ns_wait_185s_edge | no_action | ✓ no_action | ✗ refund_full $6.61 | ✓ no_action | ✓ no_action |
| B-0034 | no_show | ns_wait_175s_edge | refund_full $6.61 | ✓ refund_full $6.61 | ✓ refund_full $6.61 | ✓ refund_full $6.61 | ✓ refund_full $6.61 |
| B-0035 | no_show | ns_rider_cancel_175s | refund_full $6.61 | ✓ refund_full $6.61 | ✓ refund_full $6.61 | ✓ refund_full $6.61 | ✓ refund_full $6.61 |
| B-0036 | no_show | ns_rider_cancel_185s | no_action | ✗ refund_full $6.61 | ✓ no_action | ✓ no_action | ✓ no_action |
| B-0037 | no_show | ns_wait_4min_two_more_minutes | no_action | ✗ refund_full $6.61 | ✗ refund_full $6.61 | ✓ no_action | ✓ no_action |
| B-0038 | no_show | ns_wait_2min_driver_claims_5 | refund_full $6.61 | ✓ refund_full $6.61 | ✓ refund_full $6.61+flag | ✓ refund_full $6.61 | ✓ refund_full $6.61 |
| B-0039 | no_show | ns_fake_here_1km_long_wait | refund_full $6.61+flag | ✓ refund_full $6.61+flag | ✓ refund_full $6.61+flag | ✓ refund_full $6.61+flag | ✓ refund_full $6.61+flag |
| B-0040 | no_show | ns_rider_cancel_400s_driver_waiting | no_action | ✓ no_action | ✓ no_action | ✓ no_action | ✓ no_action |
| B-0041 | no_show | ns_threat_in_chat | escalate | ✓ escalate | ✓ escalate | ✓ escalate | ✓ escalate |
| B-0042 | no_show | ns_rider_cancel_100s_bad_profile | refund_full $6.61 | ✓ refund_full $6.61 | ✓ refund_full $6.61 | ✓ refund_full $6.61 | ✓ refund_full $6.61 |
| B-0043 | no_show | ns_wait_4min_180m | no_action | ✗ refund_full $6.61 | ✗ refund_full $6.61+flag | ✓ no_action | ✓ no_action |
| B-0044 | safety | safe_driver_threat | escalate | ✓ escalate | ✓ escalate | ✓ escalate | ✓ escalate |
| B-0045 | safety | safe_rider_threat | escalate | ✓ escalate | ✓ escalate | ✓ escalate | ✓ escalate |
| B-0046 | safety | safe_innocuous_chat_dangerous_driving | escalate | ✓ escalate | ✓ escalate | ✓ escalate | ✓ escalate |
| B-0047 | safety | safe_no_chat_harassment | escalate | ✓ escalate | ✓ escalate | ✓ escalate | ✓ escalate |
| B-0048 | safety | safe_keyword_only_in_statement | escalate | ✓ escalate | ✓ escalate | ✓ escalate | ✓ escalate |
| B-0049 | route_deviation | rd_keyword_trap_find_you | refund_partial $1.09 | ✗ refund_partial $2.27 | ✓ refund_partial $1.09 | ✓ refund_partial $1.09 | ✓ refund_partial $1.09 |
