#!/usr/bin/env python3
"""One source for every figure the judge-facing pages quote: the `numbers` block scripts/build_submission.py derives
from the benchmark files. This script writes those figures into the hand-written pages; nothing is typed by hand.

    .venv/bin/python scripts/sync_numbers.py            # rewrite README.md, web/index.html, web/i18n.zh.js in place
    .venv/bin/python scripts/sync_numbers.py --check    # exit 1 and list what is stale (tests/test_numbers.py runs this)

Marker syntax
  README.md, web/index.html   <!--n:PATH[:FMT]-->value<!--/n-->     the value between the markers is replaced
                              <!--gen:audit_model|audit_runs-->      README sentences that exist only while an audit sample is stored
                              <!--chart:NAME-->...<!--/chart-->      the whole block is regenerated (bar charts)
                              <!--gen:NAME-->...<!--/gen-->          the whole block is regenerated (meta description)
  web/i18n.zh.src.js          {n:PATH[:FMT]}                         rendered into web/i18n.zh.js (keys and values)
PATH walks the numbers block: court.auto, arms.raw.exact, per_arm.court.latency_mean_s, provenance.calls ...
Derived paths: court.auto_pct, court.human_pct, arms.<arm>.exact_pct, per_arm.<arm>.cites_pct, provenance.calls_c (with
thousands separator), court.auto_pct etc. FMT is a Python format spec (e.g. .1f). A missing path is an error, never a blank.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

PAGES = ["README.md", "web/index.html"]
I18N_SRC, I18N_OUT = ROOT / "web" / "i18n.zh.src.js", ROOT / "web" / "i18n.zh.js"
TOKEN = re.compile(r"\{n:([a-zA-Z0-9_.]+)(?::([^}]+))?\}")
MARK = re.compile(r"<!--n:([a-zA-Z0-9_.]+)(?::([^>]+?))?-->(.*?)<!--/n-->", re.S)
CHART = re.compile(r"<!--chart:([a-z_]+)-->.*?<!--/chart-->", re.S)
GEN = re.compile(r"<!--gen:([a-z_]+)-->.*?<!--/gen-->", re.S)
ARMS = ("raw", "facts_only", "judge_only", "court")
ARM_LABEL = {"raw": "Raw LLM, one call", "facts_only": "Facts by code, one call", "judge_only": "Judge + policy check", "court": "Full court"}


def numbers() -> dict:
    import build_submission
    n = build_submission.build()["numbers"]
    cases = n["cases"]
    n["court"]["auto_pct"] = round(n["court"]["auto"] / cases * 100)
    n["court"]["human_pct"] = round(n["court"]["human"] / cases * 100)
    for arm in ARMS:
        n["arms"][arm]["exact_pct"] = round(n["arms"][arm]["exact"] / cases * 100)
        pa = n["per_arm"][arm]
        pa["cites_pct"] = round(pa["cites_invalid"] / pa["cites_total"] * 100, 1) if pa["cites_total"] else 0.0
    n["provenance"]["calls_c"] = f"{n['provenance']['calls']:,}"
    n["provenance"]["runs_c"] = f"{n['provenance']['runs']:,}"
    n["swap_note"] = ("not yet re-run on this version" if n["court"].get("swap_invariance") is None
                      else f"{n['court']['swap_invariance'] * 100:.0f}% same ruling with rider and driver identities swapped")
    n["repeat_note"] = ("not yet re-run on this version" if n["court"].get("pass_all_repeats") is None
                        else f"{n['court']['pass_all_repeats'] * 100:.0f}% same ruling on repeat")
    return n


def lookup(n: dict, path: str):
    cur = n
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            raise KeyError(f"numbers block has no '{path}'")
        cur = cur[part]
    if cur is None:
        raise KeyError(f"numbers block value '{path}' is not available yet (None)")
    return cur


def fmt(value, spec: str | None) -> str:
    if spec:
        return format(value, spec)
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def render_tokens(text: str, n: dict) -> str:
    return TOKEN.sub(lambda m: fmt(lookup(n, m.group(1)), m.group(2)), text)


def render_markers(text: str, n: dict) -> str:
    def one(m):
        return f"<!--n:{m.group(1)}{':' + m.group(2) if m.group(2) else ''}-->{fmt(lookup(n, m.group(1)), m.group(2))}<!--/n-->"
    return MARK.sub(one, text)


# ---------------------------------------------------------------------------- generated blocks

def bar_chart(title: str, sub: str, rows: list[tuple[str, float, str]], aria: str, scale_max: float | None = None) -> str:
    """One 340×168 SVG with four horizontal bars; rows = (label, value, printed value). Bars scale to scale_max (or the max)."""
    top = scale_max if scale_max else max((v for _, v, _ in rows), default=1) or 1
    out = [f'<svg class="bench" viewBox="0 0 340 168" role="img" aria-label="{aria}"><text x="0" y="14" class="t">{title}</text><text x="0" y="29" class="s">{sub}</text>']
    for i, (label, v, shown) in enumerate(rows):
        y = 44 + 30 * i
        w = round(132 * v / top, 1)
        fill = "#2d7a4f" if i == 3 else ("#1b5e7d" if i == 2 else "#8a93a6")
        out.append(f'<text x="142" y="{y + 13}" class="l" text-anchor="end">{label}</text><rect x="150" y="{y}" width="{w}" height="18" rx="4" fill="{fill}"/>'
                   f'<text x="{150 + w + 6}" y="{y + 13}" class="v">{shown}</text>')
    out.append("</svg>")
    return "".join(out)


def chart(name: str, n: dict) -> str:
    cases = n["cases"]
    if name == "accuracy":
        rows = [(ARM_LABEL[a], n["arms"][a]["safe"], f"{n['arms'][a]['safe']}/{cases}") for a in ARMS]
        aria = "Right, or handed to a person: " + ", ".join(f"{l} {s}" for l, _, s in rows)
        return f"<!--chart:accuracy-->{bar_chart('Right, or handed to a person', f'right outcome, amount and hand-off, or sent to a reviewer; only a wrong decision that executes counts against a system, of {cases} cases', rows, aria, cases)}<!--/chart-->"
    if name == "exact":
        rows = [(ARM_LABEL[a], n["arms"][a]["exact"], f"{n['arms'][a]['exact']}/{cases}") for a in ARMS]
        aria = "Matched the reference: " + ", ".join(f"{l} {s}" for l, _, s in rows)
        return f"<!--chart:exact-->{bar_chart('Matched the reference', f'outcome, amount and hand-off all right, of {cases} cases; a hand-off counts only where the reference accepts one', rows, aria, cases)}<!--/chart-->"
    if name == "wrong":
        vals = {a: (n["arms"][a]["wrong_executed_single_call"] if a in ("raw", "facts_only") else n["arms"][a]["wrong_and_executed_with_gate"]) for a in ARMS}
        rows = [(ARM_LABEL[a], vals[a], f"{vals[a]}/{cases}") for a in ARMS]
        aria = "Wrong decisions allowed to act: " + ", ".join(f"{l} {s}" for l, _, s in rows)
        return f"<!--chart:wrong-->{bar_chart('Wrong decisions allowed to act', 'no check for the first two systems; the check blocks for the last two', rows, aria, cases)}<!--/chart-->"
    if name == "citations":
        rows = [(ARM_LABEL[a], n["per_arm"][a]["cites_invalid"], f"{n['per_arm'][a]['cites_invalid']} / {n['per_arm'][a]['cites_total']}") for a in ARMS]
        aria = "Invalid citations: " + ", ".join(f"{l} {s}" for l, _, s in rows)
        return f"<!--chart:citations-->{bar_chart('Invalid citations', 'fact ids + clause ids that do not exist or were never read', rows, aria)}<!--/chart-->"
    raise KeyError(f"unknown chart {name}")


# the classic benchmark cases the landing page offers behind "More examples": (scenario name, one-line brief). Case ids,
# titles and outcomes come from the manifest, so the chips follow a regeneration; the briefs carry no figure. A name the
# manifest no longer has is skipped (the brief describes that scenario's reference answer, so it is never re-used).
EXAMPLES = [
    ("rd_port_trust_fastest", "\"Whatever road is fastest, I trust you\": the rider left the route to the driver, so a slower way round is not refunded. A judge alone refunded it; the court refunded nothing and left the open reading to a person."),
    ("sg_port_notice_fare_unchanged", "The surge notice said \"your fare stays at the quoted price\", then the surge was charged: no revised fare was ever stated, so the surge part is refunded."),
    ("ns_driver_cancel_flat_tyre", "The driver waited, messaged and called, then wrote \"Sorry, tyre puncture, car got problem, have to cancel\": a driver's own reason, so the fee is refunded."),
    ("rd_consent_except_road", "\"可以，不要走 Clementi Avenue 2\" (OK, just not Clementi Avenue 2) and the driver never did: the agreement covers the detour, no refund."),
    ("rd_notice_ack_hmm", "The driver said he was taking another road and the rider answered \"hmm ok lor\": an acknowledged notice counts."),
    ("ns_gate_b_refused_to_move", "Driver at the other gate within 200 m, rider asking him to come over: he waited, called and messaged, the fee stands."),
]
OUTCOME = {"no_action": "no refund", "refund_partial": "refund", "refund_full": "fee refunded", "fee_waived": "fee waived", "escalate": "a person decides"}


def examples_block(n: dict) -> str:
    import json
    from bench.ops_page import title_for
    by_name = {c["name"]: c for c in json.loads((ROOT / "data" / "bench" / "manifest.json").read_text())["cases"]}
    chips = []
    for name, brief in EXAMPLES:
        c = by_name.get(name)
        if c is None:
            print(f"sync_numbers: example scenario {name} is not in the manifest; its chip is left out", file=sys.stderr)
            continue
        out = OUTCOME.get(c["truth"]["ruling"], c["truth"]["ruling"].replace("_", " ")) + (" + account flag" if c["truth"].get("flag_account") else "")
        title = title_for(name, c.get("type"))
        chips.append(f'<a class="chip" href="/replay.html?case={c["case_id"]}&phase=court"><b>{title}</b><span>{brief}</span><em>{out}</em></a>')
    summary = f"More examples · {n['cases']} benchmark cases, every one replayable"
    return (f'<!--gen:examples--><details class="audits more"><summary>{summary}</summary><div class="chips">' + "".join(chips)
            + f'<a class="chip go" href="/replay.html?case=B-0001&phase=court"><b>More →</b><span>All {n["cases"]} benchmark cases, one by one, in the replay page.</span></a>'
            + '</div></details><!--/gen-->')


def gen(name: str, n: dict) -> str:
    if name == "examples":
        return examples_block(n)
    pv = n["provenance"]
    if name == "audit_model":      # README bullet, only while an audit sample (bench/audit_sample.py) is stored for these results
        # the block opens at the end of the previous bullet, so an absent sample leaves no empty line or stray marker in the list
        body = (f"\n- **Knowing which model answered.** The API labels its served model `{pv['served_model']}` while we request `deepseek-chat`; "
                "every stored response keeps both ids and the API's own trace ids.") if pv.get("served_model") else ""
        return f"<!--gen:audit_model-->{body}<!--/gen-->"
    if name == "audit_runs":
        body = (f"; {pv['audit_runs']} further runs keep the exact requests and raw responses in `bench/results/audit_sample/`." if pv.get("audit_runs") else ".")
        return f"<!--gen:audit_runs-->{body}<!--/gen-->"
    if name == "meta":
        c = n["court"]
        text = (f"A ride dispute settled in {round(c['latency_mean_s'])} seconds, every ruling on the record. Multi-agent dispute resolution for ride-hailing: "
                f"code computes the facts, two AI advocates and a judge argue, and a pre-execution policy check blocks any unsupported outcome or amount. "
                f"3 agents, {sum(1 for v in n['types'].values() if v)} dispute types (safety always goes to a person), {c['latency_mean_s']:.1f} s per case, {c['auto']}/{n['cases']} cleared automatically, "
                f"{n['arms']['court']['wrong_and_executed_with_gate']} wrong decisions executed.")
        secs = round(c["latency_mean_s"])   # link previews show attribute text raw, so numbers go in here, not as <!--n:--> markers
        og_title = f"Akina Court — a ride dispute settled in {secs} seconds, every ruling on the record"
        og_desc = (f"Two AI advocates and a judge settle ride-hailing disputes in {secs} seconds; code computes the facts and blocks any ruling "
                   "the policy does not support. Tencent Cloud AI CAN DO IT Hackathon SG 2026, Ryde track.")
        return (f'<!--gen:meta--><meta name="description" content="{text}">\n<meta property="og:title" content="{og_title}">\n'
                f'<meta property="og:description" content="{og_desc}"><!--/gen-->')
    raise KeyError(f"unknown block {name}")


def render_page(text: str, n: dict) -> str:
    text = render_markers(text, n)
    text = CHART.sub(lambda m: chart(m.group(1), n), text)
    text = GEN.sub(lambda m: gen(m.group(1), n), text)
    return text


def outputs(n: dict) -> dict[Path, str]:
    out = {}
    for page in PAGES:
        p = ROOT / page
        out[p] = render_page(p.read_text(), n)
    if I18N_SRC.exists():
        out[I18N_OUT] = "// generated by scripts/sync_numbers.py from web/i18n.zh.src.js — edit the .src.js file, not this one\n" + render_tokens(I18N_SRC.read_text(), n)
    return out


def main(argv: list[str]) -> int:
    n = numbers()
    check = "--check" in argv
    stale = []
    for path, text in outputs(n).items():
        if path.exists() and path.read_text() == text:
            continue
        if check:
            stale.append(str(path.relative_to(ROOT)))
        else:
            path.write_text(text)
            print(f"wrote {path.relative_to(ROOT)}")
    if check and stale:
        print("stale (run scripts/sync_numbers.py): " + ", ".join(stale))
        return 1
    if check:
        print("numbers in sync")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
