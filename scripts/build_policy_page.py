#!/usr/bin/env python3
"""Build web/policy.html from policy/clauses_en.json and policy/sources.md.

    python3 scripts/build_policy_page.py          # writes web/policy.html and prints the counts

The page is the judge-facing English view of policy/policy.md: a plain summary of every clause the court may cite,
grouped by dispute type, with the source of each clause as a direct link to the document it comes from.
policy.md stays the only text the agents read; this page renders policy/clauses_en.json (a hand translation of it)
and resolves the source ids (A1, B1 ...) to the URLs recorded in policy/sources.md.
"""
from __future__ import annotations

import json
import re
import sys
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "policy" / "clauses_en.json"
SOURCES_MD = ROOT / "policy" / "sources.md"
OUT = ROOT / "web" / "policy.html"

GROUPS = [
    ("route_deviation", "rd", "Route deviation", "RD", "When a longer route counts against the driver, and how much the rider gets back."),
    ("no_show", "ns", "No-show and cancellation", "NS", "When Ryde's $6.61 cancellation fee and $5 waiting fee may be charged."),
    ("fare", "fare", "Fare", "FARE", "What may be added to a fixed fare, and tolls."),
    ("safety", "safe", "Safety", "SAFE", "Cases the court never decides on its own."),
]

KIND = {
    "Ryde first-hand": ("green", "Ryde official", "Stated directly in Ryde's Help Centre or Terms of Use."),
    "Derived from": ("blue", "Derived", "Ryde has published nothing; derived from Singapore law, LTA / PTC rules and peer platforms' published terms."),
    "Gap: no source": ("amber", "Gap", "No document supports it; kept as an open question for Ryde, never cited."),
}

ORIGIN = {
    "A": ("Ryde official", "Help Centre articles and Terms of Use. Read through Ryde's public Zendesk pages."),
    "B": ("Singapore law and regulators", "Road Traffic Rules on Singapore Statutes Online, LTA demerit and fare rules, PTC fare rules, LTA DataMall."),
    "C": ("Singapore peer platforms", "Grab, Gojek, ComfortDelGro and Zig: published cancellation, route and conduct rules."),
    "D": ("International reference", "NYC TLC, Transport for London, Uber and GPS.gov: supporting references only."),
}

TITLE_OVERRIDE = {
    "A18": "Other Ryde Help Centre articles (cancellation scope, RydeTAXI meter, fare calculation, dashcams)",
    "C7": "Tada cancellation rule (press report, reference only)",
    "E": "This system's code (core/): measurement parameters and procedure, never cited",
}

# ----------------------------------------------------------------------------------------------- sources.md

URL_RE = re.compile(r"https?://[^\s）]+")


def load_sources() -> dict[str, dict]:
    """{id: {title, urls, quote, category}} parsed from policy/sources.md."""
    out: dict[str, dict] = {}
    cur = None
    for line in SOURCES_MD.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^### ([A-D]\d+)\.\s*(.*)$", line)
        if m:
            cur = m.group(1)
            title = re.sub(r"（.*?）", "", m.group(2)).strip()
            out[cur] = {"id": cur, "title": title, "urls": [], "quote": "", "category": cur[0]}
            continue
        if line.startswith("## E."):
            cur = "E"
            out[cur] = {"id": "E", "title": "", "urls": [], "quote": "", "category": "E"}
            continue
        if line.startswith("## F."):
            cur = None
            continue
        if not cur:
            continue
        for u in URL_RE.findall(line):
            out[cur]["urls"].append(u.rstrip("；;，,。"))
        for i in re.findall(r"…/(\d+)", line):
            out[cur]["urls"].append(f"https://help.rydesharing.com/hc/en-us/articles/{i}")
        if line.startswith("- 摘录：") and not out[cur]["quote"]:
            q = re.findall(r"[“\"]([^”\"]{12,})[”\"]", line)
            out[cur]["quote"] = q[0] if q else ""
    for k, e in out.items():
        e["urls"] = list(dict.fromkeys(e["urls"]))
        if k in TITLE_OVERRIDE or re.search(r"[一-鿿]", e["title"]):
            e["title"] = TITLE_OVERRIDE.get(k, re.sub(r"[一-鿿]+", "", e["title"]).strip())
    return out


# ----------------------------------------------------------------------------------------------- data

def load() -> list[dict]:
    return json.loads(SRC.read_text(encoding="utf-8"))


def counts(rows: list[dict]) -> dict:
    sourced = [r for r in rows if r["group"] in ("route_deviation", "no_show", "fare", "safety")]
    citable = [r for r in sourced if r["citable"]]
    return {
        "sourced": len(sourced),
        "citable": len(citable),
        "citable_ryde": sum(1 for r in citable if r["source_kind"] == "Ryde first-hand"),
        "citable_derived": sum(1 for r in citable if r["source_kind"] == "Derived from"),
        "ryde": sum(1 for r in sourced if r["source_kind"] == "Ryde first-hand"),
        "informational": sum(1 for r in sourced if not r["citable"]),
        "gaps": sum(1 for r in rows if r["group"] == "gap"),
        "by_group": {g: sum(1 for r in rows if r["group"] == g) for g, *_ in GROUPS},
    }


# ----------------------------------------------------------------------------------------------- html bits

ORG = {"A16": "Ryde Terms of Use", "B1": "Singapore Statutes Online", "B2": "LTA", "B3": "LTA", "B4": "LTA", "B5": "LTA",
       "B6": "PTC", "B7": "LTA DataMall", "B8": "Singapore Courts", "C1": "Grab", "C2": "Grab", "C3": "Gojek", "C4": "CDG Zig",
       "C5": "ComfortDelGro", "C6": "ComfortDelGro", "C7": "Mothership (Tada)", "D1": "NYC TLC", "D2": "Transport for London",
       "D3": "Uber", "D4": "Uber", "D5": "GPS.gov", "E": "This system's code"}


def org(sid: str) -> str:
    return ORG.get(sid, "Ryde Help Centre" if sid.startswith("A") else sid)


# Short source names for the clause tail line; the full title and the quoted passage stay in the hover text.
SHORT = {
    "A1": "Ryde: Cancellation and Waiting Fee", "A2": "Ryde: Cancellation and Waiting Time Policy",
    "A3": "Ryde: driver says arrived but has not", "A4": "Ryde: fee waiver request", "A5": "Ryde: how the fees work",
    "A6": "Ryde: platform fee", "A7": "Ryde: suggested route", "A8": "Ryde: ERP and tolls", "A9": "Ryde: edit destination fee",
    "A10": "Ryde: driver standards", "A11": "Ryde: irregular trip behaviour", "A12": "Ryde: trip completed without the rider",
    "A13": "Ryde Code of Conduct", "A14": "Ryde: report a safety issue", "A15": "Ryde: rider made a mess",
    "A16": "Ryde Terms of Use", "A18": "Ryde: RydeTAXI and fare articles",
    "B1": "SG Road Traffic Rules", "B2": "LTA demerit points", "B4": "LTA enforcement on taxi drivers", "B5": "LTA taxi fares",
    "B6": "PTC point-to-point fares", "B7": "LTA DataMall", "C1": "Grab cancellation policy", "C2": "Grab driver Code of Conduct",
    "C3": "Gojek cancellation fees", "C4": "CDG Zig route choice", "C5": "ComfortDelGro cancellation policy",
    "C6": "ComfortDelGro fares", "C7": "Tada (press report)", "D1": "NYC TLC rules", "D2": "Transport for London",
    "D3": "Uber fare review", "D4": "Uber", "D5": "GPS.gov accuracy", "E": "Set in the code",
}
SHOWN = 2  # sources shown before the "+N more" fold
RANK = {"Derived from": "BACDE", "Ryde first-hand": "ABCDE"}  # a derived clause leads with the law, a Ryde clause with Ryde


def src_line(srcs: list[dict], reg: dict[str, dict], kind: str = "Ryde first-hand") -> str:
    """The tail line of a clause: Source SG Road Traffic Rules r.23 ↗ · LTA demerit points ↗ +4 more"""
    order = RANK.get(kind, "ABCDE")
    srcs = sorted(srcs, key=lambda s: order.index(s["id"][0]) if s["id"][0] in order else 9)
    parts = []
    for s in srcs:
        e = reg.get(s["id"], {"title": s.get("what", ""), "urls": [], "quote": ""})
        title = e["title"] or s.get("what", "")
        tip = f'{org(s["id"])} — {title}' + (f' — “{s["quote"]}”' if s.get("quote") else "")
        label = SHORT.get(s["id"], org(s["id"]))
        rule = re.search(r"\br\.\s?\d+", s.get("what", "")) if s["id"] == "B1" else None
        if rule:
            label += " " + rule.group(0).replace(" ", "")
        label = escape(label)
        if e["urls"]:
            parts.append(f'<a href="{escape(e["urls"][0])}" target="_blank" rel="noopener" title="{escape(tip)}">{label} ↗</a>')
        else:
            parts.append(f'<span title="{escape(tip)}">{label}</span>')
    if not parts:
        return ""
    head, rest = parts[:SHOWN], parts[SHOWN:]
    more = f' <details class="more"><summary>+{len(rest)} more</summary> · {" · ".join(rest)}</details>' if rest else ""
    return f'<div class="src"><b>Source</b> {" · ".join(head)}{more}</div>'


def clause(r: dict, reg: dict[str, dict]) -> str:
    cid = r["id"]
    kind = KIND[r["source_kind"]][1]
    return f"""
<li id="{escape(cid)}">
  <p class="t"><a class="id" href="#{escape(cid)}">{escape(cid)}</a> <b>{escape(r["title"][:1].upper() + r["title"][1:])}</b><span class="kind">{escape(kind)}</span></p>
  <p class="s">{escape(r["summary_en"])}</p>
  <details><summary>Full text</summary><p class="full">{escape(r["rule_en"])}</p>{f'<p class="full muted">{escape(r["notes_en"])}</p>' if r.get("notes_en") else ""}</details>
  {src_line(r["sources"], reg, r["source_kind"])}
</li>"""


def section(n: int, group: str, anchor: str, name: str, prefix: str, blurb: str, rows: list[dict], reg: dict) -> str:
    items = "".join(clause(r, reg) for r in rows if r["group"] == group)
    return f"""
<section id="{anchor}">
  <h2>{n}. {escape(name)}</h2>
  <p class="blurb">{escape(blurb)}</p>
  <ol class="clauses">{items}</ol>
</section>"""


def gaps_section(n: int, rows: list[dict], reg: dict) -> str:
    items = "".join(
        f'<li id="{escape(r["id"])}"><p class="t"><a class="id" href="#{escape(r["id"])}">{escape(r["id"])}</a> <b>{escape(r["title"][:1].upper() + r["title"][1:])}</b></p>'
        f'<p class="s">{escape(r["value_en"])}</p></li>'
        for r in sorted((r for r in rows if r["group"] == "gap"), key=lambda r: int(r["id"][1:])))
    return f"""
<section id="gaps">
  <h2>{n}. Thresholds set by the project</h2>
  <p class="blurb">Ryde and the other published documents give no value for the points below, so the project sets one to let the court rule; Ryde can adjust any of them. None of these is ever cited in a ruling.</p>
  <ol class="clauses gaps">{items}</ol>
</section>"""


# ----------------------------------------------------------------------------------------------- page

def page(rows: list[dict], reg: dict[str, dict]) -> str:
    c = counts(rows)
    premise = next((r for r in rows if r["id"] == "PREMISE"), None)
    toc = "".join(f'<a href="#{a}">{i + 1}. {escape(n)}</a>' for i, (_, a, n, _, _) in enumerate(GROUPS))
    k = len(GROUPS)
    toc += f'<a href="#gaps">{k + 1}. Project thresholds</a>'
    sections = "".join(section(i + 1, g, a, n, p, b, rows, reg) for i, (g, a, n, p, b) in enumerate(GROUPS))
    premise_html = ""
    if premise:
        premise_html = f"""
<section id="premise">
  <h2>Premise. How a Ryde fare works</h2>
  <p class="s">{escape(premise["summary_en"])}</p>
  <details><summary>Full text</summary><p class="full">{escape(premise["rule_en"])}</p></details>
  {src_line(premise["sources"], reg)}
</section>"""
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>The rules the court applies</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<script src="/theme.js"></script>
<link rel="stylesheet" href="/styles/base.css">
<meta name="description" content="The {c['sourced']} numbered clauses every Akina Court ruling cites, grouped by dispute type, each with its source linked.">
<style>
*{{box-sizing:border-box}}
html,body{{margin:0;background:var(--bg);color:var(--ink);font-family:var(--sans);font-size:15.5px;line-height:1.55;-webkit-font-smoothing:antialiased}}
html{{scroll-behavior:smooth}}
a{{color:var(--blue);text-decoration:none}}a:hover{{text-decoration:underline}}
a:focus-visible,summary:focus-visible{{outline:2px solid var(--blue);outline-offset:2px}}

.logo{{width:34px;height:34px;border-radius:9px;display:block;flex:none}}
h1{{font-size:clamp(28px,5vw,40px);line-height:1.1;letter-spacing:-.02em;margin:34px 0 12px}}
.lead{{font-size:16.5px;color:var(--ink2);margin:0 0 18px}}
.lead b{{color:var(--ink)}}
.toc{{display:flex;flex-wrap:wrap;gap:6px 18px;font-size:14px;font-weight:600;padding:12px 0;border-top:1px solid var(--line);border-bottom:1px solid var(--line);margin-bottom:8px}}
section{{padding:22px 0 4px}}
h2{{font-size:21px;letter-spacing:-.01em;margin:0 0 4px}}
.blurb{{color:var(--muted);margin:0 0 10px;font-size:14px}}
ol.clauses{{list-style:none;margin:0;padding:0}}
ol.clauses>li{{padding:14px 0;border-top:1px solid var(--line);scroll-margin-top:16px}}
ol.clauses>li:target{{background:rgba(91,156,255,.07);margin:0 -12px;padding-left:12px;padding-right:12px;border-radius:8px}}
p{{margin:0}}
p.t{{font-size:16px;margin-bottom:4px;display:flex;flex-wrap:wrap;align-items:baseline;gap:8px}}
p.t i{{color:var(--muted);font-size:13px}}
.id{{font:700 12.5px var(--mono);padding:2px 7px;border-radius:5px;border:1px solid var(--line);background:rgba(255,255,255,.04);color:var(--ink)}}
.id:hover{{text-decoration:none;border-color:var(--blue)}}
.kind{{font:600 11px var(--mono);color:var(--muted);letter-spacing:.03em}}
p.s{{color:var(--ink);margin-bottom:6px}}
details{{font-size:13px;margin-bottom:6px}}
summary{{cursor:pointer;color:var(--muted);list-style:none;display:inline}}
summary::before{{content:"+ ";font-family:var(--mono)}}details[open] summary::before{{content:"- "}}
summary:hover{{color:var(--blue)}}
p.full{{color:var(--ink2);margin:6px 0 4px;font-size:13.5px}}
.muted{{color:var(--muted)}}
.src{{font-size:13px;color:var(--muted);line-height:1.6;margin:0 0 1em}}
.src b{{font:700 10.5px var(--mono);letter-spacing:.08em;text-transform:uppercase;margin-right:6px;color:var(--muted)}}
.src a{{color:var(--ink2)}}.src a:hover{{color:var(--blue)}}
.src details.more{{display:inline}}
.src details.more summary{{display:inline;cursor:pointer;list-style:none;color:var(--muted);margin-left:8px;padding:1px 8px;border:1px solid var(--line);border-radius:999px;font-size:12px}}
.src details.more summary::-webkit-details-marker{{display:none}}
.src details.more summary:hover{{color:var(--ink)}}
.src details.more[open] summary{{display:none}}
.src details.more summary::before{{content:none}}
.src details.more[open]::details-content{{display:inline}}
footer{{padding:26px 0 40px;color:var(--muted);font-size:13px;border-top:1px solid var(--line);margin-top:28px}}
footer .links{{display:flex;flex-wrap:wrap;gap:16px;margin-bottom:8px;font-weight:600}}
@media(max-width:560px){{}}
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
<h1>The rules the court applies</h1>
<p class="lead">Every ruling cites one or more of the <b>{c['sourced']} numbered clauses</b> below and nothing else. <b>{c['ryde']}</b> are Ryde's own published terms. Each clause ends with the document it comes from; the link opens it.</p>
<nav class="toc" aria-label="Contents">{toc}</nav>
{premise_html}
{sections}
{gaps_section(k + 1, rows, reg)}
</main>
<footer>
  <div class="links"><a href="/">Home</a><a href="/report.html">Full results</a></div>
</footer>
</div>
</body>
</html>
"""


def main() -> int:
    rows = load()
    reg = load_sources()
    OUT.write_text(page(rows, reg), encoding="utf-8")
    c = counts(rows)
    missing = sorted({s["id"] for r in rows for s in r["sources"] if s["id"] not in reg})
    print(f"wrote {OUT.relative_to(ROOT)} ({OUT.stat().st_size} bytes)")
    print(json.dumps(c, indent=2))
    if missing:
        print("source ids without an entry in sources.md:", missing)
    return 0


if __name__ == "__main__":
    sys.exit(main())
