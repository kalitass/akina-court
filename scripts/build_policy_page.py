#!/usr/bin/env python3
"""Build web/policy.html from policy/policy.md and policy/sources.md.

    python3 scripts/build_policy_page.py          # writes web/policy.html and prints the counts

The page is the judge-facing view of policy/policy.md, the text the agents read: every clause with its label and
source, the contradictions in the official documents and the rules Ryde has not specified. There is no second copy
of the clause text; this script parses policy.md directly. Source codes (O1, A9, B7 ...) resolve to the entries of
policy/sources.md, which the page lists at the end with their links.
"""
from __future__ import annotations

import json
import re
import sys
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
POLICY_MD = ROOT / "policy" / "policy.md"
SOURCES_MD = ROOT / "policy" / "sources.md"
OUT = ROOT / "web" / "policy.html"

# the three clause labels policy.md uses, and how the page shows them
LABELS = {
    "Official": ("green", "Official"),
    "Official + system detail": ("blue", "Official + system detail"),
    "System rule": ("amber", "System rule"),
}

# ruling actions written as `code` in policy.md, shown in plain words (the code stays in the hover text)
ACTION_WORDS = {
    "refund_full": "full refund", "refund_partial": "partial refund", "fee_waived": "fee waived", "no_action": "no action",
    "escalate": "escalate to a person", "flag_account": "account review flag", "goodwill_credit": "goodwill credit",
    "interim_suspension": "interim suspension", "partial_refund": "partial refund",
}

# short names for the source line under a clause; the full title is on the source entry it links to
SHORT = {
    "O1": "Ryde Dispute Resolution Policy v2.1", "O2": "DISP-001 sample case", "O3": "DISP-002 sample case",
    "O4": "DISP-003 sample case", "A1": "Ryde Help Centre: cancellation and waiting fee",
    "A3": "Ryde Help Centre: driver marked arrival", "A7": "Ryde Help Centre: preferred route",
    "A9": "Ryde Help Centre: edit destination fee", "A10": "Ryde Help Centre: driver standards",
    "A14": "Ryde Help Centre: safety and accidents", "B7": "LTA DataMall: traffic speed bands",
}
GROUP_NAMES = {"O": "Official documents (sent by the organisers)", "A": "Ryde Help Centre", "B": "Data definitions"}

CLAUSE_RE = re.compile(r"^\*\*([A-Z]+-\d+)\*\* — (.+?) \[([^\]]+)\]\s*$")
ID_RE = re.compile(r"\b((?:FARE|RD|NS|SURGE|DMG|SAFE|TH|PREC)-\d+)\b")
CODE_RE = re.compile(r"\b([OAB]\d{1,2})\b")
SECT_RE = re.compile(r"§\s?\d+(?:\.\d+)*|Appendix [A-Z]|closing note")
SYSTEM_TAIL = re.compile(r"(?:^|\.\s)((?:(?!\.\s)[^\"])*?):\s*system rule\.?\s*$")

# ----------------------------------------------------------------------------------------------- sources.md

URL_RE = re.compile(r"https?://[^\s;)]+")


def load_sources() -> dict[str, dict]:
    """{code: {id, title, group, what, file, urls, excerpt}} parsed from policy/sources.md (removed entries excluded)."""
    out: dict[str, dict] = {}
    cur = None
    for line in SOURCES_MD.read_text(encoding="utf-8").splitlines():
        if line.startswith("## "):
            cur = None
            continue
        m = re.match(r"^### ([OAB]\d+)\.\s*(.*)$", line)
        if m:
            cur = m.group(1)
            out[cur] = {"id": cur, "title": m.group(2).strip(), "group": cur[0], "what": "", "file": "", "urls": [], "excerpt": ""}
            continue
        if not cur:
            continue
        e = out[cur]
        if line.startswith("- URL:"):
            e["urls"] = list(dict.fromkeys(URL_RE.findall(line)))
        elif line.startswith("- File:"):
            f = re.search(r"`([^`]+)`", line)
            e["file"] = f.group(1) if f else ""
        elif line.startswith("- What it is:"):
            e["what"] = line.split(":", 1)[1].strip()
        elif re.match(r"- Excerpts?:", line):
            e["excerpt"] = line.split(":", 1)[1].strip()
    return out


# ----------------------------------------------------------------------------------------------- policy.md

def load() -> dict:
    """policy.md as {title, lead, legend, sections: [{num, prefix, name, anchor, clauses, body}]}."""
    lines = POLICY_MD.read_text(encoding="utf-8").splitlines()
    doc = {"title": "", "lead": "", "legend": [], "sections": []}
    sec = None
    clause = None
    for line in lines:
        if line.startswith("# ") and not doc["title"]:
            doc["title"] = line[2:].strip()
            continue
        m = re.match(r"^## (\d+)\. (?:([A-Z]+) — )?(.+)$", line)
        if m:
            name = m.group(3).strip()
            anchor = m.group(2).lower() if m.group(2) else re.sub(r"[^a-z]+", "-", re.sub(r"\(.*?\)", "", name).lower()).strip("-")
            sec = {"num": int(m.group(1)), "prefix": m.group(2) or "", "name": name, "anchor": anchor, "clauses": [], "body": []}
            doc["sections"].append(sec)
            clause = None
            continue
        if sec is None:   # the preamble: lead sentence and label legend
            lm = re.match(r"^- \*\*(.+?)\*\*(?: in a Source line)?\s*[:=]\s*(.+)$", line)
            if lm:
                doc["legend"].append((lm.group(1).strip("[]"), lm.group(2).strip()))
            elif line.strip() and not doc["lead"] and not line.startswith(("|", "-", "Source codes")):
                doc["lead"] = line.strip()
            continue
        if line.strip() == "---":
            continue
        cm = CLAUSE_RE.match(line)
        if cm:
            clause = {"id": cm.group(1), "title": cm.group(2).strip(), "label": cm.group(3).strip(), "body": [], "source": ""}
            sec["clauses"].append(clause)
            continue
        if line.startswith("<sub>Source:"):
            src = line[len("<sub>Source:"):].removesuffix("</sub>").strip()
            if clause:
                clause["source"] = src
            else:
                sec["source"] = src
            continue
        (clause["body"] if clause else sec["body"]).append(line)
    return doc


def clauses(doc: dict) -> list[dict]:
    return [c for s in doc["sections"] for c in s["clauses"]]


def parse_source(src: str, reg: dict[str, dict]) -> dict:
    """A clause's Source line as {docs: [(code, [sections])], system_set: str|None, codes: [..], missing: [..]}."""
    system_set = None
    rest = src
    if re.fullmatch(r"system rule\.?", src.strip()):
        return {"docs": [], "system_set": "", "codes": [], "missing": [], "text": src}
    m = SYSTEM_TAIL.search(src)
    if m:
        system_set = m.group(1).strip()
        rest = src[:m.start(1)].strip()
    hits = list(CODE_RE.finditer(rest))
    docs: dict[str, list[str]] = {}
    for i, h in enumerate(hits):
        seg = rest[h.end(): hits[i + 1].start() if i + 1 < len(hits) else len(rest)]
        refs = docs.setdefault(h.group(1), [])
        for r in SECT_RE.findall(seg):
            r = r.replace("§ ", "§")
            if r not in refs:
                refs.append(r)
    codes = list(docs)
    return {"docs": list(docs.items()), "system_set": system_set, "codes": codes,
            "missing": [c for c in codes if c not in reg], "text": src}


# ----------------------------------------------------------------------------------------------- html bits

def cap(text: str) -> str:
    return text[:1].upper() + text[1:]


def inline(text: str) -> str:
    """Escape, then **bold**, `action` in plain words, clause ids and contradiction numbers as links."""
    t = escape(text, quote=False)
    t = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t)
    t = re.sub(r"`([^`]+)`", lambda m: f'<span class="act" title="{m.group(1)}">{ACTION_WORDS[m.group(1)]}</span>'
               if m.group(1) in ACTION_WORDS else f"<code>{m.group(1)}</code>", t)
    t = ID_RE.sub(lambda m: f'<a href="#{m.group(1)}">{m.group(1)}</a>', t)
    t = re.sub(r"section (\d+), (C\d+)", r'section \1, <a href="#\2">\2</a>', t)
    return t


def table(rows: list[str], row_ids: bool = False) -> str:
    cells = [[c.strip() for c in r.strip().strip("|").split("|")] for r in rows if not re.match(r"^\|[\s|:-]+\|$", r.strip())]
    head, body = cells[0], cells[1:]
    th = "".join(f"<th>{inline(c)}</th>" for c in head)
    trs = "".join(
        (f'<tr id="{escape(r[0])}">' if row_ids and re.fullmatch(r"C\d+", r[0]) else "<tr>") + "".join(f"<td>{inline(c)}</td>" for c in r) + "</tr>"
        for r in body)
    return f'<div class="tw"><table><thead><tr>{th}</tr></thead><tbody>{trs}</tbody></table></div>'


def blocks(lines: list[str], row_ids: bool = False) -> str:
    """Markdown paragraphs (one per line), bullet lists and tables."""
    out, i = [], 0
    lines = [l for l in lines]
    while i < len(lines):
        l = lines[i]
        if not l.strip():
            i += 1
            continue
        if l.startswith("|"):
            j = i
            while j < len(lines) and lines[j].startswith("|"):
                j += 1
            out.append(table(lines[i:j], row_ids))
            i = j
            continue
        if l.startswith("- "):
            j = i
            while j < len(lines) and lines[j].startswith("- "):
                j += 1
            out.append("<ul>" + "".join(f"<li>{inline(x[2:])}</li>" for x in lines[i:j]) + "</ul>")
            i = j
            continue
        out.append(f"<p>{inline(l)}</p>")
        i += 1
    return "".join(out)


def src_line(src: str, reg: dict[str, dict]) -> str:
    if not src:
        return ""
    p = parse_source(src, reg)
    parts = []
    for code, refs in p["docs"]:
        name = SHORT.get(code, reg.get(code, {}).get("title", code))
        label = escape(name + (" " + ", ".join(refs) if refs else ""))
        tip = escape(reg.get(code, {}).get("title", code))
        parts.append(f'<a href="#src-{code}" title="{tip}">{label}</a>')
    if p["system_set"] is not None:
        parts.append("Set by this system" + (f": {inline(p['system_set'][:1].lower() + p['system_set'][1:])}" if p["system_set"] else ""))
    wording = "" if not p["docs"] else f'<details class="w"><summary>Source wording</summary><p class="full">{wording_text(src, reg)}</p></details>'
    return f'<div class="src"><b>Source</b> {" · ".join(parts)}</div>{wording}'


def wording_text(src: str, reg: dict[str, dict]) -> str:
    """The Source line as written, with source codes as named links and 'system rule' in plain words."""
    t = escape(src, quote=False)
    t = re.sub(r":\s*system rule\.?\s*$", ": set by this system.", t)
    return CODE_RE.sub(lambda m: f'<a href="#src-{m.group(1)}">{escape(SHORT.get(m.group(1), m.group(1)))}</a>' if m.group(1) in reg else m.group(1), t)


# clauses where the official documents disagree or are silent and the system had to choose: a small "!" next to the
# title explains the choice in plain words on hover or focus
WHY = {
    "TH-2": "Ryde's policy says detours over 2 km go to a person. But Ryde's own example case (DISP-001) had a 4.3 km "
            "detour and settled it automatically with a $3.44 refund. We follow the example: refunds under $10 are settled "
            "by the system.",
    "RD-5": "Ryde's policy says a detour without a traffic reason is refunded, even if the rider was told about it. It also "
            "says a detour the rider agreed to counts as agreed. We read both together: just telling the rider is not "
            "enough, but if the rider clearly said yes before the detour, it was the rider's own choice, so there is no refund.",
    "SURGE-1": "Ryde's policy lists three things a surge notice must say: the new multiplier, the new estimated fare, and that "
               "the rider can cancel for free. It does not say what happens if one is missing. We count a notice that leaves "
               "any of them out as no notice, because the rider could not make a real choice without all three.",
    "DMG-4": "Ryde's policy says a rider who disputes a damage claim goes to a person (§4.4), but it also lets the system decide "
             "a cleaning fee up to $50 when the photos can be checked (§6.2). We follow the more specific rule: a cleaning fee "
             "up to $50 with checkable photos is decided by the system; anything else goes to a person (see C2 below).",
    "NS-1": "Ryde's policy counts the 5-minute free wait from the scheduled pickup time, but its own example case (DISP-002) "
            "counts from when the driver arrived and uses an 8-minute limit written in the trip record. We do both: the "
            "5 minutes count from whichever is later, arrival or the scheduled time; a limit written in the trip record "
            "counts from arrival, as the example does.",
    "NS-9": "Ryde's policy flags a rider with 3 or more no-shows in 30 days. We add one limit: the history can flag the "
            "account for review, but it never decides who is right in this dispute. That rests only on this trip's records.",
}


def why_icon(cid: str) -> str:
    if cid not in WHY:
        return ""
    return (f'<span class="why" tabindex="0" role="note" aria-label="Why we chose this: {escape(WHY[cid])}">!'
            f'<span class="tip"><b>Why we chose this</b>{escape(WHY[cid])}</span></span>')


def official_source(c: dict) -> str:
    """An official clause shown without its implementation detail also drops the source-line tail naming that detail."""
    m = SYSTEM_TAIL.search(c["source"]) if c["label"] == "Official + system detail" else None
    return c["source"][:m.start(1)].rstrip() if m else c["source"]


def clause_html(c: dict, reg: dict[str, dict]) -> str:
    colour, label = LABELS.get(c["label"], ("muted", c["label"]))
    body = c["body"]
    k = next((i for i, l in enumerate(body) if l.startswith("System detail:")), None)
    main = body if k is None else body[:k]      # the page lists the rule and its source; implementation detail is not shown
    return f"""
<li id="{escape(c["id"])}">
  <p class="t"><a class="id" href="#{escape(c["id"])}">{escape(c["id"])}</a> <b>{escape(c["title"])}</b><span class="tag {colour}">{escape(label)}</span>{why_icon(c["id"])}</p>
  <div class="body">{blocks(main)}</div>
  {src_line(official_source(c), reg)}
</li>"""


def section_html(s: dict, reg: dict[str, dict]) -> str:
    if s["clauses"]:
        inner = f'<ol class="clauses">{"".join(clause_html(c, reg) for c in s["clauses"])}</ol>'
    else:
        inner = f'<div class="body">{blocks(s["body"], row_ids=True)}</div>' + src_line(s.get("source", ""), reg)
    return f"""
<section id="{s["anchor"]}">
  <h2>{s["num"]}. {escape(s["name"])}</h2>
  {inner}
</section>"""


def sources_html(reg: dict[str, dict], cited: set[str]) -> str:
    out = []
    for g in "OAB":
        items = []
        for e in (e for e in reg.values() if e["group"] == g and e["id"] in cited):
            hosts = [re.sub(r"^https?://([^/]+).*$", r"\1", u) for u in e["urls"]]
            links = [f'<a href="{escape(u)}" target="_blank" rel="noopener">Open on {escape(h)}{f" ({i + 1})" if len(hosts) > 1 else ""} ↗</a>'
                     for i, (u, h) in enumerate(zip(e["urls"], hosts))]
            case = re.search(r"DISP-\d{3}", e["title"] + " " + e["file"])
            if g == "O" and case:
                links.append(f'<a href="/facts.html?case={case.group(0)}">Open the case in the Facts view</a>')
            what = f'<p class="s">{inline(cap(e["what"]))}</p>' if e["what"] else ""
            file = f'<p class="muted">File: {escape(e["file"])}</p>' if e["file"] else ""
            quote = f'<p class="q">{escape(e["excerpt"])}</p>' if e["excerpt"] else ""
            items.append(f"""
<li id="src-{e["id"]}">
  <p class="t"><span class="id">{e["id"]}</span> <b>{escape(e["title"])}</b></p>
  {what}{quote}{file}{f'<p class="links">{" · ".join(links)}</p>' if links else ""}
</li>""")
        if items:
            out.append(f'<h3>{escape(GROUP_NAMES[g])}</h3><ol class="clauses srcs">{"".join(items)}</ol>')
    return f"""
<section id="sources">
  <h2>Sources</h2>
  <p class="blurb">Every document a clause above names. The official documents take priority; Ryde's public help-centre pages fill in where they are silent.</p>
  {"".join(out)}
</section>"""


# ----------------------------------------------------------------------------------------------- counts and page

def not_specified(doc: dict) -> int:
    s = next((s for s in doc["sections"] if "not specified" in s["name"]), None)
    if not s:
        return 0
    rows = [l for l in s["body"] if l.startswith("|") and not re.match(r"^\|[\s|:-]+\|$", l.strip())]
    return max(0, len(rows) - 1)


def counts(doc: dict) -> dict:
    cs = clauses(doc)
    return {
        "clauses": len(cs),
        "groups": sum(1 for s in doc["sections"] if s["clauses"]),
        "by_label": {k: sum(1 for c in cs if c["label"] == k) for k in LABELS},
        "not_specified": not_specified(doc),
        "contradictions": sum(len([l for l in s["body"] if re.match(r"^\| C\d+ \|", l)]) for s in doc["sections"]),
    }


def page(doc: dict, reg: dict[str, dict]) -> str:
    c = counts(doc)
    cited = {code for x in clauses(doc) for code in parse_source(x["source"], reg)["codes"]}
    cited |= {code for s in doc["sections"] for code in parse_source(s.get("source", ""), reg)["codes"]}
    toc = "".join(f'<a href="#{s["anchor"]}">{escape(s["name"].split(" (")[0])}</a>' for s in doc["sections"]) + '<a href="#sources">Sources</a>'
    legend = "".join(
        f'<li><span class="tag {LABELS[k][0]}">{escape(LABELS[k][1])}</span> {inline(v)}</li>' if k in LABELS
        else f'<li><span class="tag">Set by this system</span> in a source line: {inline(v.replace("set by this system; ", ""))}</li>'
        for k, v in doc["legend"])
    n_off = c["by_label"]["Official"] + c["by_label"]["Official + system detail"]
    sections = "".join(section_html(s, reg) for s in doc["sections"])
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>The rules the court applies</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<script src="/theme.js"></script>
<link rel="stylesheet" href="/styles/base.css">
<meta name="description" content="The {c['clauses']} numbered clauses every Akina Court ruling cites, built on the official Ryde Dispute Resolution Policy, each with its source.">
<style>
*{{box-sizing:border-box}}
html,body{{margin:0;background:var(--bg);color:var(--ink);font-family:var(--sans);font-size:15.5px;line-height:1.55;-webkit-font-smoothing:antialiased}}
html{{scroll-behavior:smooth}}
a{{color:var(--blue);text-decoration:none}}a:hover{{text-decoration:underline}}
a:focus-visible,summary:focus-visible{{outline:2px solid var(--blue);outline-offset:2px}}

.logo{{width:34px;height:34px;border-radius:9px;display:block;flex:none}}
h1{{font-size:clamp(28px,5vw,40px);line-height:1.1;letter-spacing:-.02em;margin:34px 0 12px}}
.lead{{font-size:16.5px;color:var(--ink2);margin:0 0 14px}}
.lead b{{color:var(--ink)}}
ul.legend{{list-style:none;margin:0 0 16px;padding:0;font-size:13.5px;color:var(--ink2)}}
ul.legend li{{margin:4px 0}}
.toc{{display:flex;flex-wrap:wrap;gap:6px 18px;font-size:14px;font-weight:600;padding:12px 0;border-top:1px solid var(--line);border-bottom:1px solid var(--line);margin-bottom:8px}}
section{{padding:22px 0 4px;scroll-margin-top:16px}}
h2{{font-size:21px;letter-spacing:-.01em;margin:0 0 8px}}
h3{{font-size:15px;margin:16px 0 4px;color:var(--ink2)}}
.blurb{{color:var(--muted);margin:0 0 10px;font-size:14px}}
ol.clauses{{list-style:none;margin:0;padding:0}}
ol.clauses>li{{padding:14px 0;border-top:1px solid var(--line);scroll-margin-top:16px}}
ol.clauses>li:target,tr:target{{background:rgba(91,156,255,.07)}}
ol.clauses>li:target{{margin:0 -12px;padding-left:12px;padding-right:12px;border-radius:8px}}
p{{margin:0}}
p.t{{font-size:16px;margin-bottom:6px;display:flex;flex-wrap:wrap;align-items:baseline;gap:8px}}
.id{{font:700 12.5px var(--mono);padding:2px 7px;border-radius:5px;border:1px solid var(--line);background:var(--panel2);color:var(--ink)}}
a.id:hover{{text-decoration:none;border-color:var(--blue)}}
.tag{{font:600 11px var(--mono);letter-spacing:.03em;padding:1px 7px;border-radius:999px;border:1px solid var(--line);color:var(--muted);white-space:nowrap}}
.tag.green{{color:var(--green);border-color:color-mix(in srgb,var(--green) 45%,transparent)}}
.tag.blue{{color:var(--blue);border-color:color-mix(in srgb,var(--blue) 45%,transparent)}}
.tag.amber{{color:var(--amber);border-color:color-mix(in srgb,var(--amber) 45%,transparent)}}
.body p,.how p{{margin:0 0 4px}}
.body ul,.how ul{{margin:2px 0 6px;padding-left:20px}}
.act{{font-weight:600}}
code{{font:12.5px var(--mono);padding:0 4px;border-radius:4px;background:var(--panel2)}}
.why{{position:relative;display:inline-grid;place-items:center;width:17px;height:17px;margin-left:8px;border-radius:50%;background:#fff;color:#111827;border:1px solid var(--line);font:800 11px var(--sans);vertical-align:2px;cursor:help;box-shadow:0 1px 2px rgba(0,0,0,.15)}}
.why .tip{{display:none;position:absolute;left:50%;top:24px;transform:translateX(-50%);z-index:20;width:min(360px,80vw);padding:10px 12px;border-radius:8px;background:var(--panel);color:var(--ink);border:1px solid var(--line);box-shadow:0 8px 24px rgba(0,0,0,.18);font:400 13.5px/1.5 var(--sans);text-align:left;white-space:normal}}
.why .tip b{{display:block;margin-bottom:4px;font-size:12px}}
.why:hover .tip,.why:focus .tip{{display:block}}
.how{{margin:8px 0 6px;padding:8px 12px;border-left:2px solid var(--line);background:var(--panel2);border-radius:0 6px 6px 0;font-size:14px;color:var(--ink2)}}
.how p.h{{font:700 10.5px var(--mono);letter-spacing:.08em;text-transform:uppercase;color:var(--muted);margin-bottom:4px}}
.tw{{overflow-x:auto;margin:6px 0 8px}}
table{{border-collapse:collapse;font-size:14px;min-width:100%}}
th,td{{text-align:left;vertical-align:top;padding:6px 10px;border-bottom:1px solid var(--line)}}
th{{font-size:12px;color:var(--muted);font-weight:600}}
tr{{scroll-margin-top:16px}}
.src{{font-size:13px;color:var(--muted);line-height:1.6;margin:8px 0 2px}}
.src b{{font:700 10.5px var(--mono);letter-spacing:.08em;text-transform:uppercase;margin-right:6px;color:var(--muted)}}
.src a{{color:var(--ink2)}}.src a:hover{{color:var(--blue)}}
details.w{{font-size:13px}}
summary{{cursor:pointer;color:var(--muted);list-style:none;display:inline}}
summary::-webkit-details-marker{{display:none}}
summary::before{{content:"+ ";font-family:var(--mono)}}details[open] summary::before{{content:"- "}}
summary:hover{{color:var(--blue)}}
p.full{{color:var(--ink2);margin:6px 0 4px;font-size:13px}}
p.full a{{color:var(--ink2);text-decoration:underline;text-underline-offset:2px}}
p.q{{color:var(--ink2);font-size:13.5px;margin:4px 0;padding-left:10px;border-left:2px solid var(--line)}}
p.links{{font-size:13px;margin-top:4px;word-break:break-word}}
.muted{{color:var(--muted);font-size:13px}}
footer{{padding:26px 0 40px;color:var(--muted);font-size:13px;border-top:1px solid var(--line);margin-top:28px}}
footer .links{{display:flex;flex-wrap:wrap;gap:16px;margin-bottom:8px;font-weight:600}}
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
<p class="lead">{escape(doc["title"])}: <b>{c['clauses']} numbered clauses</b> in {c['groups']} groups, built on Ryde's official Dispute Resolution Policy v2.1. <b>{n_off}</b> come from the official documents and <b>{c['by_label']['System rule']}</b> are system rules. {escape(doc["lead"])} Every ruling names the clauses it applies, and each clause ends with the document it comes from.</p>
<ul class="legend">{legend}</ul>
<nav class="toc" aria-label="Contents">{toc}</nav>
{sections}
{sources_html(reg, cited)}
</main>
<footer>
  <div class="links"><a href="/">Home</a><a href="/report.html">Full results</a></div>
</footer>
</div>
</body>
</html>
"""


def main() -> int:
    doc, reg = load(), load_sources()
    OUT.write_text(page(doc, reg), encoding="utf-8")
    missing = sorted({m for x in clauses(doc) for m in parse_source(x["source"], reg)["missing"]})
    print(f"wrote {OUT.relative_to(ROOT)} ({OUT.stat().st_size} bytes)")
    print(json.dumps(counts(doc), indent=2))
    if missing:
        print("source codes without an entry in sources.md:", missing)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
