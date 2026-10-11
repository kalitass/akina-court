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

# =====================================================================================================================
# HAND-WRITTEN CONTENT — everything that is NOT derivable from data lives here and nowhere else.
# =====================================================================================================================
FIRST_RESULTS_N = 49      # the set size when the four systems were first scored; a larger manifest adds a caveat on the page

CONTENT = {
    "title": "Akina Court — Results",
    "subtitle": "Multi-agent autonomous dispute resolution · Tencent Cloud Hackathon SG 2026 · Ryde track",
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
        "NS-1(i)": "the 'I'm Here tap' element", "NS-1(ii)": "the 'driver at the pickup' element",
        "NS-1(iii)": "the 'waited over 3 minutes' element",
        "RD-1": "the shortest-route duty", "RD-2": "the extra-km refund rule",
        "RD-3": "the rider-stop rule", "RD-4": "the road-incident rule",
        "RD-5": "the prior-consent rule (rider agreed to the route change beforehand)", "RD-6": "the repeat-offender flag rule",
        "NS-0": "the who-cancelled rule", "NS-1": "the driver-waited rule",
        "NS-2": "the failed-wait refund rule (fake I'm Here adds an account flag)",
        "NS-3": "the driver-cancelled rule", "NS-4": "the 3-minute free-cancel window",
        "NS-5": "advance-booking rule", "NS-6": "waiting-fee rule", "NS-7": "30-day dispute window",
        "NS-8": "no such Ryde rule",
        "FARE-1": "only published add-ons may be charged", "FARE-2": "toll overcharge", "FARE-3": "cleaning-fee rule",
        "SAFE-1": "the threat-or-harassment rule (as the judge reads it)", "SAFE-2": "the dangerous-driving rule", "SAFE-3": "the phantom-trip rule",
    },
    "words": [  # ruling labels and field names → plain words (order matters)
        (r"\brefund_partial\b", "partial refund"), (r"\brefund_full\b", "full refund"),
        (r"\bno_action\b", "no refund"), (r"\bfee_waived\b", "fee waived"), (r"\bescalate\b", "escalate to a human"),
        (r"\bflag_account\b", "account flag"), (r"\bdriver_arrived_at is null\b", "no arrival was ever recorded"),
        (r"\bF\d{1,3}, a fact that", "a fact that"), (r"\b(?:RD|NS|SAFE|FARE)-\d+, a clause that", "a clause that"), (r"\bcitin[g]? (?:a )?(?:RD|NS|SAFE|FARE)-\d+", "citing a made-up clause"),
        (r"\bF\d{1,3}\b", "a fact"),
    ],

    # Scenario families: label → regex over the scenario name (data/bench/manifest.json `name`). Counts come from data.
    "families": [
        ("Consent timing — before, after, never answered, out of scope", r"consent|request_only|scope_other"),
        ("Incident on the replaced stretch, decoy incident, late report", r"incident"),
        ("Congestion band alone, heavy rain", r"band"),
        ("Named vs unnamed rider stop", r"stop_"),
        ("Two detour segments", r"two_segs"),
        ("Fixed vs metered fare", r"fixed_fare"),
        ("Prior-dispute history and account flags", r"prior|bad_profile"),
        ("Second-level boundaries of the 3-minute rules", r"175s|185s|150s|200s|edge"),
        ("Fake 'I'm Here' taps far from the pickup", r"fake_here"),
        ("Driver statement contradicted by GPS", r"claims_5|no_here_tap|driver_waiting|180m|two_more"),
        ("Threats, harassment and a hint-word trap", r"threat|safe_|keyword"),
        ("No deviation at all / plain loops", r"no_deviation|basic|plain"),
    ],
    "type_names": {"route_deviation": "Route deviation", "no_show": "No-show / cancellation fee", "safety": "Safety"},
    "arm_names": {"raw": "Raw LLM", "facts_only": "Facts only", "judge_only": "Judge + certificate (no advocates)", "court": "Court"},
    "arm_desc": {
        "raw": "the raw case JSON and the full policy text in one LLM call — what a plain chatbot does",
        "facts_only": "only the code-computed fact table in one call, no advocates, no verification",
        "judge_only": "fact table + policy certificate + the judge with one self-correction round — no advocates, no rebuttal",
        "court": "the full pipeline: fact table → two advocates + rebuttal → judge → certificate check",
    },

    # What each demo case demonstrates (no numbers here — numbers come from data/expected and data/cases).
    "demo": {
        "C-0001": "Two detours. The first is excused twice over — a reported accident on the original road and the rider's "
                  "prior agreement to go round. The second, a 7-Eleven far off the route, is not covered by 'a 7-Eleven on "
                  "the way', so only that segment is refunded. The policy engine settles everything else; the judge decides "
                  "one question: did the agreement cover the second detour?",
        "C-0002": "One unexplained detour: no chat, no incident, free-flowing traffic. Refund, plus an account flag because "
                  "the driver is a repeat offender. The refund executes automatically; the account action goes to a human "
                  "queue — money can be automatic, punishment needs a person.",
        "C-0003": "The detour is fully explained: a lane closure on the original expressway and the rider's agreement "
                  "before the turn. No refund. The system says no when the records say no.",
        "C-0004": "The driver tapped 'I'm Here' while parked hundreds of metres from the pickup, never came within the "
                  "arrival radius, then cancelled the rider as a no-show. Full refund plus an account flag for a false "
                  "arrival tap — a bad-faith signal computed from GPS, not guessed by the model.",
        "C-0005": "The rider cancelled long after the 3-minute free window while the driver was waiting at the pickup. "
                  "The fee stands: 'two more minutes' is sympathy, not a clause. The counterfactual control flips this "
                  "case exactly at the boundary (179 s vs 181 s).",
        "C-0006": "The driver threatened to lock the rider in. Safety cases are never auto-ruled: the judge writes a "
                  "fact summary only and the case is escalated to a human.",
    },

    # MVP checklist (handbook hard requirements). status: done | package (delivered with the submission, not on this page)
    "mvp": [
        {"req": "Three agents: Rider Advocate, Driver Advocate, Judge",
         "how": "Two advocate agents pull evidence through logged tools, write a brief and an append-only rebuttal; a "
                "tool-less judge answers only the questions the policy engine left open. Each is a separate role contract.",
         "where": [("Court feed (replay page)", "/replay.html?case=C-0001&phase=court"), ("Court UI", "/court.html")], "status": "done"},
        {"req": "Judge output: ruling + confidence + reasoning + recommended action (e.g. a partial refund amount)",
         "how": "Structured ruling with outcome, amount, model confidence, reasoning, cited facts and clauses, rejected "
                "claims, and a plain-language notice to each party.",
         "where": [("Ruling card", "/replay.html?case=C-0001&phase=court"), ("Reproducibility receipt", "/receipt.html?run=C-0001")], "status": "done"},
        {"req": "Evidence is text and structured data: GPS points, chat, fare lines, timestamps, both parties' history",
         "how": "Every synthetic case file carries a 5-second GPS trace (the organisers' sample is sampled every 3 minutes), the quoted route, chat, driver statement, fare breakdown, "
                "LTA traffic bands and incidents, weather and both profiles; code turns them into a numbered fact table.",
         "where": [("Fact table", "/facts.html?case=C-0001"), ("Case files", "/api/cases/C-0001")], "status": "done"},
        {"req": "At least two dispute types",
         "how": "Route deviation and no-show / cancellation fee, plus safety as a third (escalation-only) type — "
                "{n_demo} hand-built demo cases and {n_bench} benchmark cases cover all three.",
         "where": [("Demo cases", "/#watch"), ("Benchmark", "#accuracy")], "status": "done"},
        {"req": "Agent-to-agent communication must be observable",
         "how": "Every tool call, brief, rebuttal point, judge question and verifier check is an event streamed live "
                "(server-sent events) and replayed in the court feed with timestamps.",
         "where": [("Replay page (Run live needs a local copy with a DeepSeek key)", "/replay.html?case=C-0001"), ("Court UI", "/court.html")], "status": "done"},
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
         "where": [("C-0004 facts", "/replay.html?case=C-0004")]},
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
    "extra_stretch": [
        ("Policy execution certificate", "Every clause runs as code (pass / fail / left to the judge); the certificate fixes "
                                         "the allowed outcomes and the refund formula before the judge speaks."),
        ("Live fault injection", "{n_inject} switchable faults — hallucinated evidence, an unread fact, a made-up clause, a "
                                 "wrong amount, a flipped finding — each caught by a different gate in front of the audience."),
        ("Counterfactual audit", "{n_cf} one-click variants: swap or erase histories, heavy rain, prompt injection (outcome must "
                                 "not change); cancel at 179 s vs 181 s, delete the consent message, fixed fare (outcome "
                                 "must flip exactly as the policy says)."),
        ("Prompt-injection test", "A chat message telling the AI to ignore the policy and refund $99 — evidence is data, the "
                                  "outcome does not move."),
        ("Reproducibility receipt", "Every ruling ships with case, policy and code hashes, model, fact ids and certificate, "
                                    "plus an appeal path."),
        ("Four-system benchmark harness", "Raw LLM vs facts-only vs judge-only vs court on the same {n_bench} cases, with identity-swap and "
                                        "repeat runs — this page is generated from its output."),
    ],

    # Highlights in plain English. {placeholders} are filled from data.
    "highlights": [
        ("Facts are computed by code, arguments are written by the model",
         "The agents can only cite numbered facts from a table that pure code produced; the same case gives the same "
         "facts every time."),
        ("Citation firewall",
         "A claim that cites a fact that does not exist — or one the advocate never read — is voided on the record. A "
         "judge citing a non-existent clause is sent back to correct itself once."),
        ("The policy itself runs as code",
         "Every clause is a predicate: pass, fail, or left to the judge. The resulting certificate fixes the allowed "
         "outcomes and the refund formula; a ruling outside them, or off by more than a cent, is never executed."),
        ("Live fault injection",
         "Make an advocate hallucinate evidence or the judge get the amount wrong, in front of the judges, and watch "
         "each gate catch it."),
        ("Counterfactual audit",
         "Swap the parties' histories, erase them, add heavy rain: nothing changes. Move a cancellation from 179 s to "
         "181 s: the outcome flips exactly at the 3-minute rule."),
        ("Observable adversarial process",
         "Both advocates pull evidence through logged tools, build a brief and rebut point by point (append-only); "
         "every tool call is one line in the court feed."),
        ("Every policy clause has a source",
         "{n_citable} citable clauses trace to Ryde's own terms or LTA regulation; {n_gaps} rules Ryde has not published "
         "are listed as open gaps instead of being invented; the court's own procedure is code, never a citable clause."),
        ("Real road network, real map",
         "OneMap routes and LTA speed bands; detour segments coloured on the map, the 200 m arrival circle, where the "
         "car was when each message was sent — one timeline for chat, taps and detours."),
        ("Safety cases are never auto-ruled",
         "A threat in chat forces escalation with a fact summary, regardless of confidence."),
        ("Measurable value",
         "A ruling in about {latency} seconds instead of {manual}, and every automatic action carries a receipt that "
         "lets anyone reproduce it."),
    ],
    "review": [   # what three rounds of adversarial review flagged and what changed
        "Round 1 flagged the confidence add/subtract score as arithmetic without statistical basis that judges would "
        "challenge. It was removed; automation eligibility now comes from the policy certificate and confidence is "
        "diagnostic only.",
        "Round 1 found that advocates could rewrite briefs and cite facts they had never read. Briefs are now immutable, "
        "rebuttals append-only, only tool-read facts may be cited, and every model stage has a timeout that falls back to "
        "human review.",
        "Round 2 showed the arrival test used whole-trip proximity rather than position at the moment of the tap, and that "
        "the judge was being asked questions the code had already settled. Fact tools now measure distance at tap time and "
        "time in radius after it; settled sub-questions no longer reach the judge.",
        "Round 2 asked for a 'what would change this ruling' line, a reproducibility receipt, a prompt-injection "
        "experiment and separate auto / human action channels — all four shipped. Its two 'eye-catching' suggestions "
        "became the fault-injection and counterfactual demo controls.",
        "Round 3 challenged the benchmark headline: the reference answers and the court's gate share the policy engine, "
        "so a perfect score is policy conformance, not accuracy. The headline became the fair one-call comparison, metrics "
        "were renamed and defined, a refund-cases-only amount metric and a judge-only arm were added, and the gate "
        "ablation was recounted to include rulings the model itself escalated.",
    ],
    "caveats": [
        "Synthetic data: the {n_bench} benchmark cases are generated scenarios on real OneMap routes, not Ryde tickets, "
        "written by the developers.",
        "Reference answers are derived from the policy engine plus scenario labels. 'Correct' "
        "therefore means 'agrees with the written policy', not 'agrees with a human ops team'.",
        "One model ({model}) for all four arms; results may differ with other models.",
        "{n_bench} cases is a small set and the scenarios are related; one case moves a percentage by about two points.",
        "The court costs roughly {tok_x}× the input tokens and {lat_x}× the latency of a single call — still seconds, "
        "against {manual} of manual handling.",
    ],
    "arch_caption": (
        "Raw evidence — GPS trace, chat, fare lines, timestamps, both profiles, the OneMap route and LTA traffic — first "
        "passes through pure code: fact tools produce a numbered fact table and the policy engine runs every clause as a "
        "predicate. Two advocates then pull facts through logged tools, write briefs and rebuttals, and a tool-less judge "
        "answers only the questions the code left open. A verifier checks every citation and compares the ruling with the "
        "certificate: only a matching ruling is cleared for automatic execution; everything else goes to the review queue, and "
        "every outcome carries a reproducibility receipt."),
    "gate_lead": ("Offline ablation: the policy-certificate gate applied to the single-call systems' own rulings. A ruling "
                  "the certificate cannot clear is sent to a human instead of executed."),
    "gate_raw_note": ("the raw arm never sees fact ids, so the citation rule blocks everything: this row shows an interface "
                      "requirement, not the gate's discriminative power"),
    "gate_sentence": ("The gate catches contradictions a machine can check; the structured hearing removes semantic errors "
                      "and restores automatic coverage from {fo_auto} to {ct_auto}. Judge + certificate alone is right or hands off on "
                      "{jo_safe}/{n} at about 1/{ratio} of the court's token cost, but lets {jo_wrong} wrong decisions execute. {advocates_sentence}"),
    "method": [
        "Each benchmark scenario is written around one trap (a timestamp just before or after a rule boundary, a decoy "
        "incident, an unnamed stop, a fake arrival tap, an ordinary pickup message that contains a threat hint word). The "
        "reference answer is produced by running the policy engine on the scenario's own labels — what the rider meant, "
        "whether a message is a threat — and checking it against the trap the scenario was written for.",
        "The court's certificate gate and the reference answers share that policy engine. A shared bug would therefore "
        "be invisible to this benchmark: the result is a policy-conformance test, not evidence that the written policy "
        "or its implementation is what a human ops team would decide.",
        "Raw LLM receives the case JSON with the GPS trace thinned to one point every {gps_s} s (native sampling {gps_native} s) "
        "to fit the context window; everything else is verbatim. It is never given fact ids, so it cannot cite them.",
        "All four systems use the same model with the same temperature settings.{extra_runs}",
    ],
    # One-line meaning for each metric row in the comparison table.
    "metric_meaning": {
        "safe_rate": "the case was decided right, or handed to a person for a reviewer to decide; only a wrong decision that executes counts against the system",
        "exact": "outcome, refund amount (to the cent) and escalation decision all match the reference",
        "amount_1c_refund_cases": "amount within one cent, counting only cases where a refund was due (no-refund cases are excluded)",
        "ruling": "the outcome label (full refund / partial refund / no refund / escalate) matches",
        "amount_1c": "the refund amount is within one cent of the reference",
        "escalate": "the decision to hand the case to a human matches",
        "flag": "the account-flag recommendation matches",
        "f1": "macro F1 over the four outcome labels",
        "wrongful_refund_rate": "share of cases where no refund was due but one was granted",
        "missed_refund_rate": "share of cases where a refund was due but none was granted",
        "money_error_total": "sum of absolute refund errors across all cases",
        "wrong_executed": "core decision wrong and acted on with no human in the loop; raw and facts-only have no gate",
        "human_review_rate": "share of cases handed to a human",
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
    scen_src = scen_src.split("BLIND_SCENARIOS = [")[0]      # the held-out set has its own manifest and is not part of this page
    d["scenario_hard"] = re.findall(r'^\s*[RNS]\("([a-z0-9_]+)".*?hard="([^"]*)"', scen_src, flags=re.M | re.S)
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
    for n in range(1, 7):
        cid = f"C-000{n}"
        d["cases"][cid] = {"case": jload(f"data/cases/{cid}.json"), "expected": jload(f"data/expected/{cid}.json")}
        need(f"web/shots/{cid}.png")
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
    pol = need("policy/policy.md").read_text(encoding="utf-8")
    heads = re.findall(r"^\*\*((?:RD|NS|FARE|SAFE)-\d+)\*\*(（不可引用)?", pol, flags=re.M)
    d["policy"] = {
        "policy_clauses": len(heads),
        "citable": sum(1 for h, inf in heads if not inf),
        "informational": sum(1 for h, inf in heads if inf),
        "gaps": len(re.findall(r"^\| G\d+ \|", pol, flags=re.M)),
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
_ID_RE = re.compile(r"\b(RD|NS|SAFE|FARE)-(\d+)(?:\s*(?:element\s*)?\(([a-c]|[ivx]+)\))?")


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
    for pat, rep in CONTENT["words"]:
        if re.search(r"RD\||NS\||\(\?:RD", pat):      # rules that mention ids must run before ids are replaced
            out = re.sub(pat, rep, out)
    out = re.sub(r",?\s*\((?:RD|NS|SAFE|FARE)-\d+(?:\([a-c]\))?(?:[,;/ ]+(?:RD|NS|SAFE|FARE)-\d+(?:\([a-c]\))?)*\)", "", out)
    out = re.sub(r",\s*(?:RD|NS|SAFE|FARE)-\d+\)", ")", out)
    out = re.sub(r"\bSAFE-2 escalate\b", "escalate (dangerous-driving rule)", out)
    out = _ID_RE.sub(sub, out)
    for pat, rep in CONTENT["words"]:
        out = re.sub(pat, rep, out)
    out = re.sub(r"\b(?:rd|ns|safe)_([a-z0-9_]+)\b", lambda m: "the '" + m.group(1).replace("_", " ") + "' scenario", out)
    out = re.sub(r"\bthe the\b", "the", out.replace(" -> ", " → "))
    return out


def esc(s) -> str:
    return html.escape(str(s), quote=True)


def pct(x, digits=1) -> str:
    if x is None:
        return "n/a"
    return f"{x * 100:.{digits}f}%"


def money(x) -> str:
    return "–" if x is None else f"${x:,.2f}"


def ruling_word(label: str) -> str:
    return {"refund_full": "full refund", "refund_partial": "partial refund", "no_action": "no refund",
            "escalate": "escalate", "fee_waived": "fee waived"}.get(label, label or "–")


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


def blind_numbers() -> dict | None:
    """Held-out set figures (bench/results/blind): per arm, cases decided exactly right and wrong decisions executed."""
    import blind_report
    man = ROOT / "data" / "bench" / "blind" / "manifest.json"
    res = ROOT / "bench" / "results" / "blind"
    if not man.exists() or not res.exists():
        return None
    truth = {c["case_id"]: c["truth"] for c in json.loads(man.read_text(encoding="utf-8"))["cases"]}
    out = {"cases": len(truth)}
    for arm in sorted(p.name for p in res.iterdir() if p.is_dir()):
        files = [f for f in sorted((res / arm).glob("X-*.json")) if not f.name.endswith(".record.json") and ".r" not in f.name[6:]]
        if not files:
            continue
        ok = wrong = 0
        for f in files:
            rec = json.loads(f.read_text(encoding="utf-8")); t = truth[rec["case_id"]]; ru = rec.get("ruling") or {}
            if not rec.get("ok"):
                continue
            if blind_report.exact(ru, t):
                ok += 1
            elif not ru.get("escalate"):
                wrong += 1
        out[arm] = {"exact": ok, "wrong_executed": wrong}
    return out


def build(d: dict) -> str:
    S = d["summary"]
    arms = ["raw", "facts_only", "judge_only", "court"]
    raw, fo, jo, ct = (S[a] for a in arms)
    man = d["manifest"]["cases"]
    n_bench = len(man)
    if n_bench > FIRST_RESULTS_N and not any("extended" in c for c in CONTENT["caveats"]):
        CONTENT["caveats"].append(f"The benchmark set was extended from {FIRST_RESULTS_N} to {n_bench} cases on 2026-10-11, after the first four-system "
                                  "results had been seen; the added cases were written from the policy and the record like the others, every one that "
                                  "passed the generator's gates was kept, but they are not held-out. The held-out set is scored separately.")
    if n_bench != len(d["scenario_hard"]):
        sys.exit(f"dashboard: manifest has {n_bench} cases but scenarios.py defines {len(d['scenario_hard'])}")
    for a in arms:
        if S[a]["cases"] != n_bench:
            sys.exit(f"dashboard: summary arm {a} scored {S[a]['cases']} cases, manifest has {n_bench}")
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
            sys.exit(f"dashboard: gate_ablation.json {a} numbers do not add up")
        if g.get("failed_runs"):
            print(f"dashboard: {a} has {len(g['failed_runs'])} failed run(s) {g['failed_runs']}: re-run them (bench/run_bench.py --cases ... --arms {a}) before publishing", file=sys.stderr)
    tok_x = ct["input_tokens_mean"] / raw["input_tokens_mean"]
    lat_x = ct["latency_mean_s"] / raw["latency_mean_s"]
    jo_ratio = ct["input_tokens_mean"] / jo["input_tokens_mean"]
    lift_pp = 100 * (fo["exact"] - raw["exact"])
    ct_ok = sum(1 for v in ct["per_case"].values() if v["exact"])     # per-case count: a failed run is neither matched nor missed
    jo_ok = G["judge_only"]["n"] - G["judge_only"]["core_wrong"]
    pre = d["court_first_run"]
    gps_s = d["gps_interval_s"] * d["gps_thin"]
    fill = dict(n_bench=n_bench, n_demo=n_demo, n_inject=len(d["inject"]), n_cf=len(d["counterfactual"]),
                n_citable=pol["citable"], n_gaps=pol["gaps"], latency=f"{ct['latency_mean_s']:.0f}",
                manual=CONTENT["manual_handling"], model=model_short, tok_x=f"{tok_x:.0f}", lat_x=f"{lat_x:.0f}",
                gps_s=f"{gps_s:.0f}", gps_native=f"{d['gps_interval_s']:.0f}")
    now = dt.datetime.now().astimezone().strftime("%Y-%m-%d %H:%M %Z")
    arm_th = "".join(f'<th class="n">{esc(CONTENT["arm_names"][a])}</th>' for a in arms)

    H = []
    A = H.append
    # ---------------------------------------------------------------- head + hero
    swap_chip = (f'<span class="chip"><b>{pct(ct["swap_invariance"], 0)}</b>identity-swap invariance <span class="muted">(plain LLM {pct(raw["swap_invariance"], 0)})</span></span>'
                 if ct["swap_invariance"] is not None else '<span class="chip muted">identity-swap runs: not yet re-run on this version</span>')
    repeat_chip = (f'<span class="chip"><b>{pct(ct["same_ruling_rate"], 0)}</b>same ruling on repeat</span>'
                   if ct["same_ruling_rate"] is not None else '<span class="chip muted">repeat runs: not yet re-run on this version</span>')
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
<div class="tile blue"><div class="l">Right, or handed to a person</div><div class="n">{n_bench - ct['wrong_executed']}<small>/ {n_bench}</small></div><div class="m">How it is counted: a case is right when outcome, amount and hand-off all match the policy-derived reference ({ct_ok} of {n_bench}); a case the court sends to a person instead of ruling is not wrong, a reviewer decides it ({n_bench - ct_ok - ct['wrong_executed']} such case{"s" if n_bench - ct_ok - ct['wrong_executed'] != 1 else ""}). Only a wrong decision that executes counts against the court: {ct['wrong_executed']}.</div></div>
<div class="tile purple"><div class="l">Cleared · wrong decisions that passed the check</div><div class="n">{G['court']['auto']}<small>/ {n_bench}</small> · {G['court']['wrong_and_executed']}</div><div class="m">{G['court']['auto']} core decisions cleared for automatic execution, {G['court']['wrong_and_executed']} observed wrong core decisions executed. Account flags always go to a human.</div></div>
<div class="tile amber"><div class="l">Mean time per ruling</div><div class="n">{ct['latency_mean_s']:.1f}<small>s</small></div><div class="m">p95 {ct['latency_p95_s']:.1f} s, versus {esc(CONTENT['manual_handling'])} of manual handling. About {tok_x:.0f}× the tokens of one call.</div></div>
</div>
<p class="method">{esc(CONTENT['method_caveat'].format(**fill))}</p>
<div class="chips secondary">
<span class="chip"><b>{ct['invalid_citations'] + ct.get('invalid_fact_citations', 0)} / {ct['citations'] + ct.get('fact_citations', 0)}</b>invalid citations in court rulings, fact ids + clause ids <span class="muted">(plain LLM {raw['invalid_citations'] + raw.get('invalid_fact_citations', 0)} / {raw['citations'] + raw.get('fact_citations', 0)})</span></span>
{swap_chip}
{repeat_chip}
<span class="chip"><b>{n_runs}</b>case-system runs · <b>{n_calls:,}</b> model calls</span>
</div>
</section>""")

    # ---------------------------------------------------------------- 1. highlights
    hl = "".join(f"<li><b>{esc(t)}</b>{esc(b.format(**fill))}</li>" for t, b in CONTENT["highlights"])
    cx = "".join(f"<li>{esc(b)}</li>" for b in CONTENT["review"])

    # ---------------------------------------------------------------- 2. results & cost
    big = [
        ("Right, or handed to a person", {a: 1 - S[a]["wrong_executed_rate"] for a in arms}),
        ("Exact match of the reference (stricter: a hand-off on a case the reference rules counts as a miss)", {a: S[a]["exact"] for a in arms}),
        ("Outcome label correct", {a: S[a]["ruling"] for a in arms}),
        (f"Amount within one cent, refund cases (n={ct['refund_cases']})", {a: S[a]["amount_1c_refund_cases"] for a in arms}),
        ("Escalation decision correct", {a: S[a]["escalate"] for a in arms}),
        ("Account-flag decision correct", {a: S[a]["flag"] for a in arms}),
        ("Citations all valid", {a: S[a]["cite_valid"] for a in arms}),
    ]
    bad = [
        ("Wrongful refunds", {a: S[a]["wrongful_refund_rate"] for a in arms}),
        ("Missed refunds", {a: S[a]["missed_refund_rate"] for a in arms}),
        ("Core decision wrong and executed", {a: S[a]["wrong_executed_rate"] for a in arms}),
    ]
    core_tip = esc(CONTENT["core_tip"])
    rows_spec = [
        ("Right, or handed to a person", "safe_rate", pct),
        ("Exact match of the reference (stricter: a hand-off on a case the reference rules counts as a miss)", "exact", pct),
        ("Outcome label", "ruling", pct),
        ("Amount within one cent, all cases", "amount_1c", pct),
        (f"Amount within one cent, refund cases only (n={ct['refund_cases']})", "amount_1c_refund_cases", pct),
        ("Escalation decision", "escalate", pct), ("Account-flag decision", "flag", pct),
        ("Macro F1", "f1", pct),
        ("Wrongful refunds", "wrongful_refund_rate", pct), ("Missed refunds", "missed_refund_rate", pct),
        ("Total money error", "money_error_total", money),
        ("Core decision wrong and executed", "wrong_executed", lambda v: f"{v} cases"),
        ("Routed to a human", "human_review_rate", pct),
        ("Citations all valid", "cite_valid", pct),
        ("Identity-swap invariance", "swap_invariance", pct),
        ("Same ruling on repeat", "same_ruling_rate", pct),
    ]
    mrows = []
    for label, key, f in rows_spec:
        vals = []
        for a in arms:
            m = S[a]
            v = m["macro"]["f1"] if key == "f1" else m.get(key)
            vals.append(f'<td class="n">{esc(f(v))}</td>')
        lab = f'<span class="tip" title="{core_tip}">{esc(label)}</span>' if key in ("exact", "wrong_executed") else esc(label)
        mrows.append(f'<tr><td>{lab}<div class="small muted">{esc(CONTENT["metric_meaning"][key])}</div></td>{"".join(vals)}</tr>')
    pc_rows = "".join(
        f'<tr><td>{esc(ruling_word(cls))}</td><td class="n">{ct["per_class"][cls]["support"]}</td>'
        + "".join(f'<td class="n">{pct(S[a]["per_class"][cls]["precision"], 0)} / {pct(S[a]["per_class"][cls]["recall"], 0)}</td>' for a in arms)
        + "</tr>" for cls in ("refund_full", "refund_partial", "no_action", "escalate"))
    cost_rows = "".join(
        f'<tr><td>{esc(lbl)}</td>' + "".join(f'<td class="n">{esc(f(S[a]))}</td>' for a in arms) + "</tr>"
        for lbl, f in [
            ("Latency, mean", lambda m: f"{m['latency_mean_s']:.1f} s"),
            ("Latency, 95th percentile", lambda m: f"{m['latency_p95_s']:.1f} s"),
            ("Input tokens, mean", lambda m: f"{m['input_tokens_mean']:,.0f}"),
            ("Output tokens, mean", lambda m: f"{m['output_tokens_mean']:,.0f}"),
            ("LLM calls per case", lambda m: f"{m['llm_calls_mean']:.1f}"),
            ("Errors / timeouts", lambda m: f"{m['errors']}"),
        ])
    # gate ablation table (new accounting: human flow = model escalated + blocked by gate)
    def case_tip(cid):
        c = hard_by_id.get(cid)
        return f'<span class="tip" title="{esc(c["name"])}">{esc(cid)} ({esc(plain(c["hard"]))})</span>' if c else esc(cid)
    grows, gnotes = [], []
    for a in arms:
        g = G[a]
        name = CONTENT["arm_names"][a] + (" + gate" if a in ("raw", "facts_only") else "")
        blocked = "–" if g["blocked_by_gate"] is None else g["blocked_by_gate"]
        caught = [c["case_id"] for c in g["cases"] if c.get("core_wrong") and not c.get("auto")]
        leaked = [c["case_id"] for c in g["cases"] if c.get("wrong_and_executed")]
        note = ""
        if a == "raw":
            note = esc(CONTENT["gate_raw_note"])
        elif leaked:
            note = "leaked (wrong and executed): " + ", ".join(case_tip(x) for x in leaked)
        elif caught:
            note = "the wrong core decision was caught by the certificate and sent to a human: " + ", ".join(case_tip(x) for x in caught)
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
                            f"policy ground of every open question, a point both sides agree on binds the judge, and the judge may only rule as an argued ground does; "
                            f"human review moves from {pct(G['judge_only']['human_rate'], 0)} to {pct(G['court']['human_rate'], 0)}."
                            if ct_wx < jo_wx else
                            f"The two advocates change human review from {pct(G['judge_only']['human_rate'], 0)} to {pct(G['court']['human_rate'], 0)}; their other value is the observable adversarial hearing the track requires."))
    # per-case table
    pc = []
    for i, c in enumerate(man, 1):
        cid = c["case_id"]
        exp = c["truth"]
        exp_txt = ruling_word(exp["ruling"]) + (f" {money(exp['amount'])}" if exp.get("amount") else "") + (" + flag" if exp.get("flag_account") else "")
        cells = []
        for a in arms:
            s = S[a]["per_case"].get(cid)
            if s is None:
                cells.append('<td><span class="muted">run failed</span></td>')
                continue
            g = s["got"]
            got = ruling_word(g.get("ruling")) + (f" {money(g['amount'])}" if g.get("amount") else "")
            mark = ('<span class="ok">✓</span>' if s["exact"] else '<span class="ok" title="handed to a person: not wrong, a reviewer decides">→ person</span>'
                    if (g.get("escalate") or g.get("ruling") == "escalate") else '<span class="bad">✗</span>')
            cells.append(f"<td>{mark} {esc(got)}</td>")
        pc.append(f'<tr><td class="n muted">{i}</td><td><span class="tip" title="{esc(cid)} · {esc(c["name"])}">{esc(plain(c["hard"]))}</span></td>'
                  f'<td>{esc(CONTENT["type_names"].get(c["type"], c["type"]))}</td><td>{esc(exp_txt)}</td>{"".join(cells)}</tr>')
    if ct["same_ruling_rate"] is not None:
        consistency_block = (f'<h3 class="mt">Consistency <span class="hint">court run {ct["repeats"]}× on all {ct["consistency_cases"]} cases</span></h3>'
                             f'<div class="tile" style="box-shadow:none"><div class="n" style="font-size:34px">{pct(ct["same_ruling_rate"], 0)}</div>'
                             f'<div class="m">same ruling on repeat across {ct["consistency_cases"]} cases; a disagreement between runs goes to a person, never to automatic execution.</div></div>')
    else:
        consistency_block = ('<h3 class="mt">Consistency</h3><p class="small muted">The repeat runs (every case a second time) have not yet been re-run on this version of the court; '
                             'the figure from the previous version is in bench/results/archive/ and is not comparable.</p>')
    A(f"""<section class="sec first" id="accuracy"><h2><span class="num">1</span>Results and cost</h2>
<p class="lead">The same {n_bench} cases, four ways, one model. <b>Raw LLM</b>: {esc(CONTENT['arm_desc']['raw'])}. <b>Facts only</b>: {esc(CONTENT['arm_desc']['facts_only'])}. <b>Judge + certificate</b>: {esc(CONTENT['arm_desc']['judge_only'])}. <b>Court</b>: {esc(CONTENT['arm_desc']['court'])}. "Correct" throughout means "matches the reference derived from the written policy" (<a href="#method">data and method</a>).</p>
<div class="grid2">
<div class="panel"><h3>Higher is better</h3>{legend(arms)}{bar_chart([big[0], big[2]], arms)}</div>
<div class="panel"><h3>Lower is better</h3>{legend(arms)}{bar_chart([bad[0], bad[2]], arms)}
<p class="small muted"><span class="tip" title="{core_tip}">Core decision</span> = outcome + amount + escalation; account flags and citations are excluded. Raw and facts-only have no gate, so every non-escalated ruling counts as executed.</p>
{consistency_block}</div>
</div>
<div class="panel mt"><h3>Cost per case</h3><div class="scroll"><table class="t"><tr><th></th>{arm_th}</tr>{cost_rows}</table></div>
<p class="small muted">Trade-off: the full court averages {ct['latency_mean_s']:.1f} s and {ct['llm_calls_mean']:.0f} model calls per case, about {lat_x:.0f}× the latency and {tok_x:.0f}× the input tokens of one call, against {esc(CONTENT['manual_handling'])} of manual handling. Judge + code check uses about 1/{jo_ratio:.0f} of the court's tokens.</p></div>
<details class="mt more"><summary>More results — every metric, what the code check prevents, precision / recall, confusion matrices, every case</summary>
<div class="grid2 mt"><div class="panel"><h3>All metrics, higher is better</h3>{legend(arms)}{bar_chart(big, arms)}</div><div class="panel"><h3>All metrics, lower is better</h3>{legend(arms)}{bar_chart(bad, arms)}</div></div>
<div class="panel mt"><h3>What the code check prevents <span class="hint">the policy check applied offline to the single-call rulings; no extra model calls</span></h3>
<p class="small muted">{esc(CONTENT['gate_lead'])} Human flow = rulings the model itself escalated + rulings the gate blocked.</p>
<div class="scroll"><table class="t wide"><tr><th>System</th><th class="n"><span class="tip" title="{core_tip}">core decision wrong</span></th><th class="n">model escalated</th><th class="n">blocked by gate</th><th class="n">to a human</th><th class="n">auto</th><th class="n">wrong and executed</th></tr>{"".join(grows)}</table></div>
<ol class="hl small muted" style="margin:10px 0 0">{"".join(gnotes)}</ol>
<p class="small" style="margin:10px 0 0"><b>{esc(gate_sentence)}</b></p></div>
<div class="panel mt"><h3>All metrics</h3><div class="scroll"><table class="t"><tr><th>Metric</th>{arm_th}</tr>{"".join(mrows)}</table></div></div>
<div class="mt">
<div class="panel"><h3>Per outcome: precision / recall</h3><div class="scroll"><table class="t"><tr><th>Outcome</th><th class="n">cases</th>{arm_th}</tr>{pc_rows}</table></div>
<p class="small muted">Precision: of the cases given this outcome, how many should have been. Recall: of the cases that should have this outcome, how many got it.</p></div>
</div>
<h3 class="mt">Confusion matrices</h3><div class="cm">{"".join(confusion(a, S[a]) for a in arms)}</div>
<details class="mt"><summary>Per-case results — all {n_bench} cases, four systems (hover a scenario for its id)</summary>
<div class="scroll"><table class="t wide"><tr><th>#</th><th>Scenario (the trap)</th><th>Type</th><th>Reference</th>{"".join(f'<th>{esc(CONTENT["arm_names"][a])}</th>' for a in arms)}</tr>{"".join(pc)}</table></div></details>
</details>
</section>""")

    # ---------------------------------------------------------------- 3. demo cases
    cards = []
    for cid, cd in d["cases"].items():
        case, exp = cd["case"], cd["expected"]
        disp, trip = case["dispute"], case["trip"]
        flag = bool(re.search(r"add flag_account", exp.get("rationale", "")))
        rul = ruling_word(exp["ruling"]) + (f" {money(exp['amount'])}" if exp.get("amount") else "")
        rul += " + account flag" if flag else ""
        t = disp["type"]
        bcls = {"route_deviation": "amber", "no_show": "blue", "safety": "red"}.get(t, "")
        cards.append(f"""<div class="card"><a href="/replay.html?case={cid}&mode=show"><img src="shots/{cid}.png" alt="{esc(cid)} map at trip end" loading="lazy"></a>
<div class="b"><div class="h"><b>{esc(cid)}</b><span class="badge {bcls}">{esc(CONTENT['type_names'].get(t, t))}</span><span class="small muted">{esc(trip['pickup']['name'])} → {esc(trip['dropoff']['name'])} · {esc(trip['service_type'])}</span></div>
<div class="story">“{esc(disp['statement'])}” <span class="muted">— filed by the {esc(disp['filed_by'])}</span></div>
<div class="ruling">{esc(rul)}<span>reference ruling</span></div>
<div class="why"><b>What it shows.</b> {esc(CONTENT['demo'][cid])}</div>
<details><summary class="small">Why, in the reference ruling's words</summary><p class="small" style="margin:0">{esc(plain(exp.get('rationale', '')))}</p></details>
<div class="links"><a href="/replay.html?case={cid}&mode=show">Showcase replay ↗</a><a href="/replay.html?case={cid}">Expert view ↗</a></div></div></div>""")
    inj = "".join(f"<li>{esc(plain(v))}</li>" for v in d["inject"].values())
    cfs = "".join(f"<li>{esc(plain(v))}</li>" for v in d["counterfactual"].values())

    # ---------------------------------------------------------------- built: core + stretch, one compact list, no status board
    def links(where):
        return " · ".join(f'<a href="{esc(h)}">{esc(l)}</a>' for l, h in where if not h.startswith("/api/"))
    LABEL = {"Three agents": "Three agents", "Judge output": "Structured ruling and plain-language notices", "Evidence is": "Evidence from every source",
             "At least two": "Three dispute types", "Agent-to-agent": "Every exchange on the record"}
    def label(req):
        return next((v for k, v in LABEL.items() if req.startswith(k)), req)
    core_items = "".join(f'<li><b>{esc(label(r["req"]))}.</b> {esc(r["how"].format(**fill))} {links(r["where"])}</li>'
                         for r in CONTENT["mvp"] if r["where"])
    stretch_items = "".join(f'<li><b>{esc(x["name"])}.</b> {esc(x["what"])} {links(x["where"])}</li>'
                            for x in CONTENT["stretch"] if x["status"] == "done")
    A(f"""<section class="sec" id="mvp"><h2><span class="num">2</span>What is built</h2>
<p class="lead">Three agents, three dispute types, every exchange on the record; four additional safeguards on top.</p>
<div class="grid2">
<div class="panel"><h3>Core</h3><ul class="hl small">{core_items}</ul></div>
<div class="panel"><h3 id="stretch">Additional safeguards</h3><ul class="hl small">{stretch_items}</ul></div>
</div></section>""")

    # ---------------------------------------------------------------- 4. key features
    bl = blind_numbers()
    bl_court = (bl or {}).get("court")
    ct_safe, jo_safe, raw_safe = n_bench - ct["wrong_executed"], n_bench - jo["wrong_executed"], n_bench - raw["wrong_executed"]
    cites_total = ct["citations"] + ct.get("fact_citations", 0)
    cites_bad = ct["invalid_citations"] + ct.get("invalid_fact_citations", 0)
    held_out = (f" On the {bl['cases']} held-out cases, written after the prompts were frozen and never used for tuning, the court decided "
                f"{bl_court['exact']} of {bl['cases']} right with {bl_court['wrong_executed']} wrong decision{'s' if bl_court['wrong_executed'] != 1 else ''} executed."
                if bl_court else "")
    features = [
        ("The policy runs before the model.",
         f"Ryde's dispute rules are compiled into executable predicates: on every case, code first decides which of the {pol['citable']} sourced "
         f"clauses apply, which fail and which need a reading, and the model speaks only inside that remaining space. A ruling rests on the written "
         f"policy, not on the model's memory of it, which removes the room for an invented rule at the source."),
        ("Every ruling is verified by code, and the evidence chain cannot be tampered with.",
         f"The facts are computed by code from the GPS trace, the chat, the fare, traffic and weather records: numbered, identical on every run; the "
         f"advocates and the judge may cite only those numbers and the clause ids. Before anything executes, code checks the ruling item by item: "
         f"every cited id exists, the outcome is one the policy allows, the amount equals the policy formula to the cent, a consent message precedes "
         f"the detour it excuses. Each ruling carries a receipt with four fingerprints (case file, policy, code, model), so any change anywhere "
         f"invalidates it. {len(d['inject'])} deliberate tampers of the AI's output (a cited fact that does not exist, a fact never read, an invented clause, "
         f"a changed amount, a flipped finding, an account flag hidden in free text) and a prompt injection planted in the chat were all caught."),
        ("The reasoning is fully transparent and the standard is documented.",
         f"Every tool call, brief, rebuttal, ruling, check and notice is a timestamped event, streamed live and replayable step by step on the map; "
         f"every citation opens the fact or the clause it points to. Across the benchmark the court made {cites_total} citations, {cites_bad} of them invalid."),
        ("Adversarial agents beat the same model alone.",
         f"Same model, same {n_bench} cases. The raw case file handed straight to the model: {raw_safe} of {n_bench} right or handed to a person, "
         f"{raw['wrong_executed']} wrong decisions executed. The judge with the code check but no advocates: {jo_safe} of {n_bench}, "
         f"{jo['wrong_executed']} wrong decisions executed. The full court (code facts, two advocates, judge, code check): {ct_safe} of {n_bench}, "
         f"{ct['wrong_executed']} wrong decision{'s' if ct['wrong_executed'] != 1 else ''} executed. The advocates add what a single judge lacks: "
         f"each side states the policy ground of every open question, a point both sides agree on binds the judge, and a judge may only rule as one "
         f"of the argued grounds does.{held_out}"),
    ]
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
    fam_rows = []
    for label, rx in CONTENT["families"]:
        n = sum(1 for c in man if re.search(rx, c["name"]))
        fam_rows.append(f'<span class="chip"><b>{n}</b>{esc(label)}</span>')
    type_chips = "".join(f'<span class="chip"><b>{by_type[t]}</b>{esc(CONTENT["type_names"].get(t, t))}</span>'
                         for t in sorted(by_type, key=lambda t: -by_type[t]))
    run_rows = "".join(
        f'<tr><td>{esc(CONTENT["arm_names"][k.replace("_swap", "")])}{" · identities swapped" if k.endswith("_swap") else ""}</td>'
        f'<td class="n">{r["base"]}</td><td class="n">{r["repeats"] or "–"}</td><td class="n">{r["total"]}</td></tr>'
        for k, r in runs.items())
    scen_list = "".join(
        f'<li><span class="tip" title="{esc(c["case_id"])} · {esc(c["name"])}">{esc(plain(c["hard"]))}</span></li>'
        for c in man)
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
<h3 class="mt">{n_demo} demo cases</h3><p class="small">Hand-built on real OneMap routes with hand-checked reference rulings — the cases in section 2. {d['tests']} automated tests cover the fact tools, policy engine and stretch modules.</p></div>
<div class="panel"><h3>LLM runs behind this page</h3>
<div class="scroll"><table class="t"><tr><th>System</th><th class="n">cases</th><th class="n">repeat runs</th><th class="n">runs</th></tr>{run_rows}
<tr class="hl"><td><b>Total</b></td><td class="n">{n_base} + {n_swap} swapped</td><td class="n">{n_rep}</td><td class="n big">{n_runs}</td></tr></table></div>
<p class="small muted">Four systems × {n_bench} cases = {n_base} base runs{f"; three of them re-run with rider and driver identities swapped = {n_swap}" if n_swap else "; identity-swap runs not yet re-run on this version"}{f"; the court run a second time on every case for consistency = {n_rep}" if n_rep else "; repeat runs not yet re-run on this version"}. One model throughout: {esc(model)}.</p></div>
</div>
<div class="panel mt"><h3>How the reference answers were made, and what the numbers can and cannot say</h3><ul class="hl small">{method}</ul></div>
</details>
</section>""")

    # ---------------------------------------------------------------- 7. footer
    A(f"""<div class="foot"><a href="/">Start here</a><a href="/court.html">Court UI (expert)</a><a href="/replay.html?case=C-0001&mode=show">Showcase replay</a><a href="/replay.html?case=C-0001">Expert replay</a><a href="architecture-system.png">Architecture image</a></div>
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
