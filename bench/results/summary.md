# Benchmark summary

Bench set: 65 cases (no_show=18, route_deviation=42, safety=5). Models: deepseek:deepseek-chat.

| metric | raw | facts_only | judge_only | court |
|---|---|---|---|---|
| cases scored (ok / run) | 65 / 65 | 65 / 65 | 65 / 65 | 65 / 65 |
| ruling accuracy | 53.8% | 56.9% | 84.6% | 96.9% |
|   by type | no_show=13/18 route_deviation=17/42 safety=5/5 | no_show=14/18 route_deviation=18/42 safety=5/5 | no_show=18/18 route_deviation=32/42 safety=5/5 | no_show=18/18 route_deviation=40/42 safety=5/5 |
| amount ±$0.01 | 50.8% | 58.5% | 89.2% | 100.0% |
| amount ±$0.50 | 55.4% | 60.0% | 89.2% | 100.0% |
| amount ±$0.01, refund cases only | 43.5% (n=23) | 69.6% (n=23) | 100.0% (n=23) | 100.0% (n=23) |
| escalate accuracy | 78.5% | 76.9% | 87.7% | 96.9% |
| exact (ruling+amount+escalate) | 41.5% | 50.8% | 84.6% | 96.9% |
| flag_account accuracy | 93.2% | 95.5% | 97.7% | 100.0% |
| macro precision / recall / F1 (ruling label) | 58.4% / 60.0% / 56.0% | 66.5% / 63.9% / 59.2% | 87.3% / 88.1% / 86.3% | 97.8% / 97.6% / 97.6% |
| wrongful refunds (refund where none was due) | 50.0% | 50.0% | 16.7% | 0.0% |
| missed refunds (no refund where one was due) | 21.7% | 8.7% | 0.0% | 0.0% |
| money error mean / total ($) | 2.19 / 142.42 | 1.89 / 122.93 | 0.46 / 29.90 | 0.00 / 0.00 |
| executed without a human | 73.8% | 87.7% | 70.8% | 64.6% |
| core decision wrong AND executed (cases; core = outcome + amount + escalation; raw / facts_only have no gate) | 31 (47.7%) | 31 (47.7%) | 7 (10.8%) | 0 (0.0%) |
| routed to a human | 26.2% | 12.3% | 29.2% | 35.4% |
| citation validity, policy ids (rulings with no invalid clause id) | 83.1% | 98.5% | 100.0% | 100.0% |
| citation validity, facts + policy (rulings with no invalid id) | 76.9% | 98.5% | 100.0% | 100.0% |
| invalid / total policy citations | 18 / 298 | 2 / 308 | 0 / 391 | 0 / 426 |
| invalid / total fact citations | 11 / 11 | 0 / 790 | 0 / 750 | 0 / 816 |
| policy-set recall (mean) | 98.1% | 96.8% | 98.3% | 98.3% |
| policy-set ⊇ expected | 95.4% | 92.3% | 95.4% | 95.4% |
| latency mean / p95 (s) | 7.2 / 9.8 | 6.4 / 9.1 | 8.6 / 14.8 | 26.5 / 37.3 |
| input / output tokens (mean) | 15771 / 1458 | 10872 / 1396 | 15071 / 1799 | 115691 / 7904 |
| LLM calls per case (mean) | 1.0 | 1.0 | 1.8 | 5.8 |
| consistency: same ruling across repeats | – (n=0, N=–) | – (n=0, N=–) | – (n=0, N=–) | – (n=0, N=–) |
| consistency: pass^N (all repeats correct) | – | – | – | – |
| identity-swap invariance | – (n=0) | – (n=0) | – (n=0) | – (n=0) |
| errors / timeouts | 0 | 0 | 0 | 0 |

## Per-class precision / recall (ruling label)

| class | support | raw P / R / F1 | facts_only P / R / F1 | judge_only P / R / F1 | court P / R / F1 |
|---|---|---|---|---|---|
| refund_full | 10 | 69.2% / 90.0% / 78.3% | 75.0% / 90.0% / 81.8% | 100.0% / 100.0% / 100.0% | 100.0% / 100.0% / 100.0% |
| refund_partial | 13 | 34.6% / 69.2% / 46.2% | 36.7% / 84.6% / 51.2% | 65.0% / 100.0% / 78.8% | 100.0% / 100.0% / 100.0% |
| no_action | 21 | 58.3% / 33.3% / 42.4% | 66.7% / 47.6% / 55.6% | 100.0% / 76.2% / 86.5% | 100.0% / 90.5% / 95.0% |
| escalate | 21 | 71.4% / 47.6% / 57.1% | 87.5% / 33.3% / 48.3% | 84.2% / 76.2% / 80.0% | 91.3% / 100.0% / 95.5% |

### Confusion · raw (rows = expected, columns = got)

| expected \ got | refund_full | refund_partial | no_action | escalate |
|---|---|---|---|---|
| refund_full | 9 | 0 | 1 | 0 |
| refund_partial | 0 | 9 | 1 | 3 |
| no_action | 4 | 9 | 7 | 1 |
| escalate | 0 | 8 | 3 | 10 |

### Confusion · facts_only (rows = expected, columns = got)

| expected \ got | refund_full | refund_partial | no_action | escalate |
|---|---|---|---|---|
| refund_full | 9 | 0 | 1 | 0 |
| refund_partial | 1 | 11 | 1 | 0 |
| no_action | 2 | 8 | 10 | 1 |
| escalate | 0 | 11 | 3 | 7 |

### Confusion · judge_only (rows = expected, columns = got)

| expected \ got | refund_full | refund_partial | no_action | escalate |
|---|---|---|---|---|
| refund_full | 10 | 0 | 0 | 0 |
| refund_partial | 0 | 13 | 0 | 0 |
| no_action | 0 | 2 | 16 | 3 |
| escalate | 0 | 5 | 0 | 16 |

### Confusion · court (rows = expected, columns = got)

| expected \ got | refund_full | refund_partial | no_action | escalate |
|---|---|---|---|---|
| refund_full | 10 | 0 | 0 | 0 |
| refund_partial | 0 | 13 | 0 | 0 |
| no_action | 0 | 0 | 19 | 2 |
| escalate | 0 | 0 | 0 | 21 |

## Per-case diff

| case | type | scenario | expected | raw | facts_only | judge_only | court |
|---|---|---|---|---|---|---|---|
| B-0001 | route_deviation | rd_basic | refund_partial $4.33 | ✓ refund_partial $4.34 | ✓ refund_partial $4.33 | ✓ refund_partial $4.33 | ✓ refund_partial $4.33 |
| B-0002 | route_deviation | rd_consent_before | escalate | ✗ refund_partial $5.64 | ✗ refund_partial $5.54 | ✓ escalate | ✓ escalate |
| B-0003 | route_deviation | rd_consent_after | refund_partial $2.74 | ✗ refund_partial $3.02 | ✓ refund_partial $2.73 | ✓ refund_partial $2.74 | ✓ refund_partial $2.74 |
| B-0004 | route_deviation | rd_incident_on_stretch | no_action | ✗ refund_partial $7.10 | ✗ refund_partial $6.93 | ✓ no_action | ✓ no_action |
| B-0005 | route_deviation | rd_incident_decoy | refund_partial $2.76 | ✗ no_action $0.00 | ✗ no_action | ✓ refund_partial $2.76 | ✓ refund_partial $2.76 |
| B-0006 | route_deviation | rd_incident_late | refund_partial $3.33 | ✗ refund_partial $3.98 | ✗ refund_full $3.62 | ✓ refund_partial $3.33 | ✓ refund_partial $3.33 |
| B-0007 | route_deviation | rd_band1_no_incident | refund_partial $2.69 | ✗ refund_partial $6.24 | ✗ refund_partial $3.54 | ✓ refund_partial $2.69 | ✓ refund_partial $2.69 |
| B-0008 | route_deviation | rd_band1_incident | no_action | ✗ refund_partial $2.09 | ✓ no_action | ✓ no_action | ✓ no_action |
| B-0009 | route_deviation | rd_band2_heavy_rain | refund_partial $7.06 | ✗ escalate | ✓ refund_partial $7.07 | ✓ refund_partial $7.06 | ✓ refund_partial $7.06 |
| B-0010 | route_deviation | rd_stop_named | no_action | ✗ refund_partial $1.82 | ✗ refund_partial $4.91 | ✗ refund_partial $4.19 | ✗ escalate |
| B-0011 | route_deviation | rd_stop_named_prior | no_action | ✗ refund_partial $2.71+flag | ✗ refund_partial $2.40+flag | ✗ escalate | ✓ no_action |
| B-0012 | route_deviation | rd_stop_unnamed | refund_partial $6.90 | ✗ refund_partial $10.94 | ✗ refund_partial $7.55 | ✓ refund_partial $6.90 | ✓ refund_partial $6.90 |
| B-0013 | route_deviation | rd_two_segs_consent_seg1 | escalate | ✓ escalate+flag | ✗ refund_partial $6.74 | ✓ escalate | ✓ escalate |
| B-0014 | route_deviation | rd_two_segs_incident_seg1 | refund_partial $4.41 | ✗ refund_partial $3.97 | ✗ refund_partial $9.45 | ✓ refund_partial $4.41 | ✓ refund_partial $4.41 |
| B-0015 | route_deviation | rd_two_segs_plain | refund_partial $8.22 | ✗ refund_partial $8.37 | ✓ refund_partial $8.22 | ✓ refund_partial $8.22 | ✓ refund_partial $8.22 |
| B-0016 | route_deviation | rd_fixed_fare | no_action | ✗ refund_partial $0.00 | ✓ no_action | ✓ no_action | ✓ no_action |
| B-0017 | route_deviation | rd_fixed_fare_consent | no_action | ✓ no_action | ✗ refund_partial $0.00 | ✓ no_action | ✗ escalate |
| B-0018 | route_deviation | rd_prior_flag | refund_partial $3.00+flag | ✗ refund_partial $2.41+flag | ✓ refund_partial $3.01+flag | ✓ refund_partial $3.00+flag | ✓ refund_partial $3.00+flag |
| B-0019 | route_deviation | rd_fixed_fare_prior_flag | no_action+flag | ✓ no_action+flag | ✓ no_action+flag | ✓ no_action+flag | ✓ no_action+flag |
| B-0020 | route_deviation | rd_no_deviation | no_action | ✓ no_action | ✓ no_action | ✓ no_action | ✓ no_action |
| B-0021 | route_deviation | rd_request_only | refund_partial $6.27 | ✗ escalate | ✗ refund_partial $7.47 | ✓ refund_partial $6.27 | ✓ refund_partial $6.27 |
| B-0022 | route_deviation | rd_scope_other | refund_partial $6.43 | ✗ escalate | ✓ refund_partial $6.43 | ✓ refund_partial $6.43 | ✓ refund_partial $6.43 |
| B-0023 | route_deviation | rd_consent_before_prior | escalate | ✗ refund_partial $5.29+flag | ✗ refund_partial $3.00+flag | ✓ escalate | ✓ escalate |
| B-0024 | route_deviation | rd_threat_in_chat | escalate | ✓ escalate | ✓ escalate | ✓ escalate | ✓ escalate |
| B-0025 | route_deviation | rd_consent_before_light | escalate | ✗ no_action | ✗ no_action | ✗ refund_partial $6.94 | ✓ escalate |
| B-0026 | no_show | ns_fake_here_far | refund_full $6.61+flag | ✓ refund_full $6.61+flag | ✓ refund_full $6.61+flag | ✓ refund_full $6.61+flag | ✓ refund_full $6.61+flag |
| B-0027 | no_show | ns_wait_2min | refund_full $6.61 | ✓ refund_full $6.61 | ✓ refund_full $6.61 | ✓ refund_full $6.61 | ✓ refund_full $6.61 |
| B-0028 | no_show | ns_wait_4min | no_action | ✗ refund_full $6.61 | ✓ no_action | ✓ no_action | ✓ no_action |
| B-0029 | no_show | ns_rider_cancel_150s | refund_full $6.61 | ✓ refund_full $6.61 | ✓ refund_full $6.61 | ✓ refund_full $6.61 | ✓ refund_full $6.61 |
| B-0030 | no_show | ns_rider_cancel_200s | no_action | ✓ no_action | ✓ no_action | ✓ no_action | ✓ no_action |
| B-0031 | no_show | ns_no_here_tap | refund_full $6.61 | ✓ refund_full $6.61 | ✓ refund_full $6.61 | ✓ refund_full $6.61 | ✓ refund_full $6.61 |
| B-0032 | no_show | ns_fake_here_350m | refund_full $6.61+flag | ✓ refund_full $6.61+flag | ✓ refund_full $6.61+flag | ✓ refund_full $6.61+flag | ✓ refund_full $6.61+flag |
| B-0033 | no_show | ns_wait_185s_edge | no_action | ✗ refund_full $6.61 | ✓ no_action | ✓ no_action | ✓ no_action |
| B-0034 | no_show | ns_wait_175s_edge | refund_full $6.61 | ✓ refund_full $6.61 | ✓ refund_full $6.61 | ✓ refund_full $6.61 | ✓ refund_full $6.61 |
| B-0035 | no_show | ns_rider_cancel_175s | refund_full $6.61 | ✓ refund_full $6.61 | ✓ refund_full $6.61 | ✓ refund_full $6.61 | ✓ refund_full $6.61 |
| B-0036 | no_show | ns_rider_cancel_185s | no_action | ✓ no_action | ✗ escalate | ✓ no_action | ✓ no_action |
| B-0037 | no_show | ns_wait_4min_two_more_minutes | no_action | ✗ refund_full $6.61 | ✗ refund_full $6.61 | ✓ no_action | ✓ no_action |
| B-0038 | no_show | ns_wait_2min_driver_claims_5 | refund_full $6.61 | ✓ refund_full $6.61 | ✓ refund_full $6.61 | ✓ refund_full $6.61 | ✓ refund_full $6.61 |
| B-0039 | no_show | ns_fake_here_1km_long_wait | refund_full $6.61+flag | ✓ refund_full $6.61 | ✓ refund_full $6.61+flag | ✓ refund_full $6.61+flag | ✓ refund_full $6.61+flag |
| B-0040 | no_show | ns_rider_cancel_400s_driver_waiting | no_action | ✓ no_action | ✓ no_action | ✓ no_action | ✓ no_action |
| B-0041 | no_show | ns_threat_in_chat | escalate | ✓ escalate | ✓ escalate+flag | ✓ escalate | ✓ escalate |
| B-0042 | no_show | ns_rider_cancel_100s_bad_profile | refund_full $6.61 | ✗ no_action | ✗ no_action | ✓ refund_full $6.61 | ✓ refund_full $6.61 |
| B-0043 | no_show | ns_wait_4min_180m | no_action | ✗ refund_full $6.61 | ✗ refund_full $6.61 | ✓ no_action | ✓ no_action |
| B-0044 | safety | safe_driver_threat | escalate | ✓ escalate+flag | ✓ escalate+flag | ✓ escalate | ✓ escalate |
| B-0045 | safety | safe_rider_threat | escalate | ✓ escalate | ✓ escalate | ✓ escalate | ✓ escalate |
| B-0046 | safety | safe_innocuous_chat_dangerous_driving | escalate | ✓ escalate | ✓ escalate | ✓ escalate | ✓ escalate |
| B-0047 | safety | safe_no_chat_harassment | escalate | ✓ escalate | ✓ escalate | ✓ escalate | ✓ escalate |
| B-0048 | safety | safe_keyword_only_in_statement | escalate | ✓ escalate | ✓ escalate | ✓ escalate | ✓ escalate |
| B-0049 | route_deviation | rd_keyword_trap_find_you | refund_partial $2.74 | ✗ refund_partial $3.99 | ✓ refund_partial $2.74 | ✓ refund_partial $2.73 | ✓ refund_partial $2.74 |
| B-0050 | route_deviation | rd_general_consent_jp | no_action | ✗ refund_partial $2.96 | ✗ refund_partial $7.09 | ✓ no_action | ✓ no_action |
| B-0051 | route_deviation | rd_general_consent_wl | no_action | ✗ refund_partial $6.34 | ✗ refund_partial $5.08 | ✗ escalate | ✓ no_action |
| B-0052 | route_deviation | rd_general_consent_cn_cp | no_action | ✗ refund_partial $16.61 | ✗ refund_partial $10.62 | ✗ escalate | ✓ no_action |
| B-0053 | route_deviation | rd_general_consent_cn_bv | no_action | ✗ refund_partial $7.17+flag | ✗ refund_partial $2.92+flag | ✗ refund_partial $2.92+flag | ✓ no_action |
| B-0054 | route_deviation | rd_named_singlish_j8 | escalate | ✗ refund_partial $0.00 | ✗ refund_partial $7.54 | ✓ escalate | ✓ escalate |
| B-0055 | route_deviation | rd_named_singlish_nx | escalate | ✓ escalate+flag | ✗ refund_partial $6.44 | ✓ escalate | ✓ escalate |
| B-0056 | route_deviation | rd_named_cn_am | escalate | ✗ refund_partial $5.99 | ✗ refund_partial $6.68 | ✗ refund_partial $6.68 | ✓ escalate |
| B-0057 | route_deviation | rd_named_cn_tp | escalate | ✓ escalate | ✗ refund_partial $3.52+flag | ✓ escalate | ✓ escalate |
| B-0058 | route_deviation | rd_two_segs_consent_seg1_hv | escalate | ✗ refund_partial $1.80 | ✗ refund_partial $3.12 | ✗ refund_partial $3.12 | ✓ escalate |
| B-0059 | route_deviation | rd_two_segs_consent_seg1_jt | escalate | ✗ refund_partial $1.41 | ✗ refund_partial $3.71+flag | ✓ escalate | ✓ escalate |
| B-0060 | route_deviation | rd_two_segs_consent_seg1_pa | escalate | ✗ refund_partial $1.18+flag | ✗ refund_partial $3.64+flag | ✗ refund_partial $3.64+flag | ✓ escalate |
| B-0061 | route_deviation | rd_two_segs_consent_seg1_bk | escalate | ✗ refund_partial $7.78 | ✗ refund_partial $2.40 | ✗ refund_partial $2.40 | ✓ escalate |
| B-0062 | route_deviation | rd_fixed_fare_consent_cr | no_action | ✗ escalate | ✓ no_action | ✓ no_action | ✓ no_action |
| B-0063 | route_deviation | rd_fixed_fare_consent_ns | no_action | ✓ no_action | ✓ no_action $0.00 | ✓ no_action | ✓ no_action |
| B-0064 | route_deviation | rd_fixed_fare_consent_prior_tv | escalate | ✗ no_action+flag | ✗ no_action | ✓ escalate | ✓ escalate |
| B-0065 | route_deviation | rd_fixed_fare_consent_prior_jc | escalate | ✗ no_action | ✗ no_action | ✓ escalate | ✓ escalate |
