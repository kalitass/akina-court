"""Acceptance list for "no automatic ruling when the evidence is not enough" (no model call).

  * a GPS trace that stops 30 s into the trip does not pass as a measured route: insufficient, only escalate
  * a no-show wait proved by two samples 220 s apart is not a continuous wait: insufficient, only escalate
  * the organisers' sample is sampled every ~3 min; that cadence is not a hole, and the sample still clears
  * cancelled_by missing is not "the driver cancelled": insufficient
  * the no-show wait threshold comes from the case record when it states one (8 min, "reached" = at least),
    else Ryde's default (more than 3 min); the trace names the source; a platform auto-arrival is never written as a tap
  * evidence_status is a three-valued field: insufficient / unknown never execute; the words must agree with the status
  * every id the judge writes — in findings, safety basis, rejected claims — is checked, not only the top-level lists
  * safety_concern and evidence_status are required in the judge's output; old records still load
  * an escalated case gets a fixed notice that promises nothing; a notice whose amount disagrees with the ruling is replaced
  * an undetermined finding that cannot change the outcome (fixed fare, no prior) does not force a hand-off
"""
import json
from datetime import timedelta
from pathlib import Path

import pytest

from core.facts.tools import build_fact_table
from core.notices import consistent, escalation_notices, fallback_notices
from core.policy import citable_ids
from core.policy_engine import check_ruling, evaluate, no_show_threshold
from core.schemas import Case, PolicyParams, Ruling, SegmentFinding
from core.verify import citation_problems, verify_ruling
from test_facts import no_show_case

ROOT = Path(__file__).resolve().parents[1]


def load(cid):
    return Case.model_validate(json.loads((ROOT / "data" / "cases" / f"{cid}.json").read_text()))


def ruling(**kw):
    base = dict(ruling="no_action", recommended_action="x", confidence=0.9, reasoning="[F1][RD-1]", cited_facts=["F1"], cited_policy=["RD-1"],
                safety_concern="none", evidence_status="sufficient")
    base.update(kw)
    return Ruling(**base)


def with_tap(case, wait_s, **trip):
    """no_show_case with the tap at the moment the car stops, so the wait after the tap is exactly wait_s."""
    gps = case.gps
    here = gps[-(wait_s // 5) - 1].ts
    return case.model_copy(update={"trip": case.trip.model_copy(update={"driver_pressed_here_at": here, "driver_arrived_at": here, **trip})})


# ---------------------------------------------------------------------------- GPS coverage and holes

def test_trace_that_ends_30s_into_the_trip_is_insufficient():
    case = load("C-0001")
    t0 = case.trip.pickup_at
    short = [p for p in case.gps if p.ts <= t0 + timedelta(seconds=30)]
    case = case.model_copy(update={"gps": short})
    table = build_fact_table(case)
    assert any(f.value and f.value.get("uncovered_end_s") for f in table.facts), "no coverage fact for the missing tail"
    cert = evaluate(case, table)
    assert cert.insufficient and cert.allowed == ["escalate"]


def test_two_samples_220s_apart_do_not_prove_a_continuous_wait():
    case = with_tap(no_show_case(stop_offset_m=40, wait_s=240), 240)
    here = case.trip.driver_pressed_here_at
    at = lambda s: next(p for p in case.gps if p.ts == here + timedelta(seconds=s))
    keep = [p for p in case.gps if p.ts < here] + [at(0), at(220)]     # the tap sample and one 220 s later, nothing between
    case = case.model_copy(update={"gps": keep, "trip": case.trip.model_copy(update={"cancelled_at": at(220).ts})})
    table = build_fact_table(case)
    assert any(f.value and f.value.get("gps_gap_s") for f in table.facts)
    cert = evaluate(case, table)
    assert cert.insufficient and "hole" in cert.insufficient and cert.allowed == ["escalate"]


def test_sample_cadence_of_three_minutes_is_not_a_hole():
    case = load("DISP-002")
    table = build_fact_table(case)
    assert not any(f.value and f.value.get("gps_gap_s") for f in table.facts), "the sample's own cadence was read as holes"
    cadence = next(f for f in table.facts if f.value and "median_interval_s" in f.value)
    assert cadence.value["median_interval_s"] >= 120 and "every" in cadence.text
    cert = evaluate(case, table)
    assert not cert.insufficient and "no_action" in cert.allowed


def test_cancelled_by_missing_is_not_the_driver():
    case = no_show_case(stop_offset_m=40, wait_s=300)
    case = case.model_copy(update={"trip": case.trip.model_copy(update={"cancelled_by": None})})
    table = build_fact_table(case)
    cert = evaluate(case, table)
    assert cert.insufficient and "who cancelled" in cert.insufficient and cert.allowed == ["escalate"]


# ---------------------------------------------------------------------------- no-show threshold

def test_threshold_source_is_the_record_when_it_states_one_else_the_default():
    s, inclusive, source = no_show_threshold(load("DISP-002"))
    assert (s, inclusive) == (480, True) and "8" in source and "record" in source
    s, inclusive, source = no_show_threshold(no_show_case(stop_offset_m=40, wait_s=300))
    assert (s, inclusive) == (180, False) and "NS-1" in source and "more than" in source


@pytest.mark.parametrize("wait_s,ok", [(479, False), (480, True), (481, True)])
def test_explicit_eight_minute_threshold_is_reached_at_eight_minutes(wait_s, ok):
    case = with_tap(no_show_case(stop_offset_m=40, wait_s=wait_s + 5), wait_s + 5)
    case = case.model_copy(update={"trip": case.trip.model_copy(update={"cancelled_at": case.trip.driver_pressed_here_at + timedelta(seconds=wait_s)}),
                                   "policy_params": PolicyParams(no_show_threshold_min=8, free_wait_min=5)})
    case = case.model_copy(update={"gps": [p for p in case.gps if p.ts <= case.trip.cancelled_at]})
    cert = evaluate(case, build_fact_table(case))
    iii = next(p for p in cert.predicates if p.clause == "NS-1" and p.element.startswith("(iii)"))
    assert (iii.status == "pass") is ok, (wait_s, iii.detail)
    assert "8 min" in iii.element and "record" in iii.element
    assert ("no_action" in cert.allowed) is ok


@pytest.mark.parametrize("wait_s,ok", [(179, False), (180, False), (181, True)])
def test_default_threshold_is_more_than_three_minutes(wait_s, ok):
    case = with_tap(no_show_case(stop_offset_m=40, wait_s=wait_s + 5), wait_s + 5)
    case = case.model_copy(update={"trip": case.trip.model_copy(update={"cancelled_at": case.trip.driver_pressed_here_at + timedelta(seconds=wait_s)})})
    case = case.model_copy(update={"gps": [p for p in case.gps if p.ts <= case.trip.cancelled_at]})
    cert = evaluate(case, build_fact_table(case))
    iii = next(p for p in cert.predicates if p.clause == "NS-1" and p.element.startswith("(iii)"))
    assert (iii.status == "pass") is ok, (wait_s, iii.detail)
    assert "3 min" in iii.element and "NS-1" in iii.element
    assert ("no_action" in cert.allowed) is ok


def test_platform_auto_arrival_is_named_as_such_never_as_a_tap():
    case = load("DISP-002")
    table = build_fact_table(case)
    cert = evaluate(case, table)
    i = next(p for p in cert.predicates if p.clause == "NS-1" and p.element.startswith("(i)"))
    iii = next(p for p in cert.predicates if p.clause == "NS-1" and p.element.startswith("(iii)"))
    assert "platform_auto" in i.detail and "tapped" not in i.detail
    assert "platform_auto" in iii.detail
    assert not any("tapped" in f.text for f in table.facts)


# ---------------------------------------------------------------------------- evidence_status

def test_insufficient_or_unknown_evidence_never_executes():
    case = load("C-0001")
    table = build_fact_table(case); cert = evaluate(case, table)
    for status in ("insufficient", "unknown"):
        r = ruling(ruling="no_action", evidence_status=status, evidence_gap="the arrival time and the GPS conflict")
        ok, why = check_ruling(cert, r)
        assert not ok and any("evidence_status" in w for w in why), (status, why)
        out, _ = verify_ruling(r, table, citable_ids(), certificate=cert)
        assert out.escalate


def test_status_and_words_must_agree():
    case = load("C-0001")
    cert = evaluate(case, build_fact_table(case))
    ok, why = check_ruling(cert, ruling(evidence_status="sufficient", evidence_gap="No material gap: the record is complete."))
    assert not ok and any("evidence_gap" in w for w in why)
    ok, why = check_ruling(cert, ruling(ruling="escalate", escalate=True, evidence_status="insufficient", evidence_gap=None))
    assert not ok and any("evidence_gap" in w for w in why)
    ok, why = check_ruling(cert, ruling(ruling="escalate", escalate=True, evidence_status="insufficient", evidence_gap="no GPS after 14:20"))
    assert ok, why


def test_trace_insufficient_overrides_a_judge_who_says_sufficient():
    case = load("C-0001")
    case = case.model_copy(update={"gps": case.gps[:3]})
    cert = evaluate(case, build_fact_table(case))
    assert cert.insufficient
    ok, why = check_ruling(cert, ruling(ruling="escalate", escalate=True, evidence_status="sufficient"))
    assert not ok and any("insufficient" in w for w in why)


# ---------------------------------------------------------------------------- nested references

def test_every_nested_id_is_checked():
    case = load("C-0001")
    table = build_fact_table(case)
    r = ruling(segment_findings=[SegmentFinding(fact_id="F5", finding="counts", basis=["F999"], reason="counts under [RD-999]")],
               safety_basis=["F998"], rejected_claims=[{"id": "D1", "reason": "contradicted by [F997]"}])
    problems = citation_problems(r, table, citable_ids())
    joined = " ".join(problems)
    for bad in ("F999", "RD-999", "F998", "F997"):
        assert bad in joined, (bad, problems)
    out, lines = verify_ruling(r, table, citable_ids(), certificate=evaluate(case, table))
    assert out.escalate and any("F999" in l for l in lines)


def test_safety_concern_and_evidence_status_are_required_but_old_records_load():
    import pydantic
    from core.schemas import CaseRecord, legacy_ruling
    required = Ruling.model_json_schema()["required"]
    assert "safety_concern" in required and "evidence_status" in required
    legacy = {"ruling": "no_action", "recommended_action": "x", "confidence": 0.5, "reasoning": "r", "cited_facts": [], "cited_policy": []}
    with pytest.raises(pydantic.ValidationError):          # a new output without the fields is rejected, not filled in
        Ruling.model_validate(legacy)
    old = Ruling.model_validate(legacy_ruling(legacy))     # only the explicit migration fills them
    assert old.safety_concern == "none" and old.evidence_status == "sufficient"
    old_esc = Ruling.model_validate(legacy_ruling({**legacy, "ruling": "escalate", "escalate": True, "evidence_gap": "no GPS"}))
    assert old_esc.evidence_status == "insufficient"
    for f in sorted((ROOT / "runs").glob("C-*.json")):      # every stored run loads through the one entry point
        CaseRecord.load(f)


def test_uncovered_tail_is_not_counted_as_waiting():
    """B-0028-style counterexample: tap, GPS until 150 s after it, cancellation at 240 s. 150 s are measured, the
    missing 90 s would decide the 3-minute threshold: neither 'waited long enough' nor 'did not' can be measured."""
    case = with_tap(no_show_case(stop_offset_m=40, wait_s=250), 250)
    here = case.trip.driver_pressed_here_at
    gps = [p for p in case.gps if p.ts <= here + timedelta(seconds=150)]
    case = case.model_copy(update={"gps": gps, "trip": case.trip.model_copy(update={"cancelled_at": here + timedelta(seconds=240)})})
    table = build_fact_table(case)
    tl = next(f for f in table.facts if f.value and "within_200m_after_tap_s" in f.value)
    assert tl.value["within_200m_after_tap_s"] == 150 and tl.value["tail_uncovered_s"] == 90
    cert = evaluate(case, table)
    assert cert.insufficient and "uncovered" in cert.insufficient and cert.allowed == ["escalate"]
    # a tail of one sampling interval is closed (the trace reaches the cancellation to within a sample)
    case2 = case.model_copy(update={"trip": case.trip.model_copy(update={"cancelled_at": here + timedelta(seconds=153)})})
    tl2 = next(f for f in build_fact_table(case2).facts if f.value and "within_200m_after_tap_s" in f.value)
    assert tl2.value["within_200m_after_tap_s"] == 153 and tl2.value["tail_uncovered_s"] == 0
    # a tail that cannot change the answer is not a reason to refuse: 150 s measured, cancel at 170 s, threshold 180 → fail, refund
    case3 = case.model_copy(update={"trip": case.trip.model_copy(update={"cancelled_at": here + timedelta(seconds=170)})})
    cert3 = evaluate(case3, build_fact_table(case3))
    assert not cert3.insufficient and cert3.allowed == ["refund_full", "escalate"]


def test_blind_report_counts_each_case_once(tmp_path, monkeypatch):
    import importlib.util
    spec = importlib.util.spec_from_file_location("blind_report", ROOT / "bench" / "blind_report.py")
    br = importlib.util.module_from_spec(spec); spec.loader.exec_module(br)
    man = json.loads((ROOT / "data" / "bench" / "blind" / "manifest.json").read_text())
    c = man["cases"][0]; t = c["truth"]
    res = tmp_path / "court"; res.mkdir()
    good = {"case_id": c["case_id"], "ok": True, "ruling": {"ruling": t["ruling"], "amount": t.get("amount"), "escalate": t["escalate"]}}
    (res / f"{c['case_id']}.json").write_text(json.dumps(good))
    (res / f"{c['case_id']}.record.json").write_text(json.dumps({"case_id": c["case_id"], "events": []}))
    c2 = man["cases"][1]
    (res / f"{c2['case_id']}.json").write_text(json.dumps({"case_id": c2["case_id"], "ok": False, "error": "timeout"}))
    monkeypatch.setattr(br, "RES", tmp_path)
    import io, contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        br.main()
    out = buf.getvalue()
    assert "core decision 1/2, wrong and executed 0/2, runs failed 1/2" in out, out


# ---------------------------------------------------------------------------- notices

def test_escalated_case_gets_a_fixed_notice_that_promises_nothing():
    r = ruling(ruling="escalate", escalate=True, amount=None, recommended_action="Issue a $3.99 voucher",
               reasoning="2.83 km × $1.41 = $3.99 [F5][RD-2]", escalation_reason="amount 4.99 does not match the formula 3.99")
    rider, driver = escalation_notices("C-0001", r, ["the route taken and the messages exchanged"])
    for text in (rider, driver):
        assert "$" not in text and "voucher" not in text.lower() and "reviewer" in text.lower()
        assert "no decision" in text.lower() or "not been decided" in text.lower()


def test_notice_amount_must_match_the_ruling():
    r = ruling(ruling="refund_partial", amount=3.99, cited_policy=["RD-2"])
    assert consistent("You'll get $3.99 back as a Ryde voucher.", r)
    assert not consistent("You'll get $4.99 back as a Ryde voucher.", r)
    assert not consistent("You'll get $3.99 back.", ruling(ruling="no_action"))
    rider, driver = fallback_notices(r)
    assert "$3.99" in rider and "$3.99" in driver


# ---------------------------------------------------------------------------- undetermined that changes nothing

def test_undetermined_finding_that_cannot_change_the_outcome_may_still_rule():
    case = load("C-0001")
    case = case.model_copy(update={"trip": case.trip.model_copy(update={"service_type": "RydeX"}),
                                   "fare": case.fare.model_copy(update={"pricing": "fixed"}),
                                   "profiles": case.profiles.model_copy(update={"driver": case.profiles.driver.model_copy(update={"route_disputes_upheld_90d": 0})})})
    table = build_fact_table(case); cert = evaluate(case, table)
    assert any(s["exempt"] is None for s in cert.segments.values())
    findings = [SegmentFinding(fact_id=f, finding=("undetermined" if s["exempt"] is None else ("exempt" if s["exempt"] else "counts")),
                               reason=("named road; no record ties the segment to it (G13)" if s["exempt"] is None else "code-settled [RD-4]"))
                for f, s in cert.segments.items()]
    r = ruling(ruling="no_action", cited_policy=["RD-1", "RD-2"], segment_findings=findings)
    ok, why = check_ruling(cert, r)
    assert ok, why
    # the same finding on the metered original must not execute
    case_m = load("C-0001")
    table_m = build_fact_table(case_m); cert_m = evaluate(case_m, table_m)
    r_m = r.model_copy(update={"cited_policy": ["RD-1", "RD-2"]})
    ok, why = check_ruling(cert_m, r_m)
    assert not ok and any("undetermined" in w for w in why)


# ---------------------------------------------------------------------------- reference answers follow the frozen rule, not the model

def test_reference_answers_apply_g13_without_a_model():
    """Agreement to a named road with no record tying the segment to it: undetermined; a person decides when it changes
    the outcome (metered, or a prior), and the answer stays when it changes nothing (fixed fare, no prior)."""
    m = json.loads((ROOT / "data" / "bench" / "manifest.json").read_text())
    assert "G13" in m["reference_version"]
    for c in m["cases"]:
        cond, t = c["conditions"], c["truth"]
        if c["type"] != "route_deviation" or cond["consent"] not in ("before", "before_seg1") or cond["incident"] in ("on_stretch", "seg1"):
            continue
        if cond["service"] == "RydeTAXI" or cond["prior"]:
            assert t["escalate"] and t["ruling"] == "escalate" and "ties segment" in t.get("evidence_gap", ""), c["case_id"]
        else:
            assert not t["escalate"] and t["ruling"] == "no_action", c["case_id"]
    changed = (ROOT / "data" / "bench" / "REFERENCE_CHANGES.md").read_text()
    for cid in ("B-0002", "B-0013", "B-0023", "B-0025"):
        assert cid in changed, f"{cid} moved but is not in the change log"


def test_benchmark_runner_keeps_every_ruling_field():
    """The saved benchmark ruling must carry the judge's own safety_concern / evidence_status; otherwise the gate
    ablation re-validates a dict without them and the legacy loader quietly writes "none" / "sufficient"."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("run_bench", ROOT / "bench" / "run_bench.py")
    src = (ROOT / "bench" / "run_bench.py").read_text()
    for f in ("safety_concern", "safety_basis", "evidence_status", "evidence_gap", "segment_findings", "reasoning"):
        assert f'"{f}"' in src.split("RULING_KEYS")[1].split(")")[0], f
    for f in Ruling.model_fields:
        assert f'"{f}"' in src.split("RULING_KEYS")[1].split(")")[0], f"Ruling field {f} is not saved by the benchmark runner"


# ---------------------------------------------------------------------------- the two places code writes a ruling itself

def test_judge_unavailable_ruling_is_valid_and_goes_to_a_person():
    from core.orchestrate import judge_unavailable_ruling
    from core.stretch import sla
    r = judge_unavailable_ruling("ModelHTTPError: status_code: 402")
    assert r.escalate and r.ruling == "escalate" and r.safety_concern == "unscreened" and r.evidence_status == "unknown"
    case = load("C-0001")
    table = build_fact_table(case); cert = evaluate(case, table)
    ok, why = check_ruling(cert, r)
    assert ok, why                                      # an escalate that names its ground stands
    out, lines = verify_ruling(r, table, citable_ids(), certificate=cert)
    assert out.escalate
    rt = sla.route(out, case.dispute.type)                # an outage is a normal review, not a safety emergency
    assert "safety" not in rt.queue


def test_human_override_builds_a_valid_ruling():
    from core.stretch.feedback import ruling_from_override
    prev = ruling(ruling="escalate", escalate=True, safety_concern="suspected", safety_basis=["F10"], evidence_status="unknown")
    human = ruling_from_override({"ruling": "refund_partial", "amount": 3.99, "reasoning": "reviewed the chat: no threat, the detour counts"}, prev)
    assert human.ruling == "refund_partial" and human.amount == 3.99 and not human.escalate
    assert human.evidence_status == "sufficient" and human.evidence_gap is None
    assert human.safety_concern == "suspected"          # the court's reading carries over unless the reviewer states otherwise
    cleared = ruling_from_override({"ruling": "no_action", "safety_concern": "none"}, prev)
    assert cleared.safety_concern == "none" and cleared.amount is None
    kept = ruling_from_override({"ruling": "escalate", "evidence_gap": "waiting for the driver's dashcam"}, None)
    assert kept.escalate and kept.evidence_status == "unknown" and kept.evidence_gap
    after_outage = ruling_from_override({"ruling": "no_action"}, ruling(ruling="escalate", escalate=True, safety_concern="unscreened", evidence_status="unknown"))
    assert after_outage.safety_concern == "none"        # a person ruled, so the screen has now been done by a person


def test_no_sample_after_the_confirmation_is_an_unrecorded_wait_not_zero():
    """Sparse record: the last GPS sample is 1 s before the tap and nothing follows; cancellation 300 s later.
    The wait is unrecorded, so the case goes to a person — neither 'did not wait' nor 'waited'."""
    base = with_tap(no_show_case(stop_offset_m=40, wait_s=300), 300)
    here = base.trip.driver_pressed_here_at
    sparse = [p for i, p in enumerate(base.gps) if p.ts < here and i % 36 == 0] + [p for p in base.gps if p.ts < here][-1:]   # ~180 s cadence, ends just before the tap
    case = base.model_copy(update={"gps": sparse, "trip": base.trip.model_copy(update={"cancelled_at": here + timedelta(seconds=300)})})
    table = build_fact_table(case)
    tl = next(f for f in table.facts if f.value and "within_200m_after_tap_s" in f.value)
    assert tl.value["within_200m_after_tap_s"] == 0 and tl.value["tail_uncovered_s"] == 300
    cert = evaluate(case, table)
    assert cert.insufficient and cert.allowed == ["escalate"]
