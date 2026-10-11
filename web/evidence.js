const el = id => document.getElementById(id);
let busy = false;
el('run').addEventListener('click', async () => {
  if (busy) return;
  busy = true; el('run').disabled = true; el('output').hidden = true;
  el('status').textContent = 'Requesting and checking the simulated records…';
  try {
    const response = await fetch(`/api/evidence-demo/${encodeURIComponent(el('case').value)}?mode=${encodeURIComponent(el('mode').value)}`);
    if (!response.ok) throw new Error('The evidence preview could not be loaded.');
    const data = await response.json(), r = data.report;
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
