const el = id => document.getElementById(id);
let busy = false;
let handoff = null;
function showHandoff(packet) {
  handoff = packet || null;
  el('handoff').hidden = !handoff;
  if (!handoff) return;
  el('handoff-next').textContent = handoff.next_step;
  const items = texts => texts.map(text => {
    const li = document.createElement('li'); li.textContent = text; return li;
  });
  const conditionStatus = status => ({pass: 'supported by the record', fail: 'not supported by the record', judge: 'needs interpretation'})[status] || status;
  el('handoff-changes').replaceChildren(...items(handoff.changed_conditions.length ?
    handoff.changed_conditions.map(c => `${c.clause} ${c.element}: ${c.initial ? conditionStatus(c.initial.status) : 'not assessed'} → ${conditionStatus(c.current.status)}. ${c.current.detail}`) :
    ['No paired whole-case condition changed. Read each snapshot for segment-specific conditions.']));
  el('handoff-questions').replaceChildren(...items(handoff.open_questions.length ?
    handoff.open_questions.map(q => q.clause === 'SAFE-1' ?
      'Safety review: read the complaint, chat and statement for threats, intimidation, harassment or dangerous driving. Refer any concern to a safety reviewer. The complete handoff includes the messages.' :
      `${q.clause} ${q.element}: ${q.detail} (current facts: ${q.evidence.join(', ') || 'see complete handoff'})`) :
    ['No open interpretation predicate. This packet still contains no final ruling.']));
  el('handoff-text').textContent = handoff.text;
}
el('download-handoff').addEventListener('click', () => {
  if (!handoff) return;
  const url = URL.createObjectURL(new Blob([handoff.text], {type: 'text/plain;charset=utf-8'}));
  const a = document.createElement('a'); a.href = url;
  a.download = `evidence-handoff-${handoff.case_id}.txt`; a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
});
for (const id of ['case', 'mode']) el(id).addEventListener('change', () => {
  showHandoff(null); el('output').hidden = true; el('review-output').hidden = true;
});
el('run').addEventListener('click', async () => {
  if (busy) return;
  busy = true; el('run').disabled = true; el('output').hidden = true;
  showHandoff(null);
  const requestedCase = el('case').value, requestedMode = el('mode').value;
  el('status').textContent = 'Requesting and checking the simulated records…';
  try {
    const response = await fetch(`/api/evidence-demo/${encodeURIComponent(requestedCase)}?mode=${encodeURIComponent(requestedMode)}`);
    if (!response.ok) throw new Error('The evidence preview could not be loaded.');
    const data = await response.json(), r = data.report;
    if (el('case').value !== requestedCase || el('mode').value !== requestedMode) {
      el('status').textContent = 'Selection changed. Request the records for the current selection.';
      return;
    }
    showHandoff(r.reviewer_packet);
    el('gap').textContent = r.request?.reason || 'No supported evidence request.';
    const ready = r.state === 'ready_for_court';
    el('next-title').textContent = ready ? 'Ready for court review' : 'Human investigation needed';
    el('next').textContent = ready ? `${data.after.gps_points} GPS points accepted. The facts and policy assessment have been rebuilt; the AI court must now review the updated file.` : r.human_task || 'No supported recovery request.';
    el('source').textContent = r.source ? `Source: ${r.source}` : 'Original evidence remains unchanged.';
    el('trail').replaceChildren(...r.events.map(event => {
      const li = document.createElement('li'); li.textContent = event.message; return li;
    }));
    el('policy').textContent = r.policy_after?.join('\n') || 'No updated assessment: evidence was not accepted.';
    el('versions').textContent = `Initial: ${r.before_hash}\nCurrent: ${r.after_hash}\nSnapshot version: ${r.version}`;
    el('output').hidden = false;
    el('status').textContent = ready ? 'Evidence accepted. No final ruling has been made.' : 'Recovery stopped. A specific investigation task is ready.';
  } catch (error) { el('status').textContent = error.message; }
  finally { busy = false; el('run').disabled = false; }
});

let reviewing = false;
fetch('/api/demo-controls').then(r => r.json()).then(c => {
  if (c.live_runs && c.recovery_model_ready) {
    el('review').disabled = false;
    el('review').textContent = c.local_inference ? 'Run both AI hearings (local model)' : 'Run both AI hearings (uses model credits)';
    if (c.local_inference) el('review-status').textContent = 'Runs on this computer without paid API calls. The local model must be running; results are separate from the published benchmark.';
  }
  else { el('review-status').textContent = !c.live_runs ? 'Live reviews are switched off on this deployment.' : 'A model credential must be configured on the server before live review can run.'; }
}).catch(() => { el('review-status').textContent = 'Could not check live review availability.'; });
el('review').addEventListener('click', async () => {
  if (reviewing) return;
  reviewing = true; el('review').disabled = true; el('review-output').hidden = true;
  el('case').disabled = true; el('mode').disabled = true; el('run').disabled = true;
  el('review-status').textContent = 'Review requested. Waiting for the court…';
  try {
    const headers = {'Content-Type': 'application/json'};
    if (el('token').value) headers['X-Demo-Token'] = el('token').value;
    const res = await fetch(`/api/runs/${encodeURIComponent(el('case').value)}`, {
      method: 'POST', headers, body: JSON.stringify({recovery: el('mode').value})
    });
    const started = await res.json();
    if (!res.ok) throw new Error(started.detail || 'Review could not start.');
    const deadline = Date.now() + 15 * 60 * 1000;
    let state;
    while (Date.now() < deadline) {
      const response = await fetch(`/api/recovery-reviews/${encodeURIComponent(started.run_id)}`);
      if (!response.ok) throw new Error('Could not retrieve the review status.');
      state = await response.json();
      if (state.done) break;
      await new Promise(resolve => setTimeout(resolve, 2000));
    }
    if (!state?.done) throw new Error(`Review still running. Run ID: ${started.run_id}. This page timed out; do not start a duplicate.`);
    if (state.error) throw new Error(state.error);
    const r = state.review;
    if (!r) throw new Error('No review bundle returned.');
    showHandoff(r.evidence.reviewer_packet);
    el('review-record').textContent = JSON.stringify(r, null, 2);
    const outcome = value => ({escalate: 'Human review', refund_full: 'Full refund', refund_partial: 'Partial refund', fee_waived: 'Fee waived', no_action: 'Charge stands'})[value] || value;
    const show = hearing => {
      if (!hearing) return 'No completed hearing.';
      const rule = hearing.ruling;
      const amount = rule.amount == null ? 'No monetary amount' : `$${Number(rule.amount).toFixed(2)}`;
      return `Decision: ${outcome(rule.ruling)}\nAmount: ${amount}\nCore action cleared: ${hearing.eligibility?.auto ? 'Yes (simulation)' : 'No — human review'}\nAccount action: ${rule.flag_account ? 'Flag for human review' : 'None'}\n\nReasoning:\n${rule.reasoning}\n\nNotices:\n${(hearing.notices || []).map(n => `${n.to}: ${n.text}`).join('\n\n')}`;
    };
    el('before-ruling').textContent = show(r.hearings[0]);
    el('after-ruling').textContent = show(r.hearings[1]);
    const labels = {ruling:'Decision', amount:'Amount', escalate:'Human review needed', flag_account:'Account flag', evidence_status:'Evidence status'};
    const value = (key, v) => key === 'ruling' ? outcome(v) : v == null ? 'None' : typeof v === 'boolean' ? (v ? 'Yes' : 'No') : String(v);
    el('changes').textContent = r.comparison ?
      `New evidence: ${r.snapshots[1].gps.length} validated GPS points\nSource: ${r.evidence.source}\n\n` +
      (Object.entries(r.comparison.changes).map(([key, change]) => `${labels[key]}: ${value(key, change.before)} → ${value(key, change.after)}`).join('\n') || 'The decision fields did not change.') +
      '\n\nBoth versions’ reasoning is shown above. This comparison does not by itself prove improved accuracy.' :
      r.failure || r.evidence.human_task || 'No accepted evidence to review.';
    if (r.attempts?.length) {
      const attempts = r.attempts.map(a => {
        const stages = (a.stage_timings || []).map(s =>
          `  ${s.stage}: ${s.status}, ${s.duration_s}s (limit ${s.timeout_s}s)`).join('\n');
        return `${a.version === 1 ? 'Before recovery' : 'After recovery'}: ${a.state}, ${a.duration_s}s` +
          (stages ? `\n${stages}` : '') +
          (a.failure ? `\nReason: ${a.failure}\n${a.events?.length || 0} events preserved in the review record. Failed output is diagnostic only; no action is cleared by this attempt.` : '');
      }).join('\n\n');
      el('changes').textContent += `\n\nReview attempts:\n${attempts}`;
    }
    el('review-output').hidden = false;
    el('review-status').textContent = r.state === 'reviewed' ? 'Both hearings completed. Results are simulated; a changed decision does not itself prove improved accuracy.' : `Review not completed: ${r.state}`;
  } catch (error) { el('review-status').textContent = error.message; }
  finally {
    reviewing = false; el('review').disabled = false;
    el('case').disabled = false; el('mode').disabled = false; el('run').disabled = busy;
  }
});
