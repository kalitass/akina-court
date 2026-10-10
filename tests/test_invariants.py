"""Data invariants: checks that do not trust the code, only the relations between the data, the labels and the texts.

  * a scenario that says "the accident is on the stretch the driver bypassed" has the accident inside the bypassed stretch,
    and "whichever way is faster" loops really bypass a stretch (the generator and the demo case agree with their labels)
  * an independent twenty-line recomputation (own haversine) reproduces the fact table's distances, closest approach,
    cancellation timing and chat count for every case file in the repo
  * policy.md, clauses_en.json and web/policy.html carry the same clause ids and gap count, and the page is what the
    builder produces from today's files; the pages quote that gap count
  * the reference change log names cases that exist and outcomes the manifest holds
  * segment findings on a no-show case never survive verification
"""
import importlib.util
import json
import math
import re
import sys
from pathlib import Path

import pytest

from core.facts.tools import _project, build_fact_table
from core.policy import citable_ids
from core.policy_engine import evaluate
from core.schemas import Case, Ruling, SegmentFinding
from core.verify import verify_ruling

ROOT = Path(__file__).resolve().parents[1]
MAIN = json.loads((ROOT / "data" / "bench" / "manifest.json").read_text())
BLIND = json.loads((ROOT / "data" / "bench" / "blind" / "manifest.json").read_text())
CASE_FILES = sorted((ROOT / "data" / "cases").glob("*.json")) + sorted((ROOT / "data" / "bench" / "cases").glob("*.json")) + sorted((ROOT / "data" / "bench" / "blind" / "cases").glob("*.json"))


def load(path: Path) -> Case:
    return Case.model_validate(json.loads(path.read_text()))


def case_path(cid: str) -> Path:
    for d in ("data/cases", "data/bench/cases", "data/bench/blind/cases"):
        p = ROOT / d / f"{cid}.json"
        if p.exists():
            return p
    raise FileNotFoundError(cid)


def hav_m(a, b):
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 2 * 6_371_008.8 * math.asin(math.sqrt(h))


# ---------------------------------------------------------------------------- labels vs geometry

def segments_of(case: Case):
    return [f.value for f in build_fact_table(case).facts if f.value and "extra_km" in f.value and "entry_km" in f.value]


@pytest.mark.parametrize("entry", [c for c in MAIN["cases"] + BLIND["cases"] if c["type"] == "route_deviation"], ids=lambda c: c["case_id"])
def test_scenario_label_matches_the_geometry(entry):
    cond, case = entry["conditions"], load(case_path(entry["case_id"]))
    segs = segments_of(case)
    if cond["incident"] in ("on_stretch", "seg1", "late"):
        inc = case.traffic.incidents[0]
        _, along = _project(inc.lat, inc.lon, case.route.polyline)
        s = segs[0]
        assert s["exit_km"] - s["entry_km"] >= 0.3, f"{entry['case_id']}: the first loop is an out-and-back spur, it bypasses nothing"
        assert s["entry_km"] - 0.3 <= along <= s["exit_km"] + 0.3, f"{entry['case_id']}: the accident ({along:.2f} km) is not on the bypassed stretch {s['entry_km']}–{s['exit_km']}"
    if cond["consent"] in ("general", "general_cn"):
        assert segs[0]["route_km"] >= 1.0, f"{entry['case_id']}: a 'whichever way is faster' loop must bypass a real stretch"


def test_flagship_demo_bypasses_the_accident():
    case = load(ROOT / "data" / "cases" / "C-0001.json")
    table = build_fact_table(case)
    seg = next(f for f in table.facts if f.value and "extra_km" in f.value)      # the first detour
    inc = case.traffic.incidents[0]
    _, along = _project(inc.lat, inc.lon, case.route.polyline)
    assert seg.value["exit_km"] - seg.value["entry_km"] >= 0.3
    assert seg.value["entry_km"] <= along <= seg.value["exit_km"]
    cert = evaluate(case, table)
    assert cert.segments[seg.id]["exempt"] is True and "RD-4" in cert.segments[seg.id]["why"]


# ---------------------------------------------------------------------------- independent recomputation

@pytest.mark.parametrize("path", CASE_FILES, ids=lambda p: p.stem)
def test_fact_numbers_reproduce_from_the_raw_record(path):
    case = load(path)
    table = build_fact_table(case)
    vals = {f.id: f.value for f in table.facts if f.value}
    t = case.trip
    if case.dispute.type == "route_deviation" and t.pickup_at and t.dropoff_at:
        pts = [(p.lat, p.lon) for p in case.gps if t.pickup_at <= p.ts <= t.dropoff_at]
        if len(pts) >= 2:
            km = sum(hav_m(a, b) for a, b in zip(pts, pts[1:])) / 1000
            dist = next(v for v in vals.values() if "actual_km" in v)
            assert abs(dist["actual_km"] - km) <= 0.02, (path.stem, dist["actual_km"], km)
            assert abs(dist["excess_km"] - (km - case.route.total_km)) <= 0.02
            for seg in (v for v in vals.values() if "extra_km" in v):
                a, b = seg["start"], seg["end"]
                inside = [(p.lat, p.lon) for p in case.gps if a <= p.ts.isoformat() <= b]
                assert len(inside) >= 2 and seg["driven_km"] <= km + 0.01
                assert abs(seg["extra_km"] - (seg["driven_km"] - seg["route_km"])) <= 0.011
    if case.dispute.type == "no_show" and t.cancelled_at:
        pts = [p for p in case.gps if t.accepted_at <= p.ts <= t.cancelled_at]
        if pts:
            near = min(hav_m((p.lat, p.lon), (t.pickup.lat, t.pickup.lon)) for p in pts)
            got = next(v for v in vals.values() if "nearest_m" in v)
            assert abs(got["nearest_m"] - near) <= 1.0, (path.stem, got["nearest_m"], near)
        cancel = next(v for v in vals.values() if "s_after_accept" in v)
        assert cancel["s_after_accept"] == round((t.cancelled_at - t.accepted_at).total_seconds())
        assert cancel["cancelled_by"] == t.cancelled_by
    chat_facts = [v for v in vals.values() if "idx" in v and "from" in v]
    assert len(chat_facts) == len(case.chat)
    for m, v in zip(case.chat, chat_facts):
        assert v["from"] == m.sender and (v["ts"] is None) == (m.ts is None)
    # every printed delta is the difference of the numbers printed next to it
    for f in table.facts:
        m = re.search(r"Actual distance ([\d.]+) km vs optimal route ([\d.]+) km: ([+-][\d.]+) km", f.text)
        if m:
            assert abs(float(m.group(1)) - float(m.group(2)) - float(m.group(3))) < 0.051, f.text
        m = re.search(r"Trip duration ([\d.]+) min vs estimated ([\d.]+) min \(([+-][\d.]+) min\)", f.text)
        if m:
            assert abs(float(m.group(1)) - float(m.group(2)) - float(m.group(3))) < 0.051, f.text
        m = re.search(r"Excess distance billed \$([\d.]+) \(([\d.]+) km × \$([\d.]+)/km", f.text)
        if m:
            assert abs(float(m.group(1)) - round(float(m.group(2)) * float(m.group(3)), 2)) < 0.011, f.text


# ---------------------------------------------------------------------------- policy texts agree

def _policy_page_module():
    spec = importlib.util.spec_from_file_location("build_policy_page", ROOT / "scripts" / "build_policy_page.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_policy_md_clauses_en_and_policy_html_agree():
    md = (ROOT / "policy" / "policy.md").read_text()
    md_ids = set(re.findall(r"^\*\*([A-Z]+-\d+)\*\*", md, flags=re.M)) | set(re.findall(r"^\| (G\d+) \|", md, flags=re.M))
    en = json.loads((ROOT / "policy" / "clauses_en.json").read_text())
    en_ids = {x["id"] for x in en} - {"PREMISE"}
    assert md_ids == en_ids, (md_ids ^ en_ids)
    gaps = sorted(i for i in md_ids if i.startswith("G"))
    assert len(gaps) == 13
    mod = _policy_page_module()
    rows, reg = mod.load(), mod.load_sources()
    fresh = mod.page(rows, reg)
    assert fresh == (ROOT / "web" / "policy.html").read_text(), "web/policy.html is stale: run scripts/build_policy_page.py"
    for page in ("README.md", "web/index.html"):
        text = (ROOT / page).read_text()
        for m in re.finditer(r"\b(\d{1,2}) (?:rules Ryde has not published|open gaps|disclosed gaps)", text):
            assert int(m.group(1)) == len(gaps), (page, m.group(0))
    # the thresholds the engine uses appear in the clause text (no stale number survives a rule change)
    ns1 = next(x for x in en if x["id"] == "NS-1")["rule_en"]
    assert "within_200m_after_tap_s" in ns1 and "m_from_pickup_at_tap" in ns1 and "more than 3 minutes" in ns1
    assert "within_200m_after_tap_s" in md and "no_show_threshold" in md


# ---------------------------------------------------------------------------- change log vs manifest

def test_reference_change_log_names_real_cases_and_outcomes():
    truth = {c["case_id"]: c["truth"] for c in MAIN["cases"]}
    log = (ROOT / "data" / "bench" / "REFERENCE_CHANGES.md").read_text()
    rows = [l for l in log.splitlines() if re.match(r"^\| B-\d{4} \|", l)]
    assert rows, "no case rows in the change log"
    for l in rows:
        cells = [c.strip() for c in l.strip("|").split("|")]
        cid, after = cells[0], cells[3]
        assert cid in truth, cid
        word = after.split()[0]
        assert truth[cid]["ruling"] == word, (cid, after, truth[cid]["ruling"])
        if truth[cid].get("amount"):
            assert f"${truth[cid]['amount']:.2f}" in after, (cid, after)
    for cid in re.findall(r"\b(B-\d{4})\b", log):
        assert cid in truth, f"{cid} named in the change log does not exist"


# ---------------------------------------------------------------------------- verifier keeps the record clean

def test_segment_findings_on_a_no_show_are_dropped():
    case = load(ROOT / "data" / "cases" / "C-0004.json")
    table = build_fact_table(case); cert = evaluate(case, table)
    r = Ruling(ruling="refund_full", amount=6.61, recommended_action="x + flag_account", flag_account=True, confidence=0.9, reasoning="[F1][NS-1]",
               cited_facts=["F1"], cited_policy=["NS-1", "NS-2"], safety_concern="none", evidence_status="sufficient",
               segment_findings=[SegmentFinding(fact_id="F8", finding="exempt", reason="safety screen read")])
    out, lines = verify_ruling(r, table, citable_ids(), certificate=cert)
    assert out.segment_findings == [] and any("not a route case" in l for l in lines)


# ---------------------------------------------------------------------------- texts a judge reads carry no retired mechanism

def test_reference_rationales_and_prompts_name_no_retired_mechanism():
    retired = ("keyword table", "threat keyword", "gate 0.70", "threshold 0.70", "regardless of confidence", "GEN-1", "GEN-5")
    for f in sorted((ROOT / "data" / "expected").glob("*.json")) + sorted((ROOT / "data" / "bench" / "expected").glob("*.json")):
        text = f.read_text()
        for r in retired:
            assert r not in text, (f.name, r)
    for f in ("core/agents/judge.py", "core/agents/advocate.py", "bench/baseline.py", "core/facts/tools.py", "policy/policy.md", "policy/clauses_en.json", "scripts/build_policy_page.py"):
        text = (ROOT / f).read_text()
        for r in retired:
            assert r not in text, (f, r)


# ---------------------------------------------------------------------------- the numbers the texts quote are the engine's constants

def test_copy_quotes_the_engine_constants():
    """Every data-layer threshold a page or clause names must be the value the code uses (one source: the constants)."""
    from core.facts import tools
    from core import policy_engine as pe
    expect = {
        f"{tools.PICKUP_RADIUS_M} m": ("policy/policy.md", "policy/clauses_en.json", "scripts/build_policy_page.py"),
        f"{tools.OFF_ROUTE_M} m": ("scripts/build_policy_page.py",),
        f"{tools.DETOUR_MIN_KM} km": ("scripts/build_policy_page.py",),
        f"{pe.NEAR_ROUTE_M} m": ("policy/policy.md", "scripts/build_policy_page.py"),
        f"{pe.GRACE_S // 60} min": ("policy/policy.md",),
        f"{pe.CANCEL_FEE:.2f}": ("policy/policy.md", "policy/clauses_en.json"),
    }
    for needle, files in expect.items():
        for f in files:
            assert needle in (ROOT / f).read_text(), f"{f} does not quote {needle!r} (the constant changed, or the text did)"
    # the detour-merge / stop / hole seconds the policy page's "not a clause" box prints
    box = (ROOT / "scripts" / "build_policy_page.py").read_text()
    assert f"under {tools.DETOUR_MERGE_S} s" in box and f"{tools.NEAR_ROUTE_M if False else pe.NEAR_ROUTE_M} m" in box


# ---------------------------------------------------------------------------- hand-written rationales quote the file's own figures

def test_demo_rationales_quote_their_own_amounts_and_segments():
    """data/expected/*.json rationales are written by hand: every dollar figure in them must be the file's amount or a
    figure in the case's fact table, and every '+N km' must be a segment of that case."""
    for f in sorted((ROOT / "data" / "expected").glob("*.json")):
        e = json.loads(f.read_text()); cid = f.stem
        case = load(case_path(cid)); table = build_fact_table(case)
        allowed_money = {round(e["amount"], 2)} if e.get("amount") else set()
        for fact in table.facts:
            for v in (fact.value or {}).values():
                if isinstance(v, (int, float)) and not isinstance(v, bool):
                    allowed_money.add(round(float(v), 2))
            allowed_money |= {round(float(x), 2) for x in re.findall(r"\$(\d+\.\d\d)", fact.text)}
        for m in re.findall(r"\$(\d+\.\d\d)", e["rationale"]):
            assert round(float(m), 2) in allowed_money, (cid, f"${m} in the rationale is neither the amount nor a figure in the fact table")
        kms = {round(v[k], 2) for v in (x.value for x in table.facts if x.value) for k in ("extra_km", "excess_km") if k in v and v[k] is not None}
        for m in re.findall(r"\+(\d+\.\d\d) km", e["rationale"]):
            assert round(float(m), 2) in kms, (cid, f"+{m} km in the rationale is neither a segment nor the measured/billed excess: {sorted(kms)}")
