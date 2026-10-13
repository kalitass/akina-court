#!/usr/bin/env python3
"""Generate web/report.html — the one-page results dashboard for judges.

Run:  .venv/bin/python bench/dashboard.py        (stdlib only; idempotent; fails loudly if a data file is missing)

Every number on the page is read from a file (bench/results/summary.json, bench/results/*/, data/bench/manifest.json,
data/cases, data/expected, policy/policy.md, tests/, core/orchestrate.py, core/counterfactual.py). The only hand-written
material is the CONTENT dict directly below: prose, labels, plain-English meanings of clause ids and the fixed checklists.
Rule for judge-facing text: no internal identifiers (clause ids, fact ids, scenario ids). Where an id must exist it goes
into a tooltip (`title=`), never into the main text.
"""
from __future__ import annotations

import ast
import datetime as dt
import html
import json
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "web" / "report.html"
sys.path.insert(0, str(ROOT))
from core.case_format import read_case  # noqa: E402  (case files are official-plus; this reads them as the internal Case dict)

# =====================================================================================================================
# HAND-WRITTEN CONTENT — everything that is NOT derivable from data lives here and nowhere else.
# =====================================================================================================================

CONTENT = {
    "title": "Akina Court — Results",
    "blurb": "Facts by code, arguments by agents, every action checked.",
    "method_caveat": "synthetic data · one model ({model}) · reference answers derived from the written policy — a policy-conformance test, not human-ops accuracy",
    "core_tip": "core decision = outcome label + refund amount (±$0.01) + escalation flag; account flags and citations are not part of it",
    "pitch": ("A courtroom, not a chatbot: two adversarial advocates and a judge argue only from facts that code "
              "computed; the policy itself runs as code, and a ruling is executed only when it agrees with that code."),
    "manual_handling": "24–72 h",   # manual handling time per dispute, from the track brief

    # Plain-English meaning of every clause id that may appear in data text (policy/policy.md). Sub-items first.
    "clauses": {
        "RD-3(a)": "a stop the rider named", "RD-3(b)": "an unnamed 'on the way' stop",
        "RD-3(c)": "waiting time at a rider stop stays billable",
        "RD-4(a)": "a reported incident on the replaced stretch", "RD-4(b)": "congestion band on the replaced stretch",
        "NS-1(i)": "the 'driver arrived' element", "NS-1(ii)": "the 'free wait passed' element",
        "NS-1(iii)": "the 'driver messaged and called' element", "NS-1(iv)": "the 'driver stayed at the pickup' element",
        "FARE-0": "the fare build-up rule",
        "RD-1": "the shortest-route duty", "RD-2": "the extra-km refund rule",
        "RD-3": "the rider-stop rule", "RD-4": "the traffic-reason rule",
        "RD-5": "the notice-and-consent rule", "RD-6": "the repeat-offender flag rule",
        "RD-7": "the reminder after an uninformed reroute",
        "NS-0": "the who-cancelled rule", "NS-1": "the no-show-fee rule",
        "NS-2": "the false-arrival rule",
        "NS-3": "the driver-cancelled rule", "NS-4": "the 3-minute free-cancel window",
        "NS-8": "the driver-did-not-arrive rule", "NS-9": "the repeat rider no-show rule",
        "SURGE-1": "the surge notice rule", "SURGE-2": "the surge refund rule", "SURGE-3": "the surge differential rule",
        "DMG-1": "the damage-claim rule", "DMG-2": "the damage-photo rule", "DMG-3": "the damage-amount rule", "DMG-4": "the insufficient-damage-evidence rule",
        "SAFE-1": "the safety screen", "SAFE-2": "the accident-and-injury rule", "SAFE-3": "the AI-limits-in-safety rule",
        "SAFE-4": "the interim-suspension rule",
        "TH-1": "the by-amount review rule", "TH-2": "the by-category review rule", "TH-3": "the confidence rule", "TH-4": "the missing-records rule",
        "PREC-1": "the precedent rule",
    },
    # Data sentences that use a clause id as an adjective ("no SURGE-1 notice"): rewritten whole before ids are replaced,
    # so the result reads as a sentence and not as "no the surge notice rule notice".
    "phrases": [
        (r"\bevery NS-1 (?:condition|element) holds\b", "every condition of the no-show-fee rule holds"),
        (r"\bnot a SURGE-1 notice\b", "not a notice the surge notice rule accepts"),
        (r"\bno SURGE-1 notice\b", "no notice the surge notice rule accepts"),
        (r"\btrigger no RD-6 flag\b", "are not enough for a repeat-offender flag"),
        (r"\(SAFE-1 via type\)", "(a safety complaint always goes to a person)"),
        (r"\(RD-5: verbal notice needs the recording\)", "(a spoken agreement counts only with its recording)"),
        (r"\(RD-5 with a recording\)", "(on a recorded call)"),
        (r"\(merits: ([^)]*)\)", r"(the policy's answer: \1)"),
        # the scenario generator (data/synth/scenarios.py) still names this precedent by an old policy section number
        (r"\bPrecedent 7\.3 pattern\b", "the pattern of the official precedent DISP-2026-0211 (no-show cancel, zero contact)"),
    ],
    "words": [  # ruling labels and field names → plain words (order matters)
        (r"\brider_no_show\b", "'rider no-show'"), (r"\brider_notified\b", "'rider notified'"),
        (r"\brefund_partial\b", "partial refund"), (r"\brefund_full\b", "full refund"),
        (r"\bno_action\b", "no refund"), (r"\bfee_waived\b", "fee waived"), (r"\bescalate\b", "escalate to a human"),
        (r"\bflag_account\b", "account flag"), (r"\bdriver_arrived_at is null\b", "no arrival was ever recorded"),
        (r"\bF\d{1,3}, a fact that", "a fact that"), (r"\b(?:RD|NS|SAFE|FARE|SURGE|DMG|TH|PREC)-\d+, a clause that", "a clause that"), (r"\bcitin[g]? (?:a )?(?:RD|NS|SAFE|FARE|SURGE|DMG|TH|PREC)-\d+", "citing a made-up clause"),
        (r"\bF\d{1,3}\b", "a fact"),
    ],

    # Scenario families, tagged by hand per scenario name (data/bench/manifest.json `name`); a case can be in several.
    # Counts come from the manifest; build() stops if a name here is not in the manifest, and warns about an untagged case.
    "families": [
        ("What the rider agreed to: a general route choice, a named road, an acknowledged notice, an exclusion, a refusal or no answer",
         ["rd_port_trust_fastest", "rd_notice_ack_hmm", "rd_named_cn_am", "rd_consent_except_road", "rd_port_auntie_any_way",
          "bl_named_elsewhere", "rd_request_only", "rd_general_consent_jp", "rd_impatient_rider", "rd_two_segs_consent_seg1", "bl_negation"]),
        ("Agreement by phone: a logged call with no recording, a recorded call", ["rd_call_log_no_recording", "rd_recorded_call_consent"]),
        ("Chat in Chinese or Singlish",
         ["rd_notice_ack_hmm", "rd_named_cn_am", "rd_consent_except_road", "rd_port_auntie_any_way", "rd_general_consent_jp", "bl_negation",
          "ns_app_noshow_own_reason", "ns_impatient_driver"]),
        ("A stop the rider asked for", ["rd_stop_named_longer_way", "rd_stop_named_prior", "sg_mixed_rider_stop"]),
        ("Two detours on one trip, only one of them agreed", ["rd_two_segs_consent_seg1"]),
        ("Surge notice: complete, sent after pickup or just before it, free cancel already closed, a cancellation fee instead of free cancel, no revised fare, or no notice at all",
         ["sg_notice_estimate_above_charge", "sg_notified_full", "sg_notice_after_pickup", "sg_notice_no_cancel_option", "sg_port_notice_fare_unchanged",
          "sg_mixed_rider_stop", "sg_notice_just_before_pickup", "sg_over_50", "sg_port_notice_window_closed"]),
        ("Refund size: a mid-size refund the system decides, one large enough to go to a person", ["rd_long_loop_mid_amount", "sg_over_50"]),
        ("Waits, cancellations and notices close to a time limit",
         ["sg_notice_just_before_pickup", "sg_port_notice_window_closed", "ns_wait_5m10", "ns_wait_4m50", "bl_record_threshold_7m50",
          "ns_rider_cancel_200s", "ns_early_arrival_scheduled"]),
        ("The driver's contact attempts: messages but no call, no contact at all, a call only in the log",
         ["ns_wait_5m10", "ns_no_call", "ns_no_contact", "ns_driver_late_no_contact"]),
        ("Why the driver cancelled: a reason of his own, or the rider not coming",
         ["ns_app_noshow_own_reason", "ns_need_to_go_after_no_reply", "ns_driver_cancel_flat_tyre", "ns_impatient_driver", "ns_repeat_noshow_flag"]),
        ("Where the driver waited: a false 'I'm Here' tap far from the pickup, the other gate inside the arrival circle",
         ["ns_fake_here_far", "ns_gate_b_refused_to_move"]),
        ("Past disputes, earlier no-shows or a fraud flag on file",
         ["rd_named_cn_am", "rd_stop_named_prior", "rd_request_only", "rd_general_consent_jp", "sg_notified_full", "sg_notice_after_pickup",
          "sg_notice_no_cancel_option", "ns_no_call", "ns_repeat_noshow_flag", "ns_impatient_driver"]),
        ("Missing records: the GPS trace ends early, a hole in the trace during the wait", ["bl_gps_tail_missing", "bl_hole_in_wait"]),
        ("Threats and harassment, in the chat or in the complaint, and dangerous driving",
         ["rd_threat_in_chat", "sg_surge_unchanged_complaint_threat", "ns_safety_in_complaint", "ns_threat_in_chat", "safe_driver_threat",
          "safe_rider_threat", "safe_innocuous_chat_dangerous_driving", "safe_no_chat_harassment"]),
        ("Frustrated or impatient words that are not a safety matter", ["rd_impatient_rider", "ns_impatient_driver"]),
    ],
    "type_names": {"route_deviation": "Route deviation", "no_show": "No-show / cancellation fee", "fare_dispute": "Surge pricing", "safety": "Safety"},
    "arm_names": {"raw": "Raw LLM", "facts_only": "Facts only", "judge_only": "Judge + policy check", "court": "Court"},
    "arm_desc": {
        "raw": "the raw case JSON and the full policy text in one LLM call — what a plain chatbot does",
        "facts_only": "only the code-computed fact table in one call, no advocates, no verification",
        "judge_only": "fact table + policy certificate + the judge with one self-correction round — no advocates, no rebuttal",
        "court": "the full pipeline: fact table → two advocates + rebuttal → judge → certificate check",
    },

    # MVP checklist (handbook hard requirements). status: done | package (delivered with the submission, not on this page)
    "mvp": [
        {"req": "Three agents: Rider Advocate, Driver Advocate, Judge",
         "how": "Two advocate agents pull evidence through logged tools, write a brief and an append-only rebuttal; a "
                "tool-less judge answers only the questions the policy engine left open. Each is a separate role contract.",
         "where": [("Court feed (replay page)", "/replay.html?case=C-0001&phase=court")], "status": "done"},
        {"req": "Judge output: ruling + confidence + reasoning + recommended action (e.g. a partial refund amount)",
         "how": "Structured ruling with outcome, amount, model confidence, reasoning, cited facts and clauses, rejected "
                "claims, and a plain-language notice to each party.",
         "where": [("Ruling card", "/replay.html?case=C-0001&phase=court"), ("Reproducibility receipt", "/receipt.html?run=C-0001")], "status": "done"},
        {"req": "Evidence is text and structured data: GPS points, chat, fare lines, timestamps, both parties' history",
         "how": "Every synthetic case file carries a 5-second GPS trace (the organisers' samples have one point every {sample_gap}), the quoted route, chat, driver statement, fare breakdown, "
                "LTA traffic bands and incidents, weather and both profiles; code turns them into a numbered fact table.",
         "where": [("Fact table", "/facts.html?case=C-0001"), ("Case files", "/api/cases/C-0001")], "status": "done"},
        {"req": "At least two dispute types",
         "how": "{type_list}, plus safety, which always goes to a person — "
                "{n_demo} hand-built demo cases and {n_bench} benchmark cases.",
         "where": [("Demo cases", "/#watch"), ("Benchmark", "#accuracy")], "status": "done"},
        {"req": "Agent-to-agent communication must be observable",
         "how": "Every tool call, brief, rebuttal point, judge question and verifier check is an event streamed live "
                "(server-sent events) and replayed in the court feed with timestamps.",
         "where": [("Replay page (Run live needs a local copy with a DeepSeek key)", "/replay.html?case=C-0001")], "status": "done"},
        {"req": "Built with CodeBuddy (handbook requirement: conversation screenshots)",
         "how": "Developed in CodeBuddy; the conversation screenshots and a short development reflection are part of the submission package.",
         "where": [], "status": "package"},
    ],

    # Stretch modules (handbook stretch table). status: done | out
    "stretch": [
        {"name": "Precedent store", "flag": "STRETCH_PRECEDENT", "status": "done",
         "what": "Rulings are indexed; a new case retrieves similar past cases by fact values and the judge sees them as "
                 "context (never as evidence). A ruling that contradicts strong precedents raises a warning.",
         "where": [("Precedents", "/api/precedents")]},
        {"name": "Bad-faith signals", "flag": "STRETCH_FRAUD", "status": "done",
         "what": "Code-computed signals — arrival tap far from the pickup, waiting claim unsupported by GPS, jam claim "
                 "unsupported by traffic data, repeat offender — enter the fact table as citable facts.",
         "where": [("C-0004 with the screen on", "/replay.html?case=C-0004&run=C-0004~stretch&phase=court")]},
        {"name": "SLA routing and review queue", "flag": "STRETCH_SLA", "status": "done",
         "what": "Each ruling is routed: auto-resolve, 24-hour review, or urgent safety (2 h). Anything the certificate "
                 "cannot clear, any account action and any high signal goes to a human.",
         "where": [("Queue", "/api/queue")]},
        {"name": "Human feedback loop", "flag": "STRETCH_FEEDBACK", "status": "done",
         "what": "A reviewer's override is recorded, becomes a human-labelled precedent that outranks automatic ones, "
                 "and feeds an override-rate statistic per dispute type.",
         "where": [("Override endpoint", "/api/override")]},
        {"name": "Image forgery detection", "flag": None, "status": "out",
         "what": "Out of scope: there are no images in the data set (cleaning-fee claims are not covered).", "where": []},
    ],
    "caveats": [
        "Synthetic data: the {n_bench} benchmark cases are generated scenarios on real OneMap routes, not Ryde tickets, "
        "written by the developers.",
        "The reference answers follow the written policy, not the decisions of a human support team.",
        "All four systems on this page use the same AI model ({model}); a different model may give different results.",
    ],
    "gate_lead": ("The two single-call systems have no check of their own, so here the court's pre-execution policy check is "
                  "applied to their rulings afterwards. A ruling the check cannot clear goes to a person instead of executing."),
    "gate_raw_note": ("Raw LLM is never given the numbered facts, so its rulings cannot cite them and the check stops every one: "
                      "this row shows that the check needs cited facts, not how well it tells right rulings from wrong ones"),
    "gate_sentence": ("The check stops contradictions a machine can test; the hearing removes reading errors and raises the share "
                      "cleared automatically from {fo_auto} (facts only + check) to {ct_auto} (court). Judge + policy check alone is right or hands off on "
                      "{jo_safe}/{n} at about 1/{ratio} of the court's input tokens, but lets {jo_wrong} wrong decisions execute. {advocates_sentence}"),
    "method": [
        "Each benchmark scenario is written around one trap (a wait or a notice close to a time limit, a rider's agreement "
        "in Singlish or Chinese, a false arrival tap, a driver's own reason recorded as a no-show, frustrated words that are "
        "not a threat, a gap in the GPS trace). The "
        "reference answer is produced by running the policy engine on the scenario's own labels — what the rider meant, "
        "whether a message is a threat — and checking it against the trap the scenario was written for.",
        "The court's pre-execution check and the reference answers share that policy engine. A shared bug would therefore "
        "be invisible to this benchmark: the result is a policy-conformance test, not evidence that the written policy "
        "or its implementation is what a human ops team would decide.",
        "Raw LLM receives the case JSON with the GPS trace thinned to one point every {gps_s} s (native sampling {gps_native} s) "
        "to fit the context window; everything else is verbatim. It is never given fact ids, so it cannot cite them.",
        "All four systems use the same model with the same temperature settings.{extra_runs}",
    ],
    # One-line meaning for each metric row in the comparison table.
    "metric_meaning": {
        "safe_rate": "the case was decided right, or handed to a person for a reviewer to decide; only a wrong decision that executes counts against the system",
        "exact": "outcome, refund amount (to the cent) and hand-off decision all match the reference",
        "amount_1c_refund_cases": "amount within one cent, counting only cases where a refund was due (no-refund cases are excluded)",
        "ruling": "the outcome label (full refund / partial refund / no refund / escalate) matches",
        "amount_1c": "the refund amount is within one cent of the reference",
        "escalate": "the decision to hand the case to a human matches",
        "flag": "the account-flag recommendation matches",
        "f1": "macro F1 over the four outcome labels",
        "wrongful_refund_rate": "share of cases where no refund was due but one was granted",
        "missed_refund_rate": "share of cases where a refund was due but none was granted",
        "money_error_total": "sum of absolute refund errors across all cases",
        "wrong_executed": "core decision wrong and acted on with no person in the loop; Raw LLM and Facts only have no check, so every ruling they do not hand off executes",
        "human_review_rate": "share of cases handed to a human",
        "hallucination_rate": "rulings that pay money or cite evidence the record does not support: a refund where none is due, a refund amount the record does not give, or a fact or clause that does not exist",
        "cite_valid": "rulings whose every cited fact and clause actually exists",
        "swap_invariance": "same outcome after swapping the rider's and driver's identities and histories",
        "same_ruling_rate": "same outcome when the whole pipeline is run twice on the same case",
    },
}

# =====================================================================================================================
# Data loading (fail loudly)
# =====================================================================================================================


def is_arm_dir(p: Path) -> bool:
    """bench/results/<arm>[_swap] holds one json per run; other directories (audit_sample) are evidence, not runs."""
    return p.is_dir() and p.name.replace("_swap", "") in CONTENT["arm_names"]


def need(rel: str) -> Path:
    p = ROOT / rel
    if not p.exists():
        sys.exit(f"dashboard: missing required file {p}")
    return p


def jload(rel: str):
    with open(need(rel), encoding="utf-8") as f:
        return json.load(f)


def load_literal(rel: str, name: str):
    return load_dict_literal(rel, name)


def load_dict_literal(rel: str, name: str) -> dict:
    """Read a top-level `NAME = {...}` literal from a python source file without importing it."""
    tree = ast.parse(need(rel).read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in node.targets):
            return ast.literal_eval(node.value)
    sys.exit(f"dashboard: {name} not found in {rel}")


def policy_defaults(pol: str) -> int:
    """Rules Ryde has not published that the project sets itself: rows of the 'Rules Ryde has not specified' table
    (policy v3), or the older G1, G2 ... gap rows."""
    m = re.search(r"^##[^\n]*not specified[^\n]*\n(.*?)(?=^## |\Z)", pol, flags=re.M | re.S)
    if m:
        rows = [l for l in m.group(1).splitlines() if l.startswith("|") and not re.match(r"^\|[\s|:-]+\|$", l)]
        return max(0, len(rows) - 1)      # minus the header row
    return len(re.findall(r"^\| G\d+ \|", pol, flags=re.M))


def load_all() -> dict:
    d = {}
    d["summary"] = jload("bench/results/summary.json")
    for arm_m in d["summary"].values():   # swap / repeat runs are a second batch; until they are run their metrics read n/a
        for k, v in (("swap_invariance", None), ("same_ruling_rate", None), ("pass_all_repeats", None), ("repeats", 0), ("consistency_cases", 0), ("swap_cases", 0), ("swap_flips", [])):
            arm_m.setdefault(k, v)
    for arm in ("raw", "facts_only", "judge_only", "court"):
        if arm not in d["summary"]:
            sys.exit(f"dashboard: summary.json has no arm {arm}")
    d["gate"] = jload("bench/results/gate_ablation.json")
    if "arms" not in d["gate"]:
        sys.exit("dashboard: gate_ablation.json has no 'arms'")
    d["gps_thin"] = load_literal("bench/baseline.py", "GPS_THIN")
    d["manifest"] = jload("data/bench/manifest.json")
    # scenario definitions: count the `hard=` one-liners in the generator and cross-check with the manifest
    scen_src = need("data/synth/scenarios.py").read_text(encoding="utf-8")
    d["scenario_hard"] = re.findall(r'^\s*[A-Z]\("([a-z0-9_]+)".*?hard="([^"]*)"', scen_src, flags=re.M | re.S)
    # LLM runs: one *.json per run; *.record.json are side files
    runs = {}
    res = need("bench/results")
    for sub in sorted(p for p in res.iterdir() if is_arm_dir(p)):
        files = [p for p in sub.glob("*.json") if not p.name.endswith(".record.json")]
        base = [p for p in files if not re.search(r"\.r\d+\.json$", p.name)]
        runs[sub.name] = {"total": len(files), "base": len(base), "repeats": len(files) - len(base)}
    d["runs"] = runs
    models = set()
    for sub in res.iterdir():
        if is_arm_dir(sub):
            for p in list(sub.glob("B-0001*.json"))[:3]:
                if not p.name.endswith(".record.json"):
                    with open(p, encoding="utf-8") as f:
                        models.add(json.load(f).get("model", "?"))
    d["models"] = sorted(models)
    d["cases"] = {}
    for p in sorted(need("data/cases").glob("C-*.json")):     # every hand-built demo case on disk (C-0007 is the voice case)
        cid = p.stem
        d["cases"][cid] = {"case": read_case(p), "expected": jload(f"data/expected/{cid}.json")}
        need(f"web/shots/{cid}.png")
    # the organisers' sample cases (DISP-*): how far apart their GPS points are, for the evidence line on the page
    gaps = []
    for p in sorted(need("data/cases").glob("DISP-*.json")):
        ts = [dt.datetime.fromisoformat(g["ts"]) for g in read_case(p)["gps"]]
        gaps += [(b - a).total_seconds() for a, b in zip(ts, ts[1:])]
    lo, hi = (round(min(gaps) / 60), round(max(gaps) / 60)) if gaps else (0, 0)
    d["sample_gap"] = f"{lo} minutes" if lo == hi else f"{lo}–{hi} minutes"
    # court first run: did the judge's ruling match the reference core decision BEFORE verification, and what did the gate touch?
    truth = {c["case_id"]: c["truth"] for c in d["manifest"]["cases"]}
    first = sorted(p for p in (res / "court").glob("B-????.json"))
    core_ok, dropped = 0, 0
    for p in first:
        with open(p, encoding="utf-8") as f:
            j = json.load(f)
        t, pr = truth[j["case_id"]], j.get("pre_verify_ruling") or {}
        if pr.get("ruling") == t["ruling"] and abs((pr.get("amount") or 0) - (t.get("amount") or 0)) <= 0.01 \
                and bool(pr.get("escalate")) == bool(t["escalate"]):
            core_ok += 1
        dropped += sum(1 for line in j.get("verify_lines", []) if "dropped rejected_claims" in line)
    d["court_first_run"] = {"n": len(first), "core_ok": core_ok, "dropped_refs": dropped}
    g0 = d["cases"]["C-0001"]["case"]["gps"]
    t0, t1 = (dt.datetime.fromisoformat(g0[i]["ts"]) for i in (0, 1))
    d["gps_interval_s"] = (t1 - t0).total_seconds()
    d["inject"] = load_dict_literal("core/orchestrate.py", "INJECTIONS")
    d["counterfactual"] = load_dict_literal("core/counterfactual.py", "COUNTERFACTUALS")
    # stored tampered hearings of the demo case (runs/C-0001~<fault>.json): a fault counts as caught when the hearing
    # either went to a person or ended with the untampered hearing's outcome, amount and actions
    base_run = jload("runs/C-0001.json")
    sig = lambda r: ((r.get("ruling") or {}).get("ruling"), (r.get("ruling") or {}).get("amount"), bool((r.get("ruling") or {}).get("flag_account")),
                     sorted(a.get("type") for a in ((r.get("eligibility") or {}).get("actions") or [])))
    d["tampers"] = {}
    for p in sorted(need("runs").glob("C-0001~*.json")):
        fault = p.stem.split("~", 1)[1]
        if fault not in d["inject"] and fault != "prompt_injection":
            continue
        r = json.loads(p.read_text(encoding="utf-8"))
        d["tampers"][fault] = r.get("status") == "escalated" or sig(r) == sig(base_run)
    from core.policy import policy_clauses
    pol = need("policy/policy.md").read_text(encoding="utf-8")
    clauses = policy_clauses()
    d["policy"] = {
        "policy_clauses": len(clauses),
        "citable": sum(1 for v in clauses.values() if v),
        "informational": sum(1 for v in clauses.values() if not v),
        "gaps": policy_defaults(pol),
    }
    d["tests"] = sum(len(re.findall(r"^def test_", p.read_text(encoding="utf-8"), flags=re.M))
                     for p in need("tests").glob("test_*.py"))
    try:   # parametrised cases count as separate tests: prefer pytest's own count (the interpreter running this script)
        import subprocess
        out = subprocess.run([sys.executable, "-m", "pytest", "--collect-only", "-q", str(need("tests"))],
                             capture_output=True, text=True, timeout=60, cwd=ROOT).stdout
        m = re.search(r"(\d+) tests? collected", out)
        if m:
            d["tests"] = int(m.group(1))
    except Exception:
        pass
    need("web/architecture-system.png")
    return d


# =====================================================================================================================
# Text helpers
# =====================================================================================================================
_IDS = "RD|NS|SAFE|FARE|SURGE|DMG|TH|PREC"
_ID_RE = re.compile(rf"\b({_IDS})-(\d+)(?:\s*(?:element\s*)?\(([a-d]|[ivx]+)\))?")


def plain(text: str) -> str:
    """Translate clause ids / ruling labels / fact ids in data text into plain English."""
    def sub(m):
        key = f"{m.group(1)}-{m.group(2)}"
        if m.group(3):
            k2 = f"{key}({m.group(3)})"
            if k2 in CONTENT["clauses"]:
                return CONTENT["clauses"][k2]
        return CONTENT["clauses"].get(key, "a policy clause")
    out = text
    for pat, rep in CONTENT["phrases"]:
        out = re.sub(pat, rep, out)
    for pat, rep in CONTENT["words"]:
        if "(?:RD|" in pat:      # rules that mention ids must run before ids are replaced
            out = re.sub(pat, rep, out)
    out = re.sub(rf",?\s*\((?:{_IDS})-\d+(?:\([a-d]\))?(?:[,;/ ]+(?:{_IDS})-\d+(?:\([a-d]\))?)*\)", "", out)
    out = re.sub(rf",\s*(?:{_IDS})-\d+\)", ")", out)
    out = re.sub(r"\s*\(G\d{1,2}\)", "", out)
    out = re.sub(r"\bSAFE-2 escalate\b", "escalate (dangerous-driving rule)", out)
    out = _ID_RE.sub(sub, out)
    for pat, rep in CONTENT["words"]:
        out = re.sub(pat, rep, out)
    out = re.sub(r"\b(?:rd|ns|safe|sg|bl)_([a-z0-9_]+)\b", lambda m: "the '" + m.group(1).replace("_", " ") + "' scenario", out)
    out = re.sub(r"\bthe the\b", "the", out.replace(" -> ", " → "))
    return out


def esc(s) -> str:
    return html.escape(str(s), quote=True)


def pct(x, digits=1) -> str:
    if x is None:
        return "–"
    return f"{x * 100:.{digits}f}%"


def money(x) -> str:
    return "–" if x is None else f"${x:,.2f}"


def ruling_word(label: str) -> str:
    return {"refund_full": "full refund", "refund_partial": "partial refund", "no_action": "no refund",
            "escalate": "escalate", "fee_waived": "fee waived"}.get(label, (label or "–").replace("_", " "))


NUM_WORD = {1: "one", 2: "two", 3: "three", 4: "four", 5: "five", 6: "six"}


def type_list(types: list[str]) -> str:
    """'Route deviation, no-show / cancellation fee and surge pricing' from the dispute types in the manifest (safety apart)."""
    names = [CONTENT["type_names"].get(t, t.replace("_", " ")) for t in types if t != "safety"]
    names = [names[0]] + [n[:1].lower() + n[1:] for n in names[1:]] if names else []
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1] if names else ""


# =====================================================================================================================
# HTML pieces
# =====================================================================================================================
CSS = r"""
:root{--panel:rgba(13,17,25,.86);--shadow:0 10px 40px rgba(0,0,0,.45);--radius:14px;
--glow:radial-gradient(1100px 500px at 50% -10%,rgba(91,156,255,.14),transparent 60%)}
body.light{--bg:#f3f4f6;--panel:rgba(255,255,255,.92);--panel2:rgba(17,24,39,.04);--line:rgba(17,24,39,.10);
--ink:#111827;--ink2:#1f2937;--muted:#6b7280;--blue:#1a73e8;--amber:#d97706;--red:#dc2626;--green:#15803d;--purple:#7c3aed;
--shadow:0 10px 36px rgba(17,24,39,.12);--glow:radial-gradient(1100px 500px at 50% -10%,rgba(26,115,232,.10),transparent 60%)}
*{box-sizing:border-box}
html{scroll-behavior:smooth}
body{margin:0;background:var(--bg);background-image:var(--glow);color:var(--ink);font-family:var(--sans);font-size:15px;line-height:1.5;-webkit-font-smoothing:antialiased}
a{color:var(--blue);text-decoration:none}a:hover{text-decoration:underline}
.wrap{padding-bottom:80px}
.toolbar{position:absolute;right:0;top:38px;display:flex;gap:10px;align-items:center;font-size:12px;color:var(--muted)}
.toolbar button{white-space:nowrap;background:var(--panel2);color:var(--ink);border:1px solid var(--line);border-radius:999px;padding:6px 12px;font:600 12px var(--sans);cursor:pointer}
.hero{position:relative;padding:0 0 8px}
h1{font-size:40px;line-height:1.1;letter-spacing:-.02em;margin:34px 0 14px;font-weight:800}
.blurb{font-size:22px;font-weight:700;letter-spacing:-.01em;margin:-6px 0 10px;color:var(--ink)}
.method{font:500 13px var(--sans);color:var(--amber);background:rgba(245,181,68,.08);border:1px solid rgba(245,181,68,.3);border-radius:10px;padding:8px 14px;margin:16px 0 10px}
.chips.secondary .chip{color:var(--ink2)}
.pitch{font-size:19px;line-height:1.45;color:var(--ink2);max-width:900px;margin:0 0 22px}
.meta{font-size:12.5px;color:var(--muted);font-family:var(--mono);margin-bottom:22px}
.tiles{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:16px}
.tile{min-width:0;background:var(--panel);border:1px solid var(--line);border-radius:var(--radius);padding:18px 20px 16px;box-shadow:var(--shadow)}
.tile .n{font:700 44px/1 var(--mono);letter-spacing:-.03em;margin:4px 0 8px}
.tile .n small{font-size:18px;color:var(--muted);font-weight:600;margin-left:6px}
.tile .l{font-size:13px;font-weight:700;text-transform:uppercase;letter-spacing:.06em;color:var(--muted)}
.tile .m{font-size:13px;color:var(--ink2)}
.tile.green .n{color:var(--green)}.tile.blue .n{color:var(--blue)}.tile.amber .n{color:var(--amber)}.tile.purple .n{color:var(--purple)}.tile.red .n{color:var(--red)}
section.sec{margin-top:64px}
.sec > h2{display:flex;align-items:center;gap:12px;font-size:26px;letter-spacing:-.01em;margin:0 0 6px}
.sec > h2 .num{width:34px;height:34px;border-radius:10px;background:var(--panel2);border:1px solid var(--line);display:grid;place-items:center;font:700 15px var(--mono);color:var(--blue)}
.lead{color:var(--ink2);font-size:16px;max-width:900px;margin:0 0 20px}
.panel{min-width:0;background:var(--panel);border:1px solid var(--line);border-radius:var(--radius);padding:18px 20px;box-shadow:var(--shadow)}
.grid2{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px}
.grid3{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:16px}
.mt{margin-top:16px}
h3{font-size:15px;margin:0 0 10px;letter-spacing:.01em}
h3 .hint{font-weight:500;color:var(--muted);font-size:13px;margin-left:8px}
.muted{color:var(--muted)}.small{font-size:13px}
table.t{width:100%;border-collapse:collapse;font-size:13.5px}
table.t th,table.t td{padding:7px 10px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}
table.t th{font-size:11.5px;text-transform:uppercase;letter-spacing:.06em;color:var(--muted);font-weight:700}
table.t td.n,table.t th.n{text-align:right;font-family:var(--mono);white-space:nowrap}
table.t td.big{font:700 20px var(--mono)}
table.t tr.hl td{background:rgba(58,210,159,.07)}
.ok{color:var(--green);font-weight:700}.bad{color:var(--red);font-weight:700}.warn{color:var(--amber);font-weight:700}
.chips{display:flex;flex-wrap:wrap;gap:8px}
.chip{display:inline-flex;align-items:center;gap:7px;padding:5px 11px;border-radius:999px;border:1px solid var(--line);background:var(--panel2);font-size:12.5px;color:var(--ink2)}
.chip b{font-family:var(--mono);color:var(--ink);white-space:nowrap}
.chip.green{border-color:rgba(58,210,159,.4);color:var(--green)}.chip.amber{border-color:rgba(245,181,68,.4);color:var(--amber)}
.chip.red{border-color:rgba(255,92,92,.4);color:var(--red)}.chip.muted{color:var(--muted)}
.chip .dot{width:8px;height:8px;border-radius:50%;background:currentColor}
.cards{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:16px}
.card{min-width:0;background:var(--panel);border:1px solid var(--line);border-radius:var(--radius);overflow:hidden;box-shadow:var(--shadow);display:flex;flex-direction:column}
.card img{width:100%;aspect-ratio:1400/820;object-fit:cover;display:block;border-bottom:1px solid var(--line)}
.card .b{padding:14px 16px 16px;display:flex;flex-direction:column;gap:8px;flex:1}
.card .h{display:flex;align-items:center;gap:8px;flex-wrap:wrap}
.card .h b{font-family:var(--mono)}
.card .story{font-style:italic;color:var(--ink2);font-size:13.5px}
.card .ruling{font:700 16px var(--mono);margin-top:2px}
.card .ruling span{font:600 12px var(--sans);color:var(--muted);margin-left:6px}
.card .why{font-size:13px;color:var(--ink2)}
.card .links{margin-top:auto;display:flex;gap:12px;font-size:13px;font-weight:600;padding-top:6px}
.badge{display:inline-flex;align-items:center;padding:2px 9px;border-radius:999px;font-size:11px;font-weight:700;letter-spacing:.03em;border:1px solid var(--line);background:var(--panel2);color:var(--ink2);text-transform:uppercase}
.badge.amber{color:var(--amber);border-color:rgba(245,181,68,.35)}.badge.blue{color:var(--blue);border-color:rgba(91,156,255,.35)}.badge.red{color:var(--red);border-color:rgba(255,92,92,.35)}
.badge.green{color:var(--green);border-color:rgba(58,210,159,.35)}
.bars{width:100%;height:auto;display:block}
.bars text{font-family:var(--sans);fill:var(--ink2);font-size:11.5px}
.bars text.v{font-family:var(--mono);font-weight:700;fill:var(--ink)}
.bars text.lbl{font-size:12.5px;fill:var(--ink);font-weight:600}
.bars line{stroke:var(--line)}
.legend{display:flex;gap:16px;font-size:12.5px;color:var(--ink2);margin:4px 0 10px;flex-wrap:wrap}
.legend i{display:inline-block;width:12px;height:12px;border-radius:3px;vertical-align:-1px;margin-right:6px}
.cm{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px}
.cm .panel{overflow-x:auto}
.cm table{width:100%;border-collapse:collapse;font-size:12px;font-family:var(--mono)}
.cm th,.cm td{padding:5px 6px;border:1px solid var(--line);text-align:center}
.cm th{font-family:var(--sans);font-size:10.5px;text-transform:uppercase;letter-spacing:.04em;color:var(--muted);font-weight:700}
.cm th.r{text-align:left}
.cm td.diag{font-weight:700}
.bar{height:12px;border-radius:999px;background:var(--panel2);border:1px solid var(--line);overflow:hidden;margin:8px 0}
.bar i{display:block;height:100%;background:linear-gradient(90deg,var(--green),var(--blue))}
.stretch{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}
.stretch .it{background:var(--panel2);border:1px solid var(--line);border-radius:10px;padding:12px 14px}
.stretch .it .h{display:flex;align-items:center;justify-content:space-between;gap:8px;margin-bottom:4px}
.stretch .it .h b{font-size:14px}
.stretch .it p{margin:4px 0 0;font-size:13px;color:var(--ink2)}
ol.hl,ul.hl{padding-left:20px;margin:0}
ol.hl li,ul.hl li{margin:0 0 10px}
ol.hl b{display:block;font-size:14.5px}
.callout{border-left:3px solid var(--amber);background:rgba(245,181,68,.07);padding:12px 16px;border-radius:0 10px 10px 0}
.callout h3{color:var(--amber)}
details{border:1px solid var(--line);border-radius:10px;padding:10px 14px;background:var(--panel2)}
details summary{cursor:pointer;font-weight:700;font-size:14px}
details > *:not(summary){margin-top:10px}
.tip{border-bottom:1px dotted var(--muted);cursor:help}
.arch img{width:100%;height:auto;border-radius:12px;border:1px solid var(--line);display:block;background:#fff}
.foot{margin-top:56px;padding-top:18px;border-top:1px solid var(--line);font-size:13px;color:var(--muted);display:flex;gap:18px;flex-wrap:wrap}
.scroll{overflow-x:auto}
.scroll table.t td:first-child,.scroll table.t th:first-child{min-width:150px}
.scroll table.wide{min-width:760px}
table.t td.leak{min-width:260px}
.chip{max-width:100%}
.kv{display:grid;grid-template-columns:auto 1fr;gap:4px 14px;font-size:13.5px}
.kv b{font-family:var(--mono);font-weight:600;white-space:nowrap}
@media (max-width:1000px){.tiles{grid-template-columns:repeat(2,minmax(0,1fr))}.cards{grid-template-columns:repeat(2,minmax(0,1fr))}.grid3{grid-template-columns:1fr}.cm{grid-template-columns:1fr}}
@media (max-width:760px){.wrap{padding-bottom:60px}h1{font-size:30px}.blurb{font-size:18px}.pitch{font-size:17px}.tiles,.cards,.grid2,.stretch{grid-template-columns:1fr}
.tile .n{font-size:36px}section.sec{margin-top:44px}.sec > h2{font-size:22px}.kv{grid-template-columns:1fr}}
@media print{
body{--bg:#fff;--panel:#fff;--panel2:#f3f4f6;--line:#cfd4dc;--ink:#111;--ink2:#1f2937;--muted:#555;--blue:#1a4fa3;--amber:#b45309;--red:#b91c1c;--green:#15803d;--purple:#6d28d9;--shadow:none;--glow:none;font-size:12px}
.wrap{max-width:none;padding:0}.toolbar{display:none}section.sec{break-before:page;margin-top:0;padding-top:12px}
.tile,.panel,.card,details{break-inside:avoid}a{color:inherit}a[href]:after{content:""}.tile .n{font-size:34px}h1{font-size:30px}
.card img{aspect-ratio:1400/600}
}
"""

JS = r"""
(function(){
  if(AKINA_THEME.light)document.body.classList.add('light');
  document.getElementById('print').onclick=function(){window.print();};
  window.addEventListener('beforeprint',function(){document.querySelectorAll('details').forEach(function(d){d.open=true;});});
})();
"""


def bar_chart(groups: list[tuple[str, dict]], arms: list[str], fmt=lambda v: pct(v, 0), vmax=1.0) -> str:
    """Grouped horizontal bars. groups = [(label, {arm: value})]. Pure inline SVG, colours via CSS vars."""
    colors = {"raw": "var(--red)", "facts_only": "var(--amber)", "judge_only": "var(--purple)", "court": "var(--green)"}
    bh, gap, lab_w, val_w = 12, 3, 172, 46
    width = 540
    gh = len(arms) * (bh + gap) + 16
    height = len(groups) * gh + 6
    bar_w = width - lab_w - val_w - 10
    parts = [f'<svg class="bars" viewBox="0 0 {width} {height}" role="img" aria-label="comparison chart">']
    for gi, (label, vals) in enumerate(groups):
        y0 = gi * gh
        parts.append(f'<text class="lbl" x="0" y="{y0 + 13}">{esc(label)}</text>')
        for ai, arm in enumerate(arms):
            v = vals.get(arm)
            y = y0 + 18 + ai * (bh + gap)
            w = 0 if v is None else max(2, round(bar_w * min(v, vmax) / vmax))
            parts.append(f'<rect x="{lab_w}" y="{y}" width="{bar_w}" height="{bh}" rx="4" fill="var(--panel2)" stroke="var(--line)"/>')
            parts.append(f'<rect x="{lab_w}" y="{y}" width="{w}" height="{bh}" rx="4" fill="{colors[arm]}"/>')
            parts.append(f'<text class="v" x="{lab_w + bar_w + 8}" y="{y + 11}">{esc(fmt(v))}</text>')
    parts.append("</svg>")
    return "".join(parts)


def legend(arms) -> str:
    colors = {"raw": "var(--red)", "facts_only": "var(--amber)", "judge_only": "var(--purple)", "court": "var(--green)"}
    return '<div class="legend">' + "".join(
        f'<span><i style="background:{colors[a]}"></i>{esc(CONTENT["arm_names"][a])}</span>' for a in arms) + "</div>"


def confusion(arm: str, m: dict) -> str:
    cm = m["confusion"]
    labels = [l for l in ("refund_full", "refund_partial", "no_action", "escalate", "fee_waived")
              if any(cm.get(l, {}).values()) or any(cm[r].get(l, 0) for r in cm)]
    tot = sum(sum(r.values()) for r in cm.values()) or 1
    rows = [f'<h3>{esc(CONTENT["arm_names"][arm])}<span class="hint">rows = reference, columns = given</span></h3>',
            '<table><tr><th class="r"></th>' + "".join(f"<th>{esc(ruling_word(l))}</th>" for l in labels) + "</tr>"]
    for r in labels:
        cells = []
        for c in labels:
            v = cm.get(r, {}).get(c, 0)
            if v == 0:
                cells.append('<td class="muted">·</td>')
            else:
                col = "58,210,159" if r == c else "255,92,92"
                alpha = min(0.85, 0.15 + 0.7 * v / max(1, max(cm[r].values())))
                cls = ' class="diag"' if r == c else ""
                cells.append(f'<td{cls} style="background:rgba({col},{alpha:.2f})">{v}</td>')
        rows.append(f'<tr><th class="r">{esc(ruling_word(r))}</th>{"".join(cells)}</tr>')
    rows.append("</table>")
    return '<div class="panel">' + "".join(rows) + "</div>"


def chip(text: str, cls: str = "") -> str:
    return f'<span class="chip {cls}"><span class="dot"></span>{text}</span>'


# =====================================================================================================================
# Page
# =====================================================================================================================


PARTIAL = "--partial" in sys.argv     # smoke run on an incomplete batch: report the gaps, do not stop


def stop(msg: str) -> None:
    if PARTIAL:
        print(f"dashboard (partial run, page NOT publishable): {msg}", file=sys.stderr)
    else:
        sys.exit(f"dashboard: {msg}")


def build(d: dict) -> str:
    S = d["summary"]
    arms = ["raw", "facts_only", "judge_only", "court"]
    raw, fo, jo, ct = (S[a] for a in arms)
    man = d["manifest"]["cases"]
    n_bench = len(man)
    names = {c["name"] for c in man}           # scenarios.py also holds trial candidates and port bases: count the benchmark's own
    d["scenario_hard"] = [h for h in d["scenario_hard"] if h[0] in names]
    if n_bench != len(d["scenario_hard"]) and n_bench != len(names):
        stop(f"manifest has {n_bench} cases but scenarios.py defines {len(d['scenario_hard'])}")
    for a in arms:
        if S[a]["cases"] != n_bench:
            stop(f"summary arm {a} scored {S[a]['cases']} cases, manifest has {n_bench}")
    hard_by_id = {c["case_id"]: c for c in man}
    by_type = {}
    for c in man:
        by_type[c["type"]] = by_type.get(c["type"], 0) + 1
    runs = d["runs"]
    n_runs = sum(r["total"] for r in runs.values())
    n_calls = sum(json.loads(q.read_text(encoding="utf-8")).get("llm_calls", 0) for sub in need("bench/results").iterdir() if is_arm_dir(sub)
                  for q in sub.glob("*.json") if not q.name.endswith(".record.json"))
    n_base = sum(r["base"] for k, r in runs.items() if not k.endswith("_swap"))
    n_swap = sum(r["total"] for k, r in runs.items() if k.endswith("_swap"))
    n_rep = sum(r["repeats"] for r in runs.values())
    model = ", ".join(d["models"]) if d["models"] else "unknown"
    model_short = model.split(":")[-1]
    n_demo = len(d["cases"])
    pol = d["policy"]
    G = d["gate"]["arms"]
    for a in arms:
        if a not in G:
            sys.exit(f"dashboard: gate_ablation.json has no arm {a}")
        g = G[a]
        if g["n"] + len(g.get("failed_runs", [])) != n_bench or g["human_flow"] + g["auto"] != g["n"]:
            stop(f"gate_ablation.json {a} numbers do not add up")
        if g.get("failed_runs"):
            print(f"dashboard: {a} has {len(g['failed_runs'])} failed run(s) {g['failed_runs']}: re-run them (bench/run_bench.py --cases ... --arms {a}) before publishing", file=sys.stderr)
    tok_x = ct["input_tokens_mean"] / raw["input_tokens_mean"]
    lat_x = ct["latency_mean_s"] / raw["latency_mean_s"]
    jo_ratio = ct["input_tokens_mean"] / jo["input_tokens_mean"]
    ct_ok = sum(1 for v in ct["per_case"].values() if v["exact"])     # per-case count: a failed run is neither matched nor missed
    truth = {c["case_id"]: c["truth"] for c in man}

    def handed_off(g: dict) -> bool:
        return bool(g.get("escalate")) or g.get("ruling") == "escalate"

    # the two allowances in the reference (bench/report.py score): a hand-off is right where the reference accepts one
    # (escalate_ok), and an arm that checks its own confidence is scored on the policy's answer once the reading is settled
    # (merits) where the reference hands the case to a person only because that reading is unsettled
    allow = {a: {"handoff": sorted(cid for cid, s in S[a]["per_case"].items() if s["exact"] and handed_off(s["got"]) and not truth[cid].get("escalate")),
                 "settled": sorted(cid for cid, s in S[a]["per_case"].items() if s["exact"] and s["exp_class"] != truth[cid]["ruling"])}
             for a in arms}
    ct_flags_auto = sum(1 for s in ct["per_case"].values() if s["executed"] and s["got"].get("flag_account") and not handed_off(s["got"]))
    gps_s = d["gps_interval_s"] * d["gps_thin"]
    fill = dict(n_bench=n_bench, n_demo=n_demo, type_list=type_list(sorted(by_type, key=lambda t: -by_type[t])), n_inject=len(d["inject"]), n_cf=len(d["counterfactual"]),
                n_citable=pol["citable"], n_gaps=pol["gaps"], latency=f"{ct['latency_mean_s']:.0f}",
                manual=CONTENT["manual_handling"], model=model_short, tok_x=f"{tok_x:.0f}", lat_x=f"{lat_x:.0f}",
                gps_s=f"{gps_s:.0f}", gps_native=f"{d['gps_interval_s']:.0f}", sample_gap=d["sample_gap"])
    plural = lambda k, word: f"{k} {word}{'' if k == 1 else 's'}"
    # hero tile: how "right" is counted, every count from the per-case scores
    ct_handoff, ct_settled = allow["court"]["handoff"], allow["court"]["settled"]
    other_handoffs = n_bench - ct_ok - ct["wrong_executed"]       # handed to a person where the reference rules and does not accept a hand-off
    right_how = (f"How it is counted: a case is right when outcome, amount and hand-off match the policy-derived reference ({ct_ok} of {n_bench})."
                 + (f" Where the reference also accepts a hand-off, sending the case to a person counts as right: the court did that on "
                    f"{plural(len(ct_handoff), 'case')} instead of ruling." if ct_handoff else "")
                 + (f" Where the reference sends a case to a person only because a reading is unsettled, the court's ruling counts when it is the "
                    f"policy's answer once that reading is settled ({plural(len(ct_settled), 'case')})." if ct_settled else "")
                 + (f" {other_handoffs} more went to a person where the reference rules: not a wrong ruling, a reviewer decides." if other_handoffs else "")
                 + f" Only a wrong decision that executes counts against the court: {ct['wrong_executed']}.")
    # the "matched the reference" row: say which allowance produced how many of each system's matches
    allow_bits = []
    for a in arms:
        h, st = len(allow[a]["handoff"]), len(allow[a]["settled"])
        if h or st:
            allow_bits.append(CONTENT["arm_names"][a] + ": " + ", ".join(
                ([plural(h, "accepted hand-off")] if h else []) + ([f"{st} ruling{'' if st == 1 else 's'} on a settled reading"] if st else [])))
    exact_meaning = (CONTENT["metric_meaning"]["exact"] + "; a hand-off counts only where the reference accepts one, and where the reference hands a "
                     "case to a person only because a reading is unsettled, a ruling counts when it is the policy's answer once that reading is settled"
                     + (f" ({'; '.join(allow_bits)})" if allow_bits else ""))
    exact_label = "Matched the reference (a hand-off counts only where the reference accepts one)"
    # refund cases: the court is scored on the settled reading, which can move a case into or out of the refund count
    rc = {a: S[a]["refund_cases"] for a in arms}
    rc_major = max(set(rc.values()), key=list(rc.values()).count)
    rc_odd = [a for a in arms if rc[a] != rc_major]
    rc_label = (f"n={rc_major}" if not rc_odd else f"{rc_major} cases; " + ", ".join(f"{CONTENT['arm_names'][a]} {rc[a]}" for a in rc_odd))
    rc_note = ("" if not rc_odd else "; " + " and ".join(f"{CONTENT['arm_names'][a]} counts {rc[a]}" for a in rc_odd)
               + " because its rulings on settled readings are scored on the policy's answer, which changes which cases had a refund due")
    now = dt.datetime.now().astimezone().strftime("%Y-%m-%d %H:%M %Z")
    arm_th = "".join(f'<th class="n">{esc(CONTENT["arm_names"][a])}</th>' for a in arms)

    H = []
    A = H.append
    # ---------------------------------------------------------------- head + hero
    swap_chip = (f'<span class="chip"><b>{pct(ct["swap_invariance"], 0)}</b>identity-swap invariance <span class="muted">(plain LLM {pct(raw["swap_invariance"], 0)})</span></span>'
                 if ct["swap_invariance"] is not None else "")
    hal = {a: S[a].get("hallucination_rate") for a in arms}
    hal_chip = (f'<span class="chip"><b>{ct["hallucinations"]} / {ct["cases"]}</b>court rulings that pay money or cite evidence the record does not support '
                f'<span class="muted">(plain LLM {raw["hallucinations"]} / {raw["cases"]})</span></span>' if hal["court"] is not None and hal["raw"] is not None else "")
    repeat_chip = (f'<span class="chip"><b>{pct(ct["same_ruling_rate"], 0)}</b>same ruling on repeat</span>'
                   if ct["same_ruling_rate"] is not None else "")
    A(f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<script src="/theme.js"></script>
<link rel="stylesheet" href="/styles/base.css">
<title>{esc(CONTENT['title'])}</title>
<meta name="description" content="One-page results dashboard: mechanism, benchmark vs a plain LLM, demo cases, MVP status, data and method, stretch.">
<style>{CSS}details.more>summary{{cursor:pointer;font-weight:700;font-size:14px;padding:12px 16px;border:1px solid var(--line);border-radius:12px;background:var(--panel);list-style:none;display:flex;gap:10px;align-items:center}}details.more>summary::before{{content:"▸";color:var(--muted)}}details.more[open]>summary::before{{content:"▾"}}details.more[open]>summary{{margin-bottom:12px}}details.more>summary::-webkit-details-marker{{display:none}}</style></head><body><div class="wrap">
<header class="site">
  <a href="/" aria-label="Akina Court home"><img class="logo" src="/logo.svg" alt="" width="34" height="34"></a>
  <div class="ident"><div class="t">Akina Court</div><div class="s">Ryde Dispute Court · Tencent Cloud AI CAN DO IT Hackathon SG 2026 · Ryde track</div></div>
  <nav aria-label="Site"><a href="/">Home</a><a href="/#watch">Watch</a><a href="/facts.html?case=DISP-002">Facts</a><a href="/policy.html">Policy</a><a href="/ops.html">Ops</a><a href="/report.html">Results</a><button class="theme" type="button" aria-label="Switch colour theme">Light</button></nav>
</header>
<section class="hero">
<div class="toolbar"><button id="print" type="button">Print</button></div>
<h1>Results</h1>
<p class="blurb">{esc(CONTENT['blurb'])}</p>
<p class="pitch">{esc(CONTENT['pitch'])}</p>
<div class="tiles">
<div class="tile blue"><div class="l">Right, or handed to a person</div><div class="n">{n_bench - ct['wrong_executed']}<small>/ {n_bench}</small></div><div class="m">{esc(right_how)}</div></div>
<div class="tile purple"><div class="l">Auto-cleared</div><div class="n">{G['court']['auto']}<small>/ {n_bench}</small></div><div class="m"><b>{G['court']['wrong_and_executed']} wrong decision{"s" if G['court']['wrong_and_executed'] != 1 else ""} executed.</b> The other {n_bench - G['court']['auto']} went to a person.{f" The account actions proposed on {ct_flags_auto} of the {G['court']['auto']} auto-cleared cases also go to a person; only the refund or no-refund decision clears." if ct_flags_auto else ""}</div></div>
<div class="tile amber"><div class="l">Mean time per ruling</div><div class="n">{ct['latency_mean_s']:.1f}<small>s</small></div><div class="m">95% of cases are ruled within {ct['latency_p95_s']:.1f} s; a person takes {esc(CONTENT['manual_handling'])} today. Uses about {tok_x:.0f}× the input tokens and {lat_x:.0f}× the time of a single AI call.</div></div>
</div>
<p class="method">{esc(CONTENT['method_caveat'].format(**fill))}</p>
<div class="chips secondary">
<span class="chip"><b>{ct['invalid_citations'] + ct.get('invalid_fact_citations', 0)} / {ct['citations'] + ct.get('fact_citations', 0)}</b>invalid citations in court rulings, fact ids + clause ids <span class="muted">(plain LLM {raw['invalid_citations'] + raw.get('invalid_fact_citations', 0)} / {raw['citations'] + raw.get('fact_citations', 0)})</span></span>
{hal_chip}
{swap_chip}
{repeat_chip}
<span class="chip"><b>{n_runs}</b>case-system runs · <b>{n_calls:,}</b> model calls</span>
</div>
</section>""")

    # ---------------------------------------------------------------- 1. results & cost
    big = [
        ("Right, or handed to a person", {a: 1 - S[a]["wrong_executed_rate"] for a in arms}),
        (exact_label, {a: S[a]["exact"] for a in arms}),
        ("Outcome label correct", {a: S[a]["ruling"] for a in arms}),
        (f"Amount within one cent, refund cases ({rc_label})", {a: S[a]["amount_1c_refund_cases"] for a in arms}),
        ("Escalation decision correct", {a: S[a]["escalate"] for a in arms}),
        ("Account-flag decision correct", {a: S[a]["flag"] for a in arms}),
        ("Citations all valid", {a: S[a]["cite_valid"] for a in arms}),
    ]
    bad = [
        ("Wrongful refunds", {a: S[a]["wrongful_refund_rate"] for a in arms}),
        ("Missed refunds", {a: S[a]["missed_refund_rate"] for a in arms}),
        ("Core decision wrong and executed", {a: S[a]["wrong_executed_rate"] for a in arms}),
    ]
    if any(v is not None for v in hal.values()):
        bad.append(("Hallucinations: rulings that pay money or cite evidence the record does not support", hal))
    core_tip = esc(CONTENT["core_tip"])
    rows_spec = [
        ("Right, or handed to a person", "safe_rate", pct),
        ("Matched the reference", "exact", pct),
        ("Outcome label", "ruling", pct),
        ("Amount within one cent, all cases", "amount_1c", pct),
        (f"Amount within one cent, refund cases only ({rc_label})", "amount_1c_refund_cases", pct),
        ("Escalation decision", "escalate", pct), ("Account-flag decision", "flag", pct),
        ("Macro F1", "f1", pct),
        ("Wrongful refunds", "wrongful_refund_rate", pct), ("Missed refunds", "missed_refund_rate", pct),
        ("Total money error", "money_error_total", money),
        ("Core decision wrong and executed", "wrong_executed", lambda v: f"{v} cases"),
        ("Routed to a human", "human_review_rate", pct),
        ("Hallucinations", "hallucination_rate", pct),
        ("Citations all valid", "cite_valid", pct),
        ("Identity-swap invariance", "swap_invariance", pct),
        ("Same ruling on repeat", "same_ruling_rate", pct),
    ]
    mrows = []
    for label, key, f in rows_spec:
        if all((S[a]["macro"]["f1"] if key == "f1" else S[a].get(key)) is None for a in arms):
            continue   # not measured in this batch (swap / repeat): leave the row out rather than show n/a
        vals = []
        for a in arms:
            m = S[a]
            v = m["macro"]["f1"] if key == "f1" else m.get(key)
            vals.append(f'<td class="n">{esc(f(v))}</td>')
        lab = f'<span class="tip" title="{core_tip}">{esc(label)}</span>' if key in ("exact", "wrong_executed") else esc(label)
        meaning = {"exact": exact_meaning, "amount_1c_refund_cases": CONTENT["metric_meaning"][key] + rc_note}.get(key, CONTENT["metric_meaning"][key])
        mrows.append(f'<tr><td>{lab}<div class="small muted">{esc(meaning)}</div></td>{"".join(vals)}</tr>')
    def pr(a, cls):
        v = S[a]["per_class"].get(cls)
        return f'{pct(v.get("precision"), 0)} / {pct(v.get("recall"), 0)}' if v else "–"
    pc_classes = [cls for cls in ("refund_full", "refund_partial", "no_action", "fee_waived", "escalate")
                  if any((S[a]["per_class"].get(cls) or {}).get("support") for a in arms)]
    ref_n = {cls: sum(1 for t in truth.values() if t["ruling"] == cls) for cls in pc_classes}     # the reference's own count per outcome
    pc_rows = "".join(
        f'<tr><td>{esc(ruling_word(cls))}</td><td class="n">{ref_n[cls]}</td>'
        + "".join(f'<td class="n">{pr(a, cls)}</td>' for a in arms)
        + "</tr>" for cls in pc_classes)
    pc_odd = []        # systems whose cases per outcome differ from the reference's: their settled readings are scored on the policy's answer
    for a in arms:
        sup = {cls: (S[a]["per_class"].get(cls) or {}).get("support", 0) for cls in pc_classes}
        if sup != ref_n:
            pc_odd.append(f"{CONTENT['arm_names'][a]} is scored on the policy's answer in {plural(len(allow[a]['settled']), 'case')} the reference "
                          f"hands to a person only because a reading is unsettled, so its counts are "
                          + ", ".join(f"{ruling_word(cls)} {sup[cls]}" for cls in pc_classes if sup[cls]) + ".")
    pc_note = (" The cases column is the reference's count. " + " ".join(pc_odd)) if pc_odd else " The cases column is the reference's count."
    cost_rows = "".join(
        f'<tr><td>{esc(lbl)}</td>' + "".join(f'<td class="n">{esc(f(S[a]))}</td>' for a in arms) + "</tr>"
        for lbl, f in [
            ("Latency, mean", lambda m: f"{m['latency_mean_s']:.1f} s"),
            ("Latency, 95th percentile", lambda m: f"{m['latency_p95_s']:.1f} s"),
            ("Input tokens, mean", lambda m: f"{m['input_tokens_mean']:,.0f}"),
            ("Output tokens, mean", lambda m: f"{m['output_tokens_mean']:,.0f}"),
            ("Model calls per case", lambda m: f"{m['llm_calls_mean']:.1f}"),
            ("Errors / timeouts", lambda m: f"{m['errors']}"),
        ])
    # gate ablation table (new accounting: human flow = model escalated + blocked by gate)
    def case_tip(cid):
        c = hard_by_id.get(cid)
        return f'<li><span class="tip" title="{esc(c["name"])}">{esc(cid)}</span>: {esc(plain(c["hard"]))}</li>' if c else f"<li>{esc(cid)}</li>"
    grows, gnotes = [], []
    for a in arms:
        g = G[a]
        name = CONTENT["arm_names"][a] + (" + policy check" if a in ("raw", "facts_only") else "")
        blocked = "–" if g["blocked_by_gate"] is None else g["blocked_by_gate"]
        caught = [c["case_id"] for c in g["cases"] if c.get("core_wrong") and not c.get("auto")]
        leaked = [c["case_id"] for c in g["cases"] if c.get("wrong_and_executed")]
        note = ""
        if a == "raw":
            note = esc(CONTENT["gate_raw_note"])
        elif leaked:
            note = '<span>wrong and executed:</span><ul class="small">' + "".join(case_tip(x) for x in leaked) + "</ul>"
        elif caught:
            note = '<span>the wrong core decision was stopped by the check and sent to a person:</span><ul class="small">' + "".join(case_tip(x) for x in caught) + "</ul>"
        if note:
            gnotes.append(f"<li><b>{esc(name)}</b> — {note}</li>")
        wx = f'<span class="bad">{g["wrong_and_executed"]}</span>' if g["wrong_and_executed"] else f'<span class="ok">{g["wrong_and_executed"]}</span>'
        cls = ' class="hl"' if a == "court" else ""
        grows.append(f'<tr{cls}><td><b>{esc(name)}</b>{"<sup>" + str(len(gnotes)) + "</sup>" if note else ""}</td><td class="n">{g["core_wrong"]}</td><td class="n">{g["model_escalated"]}</td><td class="n">{blocked}</td>'
                     f'<td class="n">{g["human_flow"]} / {g["n"]} ({pct(g["human_rate"], 0)})</td><td class="n">{g["auto"]}</td><td class="n">{wx}</td></tr>')
    jo_wx, ct_wx = G["judge_only"]["wrong_and_executed"], G["court"]["wrong_and_executed"]
    gate_sentence = CONTENT["gate_sentence"].format(
        fo_auto=pct(G["facts_only"]["auto_rate"], 0), ct_auto=pct(G["court"]["auto_rate"], 0), jo_safe=n_bench - jo_wx, jo_wrong=jo_wx, n=n_bench,
        ratio=f"{jo_ratio:.0f}",
        advocates_sentence=(f"The two advocates take that to {n_bench - ct_wx}/{n_bench} with {ct_wx} wrong decision{'s' if ct_wx != 1 else ''} executed: each side states the "
                            f"policy ground of every open question, and a ruling against a reading both sides share goes back to the judge once for a second look; "
                            f"human review moves from {pct(G['judge_only']['human_rate'], 0)} to {pct(G['court']['human_rate'], 0)}."
                            if ct_wx < jo_wx else
                            f"The two advocates change human review from {pct(G['judge_only']['human_rate'], 0)} to {pct(G['court']['human_rate'], 0)}; their other value is the observable adversarial hearing the track requires."))
    # per-case table
    def outcome_txt(r: dict) -> str:
        """Outcome + amount (a $0.00 refund is shown, it is a real answer) + goodwill credit."""
        amt = r.get("amount")
        show_amt = amt is not None and (amt or r.get("ruling") in ("refund_full", "refund_partial", "fee_waived"))
        return (ruling_word(r.get("ruling")) + (f" {money(amt)}" if show_amt else "")
                + (f" + {money(r['goodwill_credit'])} goodwill credit" if r.get("goodwill_credit") else ""))
    pc = []
    for i, c in enumerate(man, 1):
        cid = c["case_id"]
        exp = c["truth"]
        exp_txt = outcome_txt(exp) + (" + flag" if exp.get("flag_account") else "")
        if exp.get("escalate_ok"):
            exp_txt += " (a hand-off to a person is also accepted)"
        if exp.get("merits"):
            exp_txt += f" (the policy's answer once the reading is settled: {outcome_txt(exp['merits'])})"
        cells = []
        for a in arms:
            s = S[a]["per_case"].get(cid)
            if s is None:
                cells.append('<td><span class="muted">run failed</span></td>')
                continue
            g = s["got"]
            got = outcome_txt(g)
            why = (" (accepted hand-off)" if cid in allow[a]["handoff"] else " (settled reading)" if cid in allow[a]["settled"] else "")
            mark = ('<span class="ok">✓</span>' if s["exact"] else '<span class="ok" title="handed to a person: not wrong, a reviewer decides">→ person</span>'
                    if handed_off(g) else '<span class="bad">✗</span>')
            why_html = f'<span class="small muted">{esc(why)}</span>' if why else ""
            cells.append(f"<td>{mark} {esc(got)}{why_html}</td>")
        pc.append(f'<tr><td class="n muted">{i}</td><td><span class="tip" title="{esc(cid)} · {esc(c["name"])}">{esc(plain(c["hard"]))}</span></td>'
                  f'<td>{esc(CONTENT["type_names"].get(c["type"], c["type"]))}</td><td>{esc(exp_txt)}</td>{"".join(cells)}</tr>')
    if ct["same_ruling_rate"] is not None:
        consistency_block = (f'<h3 class="mt">Consistency <span class="hint">court run {ct["repeats"]}× on all {ct["consistency_cases"]} cases</span></h3>'
                             f'<div class="tile" style="box-shadow:none"><div class="n" style="font-size:34px">{pct(ct["same_ruling_rate"], 0)}</div>'
                             f'<div class="m">same ruling on repeat across {ct["consistency_cases"]} cases; a disagreement between runs goes to a person, never to automatic execution.</div></div>')
    else:
        consistency_block = ""
    lbl_miss = [cid for cid, v in ct["per_case"].items() if not v.get("ruling", True)]
    lbl_handoff = [cid for cid in lbl_miss if ct["per_case"][cid].get("got_class") == "escalate"]
    one = len(lbl_miss) == 1
    accepted = all(truth[cid].get("escalate_ok") for cid in lbl_miss)
    label_note = ((f" The court's {len(lbl_miss)} miss{'' if one else 'es'} here {'is' if one else 'are'} not {'a wrong ruling' if one else 'wrong rulings'}: "
                   f"it found the record unclear and handed {'that case' if one else 'those cases'} to a person, where the reference rules "
                   f"{'it' if one else 'them'}" + (" but also accepts a hand-off." if accepted else "."))
                  if lbl_miss and len(lbl_handoff) == len(lbl_miss) else "")
    hal_note = (" <b>Hallucinations</b> = " + esc(CONTENT["metric_meaning"]["hallucination_rate"]) + "." if len(bad) > 3 else "")
    A(f"""<section class="sec first" id="accuracy"><h2><span class="num">1</span>Results and cost</h2>
<p class="lead">The same {n_bench} cases, four ways, one model. <b>Raw LLM</b>: {esc(CONTENT['arm_desc']['raw'])}. <b>Facts only</b>: {esc(CONTENT['arm_desc']['facts_only'])}. <b>Judge + policy check</b>: {esc(CONTENT['arm_desc']['judge_only'])}. <b>Court</b>: {esc(CONTENT['arm_desc']['court'])}. "Correct" throughout means "matches the reference derived from the written policy" (<a href="#method">data and method</a>).</p>
<div class="grid2">
<div class="panel"><h3>Higher is better</h3>{legend(arms)}{bar_chart([big[0], big[2]], arms)}
<p class="small muted"><b>Right, or handed to a person</b> = no wrong decision executed; a case sent to a person counts, a reviewer decides it. <b>Outcome label correct</b> = the kind of ruling matches the reference; the amount is checked separately.{label_note}</p></div>
<div class="panel"><h3>Lower is better</h3>{legend(arms)}{bar_chart([bad[0], bad[2]] + bad[3:], arms)}
<p class="small muted"><span class="tip" title="{core_tip}">Core decision</span> = outcome + amount + escalation; account flags and citations are excluded. Raw LLM and Facts only have no check, so every ruling they do not hand off counts as executed.{hal_note}</p>
{consistency_block}</div>
</div>
<div class="panel mt"><h3>Cost per case</h3><div class="scroll"><table class="t"><tr><th></th>{arm_th}</tr>{cost_rows}</table></div>
<p class="small muted">Trade-off: the full court averages {ct['latency_mean_s']:.1f} s and {ct['llm_calls_mean']:.0f} model calls per case, about {lat_x:.0f}× the latency and {tok_x:.0f}× the input tokens of one call, against {esc(CONTENT['manual_handling'])} of manual handling. Judge + policy check uses about 1/{jo_ratio:.0f} of the court's input tokens.</p></div>
<details class="mt more"><summary>More results — every metric, what the policy check prevents, precision / recall, confusion matrices, every case</summary>
<div class="grid2 mt"><div class="panel"><h3>All metrics, higher is better</h3>{legend(arms)}{bar_chart(big, arms)}</div><div class="panel"><h3>All metrics, lower is better</h3>{legend(arms)}{bar_chart(bad, arms)}</div></div>
<div class="panel mt"><h3>What the policy check prevents <span class="hint">applied afterwards to the single-call rulings, built into the other two; no extra model calls</span></h3>
<p class="small muted">{esc(CONTENT['gate_lead'])} To a person = rulings the model itself handed off + rulings the check stopped.</p>
<div class="scroll"><table class="t wide"><tr><th>System</th><th class="n"><span class="tip" title="{core_tip}">core decision wrong</span></th><th class="n">model handed off</th><th class="n">stopped by the check</th><th class="n">to a person</th><th class="n">auto-cleared</th><th class="n">wrong and executed</th></tr>{"".join(grows)}</table></div>
<ol class="hl small muted" style="margin:10px 0 0">{"".join(gnotes)}</ol>
<p class="small" style="margin:10px 0 0"><b>{esc(gate_sentence)}</b></p></div>
<div class="panel mt"><h3>All metrics</h3><div class="scroll"><table class="t"><tr><th>Metric</th>{arm_th}</tr>{"".join(mrows)}</table></div></div>
<div class="mt">
<div class="panel"><h3>Per outcome: precision / recall</h3><div class="scroll"><table class="t"><tr><th>Outcome</th><th class="n">cases</th>{arm_th}</tr>{pc_rows}</table></div>
<p class="small muted">Precision: of the cases given this outcome, how many should have been. Recall: of the cases that should have this outcome, how many got it.{esc(pc_note)}</p></div>
</div>
<h3 class="mt">Confusion matrices</h3><div class="cm">{"".join(confusion(a, S[a]) for a in arms)}</div>
<details class="mt"><summary>Per-case results — all {n_bench} cases, four systems (hover a scenario for its id)</summary>
<div class="scroll"><table class="t wide"><tr><th>#</th><th>Scenario (the trap)</th><th>Type</th><th>Reference</th>{"".join(f'<th>{esc(CONTENT["arm_names"][a])}</th>' for a in arms)}</tr>{"".join(pc)}</table></div></details>
</details>
</section>""")

    # ---------------------------------------------------------------- built: core + stretch, one compact list, no status board
    def links(where):
        return " · ".join(f'<a href="{esc(h)}">{esc(l)}</a>' for l, h in where if not h.startswith("/api/"))
    LABEL = {"Three agents": "Three agents", "Judge output": "Structured ruling and plain-language notices", "Evidence is": "Evidence from every source",
             "At least two": f"{NUM_WORD.get(len(by_type), len(by_type)).capitalize()} dispute types", "Agent-to-agent": "Every exchange on the record"}
    def label(req):
        return next((v for k, v in LABEL.items() if req.startswith(k)), req)
    core_items = "".join(f'<li><b>{esc(label(r["req"]))}.</b> {esc(r["how"].format(**fill))} {links(r["where"])}</li>'
                         for r in CONTENT["mvp"] if r["where"])
    stretch_items = "".join(f'<li><b>{esc(x["name"])}.</b> {esc(x["what"])} {links(x["where"])}</li>'
                            for x in CONTENT["stretch"] if x["status"] == "done")
    A(f"""<section class="sec" id="mvp"><h2><span class="num">2</span>What is built</h2>
<p class="lead">Three agents, {NUM_WORD.get(len(by_type), len(by_type))} dispute types, every exchange on the record; four additional safeguards on top.</p>
<div class="grid2">
<div class="panel"><h3>Core</h3><ul class="hl small">{core_items}</ul></div>
<div class="panel"><h3 id="stretch">Additional safeguards</h3><ul class="hl small">{stretch_items}</ul></div>
</div></section>""")

    # ---------------------------------------------------------------- 4. key features
    ct_safe, jo_safe, raw_safe = n_bench - ct["wrong_executed"], n_bench - jo["wrong_executed"], n_bench - raw["wrong_executed"]
    # what the stored tampered hearings show (runs/C-0001~<fault>.json); faults without a stored hearing are not claimed
    tamper_words = {"fake_fact": "a cited fact that does not exist", "unread_fact": "a fact the advocate never read", "fake_clause": "an invented clause",
                    "wrong_amount": "a changed amount", "flip_finding": "a flipped finding", "flag_text": "an account flag hidden in free text"}
    faults = [tamper_words.get(k, k.replace("_", " ")) for k in d["tampers"] if k != "prompt_injection"]
    n_caught = sum(d["tampers"].values())
    and_list = lambda xs: xs[0] if len(xs) == 1 else ", ".join(xs[:-1]) + " and " + xs[-1]
    tamper_sentence = ((f"Stored hearings of the demo case C-0001 put {plural(len(faults), 'deliberate fault')} into the AI's output ({and_list(faults)})"
                        + (" and a prompt injection into the chat" if "prompt_injection" in d["tampers"] else "") + ": "
                        + ("each was caught, and none led to an action the untampered hearing would not take." if n_caught == len(d["tampers"])
                           else f"{n_caught} of {len(d['tampers'])} were caught."))
                       if d["tampers"] else "")
    cites_total = ct["citations"] + ct.get("fact_citations", 0)
    cites_bad = ct["invalid_citations"] + ct.get("invalid_fact_citations", 0)
    features = [
        ("The policy runs before the model.",
         f"Ryde's dispute rules are compiled into executable predicates: on every case, code first decides which of the policy's "
         f"clauses apply, which fail and which need a reading, and the model speaks only inside that remaining space. A ruling rests on the written "
         f"policy, not on the model's memory of it, which removes the room for an invented rule at the source."),
        ("Every ruling is verified by code, and a change to what it rests on shows on its receipt.",
         f"The facts are computed by code from the GPS trace, the chat, the fare, traffic and weather records: numbered, identical on every run; the "
         f"advocates and the judge may cite only those numbers and the clause ids. Before anything executes, code checks the ruling item by item: "
         f"every cited id exists, the outcome is one the policy allows, the amount equals the policy formula to the cent, a consent message precedes "
         f"the detour it excuses. Each ruling carries a receipt with four fingerprints (case file, policy, code, model), so a change to the "
         f"case, the policy, the code or the model shows on the receipt. {tamper_sentence}"),
        ("The reasoning is fully transparent and the standard is documented.",
         f"Every tool call, brief, rebuttal, ruling, check and notice is a timestamped event, streamed live and replayable step by step on the map; "
         f"every citation opens the fact or the clause it points to. Across the benchmark the court made {cites_total} citations, {cites_bad} of them invalid."),
        ("Adversarial agents beat the same model alone.",
         f"Same model, same {n_bench} cases. The raw case file handed straight to the model: {raw_safe} of {n_bench} right or handed to a person, "
         f"{raw['wrong_executed']} wrong decisions executed. The judge with the code check but no advocates: {jo_safe} of {n_bench}, "
         f"{jo['wrong_executed']} wrong decisions executed. The full court (code facts, two advocates, judge, code check): {ct_safe} of {n_bench}, "
         f"{ct['wrong_executed']} wrong decision{'s' if ct['wrong_executed'] != 1 else ''} executed. The advocates add what a single judge lacks: "
         f"each side states the policy ground of every open question, and a ruling against a reading both sides share goes back to the judge once "
         f"for a second look."),
    ]
    stretch = json.loads((ROOT / "runs" / "C-0004~stretch.json").read_text())
    sig = [f for f in stretch["facts"]["facts"] if (f.get("value") or {}).get("signal")]
    sig_cited = sum(1 for f in sig if f["id"] in (stretch["ruling"].get("cited_facts") or []))
    features.append(
        ("Fraud is screened by code before anyone argues.",
         f"A bad-faith screen runs over the record before the advocates speak: an arrival tap far from the pickup, a waiting claim the GPS does not "
         f"show, a jam claim the traffic record does not support, a repeat offender on file. Each signal enters the fact table as a numbered fact with "
         f"the evidence it rests on, so the advocates and the judge can cite it and the audience can check it. On the no-show case C-0004 the screen "
         f"found {len(sig)} signals and the judge cited {sig_cited} of them; the ruling and the amount are the ones the bare court reached, and the "
         f"account action still goes to a person. The benchmark itself runs without the screen, so its figures are the bare court's."))
    feat_html = "".join(f"<li><b>{esc(t)}</b> {esc(b)}</li>" for t, b in features)
    resp = [
        "Safety complaints and account actions are never automated; a threat in the chat stops the court and the case goes to a person.",
        "Insufficient evidence is a formal finding: a GPS hole, a missing record or an agreement the record cannot tie to the road sends the case to a person, with what is missing named.",
        "The notices to rider and driver are plain language, and their amounts are checked by code against the final ruling.",
    ]
    resp_html = "".join(f"<li>{esc(r)}</li>" for r in resp)
    A(f"""<section class="sec" id="features"><h2><span class="num">3</span>Key features</h2>
<p class="lead">The AI argues; only verified policy executes.</p>
<ol class="hl">{feat_html}</ol>
<h3 class="mt">Responsible AI</h3>
<ul class="hl small">{resp_html}</ul>
</section>""")

    # ---------------------------------------------------------------- 5. data & method
    fam_rows, tagged = [], set()
    for label, members in CONTENT["families"]:
        missing = [m for m in members if m not in names]
        if missing:
            stop(f"scenario family {label!r} names scenarios not in the manifest: {missing}")
        n = sum(1 for c in man if c["name"] in members)
        tagged |= set(members)
        if n:
            fam_rows.append(f'<span class="chip"><b>{n}</b>{esc(label)}</span>')
    untagged = sorted(c["case_id"] for c in man if c["name"] not in tagged)
    if untagged:
        print(f"dashboard: cases in no scenario family (add them to CONTENT['families']): {untagged}", file=sys.stderr)
    type_chips = "".join(f'<span class="chip"><b>{by_type[t]}</b>{esc(CONTENT["type_names"].get(t, t))}</span>'
                         for t in sorted(by_type, key=lambda t: -by_type[t]))
    def rep_cell(r):   # the repeat-runs column only appears once repeat runs exist
        return f'<td class="n">{r["repeats"] or "–"}</td>' if n_rep else ""
    rep_th = '<th class="n">repeat runs</th>' if n_rep else ""
    rep_total = f'<td class="n">{n_rep}</td>' if n_rep else ""
    run_rows = "".join(
        f'<tr><td>{esc(CONTENT["arm_names"][k.replace("_swap", "")])}{" · identities swapped" if k.endswith("_swap") else ""}</td>'
        f'<td class="n">{r["base"]}</td>{rep_cell(r)}<td class="n">{r["total"]}</td></tr>'
        for k, r in runs.items())

    extra = ((" The court was additionally run with rider and driver identities swapped" if n_swap else "")
             + (" and a second time on every case" if n_rep and n_swap else (" The court was additionally run a second time on every case" if n_rep else ""))
             + ("." if (n_swap or n_rep) else ""))
    method = "".join(f"<li>{esc(p.format(**fill, extra_runs=extra))}</li>" for p in CONTENT["method"])
    A(f"""<section class="sec" id="method"><h2><span class="num">4</span>Data and method</h2>
<p class="lead">{n_bench} synthetic benchmark trips on real OneMap road geometry, each built around one trap a careless system would fall into, plus {n_demo} hand-built demo cases.</p>
<div class="callout mt"><h3>Caveats</h3><ul class="hl small" style="margin:0">{"".join(f"<li>{esc(c.format(**fill))}</li>" for c in CONTENT['caveats'])}</ul></div>
<details class="mt more"><summary>Where the data comes from, how the reference answers were made, and the runs behind every number</summary>
<div class="grid2 mt">
<div class="panel"><h3>{n_bench} benchmark cases by dispute type</h3><div class="chips">{type_chips}</div>
<h3 class="mt">Scenario families <span class="hint">a case can belong to several</span></h3><div class="chips">{"".join(fam_rows)}</div>
<h3 class="mt">{n_demo} demo cases</h3><p class="small">Hand-built on real OneMap routes with hand-checked reference rulings — the cases on the <a href="/#watch">start page</a>. {d['tests']} automated tests cover the fact tools, policy engine and stretch modules.</p></div>
<div class="panel"><h3>Model runs behind this page</h3>
<div class="scroll"><table class="t"><tr><th>System</th><th class="n">cases</th>{rep_th}<th class="n">runs</th></tr>{run_rows}
<tr class="hl"><td><b>Total</b></td><td class="n">{n_base}{f" + {n_swap} swapped" if n_swap else ""}</td>{rep_total}<td class="n big">{n_runs}</td></tr></table></div>
<p class="small muted">Four systems × {n_bench} cases = {n_base} base runs{f"; three of them re-run with rider and driver identities swapped = {n_swap}" if n_swap else ""}{f"; the court run a second time on every case for consistency = {n_rep}" if n_rep else ""}. One model throughout: {esc(model)}.</p></div>
</div>
<div class="panel mt"><h3>How the reference answers were made, and what the numbers can and cannot say</h3><ul class="hl small">{method}</ul></div>
</details>
</section>""")

    # ---------------------------------------------------------------- 7. footer
    A(f"""<div class="foot"><a href="/">Start here</a><a href="/replay.html?case=C-0001&mode=show">Showcase replay</a><a href="/replay.html?case=C-0001">Expert replay</a><a href="architecture-system.png">Architecture image</a></div>
</section>
</div><script>{JS}</script></body></html>""")
    return "\n".join(H)


def main() -> None:
    d = load_all()
    page = build(d)
    OUT.write_text(page, encoding="utf-8")
    ct = d["summary"]["court"]
    raw = d["summary"]["raw"]
    print(f"wrote {OUT} ({len(page) / 1024:.0f} kB)")
    print(f"hero: exact {ct['exact']:.3f} (raw {raw['exact']:.3f}) · wrong&executed {ct['wrong_executed']} (raw {raw['wrong_executed']}) · "
          f"invalid citations {ct['invalid_citations']}/{ct['citations']} (raw {raw['invalid_citations']}/{raw['citations']}) · "
          f"latency {ct['latency_mean_s']} s · runs {sum(r['total'] for r in d['runs'].values())}")


if __name__ == "__main__":
    main()
