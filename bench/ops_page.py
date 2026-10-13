#!/usr/bin/env python3
"""Generate web/ops.html: the operations hand-off page.

Run:  .venv/bin/python bench/ops_page.py        (stdlib only; idempotent; reads stored artifacts, never runs the court)

A Ryde operations reviewer opens the page and sees, in about twenty seconds, what work disappears and what still
reaches their team after the system processed the synthetic policy-conformance benchmark batch. Every number is computed
from bench/results/court/B-00NN.record.json (primary runs only; *.r1.* repeats are ignored), the matching B-00NN.json
run file (latency) and data/bench/manifest.json (scenario names). Nothing is hard-coded except the prose below.

Judge-facing wording rules: no "paid automatically", "executed automatically" or "accurate"; refunds are Ryde vouchers;
account flags and safety always go to a person; clause ids and fact ids appear only inside chips whose title is the
plain-language label; no em-dashes in page copy.
"""
from __future__ import annotations

import datetime as dt
import html
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COURT = ROOT / "bench" / "results" / "court"
MANIFEST = ROOT / "data" / "bench" / "manifest.json"
OUT = ROOT / "web" / "ops.html"

# Plain-English clause labels (copied from web/replay.js CLAUSE).
CLAUSE = {
    "RD-1": "driver must take the direct route", "RD-2": "refund for extra kilometres", "RD-3": "rider-requested stop",
    "RD-4": "reroute justified by traffic or an incident", "RD-5": "rider agreed to the route beforehand",
    "RD-6": "repeat offender: account flag",
    "NS-0": "when a cancellation fee applies", "NS-1": "driver waited 3 min at pickup after \"I'm Here\"",
    "NS-2": "no-show not proven: fee refunded", "NS-3": "driver cancelled: no fee", "NS-4": "3-minute free-cancel window",
    "NS-6": "waiting-fee conditions", "NS-7": "30-day dispute window",
    "FARE-1": "fixed fare: only published extras", "FARE-2": "toll overcharge", "FARE-3": "cleaning-fee claim (not in this data)",
    "NS-5": "advance-booking cancellation (not in this data)", "NS-8": "driver-late free cancel (no such Ryde rule)",
    "SAFE-3": "trip completed without the rider (fraud)", "SAFE-1": "threat or harassment: human review",
    "SAFE-2": "accident or dangerous driving: human review",
}
OUTW = {"refund_partial": "Partial refund", "refund_full": "Full refund", "no_action": "No refund",
        "fee_waived": "Fee waived", "escalate": "Human review", "flag_account": "Account flag"}
TYPE_LABEL = {"route_deviation": "Route deviation", "no_show": "No-show fee", "safety": "Safety"}

# Scenario titles: plain language for every manifest name. Unknown names fall back to humanize().
SCENARIO = {
    "rd_basic": "Detour · unexplained loop",
    "rd_consent_before": "Detour · consent given beforehand",
    "rd_consent_after": "Detour · consent only after the fact",
    "rd_incident_on_stretch": "Detour · incident on the replaced stretch",
    "rd_incident_decoy": "Detour · incident elsewhere (decoy)",
    "rd_incident_late": "Detour · incident reported after the detour",
    "rd_band1_no_incident": "Detour · heavy traffic, no incident",
    "rd_band1_incident": "Detour · heavy traffic plus incident",
    "rd_band2_heavy_rain": "Detour · heavy rain, slow traffic",
    "rd_stop_named": "Detour · rider named a stop",
    "rd_stop_named_prior": "Detour · rider named a stop, driver has history",
    "rd_stop_unnamed": "Detour · stop the rider never named",
    "rd_two_segs_consent_seg1": "Two detours · first one agreed",
    "rd_two_segs_consent_seg1_hv": "Two detours · first one agreed · Hougang → VivoCity",
    "rd_two_segs_consent_seg1_jt": "Two detours · first one agreed · Jurong Point → Toa Payoh",
    "rd_two_segs_consent_seg1_pa": "Two detours · first one agreed, driver has history",
    "rd_two_segs_consent_seg1_bk": "Two detours · first one agreed · Buona Vista → Kallang",
    "rd_two_segs_incident_seg1": "Two detours · first one excused by incident",
    "rd_two_segs_plain": "Two detours · neither excused",
    "rd_fixed_fare": "Detour on a fixed fare",
    "rd_fixed_fare_consent": "Detour on a fixed fare · consent given",
    "rd_fixed_fare_consent_cr": "Detour on a fixed fare · consent given · Compass One → Raffles Place",
    "rd_fixed_fare_consent_ns": "Detour on a fixed fare · consent given · NUS → Suntec City",
    "rd_fixed_fare_consent_prior_tv": "Fixed fare · consent given, driver has history · Toa Payoh → VivoCity",
    "rd_fixed_fare_consent_prior_jc": "Fixed fare · consent given, driver has history · Junction 8 → Changi",
    "rd_fixed_fare_prior_flag": "Detour on a fixed fare · repeat offender",
    "rd_prior_flag": "Detour · repeat offender",
    "rd_no_deviation": "No detour · rider overstated the route",
    "rd_request_only": "Detour · driver asked, rider never agreed",
    "rd_scope_other": "Detour · complaint about something else",
    "rd_consent_before_prior": "Detour · consent beforehand, driver has history",
    "rd_threat_in_chat": "Detour · threat language in chat",
    "rd_consent_before_light": "Detour · brief consent beforehand",
    "rd_keyword_trap_find_you": "Detour · pickup chat contains a threat hint word (ordinary message)",
    "ns_fake_here_far": "No-show · \"I'm Here\" tapped 600 m away",
    "ns_wait_2min": "No-show · driver waited only 2 min",
    "ns_wait_4min": "No-show · driver waited 4 min",
    "ns_rider_cancel_150s": "Rider cancelled at 150 s",
    "ns_rider_cancel_200s": "Rider cancelled at 200 s",
    "ns_no_here_tap": "No-show · no \"I'm Here\" tap",
    "ns_fake_here_350m": "No-show · \"I'm Here\" tapped 350 m away",
    "ns_wait_185s_edge": "No-show · waited 185 s (edge)",
    "ns_wait_175s_edge": "No-show · waited 175 s (edge)",
    "ns_rider_cancel_175s": "Rider cancelled at 175 s (edge)",
    "ns_rider_cancel_185s": "Rider cancelled at 185 s (edge)",
    "ns_wait_4min_two_more_minutes": "No-show · rider asked for two more minutes",
    "ns_wait_2min_driver_claims_5": "No-show · driver claims 5 min, GPS says 2",
    "ns_fake_here_1km_long_wait": "No-show · \"I'm Here\" tapped 1 km away",
    "ns_rider_cancel_400s_driver_waiting": "Rider cancelled at 400 s, driver waiting",
    "ns_threat_in_chat": "No-show · threat language in chat",
    "ns_rider_cancel_100s_bad_profile": "Rider cancelled at 100 s · poor history",
    "ns_wait_4min_180m": "No-show · waited 4 min, 180 m from pickup",
    "safe_driver_threat": "Safety · driver threat in chat",
    "safe_rider_threat": "Safety · rider threat in chat",
    "safe_innocuous_chat_dangerous_driving": "Safety · dangerous driving alleged, chat clean",
    "safe_no_chat_harassment": "Safety · harassment alleged, no chat",
    "safe_keyword_only_in_statement": "Safety · hint word only in driver's statement",
    # consent scope, second round
    "rd_general_consent_jp": "Detour \u00b7 \"whichever way is faster\"",
    "rd_general_consent_wl": "Detour \u00b7 general route choice, light rain",
    "rd_general_consent_cn_cp": "Detour \u00b7 general consent, in Chinese",
    "rd_general_consent_cn_bv": "Detour \u00b7 general consent in Chinese, driver has priors",
    "rd_named_singlish_j8": "Detour \u00b7 consent in Singlish to a named road",
    "rd_named_singlish_nx": "Detour \u00b7 Singlish consent, heavy rain",
    "rd_named_cn_am": "Detour \u00b7 consent in Chinese to a named road",
    "rd_named_cn_tp": "Detour \u00b7 Chinese consent, driver has priors",
    # held-out set
    "bl_general_consent": "Detour \u00b7 \"whichever way is faster\"",
    "bl_general_consent_cn": "Detour \u00b7 general consent, in Chinese",
    "bl_general_errand": "Detour \u00b7 general consent, driver's own stop inside",
    "bl_negation": "Detour \u00b7 rider said no",
    "bl_named_singlish": "Detour \u00b7 consent in Singlish",
    "bl_named_cn": "Detour \u00b7 consent in Chinese",
    "bl_named_elsewhere": "Detour \u00b7 agreed road, driver says he went another way",
    "bl_gps_tail_missing": "Detour \u00b7 GPS trace ends before the drop-off",
    "bl_record_threshold_7m50": "No-show \u00b7 record says 8 min, waited 7:50",
    "bl_record_threshold_8m10": "No-show \u00b7 record says 8 min, waited 8:10",
    "bl_hole_in_wait": "No-show \u00b7 hole in the GPS during the wait",
    "bl_cancelled_by_missing": "No-show \u00b7 record does not say who cancelled",
}



def humanize(name: str) -> str:
    """Fallback for a manifest name missing from SCENARIO: 'rd_foo_bar' -> 'Detour · foo bar'."""
    prefix = {"rd": "Detour", "ns": "No-show", "safe": "Safety"}
    head, _, rest = name.partition("_")
    return f"{prefix.get(head, head.title())} · {rest.replace('_', ' ')}"


def esc(s) -> str:
    """HTML-escape; stored data may contain em-dashes, the page may not, so they become plain hyphens."""
    return html.escape(str(s if s is not None else "").replace(" \u2014 ", " - ").replace("\u2014", "-"), quote=True)


def clause_tag(ids: list[str]) -> str:
    """One short tag ("10 clauses") that opens a popover listing every cited clause with its title and policy-page link."""
    if not ids:
        return '<span class="muted">no clause cited</span>'
    rows = []
    for c in ids:
        base = re.sub(r"\([a-z]\)$", "", c)
        title = CLAUSE.get(base, "")
        rows.append(f'<a href="/policy.html#{esc(base)}" target="_blank" rel="noopener"><b>{esc(c)}</b><span>{esc(title)}</span></a>')
    n = len(ids)
    return (f'<button type="button" class="ctag" aria-haspopup="true" aria-expanded="false" title="Clauses the ruling cites">{n} clause{"s" if n != 1 else ""} ▾</button>'
            f'<div class="cpop" hidden><div class="cpop-h">Clauses cited in this ruling</div>{"".join(rows)}</div>')


def money(v) -> str:
    return f"${float(v):,.2f}"


def outcome_text(ruling: dict) -> str:
    r = ruling.get("ruling")
    base = OUTW.get(r, str(r))
    if r in ("refund_partial", "refund_full") and ruling.get("amount") is not None:
        return f"{base} {money(ruling['amount'])}"
    return base


def plain_reason(reason: str, rec: dict) -> tuple[str, str]:
    """(short label, one line <=140 chars), plain language, no ids. Pattern-based; falls back to a stripped clip of the reason."""
    low = reason.lower()
    dtype = rec["dispute"]["type"]
    if "unscreened" in low or "judge unavailable" in low:
        return "Judge did not answer", "The judge did not answer (timeout or provider error); nothing was weighed → a person decides"
    if low.startswith("safety concern"):
        return "Threat in chat", "The judge read a threat or intimidation in the chat or statements → human review (safety)"
    if "segment finding undetermined" in low:
        return "Agreement unclear", "The judge could not settle from the record what the rider agreed to, or whether this stretch is the road agreed → a person decides"
    if low.startswith("evidence gap") or "evidence insufficient" in low or "evidence unknown" in low:
        return "Evidence missing", "Evidence the policy needs is missing from the record → a person decides"
    if "harass" in low or "sexual" in low:
        return "Harassment alleged", "Harassment alleged in a safety complaint → policy forbids automatic ruling"
    if "dangerous driving" in low:
        return "Dangerous driving alleged", "Dangerous driving alleged; no telematics to confirm or refute → safety review"
    if dtype == "safety":
        return "Safety complaint", "Safety complaint → policy forbids automatic ruling"
    # fallback: strip parenthetical ids, bracketed ids and bare ids, then clip
    s = re.sub(r"\s*\((?:RD|NS|SAFE|FARE)-\d+[^)]*\)", "", reason)
    s = re.sub(r"\s*\[(?:F\d+|(?:RD|NS|SAFE|FARE)-\d+)[^\]]*\]", "", s)
    s = re.sub(r"\b(?:RD|NS|SAFE|FARE)-\d+(?:\([a-z]\))?\b", "policy", s)
    s = re.sub(r"\s{2,}", " ", s).strip()
    return "Other", (s if len(s) <= 140 else s[:139].rstrip(" ,;:(-") + "…")


# ---------------------------------------------------------------------------------------------------------------------
def load() -> list[dict]:
    manifest = {c["case_id"]: c for c in json.loads(MANIFEST.read_text())["cases"]}
    rows = []
    for p in sorted(COURT.glob("B-*.record.json")):
        if ".r1." in p.name or re.search(r"\.r\d+\.record\.json$", p.name):
            continue
        rec = json.loads(p.read_text())
        cid = rec["case_id"]
        run_path = COURT / f"{cid}.json"
        run = json.loads(run_path.read_text()) if run_path.exists() else {}
        if not run.get("ok", True):
            print(f"ops_page: {cid} run failed ({run.get('error', '')[:80]}); its record is not a queue item until it is re-run", file=sys.stderr)
            continue
        man = manifest.get(cid)
        if man is None:
            print(f"warning: {cid} has a record but no manifest entry", file=sys.stderr)
            man = {"name": cid.lower(), "type": rec["dispute"]["type"], "truth": {}, "hard": ""}
        facts_block = rec.get("facts") or {}
        facts = facts_block.get("facts", facts_block if isinstance(facts_block, list) else [])
        elig = rec.get("eligibility") or {}
        ruling = rec.get("ruling") or {}
        actions = elig.get("actions") or []
        flag = (bool(ruling.get("flag_account")) and not ruling.get("escalate")) or any(a.get("type") == "flag_account" for a in actions)   # an escalated case creates no account action; the reviewer decides
        auto = bool(elig.get("auto")) and not ruling.get("escalate")
        rows.append({
            "id": cid, "name": man["name"], "title": SCENARIO.get(man["name"]) or humanize(man["name"]),
            "hard": man.get("hard", ""), "type": rec["dispute"]["type"], "rec": rec, "facts": facts,
            "elig": elig, "ruling": ruling, "auto": auto, "flag": flag,
            "latency": run.get("latency_s"), "llm_calls": run.get("llm_calls"), "input_tokens": run.get("input_tokens"),
        })
    return rows


def funnel(rows: list[dict]) -> dict:
    auto = [r for r in rows if r["auto"]]
    human = [r for r in rows if not r["auto"]]
    voucher = [r for r in auto if r["ruling"].get("ruling") in ("refund_partial", "refund_full", "fee_waived")]
    noref = [r for r in auto if r["ruling"].get("ruling") == "no_action"]
    other = [r for r in auto if r not in voucher and r not in noref]
    flags = [r for r in rows if r["flag"]]
    lat = [r["latency"] for r in rows if r["latency"] is not None]
    return {"total": len(rows), "auto": len(auto), "voucher": len(voucher), "noref": len(noref), "other": len(other),
            "human": len(human), "flags": len(flags), "voucher_sum": sum(float(r["ruling"].get("amount") or 0) for r in voucher),
            "lat_mean": (sum(lat) / len(lat)) if lat else 0.0, "lat_max": max(lat) if lat else 0.0,
            "human_ids": [r["id"] for r in human], "flag_ids": [r["id"] for r in flags]}


# ---------------------------------------------------------------------------------------------------------------------
def row_html(r: dict, review_col: bool = False) -> str:
    rec, ruling, elig = r["rec"], r["ruling"], r["elig"]
    reasons = elig.get("reasons") or []
    badge = '<span class="badge ok">auto-cleared</span>' if r["auto"] else '<span class="badge hr">human review</span>'
    clauses = clause_tag(ruling.get("cited_policy") or [])
    lat = f"{r['latency']:.1f} s" if r["latency"] is not None else "n/a"
    flagnote = '<div class="flagnote">+ account flag → a person</div>' if r["flag"] else ""
    out_cls = "c-amber" if ruling.get("ruling") in ("refund_partial", "refund_full", "fee_waived") else ("c-red" if not r["auto"] else "")
    replay = (f'<td class="open"><a href="/replay.html?case={esc(r["id"])}&phase=court" '
              f'title="Open the stored court run: map, then every agent step and the ruling">Replay</a></td></tr>')
    head = (f'<tr class="row"><td><div class="ttl">{esc(r["title"])}</div><span class="cid">{esc(r["id"])}</span></td>'
            f'<td>{esc(TYPE_LABEL.get(r["type"], r["type"]))}</td>')
    if review_col:      # the escalated tab: outcome and automation are "human review" on every row, so the reviewer's page takes their place
        label, why = plain_reason(reasons[0] if reasons else (ruling.get("escalation_reason") or "Escalated by the judge"), rec)
        safety = rec["dispute"]["type"] == "safety" or label in ("Threat in chat", "Harassment alleged", "Dangerous driving alleged")
        return (head + f'<td><span class="why{" safety" if safety else ""}" tabindex="0">{esc(label)}'
                f'<span class="tip" role="tooltip">{esc(why)}</span></span></td><td class="chips">{clauses}</td><td class="mono">{esc(lat)}</td>'
                f'<td class="rvl"><a href="/human-review.html?case={esc(r["id"])}" '
                f'title="Open this case on the human review page: the open question, the evidence and the decision">'
                f'<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" aria-hidden="true">'
                f'<path d="M10 14 21 3M15 3h6v6M21 14v5a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5"/></svg>'
                f'/human-review.html?case={esc(r["id"])}</a></td>' + replay)
    return (head + f'<td class="{out_cls}"><b>{esc(outcome_text(ruling))}</b>{flagnote}</td>'
            f'<td>{badge}</td><td class="chips">{clauses}</td>'
            f'<td class="mono">{esc(lat)}</td>' + replay)


def table_html(rows: list[dict], key: str, empty: str) -> str:
    if not rows:
        return f'<p class="muted">{esc(empty)}</p>'
    review_col = key == "human"
    head = ("<tr><th>Case</th><th>Dispute type</th><th>Why it stopped</th><th>Clauses</th><th>Time</th><th>Review page</th><th>Replay</th></tr>"
            if review_col else
            "<tr><th>Case</th><th>Dispute type</th><th>Proposed outcome</th><th>Automation</th>"
            "<th>Clauses</th><th>Time</th><th>Replay</th></tr>")
    body = "".join(row_html(r, review_col) for r in rows)
    return f'<div class="tw"><table>{head}{body}</table></div>'


def page(rows: list[dict], f: dict, model: str) -> str:
    human = [r for r in rows if not r["auto"]]
    flagged = [r for r in rows if r["flag"]]
    auto = [r for r in rows if r["auto"]]
    H, A, N = f["human"], f["flags"], f["auto"]
    # the flagged cases are counted inside the auto-cleared ones (refund cleared, the flag waits for a person): say so, so the tabs add up
    flags_in_auto = sum(1 for r in rows if r["flag"] and r["auto"])
    flag_tab = f"{A} of the {N}" if A and flags_in_auto == A else str(A)
    flag_tip = (f'<span class="tip" role="tooltip" id="tip-flag">These {A} are part of the {N} auto-cleared cases. The refund is automatic; '
                'the account action cannot be automated, so a person handles it.</span>' if A and flags_in_auto == A else "")
    gen = dt.date.today().isoformat()
    pct_auto = round(100 * N / f["total"]) if f["total"] else 0
    pct_h = 100 - pct_auto
    all_safety = human and all(any(c.startswith("SAFE-") for c in (r["ruling"].get("cited_policy") or [])) for r in human)
    human_note = ("Every one is a safety complaint or a message the judge read as a threat; the policy allows only human review for those."
                  if all_safety else "Each one was stopped by the policy check or escalated by the judge.")
    fl_types = sorted({TYPE_LABEL.get(r["type"], r["type"]).lower() for r in flagged})
    flag_note = (f"Proposed in {', '.join(fl_types)} cases (repeat offenders, false \"I'm Here\" taps)." if flagged
                 else "No account action was proposed in this batch.")
    return f'''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Akina Court · Ops hand-off</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<script src="/theme.js"></script>
<link rel="stylesheet" href="/styles/base.css">
<meta name="description" content="What reaches a human after the {f["total"]}-case synthetic policy-conformance batch: {N} core decisions cleared by the policy check, {H} sent to a person, {A} account flags always routed to a person.">
<style>
*{{box-sizing:border-box}}
html,body{{margin:0;background:var(--bg);color:var(--ink);font-family:var(--sans);font-size:15px;line-height:1.5;-webkit-font-smoothing:antialiased}}
a{{color:var(--blue);text-decoration:none}}a:hover{{text-decoration:underline}}
a:focus-visible,button:focus-visible{{outline:2px solid var(--blue);outline-offset:2px}}

.logo{{width:34px;height:34px;border-radius:9px;display:block}}
.hero{{padding:34px 0 6px}}
h1{{font-size:clamp(32px,5vw,50px);line-height:1.05;letter-spacing:-.025em;margin:0 0 14px;max-width:900px}}
.lead{{font-size:18px;color:var(--ink2);max-width:880px;margin:0 0 16px}}
.lead b{{color:var(--ink)}}
.btn{{display:inline-flex;align-items:center;gap:8px;padding:10px 16px;border-radius:10px;font-weight:700;font-size:14px;border:1px solid var(--line);background:var(--panel2);color:var(--ink)}}
.btn:hover{{text-decoration:none;filter:brightness(1.1)}}
.meta{{font:12px var(--mono);color:var(--muted);margin-top:6px}}
.grid{{display:grid;gap:14px}}
.g3{{grid-template-columns:repeat(3,1fr)}}.g4{{grid-template-columns:repeat(4,1fr)}}
@media(max-width:860px){{.g3,.g4{{grid-template-columns:1fr 1fr}}}}
@media(max-width:560px){{.g3,.g4{{grid-template-columns:1fr}}}}
.card{{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:16px 18px 14px}}
.card p{{margin:0;color:var(--ink2);font-size:13.5px}}
section{{padding:26px 0 6px}}
h2{{font-size:22px;letter-spacing:-.01em;margin:0 0 6px}}
h3{{font-size:17px;margin:2px 0 4px}}
.sub{{color:var(--muted);margin:0 0 14px;font-size:14px}}
.num{{font:800 38px/1 var(--mono);letter-spacing:-.02em;margin:6px 0 8px}}
.num small{{font-size:15px;color:var(--muted);font-weight:600;margin-left:4px}}
.k{{font-size:11px;letter-spacing:.08em;text-transform:uppercase;color:var(--muted);font-weight:700}}
.c-green{{color:var(--green)}}.c-blue{{color:var(--blue)}}.c-purple{{color:var(--purple)}}.c-amber{{color:var(--amber)}}.c-red{{color:var(--red)}}
.caveat{{margin-top:12px;padding:10px 14px;border:1px solid rgba(245,181,68,.35);background:rgba(245,181,68,.07);border-radius:10px;color:var(--amber);font-size:13px}}
.muted{{color:var(--muted)}}.small{{font-size:12.5px}}.mono{{font-family:var(--mono);font-size:12.5px}}
/* funnel */
.funnel{{display:grid;grid-template-columns:1fr auto 1fr auto 1fr;gap:10px;align-items:stretch;margin-top:16px}}
.funnel .arrow{{display:grid;place-items:center;color:var(--muted);font-size:22px}}
@media(max-width:860px){{.funnel{{grid-template-columns:1fr}}.funnel .arrow{{transform:rotate(90deg);font-size:18px;height:16px}}}}
.bar{{display:flex;height:12px;border-radius:999px;overflow:hidden;margin:16px 0 6px;background:var(--panel2);gap:2px}}
.bar>i{{display:block;height:100%}}
.bar .a{{background:var(--green)}}.bar .h{{background:var(--amber)}}
.legend{{display:flex;gap:16px;flex-wrap:wrap;font-size:12.5px;color:var(--ink2)}}
.legend i{{display:inline-block;width:10px;height:10px;border-radius:3px;margin-right:6px;vertical-align:-1px}}
.lane{{margin-top:12px;display:flex;gap:14px;align-items:center;border:1px solid rgba(180,140,255,.35);background:rgba(180,140,255,.06);border-radius:14px;padding:12px 18px}}
.lane .num{{margin:0;font-size:30px}}
.lane p{{margin:0;font-size:13.5px;color:var(--ink2)}}
/* tabs */
.tabs{{display:flex;gap:6px;flex-wrap:wrap;margin:0 0 12px}}
.tab .tipi{{display:inline-grid;place-items:center;width:15px;height:15px;margin-left:6px;border-radius:50%;border:1px solid currentColor;font:700 10px var(--mono);opacity:.7;vertical-align:1px}}
.tab .tip{{position:absolute;left:50%;top:calc(100% + 8px);transform:translateX(-50%);z-index:5;width:max-content;max-width:min(300px,80vw);padding:9px 12px;border-radius:10px;background:var(--ink);color:var(--bg);font-size:12.5px;font-weight:500;line-height:1.45;text-align:left;white-space:normal;box-shadow:0 8px 24px rgba(0,0,0,.35);opacity:0;visibility:hidden;transition:opacity .12s;pointer-events:none}}
.tab .tip::before{{content:"";position:absolute;left:50%;top:-5px;width:10px;height:10px;background:inherit;transform:translateX(-50%) rotate(45deg)}}
.tab:hover .tip,.tab:focus-visible .tip{{opacity:1;visibility:visible}}
@media (max-width:600px){{.tab .tip{{left:0;transform:none}}.tab .tip::before{{left:24px}}}}
.tab{{position:relative;padding:9px 14px;border-radius:999px;border:1px solid var(--line);background:var(--panel2);color:var(--ink2);font-weight:700;font-size:13.5px;cursor:pointer;font-family:inherit}}
.tab[aria-selected=true]{{background:#fff;color:#111;border-color:transparent}}
.panel[hidden]{{display:none}}
.tw{{overflow-x:auto;-webkit-overflow-scrolling:touch;border:1px solid var(--line);border-radius:14px;background:var(--panel)}}
table{{width:100%;min-width:720px;border-collapse:collapse;font-size:13.5px}}
th{{text-align:left;font-size:11px;letter-spacing:.08em;text-transform:uppercase;color:var(--muted);padding:10px 10px;border-bottom:1px solid var(--line);white-space:nowrap}}
td{{padding:9px 10px;border-bottom:1px solid var(--line);vertical-align:top;color:var(--ink2)}}
tr.row:hover td{{background:var(--panel2)}}
tr.row:last-child td{{border-bottom:0}}
td:first-child{{min-width:170px}}td .ttl{{color:var(--ink);font-weight:600}}td.mono{{white-space:nowrap}}
.cid{{color:var(--muted);font:11px var(--mono)}}
.why{{position:relative;display:inline-block;padding:2px 10px;border-radius:999px;font-size:12px;font-weight:600;white-space:nowrap;color:var(--ink2);border:1px solid var(--line);cursor:default}}
.why.safety{{color:var(--red);border-color:rgba(255,107,107,.45)}}
.why .tip{{position:absolute;left:0;bottom:calc(100% + 8px);z-index:5;width:max-content;max-width:min(320px,80vw);padding:9px 12px;border-radius:10px;background:var(--ink);color:var(--bg);font-size:12.5px;font-weight:500;line-height:1.45;white-space:normal;opacity:0;visibility:hidden;transition:opacity .15s;pointer-events:none}}
.why .tip::before{{content:"";position:absolute;left:18px;bottom:-5px;width:10px;height:10px;background:inherit;transform:rotate(45deg)}}
.why:hover .tip,.why:focus-visible .tip{{opacity:1;visibility:visible}}
tr.row:nth-child(2) .why .tip{{bottom:auto;top:calc(100% + 8px)}}tr.row:nth-child(2) .why .tip::before{{bottom:auto;top:-5px}}
.flagnote{{font-size:11.5px;color:var(--purple);font-weight:600}}
.badge{{display:inline-block;padding:2px 9px;border-radius:999px;font:700 11px var(--mono);white-space:nowrap;border:1px solid}}
.badge.ok{{color:var(--green);border-color:rgba(58,210,159,.45);background:rgba(58,210,159,.08)}}
.badge.hr{{color:var(--amber);border-color:rgba(245,181,68,.45);background:rgba(245,181,68,.08)}}
td.rvl{{white-space:nowrap}}td.rvl a{{display:inline-flex;align-items:center;gap:6px;font:600 12.5px var(--mono);color:var(--amber);text-decoration:none}}td.rvl a:hover{{text-decoration:underline;text-underline-offset:3px}}td.rvl svg{{flex:none}}
.chip{{display:inline-block;padding:1px 6px;border-radius:6px;font:600 11px var(--mono);color:var(--ink2);background:var(--panel2);border:1px solid var(--line);margin:1px 2px 1px 0;cursor:help;white-space:nowrap;text-decoration:none}}a.chip:hover{{border-color:var(--blue);color:var(--ink)}}
.chip.f{{color:var(--blue)}}
td.chips{{min-width:110px;position:relative}}
.ctag{{font:600 11px var(--mono);color:var(--ink2);background:var(--panel2);border:1px solid var(--line);border-radius:999px;padding:3px 9px;cursor:pointer;white-space:nowrap}}
.ctag:hover,.ctag[aria-expanded="true"]{{border-color:var(--blue);color:var(--ink)}}
.cpop{{position:fixed;z-index:30;width:340px;background:var(--panel);border:1px solid rgba(91,156,255,.5);border-radius:12px;padding:8px;box-shadow:0 12px 32px rgba(0,0,0,.45);text-align:left}}
.cpop-h{{font:600 10.5px var(--mono);letter-spacing:.06em;text-transform:uppercase;color:var(--muted);padding:2px 6px 6px}}
.cpop a{{display:flex;gap:10px;align-items:baseline;padding:5px 6px;border-radius:7px;color:var(--ink);text-decoration:none;font-size:12.5px;white-space:normal}}
.cpop a b{{font:700 11px var(--mono);color:var(--blue);flex:none;min-width:52px}}
.cpop a span{{color:var(--ink2)}}
.cpop a:hover{{background:var(--panel2)}}
/* strips */
.strip{{display:grid;grid-template-columns:repeat(3,1fr);border:1px solid var(--line);border-radius:14px;overflow:hidden;background:var(--panel)}}
.strip>div{{padding:18px;border-left:1px solid var(--line)}}.strip>div:first-child{{border-left:0}}
@media(max-width:860px){{.strip{{grid-template-columns:1fr}}.strip>div{{border-left:0;border-top:1px solid var(--line)}}.strip>div:first-child{{border-top:0}}}}
.strip h3{{margin:4px 0 6px;font-size:15px}}.strip p,.strip li{{margin:0;font-size:13.5px;color:var(--ink2)}}
.strip ul{{margin:6px 0 0;padding-left:18px}}
.strip code{{font:12.5px var(--mono);color:var(--ink)}}
.foot{{font-size:12.5px;color:var(--muted);margin-top:10px}}
footer{{padding:28px 0 40px;color:var(--muted);font-size:13px;border-top:1px solid var(--line);margin-top:30px}}
footer .links{{display:flex;flex-wrap:wrap;gap:16px;margin-bottom:10px;font-weight:600}}
@media(max-width:560px){{h1{{font-size:32px}}.lead{{font-size:16px}}.num{{font-size:32px}}}}
</style>
</head>
<body>
<div class="wrap">
<header class="site">
  <a href="/" aria-label="Akina Court home"><img class="logo" src="/logo.svg" alt="" width="34" height="34"></a>
  <div class="ident"><div class="t">Akina Court</div><div class="s">Ryde Dispute Court · Tencent Cloud AI CAN DO IT Hackathon SG 2026 · Ryde track</div></div>
  <nav aria-label="Site"><a href="/">Home</a><a href="/#watch">Watch</a><a href="/facts.html?case=DISP-002">Facts</a><a href="/policy.html">Policy</a><a href="/ops.html">Ops</a><a href="/report.html">Results</a><button class="theme" type="button" aria-label="Switch colour theme">Light</button></nav>
</header>

<main>
<div class="hero">
  <h1>What reaches a human after {f["total"]} cases</h1>
  <p class="lead">A {f["total"]}-case synthetic benchmark, not live Ryde volume. Each count is recomputed from the stored rulings.</p>

  <div class="funnel" aria-label="Case funnel">
    <div class="card"><div class="k">Cases in the batch</div><div class="num">{f["total"]}</div><p>Route deviation, no-show fee and safety scenarios, each with reference outcomes derived from the written policy.</p></div>
    <div class="arrow" aria-hidden="true">→</div>
    <div class="card"><div class="k">Core decisions auto-cleared</div><div class="num c-green">{N}<small>/ {f["total"]}</small></div><p><b>{f["voucher"]}</b> auto-cleared for voucher issuance ({money(f["voucher_sum"])} in Ryde vouchers) and <b>{f["noref"]}</b> with no refund due. Each one passed the pre-execution policy check.</p></div>
    <div class="arrow" aria-hidden="true">→</div>
    <div class="card"><div class="k">Sent to a person</div><div class="num c-amber">{H}</div><p>{human_note} They arrive with the facts, both arguments and the policy trace already prepared.</p></div>
  </div>
  <div class="bar" role="img" aria-label="{N} auto-cleared, {H} sent to a person"><i class="a" style="width:{pct_auto}%"></i><i class="h" style="width:{pct_h}%"></i></div>
  <div class="legend"><span><i style="background:var(--green)"></i>Cleared by the policy check ({pct_auto}%)</span><span><i style="background:var(--amber)"></i>Human review ({pct_h}%)</span></div>


  <div class="meta">Mean handling time {f["lat_mean"]:.1f} s per case.</div>
</div>

<section id="integration">
  <h2>Where it plugs in</h2>
  <div class="strip">
    <div><div class="k">Inputs</div><h3>What the court reads</h3><p>trip · GPS · chat · fare · profiles · OneMap route · LTA traffic · weather</p></div>
    <div><div class="k">Outputs</div><h3>What it hands back</h3><p>cleared / needs a person · proposed actions · plain-language notices · audit receipt</p></div>
    <div><div class="k">Production connectors (not included)</div><h3>Where Ryde would connect</h3>
      <ul><li>trip records in → one case record</li><li>refund → wallet / voucher API</li><li>account flag → trust and safety queue</li><li>appeals → audit receipt</li></ul></div>
  </div>
</section>

<section id="cases">
  <h2>The cases, by where they land</h2>
  <p class="sub">Each escalated case links to its human review page: the open question, the evidence on it and the decision. Replay shows the full court run.</p>
  <div class="tabs" role="tablist">
    <button class="tab" role="tab" aria-selected="true" aria-controls="p-human" id="t-human" type="button">Needs a human ({H})</button>
    <button class="tab" role="tab" aria-selected="false" aria-controls="p-flag" id="t-flag" type="button"{' aria-describedby="tip-flag"' if flag_tip else ""}>Account actions ({flag_tab}){' <span class="tipi" aria-hidden="true">i</span>' if flag_tip else ""}{flag_tip}</button>
    <button class="tab" role="tab" aria-selected="false" aria-controls="p-auto" id="t-auto" type="button">Auto-cleared ({N})</button>
  </div>
  <div class="panel" id="p-human" role="tabpanel" aria-labelledby="t-human">{table_html(human, "human", "No case needed a human in this batch.")}</div>
  <div class="panel" id="p-flag" role="tabpanel" aria-labelledby="t-flag" hidden>{table_html(flagged, "flag", "No account action was proposed in this batch.")}</div>
  <div class="panel" id="p-auto" role="tabpanel" aria-labelledby="t-auto" hidden>{table_html(auto, "auto", "No case was auto-cleared in this batch.")}</div>
</section>



</main>

<footer>
  <div class="links"><a href="/">Start here</a><a href="/replay.html?case=C-0001">Guided case</a><a href="/report.html">Full results</a></div>
  Akina Court · Ryde Dispute Court · operations hand-off
</footer>
</div>

<script>
(function(){{
  var tabs=document.querySelectorAll('.tab');
  tabs.forEach(function(t){{t.addEventListener('click',function(){{
    tabs.forEach(function(o){{o.setAttribute('aria-selected',o===t?'true':'false');document.getElementById(o.getAttribute('aria-controls')).hidden=(o!==t);}});
  }});}});
  function closePops(){{document.querySelectorAll('.cpop').forEach(function(p){{p.hidden=true;}});document.querySelectorAll('.ctag').forEach(function(b){{b.setAttribute('aria-expanded','false');}});}}
  document.addEventListener('click',function(e){{
    var b=e.target.closest('.ctag');
    if(b){{e.stopPropagation();var p=b.nextElementSibling,open=!p.hidden;closePops();if(!open){{p.hidden=false;b.setAttribute('aria-expanded','true');
      var r=b.getBoundingClientRect(),w=p.offsetWidth,h=p.offsetHeight,left=Math.max(12,Math.min(r.left,innerWidth-w-12)),top=r.bottom+6;
      if(top+h>innerHeight-12)top=Math.max(12,r.top-h-6);p.style.left=left+'px';p.style.top=top+'px';}}return;}}
    if(e.target.closest('.cpop')){{e.stopPropagation();return;}}
    closePops();
  }},true);
  document.addEventListener('keydown',function(e){{if(e.key==='Escape')closePops();}});
  addEventListener('scroll',closePops,true);
}})();
</script>
</body>
</html>
'''


def main() -> None:
    if not COURT.exists():
        sys.exit(f"missing {COURT}")
    rows = load()
    if not rows:
        sys.exit("no primary records found")
    f = funnel(rows)
    models = {json.loads((COURT / f"{r['id']}.json").read_text()).get("model") for r in rows if (COURT / f"{r['id']}.json").exists()}
    models.discard(None)
    model = ", ".join(sorted(models)) if models else "DeepSeek-chat"
    if "deepseek-chat" in model.lower():
        model = "DeepSeek-chat"
    html_text = page(rows, f, model)
    # the wording rules apply to this page's own copy; quoted model and record text (claims, facts, notices, statements) is exempt
    own_copy = re.sub(r'<li>.*?</li>|<pre>.*?</pre>|<p class="quote">.*?</p>|<p class="small">.*?</p>', '', html_text, flags=re.S)
    for bad in ("paid automatically", "executed automatically", "accurate", "—"):
        if bad in own_copy:
            sys.exit(f"wording rule violated: {bad!r} found in page")
    OUT.write_text(html_text)
    print(f"cases={f['total']} auto={f['auto']} (voucher={f['voucher']}, no_refund={f['noref']}, other={f['other']}) "
          f"human={f['human']} flags={f['flags']} voucher_total=${f['voucher_sum']:.2f} "
          f"latency_mean={f['lat_mean']:.1f}s max={f['lat_max']:.1f}s")
    print("human:", ", ".join(f["human_ids"]))
    print("flags:", ", ".join(f["flag_ids"]))
    for r in rows:
        if not r["auto"]:
            reasons = r["elig"].get("reasons") or [r["ruling"].get("escalation_reason") or ""]
            print(f"  {r['id']} {r['title']}: " + " · ".join(plain_reason(reasons[0], r['rec'])))
    print(f"wrote {OUT.relative_to(ROOT)} ({OUT.stat().st_size / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
