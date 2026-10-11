#!/usr/bin/env python3
"""Generate an evidence-backed presentation from stored benchmark results only."""
import json
import html
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from bench.report import score


def read(path):
    return json.loads((ROOT / path).read_text())


def esc(value):
    return html.escape(str(value))


def outcome(r):
    return r['ruling'] + (f" · SGD {r['amount']:.2f}" if r.get('amount') is not None else '') + (' · account referral' if r.get('flag_account') else '')


STORIES = [
 ('B-0053', 'Protect both sides, including the driver',
  'The rider authorised a faster route before the deviation. The disagreement is whether that authorisation covers the measured segment.',
  'The single-judge result refunds SGD 2.92 and refers the account. Its narrative and segment finding are internally inconsistent about the scope of consent. The recorded result, not just a persuasive explanation, is what we compare.',
  'Both advocates classify the message as general route consent. The driver challenges the rider’s refund claim using the rider’s own message and the absence of a recorded personal errand. The court applies that shared reading and closes with no refund or account referral.',
  ['F3','F8','F9'], {'driver':['D2','D3','D4'], 'rider':['C3','C4']},
  'A fair dispute system must avoid unsupported refunds and account referrals as well as find valid rider claims.'),
 ('B-0056', 'Consent is not proof of the road actually driven',
  'The rider agrees to Balestier Road. The GPS-derived facts measure a detour but do not name the road travelled.',
  'The single judge refunds SGD 6.68. The reference answer requires escalation because the connection between the driven path and the agreed road is missing.',
  'The briefs disagree about the money. Their final segment grounds both identify named_road_untied. The court preserves that uncertainty and asks for the road-name trace rather than deciding the refund.',
  ['F3','F8','F9'], {'driver':['D1','D3'], 'rider':['C3','C4']},
  'The useful output is the precise unanswered question. This case needs road linkage, not the missing-GPS demonstration’s synthetic trace.'),
 ('B-0061', 'Separate a settled segment from an unresolved one',
  'Two deviations are disputed. The second lacks applicable rider consent; the first needs proof that the driven path matches the agreed road.',
  'The single judge refunds SGD 2.40, treating the first segment as exempt. Its geometry-based explanation does not establish the road-name linkage required by the reference policy interpretation.',
  'The driver revises its requested amount after rebuttal. Both final grounds identify the first segment as named_road_untied and the second as consent_after_or_none. The court transfers the open question with conditional amounts instead of declaring the whole case settled.',
  ['F3','F4','F9','F10','F12'], {'driver':['D1','D3'], 'rider':['C3','C4']},
  'An actionable handoff preserves what is already established and tells the reviewer exactly what would change the amount.')
]


def generate():
    ids = sorted(p.stem for p in (ROOT/'data/bench/expected').glob('B-*.json'))
    scores, runs = {}, {}
    for arm in ('judge_only','court'):
        runs[arm] = {cid:read(f'bench/results/{arm}/{cid}.json') for cid in ids}
        assert all(r.get('ok') for r in runs[arm].values()), 'Incomplete benchmark; do not present partial results as complete'
        scores[arm] = {cid:score(runs[arm][cid], read(f'data/bench/expected/{cid}.json'), set(), set()) for cid in ids}
    wins = [cid for cid in ids if not scores['judge_only'][cid]['exact'] and scores['court'][cid]['exact']]
    losses = [cid for cid in ids if scores['judge_only'][cid]['exact'] and not scores['court'][cid]['exact']]
    failures = [cid for cid in ids if not scores['court'][cid]['exact']]
    def count(a,k): return sum(s[k] for s in scores[a].values())
    def automatic_correct(a): return sum(s['exact'] and s['executed'] for s in scores[a].values())
    rows = [('Exact core result (outcome + amount + escalation)', 'exact'),
            ('Wrong decisions marked eligible to act', 'wrong_executed'),
            ('Cases marked eligible without human review', 'executed')]
    table = ''.join(f'<tr><th>{esc(label)}</th><td>{count("judge_only",key)}/{len(ids)}</td><td>{count("court",key)}/{len(ids)}</td></tr>' for label,key in rows)
    table += f'<tr><th>Correct core result and eligible without human review</th><td>{automatic_correct("judge_only")}/{len(ids)}</td><td>{automatic_correct("court")}/{len(ids)}</td></tr>'
    latency = {a:sum(r['latency_s'] for r in rs.values())/len(rs) for a,rs in runs.items()}
    cards = []
    for cid,title,question,single,debate,fids,claims,value in STORIES:
        assert cid in wins, f'{cid} is no longer a court win; review the editorial story'
        rec = read(f'bench/results/court/{cid}.record.json')
        factmap = {f['id']:f for f in rec['facts']['facts']}
        facts = ''.join(f'<li><b>{fid}</b> {esc(factmap[fid]["text"])}</li>' for fid in fids)
        excerpts = ''
        for side,claimids in claims.items():
            for claimid in claimids:
                claim = next(c for c in rec['briefs'][side]['claims'] if c['id']==claimid)
                assert not claim.get('void'), 'Do not promote a struck claim'
                excerpts += f'<blockquote><b>{side.title()} · {claimid}</b><p>{esc(claim["assertion"])}</p><small>Facts: {esc(", ".join(claim["facts"]))} · Policy: {esc(", ".join(claim["policy"]))}. Advocate claim, not established truth.</small></blockquote>'
        for side in ('rider','driver'):
            rb = rec['rebuttals'][side]
            excerpts += f'<p><b>{side.title()} after rebuttal:</b> {esc(json.dumps(rb["revised_outcome"],ensure_ascii=False))}<br>Segment grounds: {esc(json.dumps(rb["segment_grounds"]))}</p>'
        exp = read(f'data/bench/expected/{cid}.json')
        paths = [f'data/bench/expected/{cid}.json', f'bench/results/judge_only/{cid}.json', f'bench/results/court/{cid}.json', f'bench/results/court/{cid}.record.json']
        links = ' · '.join(f'<a href="https://github.com/kalitass/akina-court/blob/main/{p}">{esc(p)}</a>' for p in paths)
        cards.append(f'''<article id="{cid}"><span class="eyebrow">{cid} · selected court win</span><h2>{esc(title)}</h2><p>{esc(question)}</p>
        <ul class="facts">{facts}</ul><div class="compare"><section><h3>Single judge + policy check</h3><b class="bad">{esc(outcome(runs['judge_only'][cid]['ruling']))}</b><p>{esc(single)}</p></section>
        <section><h3>Full court + policy check</h3><b class="good">{esc(outcome(runs['court'][cid]['ruling']))}</b><p>{esc(debate)}</p></section></div>
        <p><b>Policy-derived synthetic reference:</b> {esc(outcome(exp))}</p><p class="value">{esc(value)}</p>
        <details><summary>Inspect actual advocate excerpts and final reasoning</summary>{excerpts}<h3>Single-judge final reasoning</h3><p class="verbatim">{esc(runs['judge_only'][cid]['ruling']['reasoning'])}</p><h3>Court final reasoning</h3><p class="verbatim">{esc(rec['ruling']['reasoning'])}</p><p>{links}</p></details>
        <nav><a href="/replay.html?case={cid}&phase=court">Stored court replay →</a> <a href="/review.html?case={cid}">Human review page →</a></nav></article>''')
    # B-0053 is automatic: never send it to a misleading human-review page.
    cards[0] = cards[0].replace('<a href="/review.html?case=B-0053">Human review page →</a>', '')
    failuretext = ''.join(f'<li>{cid}: reference {esc(outcome(read(f"data/bench/expected/{cid}.json")))}; court {esc(outcome(runs["court"][cid]["ruling"]))}. Eligible to act: {scores["court"][cid]["executed"]}.</li>' for cid in failures)
    model = {r['model'] for rs in runs.values() for r in rs.values()}
    dates = sorted(r['ts'] for rs in runs.values() for r in rs.values())
    return f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Why a court? · Akina Court</title>
    <style>body{{margin:0;background:#0d131b;color:#e7edf4;font:17px/1.65 system-ui}}main{{max-width:1050px;margin:auto;padding:32px 22px}}a{{color:#7acbff}}h1{{font-size:clamp(32px,6vw,52px);line-height:1.12}}h2{{line-height:1.25}}article,.box{{background:#161f2b;border:1px solid #334152;border-radius:16px;padding:24px;margin:24px 0}}.eyebrow,small{{color:#b1c0d1}}.compare{{display:grid;grid-template-columns:1fr 1fr;gap:20px}}.compare section{{background:#0f1722;padding:18px;border-radius:10px}}.bad{{color:#ffbb8b}}.good{{color:#75e0b3}}.facts li{{margin:12px 0}}.value{{border-left:3px solid #75e0b3;padding-left:16px}}table{{width:100%;border-collapse:collapse}}th,td{{padding:12px;text-align:left;border-bottom:1px solid #334152}}blockquote{{margin:18px 0;padding:14px;border-left:3px solid #7acbff;background:#101925}}summary{{cursor:pointer;font-weight:700}}.verbatim{{white-space:pre-wrap;font-size:15px}}nav{{display:flex;gap:18px;flex-wrap:wrap}}.sources{{overflow-wrap:anywhere}}@media(max-width:680px){{.compare{{grid-template-columns:1fr}}article,.box{{padding:18px}}table{{font-size:14px}}}}</style></head><body><main>
    <nav><a href="/">Akina Court</a><a href="/report.html">Full benchmark</a><a href="/review.html?case=C-0004&scenario=missing_gps">Evidence recovery demonstration</a></nav>
    <h1>Why a court, rather than one judge?</h1><p>Give both sides a voice. Check the evidence. Know when to stop.</p>
    <div class="box"><h2>The comparison, including its trade-off</h2><p>Same {len(ids)} synthetic cases and model ({esc(', '.join(model))}). Both configurations include policy checks. The full court also adds advocate briefs and rebuttals; prompts and workflow differ. This comparison does not isolate debate as the sole cause.</p>
    <table><thead><tr><th>Metric</th><th>Single judge</th><th>Full court</th></tr></thead><tbody>{table}</tbody></table>
    <p><b>Exact core result is not the same as safe handling:</b> a correct escalation can match the reference without resolving the dispute. “Eligible to act” is a simulation flag, not an actual payment.</p>
    <p>Mean stored latency: single judge {latency['judge_only']:.1f}s; court {latency['court']:.1f}s. Better handling costs more time and calls. We have not measured production savings or ROI.</p>
    <p>All-case paired audit: court correct / single judge wrong: {len(wins)} ({esc(', '.join(wins))}). Single judge correct / court wrong: {len(losses)} ({esc(', '.join(losses)) or 'none'}). The three stories below are selected examples, not an unbiased sample.</p></div>
    {''.join(cards)}
    <div class="box"><h2>What the court still got wrong</h2><ul>{failuretext}</ul><p>These failures are disclosed so “safe handling” is not presented as perfect judgment. Labels are policy-derived synthetic references, not adjudicated real-world disputes.</p></div>
    <div class="box"><h2>A 90-second presentation script</h2><p>“A dispute has two sides. In this recorded case, the single judge refunds SGD 2.92 and refers a driver’s account. The rider had already authorised the route. Both advocates identify that consent, and the full court reaches the reference outcome: no refund and no account referral.</p><p>But more agents should not mean more confidence in missing evidence. In the next case, the rider agrees to Balestier Road, yet the record never proves which road was driven. The court stops and sends the precise question to a reviewer.</p><p>For complete GPS absence, our separate synthetic recovery demonstration requests records, validates them and lets a human complete the same review case. That adapter does not solve missing road-name linkage.</p><p>Across these 65 synthetic cases the court improves exact core results, with a longer runtime. We show the errors too. Our value is evidence-based decisions and actionable handoffs, not a claim that AI never makes mistakes.”</p></div>
    <footer class="sources"><p>Generated by scripts/build_court_story.py from committed primary run files, court records and data/bench/expected. Scoring uses bench/report.py. Stored runs span {esc(dates[0])} to {esc(dates[-1])}. No new model calls. Business implications are hypotheses; validate reviewer time, resolution rate and cost in a pilot.</p></footer></main></body></html>'''


if __name__ == '__main__':
    path = ROOT/'web/court-value.html'
    path.write_text(generate(), encoding='utf-8')
    print(f'Generated {path.relative_to(ROOT)} from stored evidence')
