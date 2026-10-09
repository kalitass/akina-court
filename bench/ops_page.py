#!/usr/bin/env python3
"""Generate web/ops.html: the operations hand-off page.

Run:  .venv/bin/python bench/ops_page.py        (stdlib only; idempotent; reads stored artifacts, never runs the court)

A Ryde operations reviewer opens the page and sees, in about twenty seconds, what work disappears and what still
reaches their team after the system processed the 49-case synthetic policy-conformance batch. Every number is computed
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
    "rd_two_segs_incident_seg1": "Two detours · first one excused by incident",
    "rd_two_segs_plain": "Two detours · neither excused",
    "rd_fixed_fare": "Detour on a fixed fare",
    "rd_fixed_fare_consent": "Detour on a fixed fare · consent given",
    "rd_fixed_fare_prior_flag": "Detour on a fixed fare · repeat offender",
    "rd_prior_flag": "Detour · repeat offender",
    "rd_no_deviation": "No detour · rider overstated the route",
    "rd_request_only": "Detour · driver asked, rider never agreed",
    "rd_scope_other": "Detour · complaint about something else",
    "rd_consent_before_prior": "Detour · consent beforehand, driver has history",
    "rd_threat_in_chat": "Detour · threat language in chat",
    "rd_consent_before_light": "Detour · brief consent beforehand",
    "rd_keyword_trap_find_you": "Detour · pickup chat trips the threat keyword",
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
    "safe_keyword_only_in_statement": "Safety · threat word only in driver's statement",
}

ID_RE = re.compile(r"\b((?:RD|NS|SAFE|FARE)-\d+)(\([a-z]\)|\s\((?:i|ii|iii|iv)\))?")
FACT_RE = re.compile(r"\bF(\d{1,2})\b")


def humanize(name: str) -> str:
    """Fallback for a manifest name missing from SCENARIO: 'rd_foo_bar' -> 'Detour · foo bar'."""
    prefix = {"rd": "Detour", "ns": "No-show", "safe": "Safety"}
    head, _, rest = name.partition("_")
    return f"{prefix.get(head, head.title())} · {rest.replace('_', ' ')}"


def esc(s) -> str:
    """HTML-escape; stored data may contain em-dashes, the page may not, so they become plain hyphens."""
    return html.escape(str(s if s is not None else "").replace(" \u2014 ", " - ").replace("\u2014", "-"), quote=True)


def chip(cid: str, label: str | None, cls: str = "chip") -> str:
    t = f' title="{esc(label)}"' if label else ""
    base = re.sub(r"\([a-z]\)$", "", cid)
    if re.fullmatch(r"(RD|NS|SAFE)-\d+", base):   # clause ids open the policy page at that clause
        return f'<a class="{cls}" href="/policy.html#{esc(base)}" target="_blank" rel="noopener"{t}>{esc(cid)}</a>'
    return f'<span class="{cls}"{t}>{esc(cid)}</span>'


def clause_tag(ids: list[str]) -> str:
    """One short tag ("10 clauses") that opens a popover listing every cited clause with its title and policy-page link."""
    if not ids:
        return '<span class="muted">—</span>'
    rows = []
    for c in ids:
        base = re.sub(r"\([a-z]\)$", "", c)
        title = CLAUSE.get(base, "")
        rows.append(f'<a href="/policy.html#{esc(base)}" target="_blank" rel="noopener"><b>{esc(c)}</b><span>{esc(title)}</span></a>')
    n = len(ids)
    return (f'<button type="button" class="ctag" aria-haspopup="true" aria-expanded="false" title="Clauses the ruling cites">{n} clause{"s" if n != 1 else ""} ▾</button>'
            f'<div class="cpop" hidden><div class="cpop-h">Clauses cited in this ruling</div>{"".join(rows)}</div>')


def chipify(text: str, facts: dict[str, str]) -> str:
    """HTML-escape text, then wrap clause ids / fact ids in chips whose title is the plain label."""
    out = esc(text)
    out = ID_RE.sub(lambda m: chip(m.group(1) + (m.group(2) or ""), CLAUSE.get(m.group(1))), out)
    out = FACT_RE.sub(lambda m: chip("F" + m.group(1), facts.get("F" + m.group(1)), "chip f"), out)
    return out


def money(v) -> str:
    return f"${float(v):,.2f}"


def outcome_text(ruling: dict) -> str:
    r = ruling.get("ruling")
    base = OUTW.get(r, str(r))
    if r in ("refund_partial", "refund_full") and ruling.get("amount") is not None:
        return f"{base} {money(ruling['amount'])}"
    return base


def plain_reason(reason: str, rec: dict) -> str:
    """One line, <=140 chars, plain language, no ids. Pattern-based; falls back to a stripped clip of the reason."""
    low = reason.lower()
    dtype = rec["dispute"]["type"]
    keyword_hit = ("keyword" in low or "flagged" in low or "threat" in low) and ("chat" in low or "message" in low)
    if "harass" in low or "sexual" in low:
        return "Harassment alleged in a safety complaint → policy forbids automatic ruling"
    if "dangerous driving" in low:
        if "statement" in low and ("keyword" in low or "flagged" in low):
            return "Safety complaint; threat word in the driver's own statement → human review"
        return "Dangerous driving alleged; no telematics to confirm or refute → safety review"
    if keyword_hit:
        m = re.search(r"\b(driver|rider)(?:'s)?(?: in-app)?(?: chat)?(?: message)?(?: #\d+)?(?: at \d\d:\d\d)?\s+(?:contains|wrote|message)", low)
        m = m or re.search(r"\bin (driver|rider)(?:'s)? chat", low)
        who = (m.group(1) + "'s") if m else "the"
        q = re.search(r'["\u201c]([^"\u201d]{3,40})["\u201d]', reason)
        kw = f' ("{q.group(1)}")' if q else ""
        return f"Threat keyword in {who} chat{kw} → policy forbids automatic ruling"
    if dtype == "safety":
        return "Safety complaint → policy forbids automatic ruling"
    # fallback: strip parenthetical ids, bracketed ids and bare ids, then clip
    s = re.sub(r"\s*\((?:RD|NS|SAFE|FARE)-\d+[^)]*\)", "", reason)
    s = re.sub(r"\s*\[(?:F\d+|(?:RD|NS|SAFE|FARE)-\d+)[^\]]*\]", "", s)
    s = re.sub(r"\b(?:RD|NS|SAFE|FARE)-\d+(?:\([a-z]\))?\b", "policy", s)
    s = re.sub(r"\s{2,}", " ", s).strip()
    return s if len(s) <= 140 else s[:139].rstrip(" ,;:(-") + "…"


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
        man = manifest.get(cid)
        if man is None:
            print(f"warning: {cid} has a record but no manifest entry", file=sys.stderr)
            man = {"name": cid.lower(), "type": rec["dispute"]["type"], "truth": {}, "hard": ""}
        facts_block = rec.get("facts") or {}
        facts = facts_block.get("facts", facts_block if isinstance(facts_block, list) else [])
        elig = rec.get("eligibility") or {}
        ruling = rec.get("ruling") or {}
        actions = elig.get("actions") or []
        flag = bool(ruling.get("flag_account")) or any(
            a.get("type") == "flag_account" or (a.get("mode") or "").startswith("human") and a.get("type") == "flag_account"
            for a in actions)
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
def row_html(r: dict) -> str:
    rec, ruling, elig = r["rec"], r["ruling"], r["elig"]
    reasons = elig.get("reasons") or []
    if r["auto"]:
        why = "Cleared by the policy check: allowed outcome, amount matches the code"
        if r["flag"]:
            why = "Cleared; the account flag goes to a person"
    else:
        why = plain_reason(reasons[0] if reasons else (ruling.get("escalation_reason") or "Escalated by the judge"), rec)
    badge = '<span class="badge ok">auto-cleared</span>' if r["auto"] else '<span class="badge hr">human review</span>'
    clauses = clause_tag(ruling.get("cited_policy") or [])
    lat = f"{r['latency']:.1f} s" if r["latency"] is not None else "n/a"
    flagnote = '<div class="flagnote">+ account flag → a person</div>' if r["flag"] else ""
    out_cls = "c-amber" if ruling.get("ruling") in ("refund_partial", "refund_full", "fee_waived") else ("c-red" if not r["auto"] else "")
    return (f'<tr class="row" data-id="{esc(r["id"])}" tabindex="0" role="button" aria-expanded="false">'
            f'<td><div class="ttl">{esc(r["title"])}</div><span class="cid">{esc(r["id"])}</span></td>'
            f'<td>{esc(TYPE_LABEL.get(r["type"], r["type"]))}</td>'
            f'<td class="{out_cls}"><b>{esc(outcome_text(ruling))}</b>{flagnote}</td>'
            f'<td>{badge}</td><td class="why">{esc(why)}</td><td class="chips">{clauses}</td>'
            f'<td class="mono">{esc(lat)}</td>'
            f'<td><a href="/replay.html?case={esc(r["id"])}&phase=court" onclick="event.stopPropagation()" title="Open the stored court run: map, then every agent step and the ruling">Replay</a></td></tr>')


def drawer_html(r: dict) -> str:
    rec, ruling, elig = r["rec"], r["ruling"], r["elig"]
    fmap = {f["id"]: f["text"] for f in r["facts"]}
    facts = "".join(f'<li>{chip(f["id"], f.get("source"), "chip f")} {chipify(f["text"], fmap)}</li>' for f in r["facts"][:8])
    briefs = rec.get("briefs") or {}

    def claims(side: str) -> str:
        b = briefs.get(side) or {}
        cl = (b.get("claims") or [])[:2]
        if not cl:
            return "<li class='muted'>no brief stored</li>"
        return "".join(f'<li>{chipify(c.get("assertion", ""), fmap)}</li>' for c in cl)

    cert = "".join(f'<li class="{"ok" if ln.startswith("✓") else "no" if ln.startswith("✗") else "info"}">{chipify(ln, fmap)}</li>'
                   for ln in (rec.get("certificate") or []))
    reasons = elig.get("reasons") or []
    if r["auto"]:
        stop = "<p>All checks passed: the policy trace allows this outcome and the amount matches what the code computed. "
        stop += ("The refund is cleared for voucher issuance." if ruling.get("ruling") in ("refund_partial", "refund_full") else "No refund is due.")
        if r["flag"]:
            stop += " The account flag is not cleared: it goes to a person in the trust and safety queue.</p>"
        else:
            stop += "</p>"
    else:
        stop = "".join(f"<p>{chipify(x, fmap)}</p>" for x in reasons) or f"<p>{chipify(ruling.get('escalation_reason') or 'Escalated by the judge.', fmap)}</p>"
    wwc = elig.get("what_would_change") or []
    wwc_html = "".join(f"<li>{chipify(x, fmap)}</li>" for x in wwc) or "<li class='muted'>nothing recorded: no automatic outcome was issued</li>"
    notices = "".join(f'<details><summary>Notice to the {esc(n.get("to"))}</summary><pre>{esc(n.get("text"))}</pre></details>'
                      for n in (rec.get("notices") or []))
    hard = ""
    meta = []
    if r["llm_calls"] is not None:
        pass
    if r["latency"] is not None:
        meta.append(f"{r['latency']:.1f} s")
    if r["input_tokens"]:
        pass
    return f'''<div class="drawer" id="d-{esc(r["id"])}" hidden>
  <div class="dhead"><div><div class="k">{esc(TYPE_LABEL.get(r["type"], r["type"]))} · {esc(r["id"])}</div><h3>{esc(r["title"])}</h3>
    <div class="muted small">{esc(" · ".join(meta))}</div></div>
    <button class="close" type="button" aria-label="Close details">Close</button></div>
  <div class="dgrid">
    <div>
      <div class="k">Dispute statement</div><p class="quote">{esc(rec["dispute"].get("statement"))}</p>
      <div class="k">Trip summary</div><p>{esc((rec.get("trip_summary") or {}).get("text"))}</p>
      {hard}
      <div class="k">Proposed outcome</div><p><b>{esc(outcome_text(ruling))}</b>{" · account flag → a person" if r["flag"] else ""}</p>
      <p class="small">{chipify(ruling.get("recommended_action") or "", fmap)}</p>
      <div class="k">Facts the code computed</div><ul class="facts">{facts}</ul>
    </div>
    <div>
      <div class="k">What each side argued</div>
      <div class="side"><b>Rider's advocate</b><ul>{claims("rider")}</ul></div>
      <div class="side"><b>Driver's advocate</b><ul>{claims("driver")}</ul></div>
      <div class="k">Policy trace</div><ul class="cert">{cert}</ul>
      <div class="k">{"Why it was cleared" if r["auto"] else "Why automation stopped"}</div>{stop}
      <div class="k">What would change this ruling</div><ul>{wwc_html}</ul>
      <div class="k">Notices</div>{notices or "<p class='muted'>none stored</p>"}
      <p><a class="btn" href="/replay.html?case={esc(r["id"])}&phase=court">Replay: the court on this case</a> <a class="btn" href="/replay.html?case={esc(r["id"])}">the trip on the map</a></p>
    </div>
  </div>
</div>'''


def table_html(rows: list[dict], key: str, empty: str) -> str:
    if not rows:
        return f'<p class="muted">{esc(empty)}</p>'
    head = ("<tr><th>Case</th><th>Dispute type</th><th>Proposed outcome</th><th>Automation</th><th>Why it stopped</th>"
            "<th>Clauses</th><th>Time</th><th>Replay</th></tr>")
    body = "".join(row_html(r) for r in rows)
    drawers = "".join(drawer_html(r) for r in rows)
    return f'<div class="tw"><table>{head}{body}</table></div><div class="drawers">{drawers}</div>'


def page(rows: list[dict], f: dict, model: str) -> str:
    human = [r for r in rows if not r["auto"]]
    flagged = [r for r in rows if r["flag"]]
    auto = [r for r in rows if r["auto"]]
    H, A, N = f["human"], f["flags"], f["auto"]
    gen = dt.date.today().isoformat()
    pct_auto = round(100 * N / f["total"]) if f["total"] else 0
    pct_h = 100 - pct_auto
    all_safety = human and all(any(c.startswith("SAFE-") for c in (r["ruling"].get("cited_policy") or [])) for r in human)
    human_note = ("Every one is a safety complaint or a threat-language hit; the policy allows only human review for those."
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
<script>(function(){{var q=new URLSearchParams(location.search),st=q.get('style');try{{if(st===null)st=localStorage.getItem('style')||'';}}catch(e){{st=st||''}}if(st==='dark')st='';if(!st)return;var l=document.createElement('link');l.rel='stylesheet';l.href='/styles/'+st+'.css';var add=function(){{document.head.appendChild(l)}};document.readyState==='loading'?document.addEventListener('DOMContentLoaded',add):add();document.documentElement.dataset.style=st;}})();</script>
<meta name="description" content="What reaches a human after the 49-case synthetic policy-conformance batch: {N} core decisions cleared by the policy check, {H} sent to a person, {A} account flags always routed to a person.">
<style>
:root{{--bg:#0a0e15;--panel:#0f141c;--panel2:rgba(255,255,255,.04);--line:rgba(255,255,255,.09);--ink:#e9ecf2;--ink2:#c3c9d6;--muted:#8a93a6;--blue:#5b9cff;--amber:#f5b544;--red:#ff5c5c;--green:#3ad29f;--purple:#b48cff;
  --mono:"SF Mono",Menlo,Consolas,monospace;--sans:-apple-system,BlinkMacSystemFont,"SF Pro Text","Inter","Segoe UI","Helvetica Neue",Arial,sans-serif}}
*{{box-sizing:border-box}}
html,body{{margin:0;background:var(--bg);color:var(--ink);font-family:var(--sans);font-size:15px;line-height:1.5;-webkit-font-smoothing:antialiased}}
a{{color:var(--blue);text-decoration:none}}a:hover{{text-decoration:underline}}
a:focus-visible,button:focus-visible,.row:focus-visible{{outline:2px solid var(--blue);outline-offset:2px}}
.wrap{{max-width:1120px;margin:0 auto;padding:0 20px}}
header{{padding:26px 0 6px;display:flex;align-items:center;gap:12px}}
.logo{{width:34px;height:34px;border-radius:9px;display:block}}
header .t{{font-weight:700;font-size:15px}}header .s{{font-size:12px;color:var(--muted)}}
header nav{{margin-left:auto;display:flex;gap:16px;font-size:13px;font-weight:600}}
.hero{{padding:30px 0 6px}}
h1{{font-size:clamp(32px,5vw,50px);line-height:1.05;letter-spacing:-.025em;margin:0 0 14px;max-width:900px}}
.lead{{font-size:18px;color:var(--ink2);max-width:880px;margin:0 0 16px}}
.lead b{{color:var(--ink)}}
.btn{{display:inline-flex;align-items:center;gap:8px;padding:10px 16px;border-radius:10px;font-weight:700;font-size:14px;border:1px solid var(--line);background:var(--panel2);color:var(--ink)}}
.btn:hover{{text-decoration:none;filter:brightness(1.1)}}
.meta{{font:12px var(--mono);color:var(--muted);margin-top:6px}}
.grid{{display:grid;gap:14px}}
.g3{{grid-template-columns:repeat(3,1fr)}}.g4{{grid-template-columns:repeat(4,1fr)}}
@media(max-width:860px){{.g3,.g4{{grid-template-columns:1fr 1fr}}}}
@media(max-width:560px){{.g3,.g4{{grid-template-columns:1fr}}header nav{{display:none}}}}
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
.tab{{padding:9px 14px;border-radius:999px;border:1px solid var(--line);background:var(--panel2);color:var(--ink2);font-weight:700;font-size:13.5px;cursor:pointer;font-family:inherit}}
.tab[aria-selected=true]{{background:#fff;color:#111;border-color:transparent}}
.panel[hidden]{{display:none}}
.tw{{overflow-x:auto;-webkit-overflow-scrolling:touch;border:1px solid var(--line);border-radius:14px;background:var(--panel)}}
table{{width:100%;min-width:720px;border-collapse:collapse;font-size:13.5px}}
th{{text-align:left;font-size:11px;letter-spacing:.08em;text-transform:uppercase;color:var(--muted);padding:10px 10px;border-bottom:1px solid var(--line);white-space:nowrap}}
td{{padding:9px 10px;border-bottom:1px solid var(--line);vertical-align:top;color:var(--ink2)}}
tr.row{{cursor:pointer}}tr.row:hover td{{background:var(--panel2)}}tr.row.open td{{background:rgba(91,156,255,.08)}}
tr.row:last-child td{{border-bottom:0}}
td:first-child{{min-width:170px}}td .ttl{{color:var(--ink);font-weight:600}}td.mono{{white-space:nowrap}}
.cid{{color:var(--muted);font:11px var(--mono)}}
td.why{{min-width:200px;max-width:300px}}
.flagnote{{font-size:11.5px;color:var(--purple);font-weight:600}}
.badge{{display:inline-block;padding:2px 9px;border-radius:999px;font:700 11px var(--mono);white-space:nowrap;border:1px solid}}
.badge.ok{{color:var(--green);border-color:rgba(58,210,159,.45);background:rgba(58,210,159,.08)}}
.badge.hr{{color:var(--amber);border-color:rgba(245,181,68,.45);background:rgba(245,181,68,.08)}}
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
/* drawer */
.drawer{{margin-top:12px;border:1px solid rgba(91,156,255,.4);border-radius:14px;background:var(--panel);padding:16px 18px}}
.dhead{{display:flex;align-items:flex-start;gap:12px;border-bottom:1px solid var(--line);padding-bottom:10px;margin-bottom:12px}}
.dhead .close{{margin-left:auto;background:var(--panel2);border:1px solid var(--line);color:var(--ink);border-radius:8px;padding:6px 12px;font-weight:700;cursor:pointer;font-family:inherit}}
.dgrid{{display:grid;grid-template-columns:1fr 1fr;gap:22px}}
@media(max-width:860px){{.dgrid{{grid-template-columns:1fr}}}}
.dgrid .k{{margin-top:12px}}.dgrid .k:first-child{{margin-top:0}}
.dgrid p{{margin:4px 0 6px;font-size:14px;color:var(--ink2)}}
.dgrid ul{{margin:4px 0 6px;padding-left:18px;font-size:13.5px;color:var(--ink2)}}
.dgrid li{{margin:3px 0}}
.quote{{border-left:3px solid var(--line);padding-left:10px;font-style:italic}}
.side{{margin:4px 0 8px}}.side b{{font-size:13px;color:var(--ink)}}
.cert{{list-style:none;padding-left:0}}.cert li{{font-family:var(--mono);font-size:12px;padding-left:4px}}
.cert li.ok{{color:var(--green)}}.cert li.no{{color:var(--muted)}}.cert li.info{{color:var(--ink2)}}
details{{margin:6px 0}}summary{{cursor:pointer;color:var(--blue);font-weight:600;font-size:13.5px}}
pre{{white-space:pre-wrap;font:13px/1.5 var(--sans);color:var(--ink2);background:var(--panel2);border:1px solid var(--line);border-radius:10px;padding:10px 12px;margin:6px 0}}
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
@media(max-width:560px){{.wrap{{padding:0 16px}}h1{{font-size:32px}}.lead{{font-size:16px}}.num{{font-size:32px}}.dgrid{{gap:14px}}}}
</style>
</head>
<body>
<div class="wrap">
<header>
  <a href="/" aria-label="Akina Court home"><img class="logo" src="/logo.svg" alt="Akina Court logo" width="34" height="34"></a>
  <div><div class="t">Akina Court</div><div class="s">Ryde Dispute Court · operations hand-off · what the system clears and what still reaches your team</div></div>
  <nav aria-label="Site"><a href="/">Home</a><a href="/replay.html?case=C-0001&amp;phase=court">Watch</a><a href="/policy.html">Policy</a><a href="/report.html">Results</a></nav>
</header>

<main>
<div class="hero">
  <h1>What reaches a human after {f["total"]} cases</h1>
  <p class="lead">A 49-case synthetic benchmark, not live Ryde volume. Each count is recomputed from the stored rulings.</p>

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
  <p class="sub">Click a row for the full hand-off: statement, computed facts, both sides' arguments, the policy trace, the reason automation stopped and the notices each party would receive.</p>
  <div class="tabs" role="tablist">
    <button class="tab" role="tab" aria-selected="true" aria-controls="p-human" id="t-human" type="button">Needs a human ({H})</button>
    <button class="tab" role="tab" aria-selected="false" aria-controls="p-flag" id="t-flag" type="button">Account actions ({A})</button>
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
  function toggle(tr){{
    var id=tr.getAttribute('data-id'),panel=tr.closest('.panel'),d=panel.querySelector('#d-'+id),open=!d.hidden;
    panel.querySelectorAll('.drawer').forEach(function(x){{x.hidden=true;}});
    panel.querySelectorAll('tr.row').forEach(function(x){{x.classList.remove('open');x.setAttribute('aria-expanded','false');}});
    if(!open){{d.hidden=false;tr.classList.add('open');tr.setAttribute('aria-expanded','true');
      if(window.matchMedia('(max-width:860px)').matches)d.scrollIntoView({{behavior:'smooth',block:'start'}});}}
  }}
  document.querySelectorAll('tr.row').forEach(function(tr){{
    tr.addEventListener('click',function(){{toggle(tr);}});
    tr.addEventListener('keydown',function(e){{if(e.key==='Enter'||e.key===' '){{e.preventDefault();toggle(tr);}}}});
  }});
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
  document.querySelectorAll('.drawer .close').forEach(function(b){{b.addEventListener('click',function(){{
    var d=b.closest('.drawer'),panel=d.closest('.panel');d.hidden=true;
    var tr=panel.querySelector('tr.row[data-id="'+d.id.slice(2)+'"]');if(tr){{tr.classList.remove('open');tr.setAttribute('aria-expanded','false');}}
  }});}});
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
            print(f"  {r['id']} {r['title']}: {plain_reason(reasons[0], r['rec'])}")
    print(f"wrote {OUT.relative_to(ROOT)} ({OUT.stat().st_size / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
