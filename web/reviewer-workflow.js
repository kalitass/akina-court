'use strict';
const $ = id => document.getElementById(id);
let packet = null, busy = false, pending = null;
const query = new URLSearchParams(location.search);
if (query.has('case')) $('case').value = query.get('case');
if (query.get('scenario') === 'missing_gps') $('scenario').value = 'missing_gps';
const text = (tag, value, cls) => { const n = document.createElement(tag); n.textContent = value; if (cls) n.className = cls; return n; };
function headers() { return {'Content-Type':'application/json', ...($('token').value ? {'X-Demo-Token':$('token').value} : {})}; }
function endpoint(suffix='') { return `/api/reviewer/${encodeURIComponent($('case').value.trim())}${suffix}?scenario=${encodeURIComponent($('scenario').value)}`; }
function fields() { const action=$('action').value; $('decision-fields').hidden=action!=='own_decision'; $('evidence-fields').hidden=action!=='request_evidence'; $('preview').disabled=busy||action==='request_evidence'; }
function render(p) {
  packet=p; $('workspace').hidden=false; pending=null;
  const c=p.comparison; $('comparison').hidden=!c;
  if(c){
    const decision=c.human_assessment;
    $('progress').replaceChildren(...[
      'Identify the missing GPS: '+(c.before.evidence_gap||'no mechanical gap'),
      c.evidence_changed?'Validate and retain the returned GPS: completed':'Request and validate GPS: waiting for accepted evidence',
      decision?'Record human assessment: completed':'Assess the evidence and record a reason: pending'
    ].map(s=>text('li',s)));
    for(const [id,s] of [['before-state',c.before],['after-state',c.after]]){
      $(id).replaceChildren(text('p',`${s.gps_samples} GPS samples`),text('p',s.evidence_gap||'The mechanical GPS gap is resolved.'),text('p','Policy permits: '+s.allowed_outcomes.map(v=>v.replaceAll('_',' ')).join(', ')));
      s.location_facts.forEach(f=>$(id).append(text('p',`${f.id}: ${f.text}`)));
    }
    $('change-reason').textContent=c.evidence_changed?`What changed: source-linked GPS from ${c.accepted_source} replaced the missing interval. The original policy was applied again; this does not itself issue a decision.`:'No accepted GPS has been added. A missing or conflicting record cannot establish arrival or waiting time.';
    $('human-result').textContent=decision?`Saved human assessment by ${decision.reviewer}: ${decision.decision.ruling.replaceAll('_',' ')}${decision.decision.amount==null?'':` · $${decision.decision.amount.toFixed(2)}`} (simulation). Reason: ${decision.reason}`:'No human assessment has been saved.';
  }
  $('complaint').textContent=p.complaint.statement;
  $('trip').textContent=`${p.case_id} · ${p.complaint.filed_by} · ${p.complaint.filed_at} · ${p.route.pickup.name} → ${p.route.dropoff.name}`;
  $('court').href=p.court_url;
  const showMap=p.scenario==='stored'||p.evidence_recovered;
  $('map').hidden=!showMap;
  if(showMap) $('map').src=p.route.replay_url;
  else $('map').removeAttribute('src');
  $('map-note').textContent=showMap?'Original fixture replay; current review evidence and decisions are shown separately.':'GPS is absent from this review snapshot. The full fixture map is hidden until accepted evidence is recovered.';
  $('gap').textContent=p.evidence_gap||'No mechanical evidence gap detected. Remaining interpretation still needs assessment.';
  $('questions').replaceChildren(...p.questions.map(q=>{
    const item=text('div','', 'question'); item.append(text('h3',q.title));
    const select=document.createElement('select'); select.dataset.segment=q.id; select.setAttribute('aria-label',q.title);
    select.append(new Option('Choose an interpretation…',''));
    q.options.forEach(o=>select.append(new Option(o.label,o.value)));
    select.addEventListener('change',()=>{pending=null; $('decision').textContent=q.options.find(o=>o.value===select.value)?.consequence||'';});
    item.append(select,text('p',q.scope,'muted'));
    q.readings.forEach(r=>{if(r.ground) item.append(text('p',`${r.party} advocate: ${r.ground}`));});
    const links=text('p','Evidence: '); q.evidence_ids.forEach(id=>{const a=text('a',id+' ');a.href='#fact-'+id; a.addEventListener('click',()=>{$('facts').closest('details').open=true;});links.append(a);});item.append(links);
    q.evidence_ids.map(id=>p.facts.find(f=>f.id===id)).filter(f=>f&&f.source==='chat').slice(0,4).forEach(f=>item.append(text('p',`${f.id}: ${f.text}`)));
    const detail=document.createElement('details');detail.append(text('summary','Policy conditions and recorded arguments'));
    q.policy.forEach(p=>detail.append(text('p',`${p.clause}: ${p.detail}`)));
    q.readings.forEach(r=>r.claims.forEach(c=>detail.append(text('p',`${r.party} · ${c.id}: ${c.assertion}`))));item.append(detail); return item;
  }));
  if(!p.questions.length) $('questions').append(text('p','No open route segment. Check the evidence gap and safety conditions before deciding.'));
  $('other-questions').replaceChildren(...p.other_questions.map(q=>text('p',`${q.clause}: ${q.detail}`)));
  $('facts').replaceChildren(...p.facts.map(f=>{const n=text('div',`${f.id} · ${f.source}: ${f.text}`, 'fact');n.id='fact-'+f.id;return n;}));
  $('ai').textContent=p.ai_ruling ? JSON.stringify({ruling:p.ai_ruling.ruling,amount:p.ai_ruling.amount,reasoning:p.ai_ruling.reasoning,receipt:p.receipt_check},null,2):'No AI hearing was run on this snapshot.';
  $('receipt').hidden=!p.receipt_url; if(p.receipt_url) $('receipt').href=p.receipt_url;
  $('outcome').replaceChildren(...p.allowed_outcomes.map(v=>new Option(v.replaceAll('_',' '),v)));
  if(p.allowed_outcomes.includes('escalate')) $('outcome').value='escalate';
  [...$('action').options].find(o=>o.value==='accept_ai').disabled=!p.can_accept_ai;
  if($('action').value==='accept_ai'&&!p.can_accept_ai) $('action').value='own_decision';
  $('history').replaceChildren(...p.history.map(h=>{
    const n=text('div','', 'history'); n.append(text('strong',`${h.revision}. ${h.action} · ${h.status}`),text('p',`${h.reviewer}: ${h.reason}`));
    if(h.decision)n.append(text('p',`Recorded human outcome: ${h.decision.ruling} · ${h.decision.amount == null ? 'no refund amount' : '$'+h.decision.amount.toFixed(2)} (simulation)`));
    if(h.recovery){const r=h.recovery.evidence;n.append(text('p',`${r.state}: ${r.human_task||'GPS accepted; facts rebuilt. This is not a final ruling.'}`));const d=document.createElement('details');d.append(text('summary','Source-linked evidence handoff'),text('pre',r.reviewer_packet?.text||JSON.stringify(r,null,2)));n.append(d);}
    if(h.investigation_task)n.append(text('p',h.investigation_task));return n;
  }));
  if(!p.history.length)$('history').append(text('p','No human actions recorded.'));
  fields(); $('status').textContent=`Loaded ${p.case_id} · revision ${p.revision}${p.evidence_recovered?' · accepted GPS retained':''}`;
}
async function load() {const r=await fetch(endpoint(),{headers:headers()});const d=await r.json();if(!r.ok)throw Error(d.detail||'Cannot load review');render(d);}
function payload() {
  if(!packet)throw Error('Load a workspace first.');
  const choices={};document.querySelectorAll('[data-segment]').forEach(n=>{if(n.value)choices[n.dataset.segment]=n.value;});
  const body={source_fingerprint:packet.source_fingerprint,revision:packet.revision,action:$('action').value,reviewer:$('reviewer').value,reason:$('reason').value,choices,outcome:$('action').value==='own_decision'?$('outcome').value:null,evidence_kind:$('evidence-kind').value,response_mode:$('response-mode').value};
  if(!body.reviewer.trim()||body.reason.trim().length<10)throw Error('Enter your name and a reason of at least 10 characters.');
  const identity=JSON.stringify(body); if(!pending||pending.identity!==identity)pending={identity,id:crypto.randomUUID()};return {...body,request_id:pending.id};
}
async function submit(preview) {
  const body=payload(),url=endpoint(preview?'/preview':'/actions');const r=await fetch(url,{method:'POST',headers:headers(),body:JSON.stringify(body)});const d=await r.json();if(!r.ok)throw Error(typeof d.detail==='string'?d.detail:JSON.stringify(d.detail));
  if(preview)$('decision').textContent=JSON.stringify(d.decision,null,2)+'\nPreview only; not saved.';
  else {await load();$('decision').textContent=`Saved ${d.action} · ${d.status}. No payment or original queue change.`;}
}
async function task(fn){if(busy)return;busy=true;$('save').disabled=$('load').disabled=true;fields();try{await fn();}catch(e){$('status').textContent=e.message;}finally{busy=false;$('save').disabled=$('load').disabled=false;fields();}}
$('load').addEventListener('click',()=>task(load));$('save').addEventListener('click',()=>task(()=>submit(false)));$('preview').addEventListener('click',()=>task(()=>submit(true)));$('action').addEventListener('change',fields);
for(const id of ['case','scenario']) $(id).addEventListener('change',()=>{packet=null;pending=null;$('workspace').hidden=true;});
task(load);
