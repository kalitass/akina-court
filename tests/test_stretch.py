"""Stretch modules (core/stretch). Fixtures: runs/C-0001.json .. C-0006.json (CaseRecords from real runs) and
data/cases/*.json. Tests that need a missing fixture skip. All stores are written to tmp_path, never to runs/."""
from __future__ import annotations

import shutil
from datetime import timedelta
from pathlib import Path

import pytest

from core.schemas import Case, CaseRecord, Fact, FactSource, Ruling
from core.stretch import Hooks, enabled, feedback, fraud, precedent, renumber, replay, sla
from core.stretch._util import make_event, now

ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / "runs"
CASES = ROOT / "data" / "cases"
ALL_IDS = [f"C-000{i}" for i in range(1, 7)]
FLAGS = ("STRETCH_PRECEDENT", "STRETCH_FRAUD", "STRETCH_SLA", "STRETCH_FEEDBACK")


def record(cid: str) -> CaseRecord:
    p = RUNS / f"{cid}.json"
    if not p.exists():
        pytest.skip(f"fixture {p} missing (run the case first)")
    rec = CaseRecord.model_validate_json(p.read_text(encoding="utf-8"))
    if rec.ruling is None:
        pytest.skip(f"{cid} has no ruling")
    return rec


def case(cid: str) -> Case:
    p = CASES / f"{cid}.json"
    if not p.exists():
        pytest.skip(f"case file {p} missing")
    return Case.model_validate_json(p.read_text(encoding="utf-8"))


@pytest.fixture
def runs_copy(tmp_path: Path) -> Path:
    """A private copy of every available runs/C-*.json, so stores land in tmp."""
    found = [p for p in (RUNS / f"{c}.json" for c in ALL_IDS) if p.exists()]
    if not found:
        pytest.skip("no runs/C-*.json fixtures")
    for p in found:
        shutil.copy(p, tmp_path / p.name)
    return tmp_path


@pytest.fixture
def all_on(monkeypatch):
    for f in FLAGS:
        monkeypatch.setenv(f, "1")


@pytest.fixture
def all_off(monkeypatch):
    for f in FLAGS:
        monkeypatch.delenv(f, raising=False)


def _ruling(action: str, amount=None, conf=0.95, rec_action="x", escalate=False) -> Ruling:
    return Ruling(ruling=action, amount=amount, recommended_action=rec_action, confidence=conf, reasoning="t", safety_concern="none", evidence_status="sufficient", flag_account="flag_account" in rec_action,
                  cited_facts=["F1"], cited_policy=["RD-1"], escalate=escalate,
                  escalation_reason="r" if escalate else None)


# ---------------------------------------------------------------------------
# flags + hooks
# ---------------------------------------------------------------------------

def test_enabled_reads_env(monkeypatch):
    monkeypatch.delenv("STRETCH_FRAUD", raising=False)
    assert enabled("fraud") is False
    for v in ("1", "true", "YES", " on "):
        monkeypatch.setenv("STRETCH_FRAUD", v)
        assert enabled("fraud") is True and enabled("STRETCH_FRAUD") is True
    monkeypatch.setenv("STRETCH_FRAUD", "0")
    assert enabled("fraud") is False


def test_hooks_are_noop_when_disabled(all_off, runs_copy):
    rec = record("C-0004")
    h = Hooks(runs_copy)
    assert h.before_judge(rec.facts, None, None) == []
    assert h.events == [] and h.judge_context() == ""
    assert h.after_ruling(rec) == []
    assert h.on_human_override("C-0004", _ruling("no_action")) is None
    assert not (runs_copy / "precedents.json").exists() and not (runs_copy / "queue.json").exists()


def test_hooks_full_pipeline_on_fixture(all_on, runs_copy):
    precedent.seed_from_runs(runs_copy)
    rec = record("C-0004")
    h = Hooks(runs_copy)
    extra = h.before_judge(rec.facts, None, case("C-0004"))
    assert extra and all(f.id.startswith("fraud-") for f in extra)
    numbered = renumber(extra, rec.facts)
    n = len(rec.facts.facts)
    assert [f.id for f in numbered] == [f"F{n + i}" for i in range(1, len(extra) + 1)]
    assert {e.kind for e in h.events} <= {"check", "facts"}
    ctx = h.judge_context()
    assert ctx == "" or ("PRECEDENTS" in ctx)   # weak matches (< MIN_SHOWN) are not shown to the judge
    after = h.after_ruling(rec)
    assert [e.kind for e in after] == ["check", "notify"]
    assert h.route is not None and h.route.queue == "review_24h"
    # replay through an EventLog-like emitter assigns seq
    seq = []
    out = replay(h.events + after, lambda actor, kind, title, body="", **p: seq.append((actor, kind, title)) or make_event(actor, kind, title, body))
    assert len(out) == len(seq) == len(h.events) + len(after)


# ---------------------------------------------------------------------------
# precedent
# ---------------------------------------------------------------------------

def test_precedent_features_fixture_values():
    f4 = precedent.features(record("C-0004").facts)
    assert f4["nearest_m"] == 612 and f4["pressed_here"] == 1 and f4["arrival_recorded"] == 0 and f4["cancelled_by_driver"] == 1
    assert "fake_here" in precedent.flags_of(f4)
    f1 = precedent.features(record("C-0001").facts)
    assert f1["n_detours"] == 2 and f1["consent_before_detour"] == 1 and f1["incident_on_route"] == 1
    assert set(f1) == set(precedent.FEATURES["route_deviation"])


def test_precedent_seed_similar_same_type_excludes_self(runs_copy):
    n = precedent.seed_from_runs(runs_copy)
    assert n == len(list(runs_copy.glob("C-*.json")))
    assert (runs_copy / "precedents.json").exists()
    t = record("C-0003").facts
    hits = precedent.similar(t, k=3, runs_dir=runs_copy)
    assert hits and all(h.case_id != "C-0003" for h in hits)
    stored = {e.case_id: e for e in precedent.load(runs_copy)}
    assert all(stored[h.case_id].dispute_type == "route_deviation" for h in hits)
    assert [h.similarity for h in hits] == sorted((h.similarity for h in hits), reverse=True)
    assert all(0.0 <= h.similarity <= 1.0 and h.why for h in hits)
    if "C-0001" in stored:
        assert hits[0].case_id == "C-0001"          # same binaries (incident, consent, severe band) -> nearest
    assert "C-0003" not in precedent.judge_block(hits) and all(h.case_id in precedent.judge_block(hits) for h in hits)
    assert "similar case(s)" in precedent.event(hits).title


def test_precedent_index_is_upsert_and_keeps_human(runs_copy):
    rec = record("C-0001")
    assert precedent.index(rec, runs_copy).source == "auto"
    precedent.index(rec, runs_copy)
    assert len(precedent.load(runs_copy)) == 1
    human = precedent.index(rec, runs_copy, source="human", ruling=_ruling("no_action"), reviewer="amy")
    assert human.source == "human" and human.ruling == "no_action"
    assert precedent.index(rec, runs_copy).source == "human"       # auto re-run never downgrades
    assert len(precedent.load(runs_copy)) == 1


def test_precedent_index_without_ruling_returns_none(tmp_path):
    rec = record("C-0001").model_copy(update={"ruling": None})
    assert precedent.index(rec, tmp_path) is None


def test_precedent_consistency_warning():
    mk = lambda cid, r, s: precedent.PrecedentHit(case_id=cid, ruling=r, similarity=s, source="auto", why="w")
    assert precedent.consistency(_ruling("no_action"), []) == ["precedent: none stored for this dispute type"]
    warn = precedent.consistency(_ruling("no_action"), [mk("A", "refund_partial", 0.9), mk("B", "refund_partial", 0.85), mk("C", "no_action", 0.3)])
    assert any(l.startswith("WARNING") and "A=refund_partial" in l for l in warn)
    ok = precedent.consistency(_ruling("refund_partial"), [mk("A", "refund_partial", 0.9), mk("B", "refund_partial", 0.85)])
    assert not any(l.startswith("WARNING") for l in ok) and any("consistent with 2" in l for l in ok)
    # one dissenting high-similarity precedent is not enough
    one = precedent.consistency(_ruling("no_action"), [mk("A", "refund_partial", 0.9), mk("B", "no_action", 0.5)])
    assert not any(l.startswith("WARNING") for l in one)


# ---------------------------------------------------------------------------
# fraud
# ---------------------------------------------------------------------------

def test_fraud_signals_per_fixture():
    expect = {
        "C-0001": set(), "C-0003": set(),
        "C-0002": {("REPEAT_OFFENDER", "driver")},
        "C-0004": {("ARRIVAL_LOCATION_MISMATCH", "driver"), ("WAIT_CLAIM_UNSUPPORTED", "driver"), ("JAM_CLAIM_UNSUPPORTED", "driver")},
        "C-0005": {("SERIAL_COMPLAINANT", "rider")},
        "C-0006": set(),                 # threats are the judge's reading (SAFE-1 screen), not a code signal
    }
    for cid, want in expect.items():
        if not (RUNS / f"{cid}.json").exists():
            continue
        t = record(cid).facts
        sigs = fraud.detect(t, case(cid) if (CASES / f"{cid}.json").exists() else None)
        assert {(s.code, s.party) for s in sigs} == want, cid
        ids = t.ids()
        assert all(e in ids for s in sigs for e in s.evidence), cid


def test_fraud_fake_here_is_high_and_cites_timeline_and_gps():
    t = record("C-0004").facts
    s = next(s for s in fraud.detect(t) if s.code == "ARRIVAL_LOCATION_MISMATCH")
    assert s.severity == "high"
    srcs = {next(f.source for f in t.facts if f.id == e) for e in s.evidence}
    assert srcs == {"timeline", "gps"}
    assert fraud.highest(fraud.detect(t)) == "high"


def test_fraud_as_facts_legal_sources_and_safe_values():
    t = record("C-0004").facts
    sigs = fraud.detect(t)
    facts = fraud.as_facts(sigs)
    legal = set(FactSource.__args__)
    assert facts and all(f.source in legal and f.source in ("timeline", "profile") for f in facts)
    for f in facts:
        assert set(f.value) == {"signal", "signal_party", "severity", "evidence"}   # never trips verify / policy_engine sniffing
        assert "threat" not in f.value and "nearest_m" not in f.value and "party" not in f.value
    ev = fraud.event(sigs)
    assert ev.actor == "verify" and ev.kind == "check" and "3 signal(s)" in ev.title and ev.seq == 0
    assert "no bad-faith signal" in fraud.event([]).body


def test_fraud_facts_do_not_change_verify_outcome():
    """Appending signal facts to the table must not flip the stored ruling through core.verify."""
    from core.policy import citable_ids
    from core.verify import verify_ruling
    rec = record("C-0004")
    t = rec.facts
    extra = renumber(fraud.as_facts(fraud.detect(t)), t)
    t2 = t.model_copy(update={"facts": t.facts + extra})
    assert len(t2.ids()) == len(t.facts) + len(extra)
    before, _ = verify_ruling(rec.ruling, t, citable_ids())
    after, _ = verify_ruling(rec.ruling, t2, citable_ids())
    assert (before.ruling, before.escalate) == (after.ruling, after.escalate)


# ---------------------------------------------------------------------------
# sla
# ---------------------------------------------------------------------------

def test_sla_route_rules():
    assert sla.route(_ruling("no_action"), "safety").queue == "urgent_safety"
    concern = _ruling("escalate", escalate=True).model_copy(update={"safety_concern": "suspected", "safety_basis": ["F5"]})
    assert sla.route(concern, "route_deviation").queue == "urgent_safety"      # the judge's reading, not a keyword
    assert sla.route(_ruling("escalate", escalate=True), "no_show").queue == "review_24h"
    assert sla.route(_ruling("no_action", conf=0.72), "no_show").queue == "auto_resolve"   # confidence is diagnostic only
    assert sla.route(_ruling("refund_full", amount=45.0), "route_deviation").queue == "review_24h"
    assert sla.route(_ruling("refund_partial", 3.0, rec_action="voucher + flag_account"), "route_deviation").queue == "review_24h"
    high = [fraud.Signal(code="ARRIVAL_LOCATION_MISMATCH", party="driver", severity="high", evidence=["F1"], text="t")]
    assert sla.route(_ruling("refund_full", 6.61), "no_show", high).queue == "review_24h"
    r = sla.route(_ruling("refund_partial", 3.99, conf=0.86), "route_deviation")
    assert r.queue == "auto_resolve" and r.sla_hours == 0 and r.priority == 0
    assert sla.event(r).kind == "notify" and "auto_resolve" in sla.event(r).title


def test_sla_routes_fixtures_as_expected():
    """Fixtures are LLM runs (confidence drifts between re-runs), so the expectation is derived from
    the ruling's own properties rather than hard-coded per case."""
    for cid in ALL_IDS:
        if not (RUNS / f"{cid}.json").exists():
            continue
        rec = record(cid)
        sigs = fraud.detect(rec.facts)
        r = sla.route(rec.ruling, rec.facts.dispute_type, sigs, rec.eligibility)
        ru = rec.ruling
        if rec.facts.dispute_type == "safety" or ru.safety_concern != "none":
            want = "urgent_safety"
        elif (ru.escalate or (rec.eligibility or {}).get("auto") is False or ru.confidence < sla.AUTO_CONFIDENCE
              or (ru.amount or 0) > sla.AUTO_CAP_SGD or ru.flag_account
              or any(s.severity == "high" for s in sigs)):
            want = "review_24h"
        else:
            want = "auto_resolve"
        assert r.queue == want, (cid, r.reason)
        assert r.sla_hours == sla.SLA_HOURS[want]
    # the invariants the demo relies on
    if (RUNS / "C-0006.json").exists():
        assert sla.route(record("C-0006").ruling, "safety").queue == "urgent_safety"
    if (RUNS / "C-0004.json").exists():
        r4 = record("C-0004")
        assert sla.route(r4.ruling, "no_show", fraud.detect(r4.facts)).queue == "review_24h"


def test_sla_certificate_ineligible_goes_to_review():
    r = sla.route(_ruling("refund_partial", 3.0, conf=0.99), "route_deviation", eligibility={"auto": False, "reasons": ["RD-4 judge item open"]})
    assert r.queue == "review_24h" and "RD-4 judge item open" in r.reason
    assert sla.route(_ruling("refund_partial", 3.0, conf=0.99), "route_deviation", eligibility={"auto": True, "reasons": []}).queue == "auto_resolve"


def test_sla_queue_file(tmp_path):
    a = sla.enqueue("C-1", sla.route(_ruling("no_action"), "safety"), tmp_path)
    b = sla.enqueue("C-2", sla.route(_ruling("no_action", conf=0.99), "no_show"), tmp_path)
    sla.enqueue("C-2", sla.route(_ruling("escalate", escalate=True), "no_show"), tmp_path)   # upsert (escalated → review)
    items = sla.list_queue(tmp_path)
    assert [i.case_id for i in items] == ["C-1", "C-2"] and items[1].queue == "review_24h"
    assert a.due_at - a.enqueued_at == timedelta(hours=2)
    assert [i.case_id for i in sla.list_queue(tmp_path, queue="urgent_safety")] == ["C-1"]
    assert sla.overdue(tmp_path, at=now() + timedelta(hours=3)) and [i.case_id for i in sla.overdue(tmp_path, at=now() + timedelta(hours=3))] == ["C-1"]
    done = sla.resolve("C-1", "amy", "checked", tmp_path)
    assert done.status == "resolved" and done.resolved_by == "amy"
    assert [i.case_id for i in sla.list_queue(tmp_path, status="open")] == ["C-2"]
    assert sla.resolve("nope", "amy", runs_dir=tmp_path) is None


# ---------------------------------------------------------------------------
# feedback
# ---------------------------------------------------------------------------

def test_feedback_override_reindexes_as_human_and_ranks_first(runs_copy):
    precedent.seed_from_runs(runs_copy)
    r3 = record("C-0003")
    sla.enqueue("C-0003", sla.route(r3.ruling, "route_deviation"), runs_copy)
    ov = feedback.record_override("C-0003", _ruling("refund_partial", 1.18), "ops-amy", "ECP exemption rejected", runs_copy)
    assert ov.changed_outcome and ov.auto_ruling == "no_action" and ov.human_ruling == "refund_partial"
    assert (runs_copy / "overrides.json").exists()
    entry = next(e for e in precedent.load(runs_copy) if e.case_id == "C-0003")
    assert entry.source == "human" and entry.ruling == "refund_partial" and entry.reviewer == "ops-amy"
    assert sla.list_queue(runs_copy, status="resolved")[0].case_id == "C-0003"
    hits = precedent.similar(record("C-0001").facts, runs_dir=runs_copy)
    assert hits[0].case_id == "C-0003" and hits[0].source == "human" and "human-reviewed" in hits[0].why
    assert "[human-reviewed]" in precedent.judge_block(hits)
    # same outcome re-entered by a human is a review, not an override
    ov2 = feedback.record_override("C-0001", record("C-0001").ruling, "ops-bob", runs_dir=runs_copy)
    assert ov2.changed_outcome is False
    st = feedback.stats(runs_copy)
    rd = st["route_deviation"]
    assert rd["reviewed"] == 2 and rd["overridden"] == 1 and rd["cases"] >= 2
    assert rd["override_rate"] == round(1 / rd["cases"], 3)
    assert all(v["override_rate"] == 0.0 for k, v in st.items() if k != "route_deviation")


def test_feedback_via_hooks(all_on, runs_copy):
    h = Hooks(runs_copy)
    ov = h.on_human_override("C-0005", _ruling("refund_full", 6.61), reviewer="ops", note="rider was 2 min away")
    assert ov is not None and ov.dispute_type == "no_show" and ov.changed_outcome
    assert next(e for e in precedent.load(runs_copy) if e.case_id == "C-0005").source == "human"
