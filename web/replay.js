/* Ryde Dispute Court · replay page. Data from the FastAPI backend (/api/*). */
(async function(){
'use strict';
// ---------------- params ----------------
const Q = new URLSearchParams(location.search);
const SAVED_STYLE = (() => { try { return localStorage.getItem('style') || ''; } catch (e) { return ''; } })();
const THEME = Q.get('theme') ? (Q.get('theme') === 'light' ? 'light' : 'dark') : (SAVED_STYLE === 'mono' ? 'light' : 'dark');
if (THEME === 'light') document.body.classList.add('light');
const MINI = Q.get('mini') === '1';   // hero micro-demo: map only, silent, ends on the result card (no court)
let SPEED = +(Q.get('speed') || 200);
if (MINI) document.documentElement.classList.add('mini');
const REDUCED = matchMedia && matchMedia('(prefers-reduced-motion: reduce)').matches;
const AUTOPLAY = Q.get('autoplay') !== '0' && !REDUCED;   // respects the OS reduced-motion setting; Play still works
const AUTORUN = Q.get('autorun') === '1';
const CF = Q.get('cf') || null;
const SHOW = Q.get('mode') !== 'expert';   // judge view (plain language) unless ?mode=expert
const TITLES = {   // judge-facing names; the C-000n id stays in Expert view and the URL
  'C-0001': 'The 7-Eleven detour', 'C-0002': 'Off the PIE at Paya Lebar', 'C-0003': 'Five dollars over the estimate',
  'C-0004': '"Arrived" 613 m away', 'C-0005': 'Two minutes away, $6.61 fee', 'C-0006': '"Sit down or I lock the doors"', 'C-0007': 'The rider replied by voice', 'DISP-002': "Organisers' sample: the Tiong Bahru no-show" };
const caseTitle = id => TITLES[id] || (id.startsWith('B-') ? `Benchmark case ${id.slice(2).replace(/^0+/, '')}` : id);
const $ = id => document.getElementById(id);
const el = (tag, cls, html) => { const e = document.createElement(tag); if (cls) e.className = cls; if (html != null) e.innerHTML = html; return e; };
const esc = s => String(s == null ? '' : s).replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const short = (s, n=24) => s.length > n ? s.slice(0, n-1).replace(/[\s(·,-]+$/, '') + '…' : s;
const title = s => s.replace(/\w\S*/g, w => w[0] + w.slice(1).toLowerCase());
const hms = s => { s = Math.max(0, Math.round(s)); const h = Math.floor(s/3600), m = Math.floor(s%3600/60), x = s%60; return `${String(h).padStart(2,'0')}:${String(m).padStart(2,'0')}:${String(x).padStart(2,'0')}`; };
const hm = s => hms(s).slice(0,5);
const isoSec = ts => ts ? (+ts.slice(11,13))*3600 + (+ts.slice(14,16))*60 + (+ts.slice(17,19)) : null;
const api = async (path, opts) => { const r = await fetch(path, opts); if (!r.ok) throw Object.assign(new Error(`${r.status} ${path}`), { status:r.status }); return r.json(); };
const css = v => getComputedStyle(document.body).getPropertyValue(v).trim();

// ---------------- load ----------------
const cases = await api('/api/cases');
const CID = Q.get('case') && /^[A-Z]+-\d{3,4}$/.test(Q.get('case')) ? Q.get('case') : (cases[0] || {}).case_id;   // C-000n demo cases or B-00nn benchmark cases
if (!cases.some(c => c.case_id === CID)) cases.push({ case_id: CID, type: 'benchmark case' });
const CASEQ = CF ? `${CID}~${CF}` : CID;                       // which case (possibly transformed) to draw
const RID0 = Q.get('run') || CASEQ;                           // which stored run to replay (?run= for pre-recorded fault-injection demos)
const [caseJ, factsJ, runJ, controls, policyTxt, voiceJ] = await Promise.all([
  api(`/api/cases/${encodeURIComponent(CASEQ)}`), api(`/api/cases/${encodeURIComponent(CASEQ)}/facts`),
  api(`/api/runs/${encodeURIComponent(RID0)}`).catch(e => e.status === 404 ? null : Promise.reject(e)),
  api('/api/demo-controls').catch(() => ({ inject:{}, counterfactual:{} })),
  fetch('/api/policy').then(r => r.ok ? r.text() : '').catch(() => ''),
  api(`/api/cases/${encodeURIComponent(CID)}/voice`).catch(() => null),    // the spoken complaint, when the case has one
]);
const VOICE = voiceJ && voiceJ.audio ? voiceJ : null;                                   // a spoken complaint
const VOICE_CHAT = (voiceJ && voiceJ.chat) || [];                                      // chat messages that arrived as voice
// a spoken complaint: the player, then the transcript the recogniser produced (the court reads text only)
function voiceCard(){ if (!VOICE) return ''; return `<div class="card voice"><audio controls preload="none" src="${esc(VOICE.audio)}"></audio><div class="line" title="${esc(VOICE.engine)} · ${esc(VOICE.request_id)}"><b>The complaint was spoken</b> · ${esc(VOICE.audio_s)} s · transcribed by Tencent Cloud ASR</div><div class="line muted">“${esc(VOICE.transcript)}”</div></div>`; }
// a chat message that arrived as voice: the player beside the line the court cites
function voiceChatCards(){ return VOICE_CHAT.map(v => { const f = C.facts.find(x => x.source === 'chat' && x.value && x.value.idx === v.idx); return `<div class="card voice"><audio controls preload="none" src="${esc(v.audio)}"></audio><div class="line" title="${esc(v.engine)} · ${esc(v.request_id)}"><b>The ${esc(v.from || 'rider')} replied by voice message</b> · ${esc(v.audio_s)} s · transcribed by Tencent Cloud ASR${f ? ' · on the record as ' + esc(f.id) : ''}</div><div class="line muted">“${esc(v.transcript)}”</div></div>`; }).join(''); }
const POLICY = {}; for (const line of policyTxt.split('\n')) { const m = line.trim().match(/^\*\*([A-Z]+-\d+)\*\*\s*(.*)$/); if (m) POLICY[m[1]] = m[2].replace(/\*\*|`/g, '').slice(0, 260); }
let RECORD = runJ;            // CaseRecord of the run being shown (null until a run exists)
let RUN_ID = RID0;
let MODEL = null;

function compact(c, ft, run){
  const t = c.trip, sec = isoSec;
  const endT = sec(t.dropoff_at) || sec(t.cancelled_at) || null;
  let gps = c.gps.map(p => [sec(p.ts), p.lon, p.lat, p.speed_kmh]);
  if (endT) { const g2 = gps.filter(p => p[0] <= endT); if (g2.length > 1) gps = g2; }
  return {
    id: c.case_id, type: c.dispute.type, filed_by: c.dispute.filed_by, filed_at: (c.dispute.filed_at||'').slice(0,16).replace('T',' '), statement: c.dispute.statement,
    summary: run && run.trip_summary ? run.trip_summary.text : '',
    trip: { trip_id:t.trip_id, service_type:t.service_type, pickup:t.pickup, dropoff:t.dropoff, estimated_km:t.estimated_km, estimated_min:t.estimated_min, date:(t.requested_at||'').slice(0,10),
      requested:sec(t.requested_at), accepted:sec(t.accepted_at), arrived:sec(t.driver_arrived_at), here:sec(t.driver_pressed_here_at), hereAuto:t.arrival_confirmed_by === 'platform_auto', pickup_at:sec(t.pickup_at), dropoff_at:sec(t.dropoff_at), cancelled_at:sec(t.cancelled_at), cancelled_by:t.cancelled_by },
    route: (c.route.polyline||[]).map(p => [p[1], p[0]]), roads: (c.route.roads||[]).map(x => x.name),
    gps,
    bands: (c.traffic.speed_bands||[]).map(b => ({ road:b.road_name, band:b.speed_band, ws:sec(b.window_start), we:sec(b.window_end), geometry:(b.geometry||[]).map(g => [g[1], g[0]]) })),
    incidents: (c.traffic.incidents||[]).map(i => ({ lat:i.lat, lon:i.lon, type:i.type, msg:i.message, at:sec(i.reported_at) })),
    weather: c.weather || { rain_mm:0, description:'' }, fare: c.fare || {},
    chat: (c.chat||[]).map(m => ({ t:sec(m.ts), from:m.sender || m.from, text:m.text })),
    driver_statement: c.driver_statement || '', profiles: c.profiles || {},
    // a stored run is shown with the fact table it was ruled on; the live table only when no run exists
    facts: (run && run.facts && run.facts.facts && run.facts.facts.length) ? run.facts.facts : ft.facts, events: run ? run.events : [], ruling: run ? run.ruling : null, notices: run ? (run.notices||[]) : [],
    findings: run && run.ruling && run.ruling.segment_findings ? Object.fromEntries(run.ruling.segment_findings.map(f => [f.fact_id, f])) : null,
  };
}
// a finding is three-valued: exempt (true) / counts (false) / undetermined (null); records written before that stored exempt: bool
function fState(f){ return f.finding ? (f.finding === 'exempt' ? true : f.finding === 'counts' ? false : null) : (f.exempt == null ? null : !!f.exempt); }
function fWord(f){ const st = fState(f); return st === null ? 'undetermined' : st ? (SHOW ? 'excused' : 'exempt') : (SHOW ? 'not excused' : 'not exempt'); }
function fCls(f){ const st = fState(f); return st === null ? 'und' : st ? 'amb' : 'red'; }
const C = compact(caseJ, factsJ, runJ);
const MODE = C.type === 'no_show' ? 'no_show' : C.type === 'safety' ? 'safety' : 'route';
const T = C.trip;
const CLR = () => ({ink:css('--ink'), bg:css('--bg'), blue:css('--blue'), amber:css('--amber'), red:css('--red'), green:css('--green'), purple:css('--purple'), muted:css('--muted')});
let K = CLR();

// ---------------- plain language (judge view) ----------------
const CLAUSE = { 'RD-1':'driver must take the direct route', 'RD-2':'refund for extra kilometres', 'RD-3':'rider-requested stop', 'RD-4':'reroute justified by traffic or an incident', 'RD-5':'rider agreed to the route beforehand', 'RD-6':'repeat offender → account flag',
  'NS-0':'when a cancellation fee applies', 'NS-1':'driver waited 3 min at pickup after "I\'m Here"', 'NS-2':'no-show not proven → fee refunded', 'NS-3':'driver cancelled → no fee', 'NS-4':'3-minute free-cancel window', 'NS-6':'waiting-fee conditions', 'NS-7':'30-day dispute window',
  'FARE-1':'fixed fare: only published extras', 'FARE-2':'toll overcharge', 'FARE-3':'cleaning-fee claim (not in this data)', 'NS-5':'advance-booking cancellation (not in this data)', 'NS-8':'driver-late free cancel (no such Ryde rule)', 'SAFE-3':'trip completed without the rider (fraud)', 'SAFE-1':'threat or harassment → human review', 'SAFE-2':'accident or dangerous driving → human review' };
const OUTW = { refund_partial:'Partial refund', refund_full:'Full refund', no_action:'No refund', fee_waived:'Fee waived', escalate:'Human review', flag_account:'Account flag' };
const ROAD = s => title(String(s || ''));
function factLabel(f){
  if (!f) return null; const v = f.value || {}, src = f.source;
  if (SEGNAME[f.id]) return SEGNAME[f.id] + ' (+' + (+v.extra_km).toFixed(2) + ' km)';
  if ('duration_s' in v && 'm_from_pickup' in v) return Math.round(v.duration_s/60) + '-min stop' + (MODE === 'no_show' ? ' ' + v.m_from_pickup + ' m from pickup' : '');
  if ('actual_km' in v) return 'distance driven vs optimal';
  if ('actual_min' in v) return 'trip duration';
  if ('nearest_m' in v) return 'closest approach to pickup (' + v.nearest_m + ' m)';
  if ('within_200m_s' in v) return 'time spent within 200 m';
  if ('driver_pressed_here_at' in v) return v.driver_pressed_here_at ? (v.arrival_confirmed_by === 'platform_auto' ? 'arrival auto-confirmed' : '"I\'m Here" tap') : 'no "I\'m Here" tap';
  if ('cancelled_at' in v) return 'cancellation ' + (v.s_after_accept != null ? Math.round(v.s_after_accept) + ' s after matching' : 'time');
  if ('driver_arrived_at' in v) return v.driver_arrived_at ? 'recorded arrival' : 'no arrival recorded';
  if (v.signal) return 'signal: ' + String(v.signal).toLowerCase().replace(/_/g, ' ');
  if (v.gps_missing) return 'no GPS trace on record';
  if ('gps_gap_s' in v) return 'hole in the GPS trace';
  if ('complete' in v && 'count' in v) return v.count ? 'chat record' : 'no chat';
  if (src === 'chat') return v.idx != null ? (v.from + "'s message " + (v.ts ? hm(isoSec(v.ts)) : '')) : (v.from + "'s statement");
  if (src === 'fare') return 'excess_amount' in v ? 'excess distance billed' : 'waiting_fee' in v && !('total' in v) ? 'waiting fee' : 'surge_multiplier' in v && Object.keys(v).length === 1 ? 'surge' : 'cancellation_fee' in v && Object.keys(v).length === 1 ? 'cancellation fee charged' : 'fare breakdown';
  if (src === 'traffic') return v.road_name ? ROAD(v.road_name) + (v.severe ? ' congestion' : ' traffic') : (v.type ? String(v.type).toLowerCase() + ' report' + (v.reported_at ? ' ' + hm(isoSec(v.reported_at)) : '') : 'traffic record');
  if (src === 'weather') return 'weather';
  if (src === 'profile') return (v.party || 'party') + "'s history";
  return f.text.slice(0, 40);
}
const plainId = id => { const base = id.replace(/\([a-z]\)$/, ''); if (/^F\d+$/.test(id)) return factLabel(FACT[id]); return CLAUSE[base] || null; };
const stripIds = s => String(s || '').replace(/\s*\((?:RD|NS|SAFE|FARE)-\d+(?:\([a-z]\))?(?:[,\s]+(?:RD|NS|SAFE|FARE)-\d+(?:\([a-z]\))?)*\)/g, '');
const WHO_SHOW = { rider:"Rider's advocate", driver:"Driver's advocate", judge:'Judge', verify:'Code check', system:'System' };
const clip = (t, n) => { t = String(t || ''); return t.length > n ? t.slice(0, n - 1).replace(/[\s,;:(-]+$/, '') + '…' : t; };

// ---------------- geometry helpers ----------------
const R = 6371000, D2R = Math.PI/180;
function haver(a, b){ const dl=(b[0]-a[0])*D2R, dn=(b[1]-a[1])*D2R; const x=Math.sin(dn/2)**2+Math.cos(a[1]*D2R)*Math.cos(b[1]*D2R)*Math.sin(dl/2)**2; return 2*R*Math.asin(Math.sqrt(x)); }
function bearing(a, b){ const y=Math.sin((b[0]-a[0])*D2R)*Math.cos(b[1]*D2R), x=Math.cos(a[1]*D2R)*Math.sin(b[1]*D2R)-Math.sin(a[1]*D2R)*Math.cos(b[1]*D2R)*Math.cos((b[0]-a[0])*D2R); return (Math.atan2(y,x)/D2R+360)%360; }
const G = C.gps;
const t0 = G[0][0], t1 = G[G.length-1][0];
const PICK = T.pickup_at, DROP = T.dropoff_at == null ? null : Math.min(T.dropoff_at, t1), CANCEL = T.cancelled_at == null ? null : Math.min(T.cancelled_at, t1), HERE = T.here;
const FACT = Object.fromEntries(C.facts.map(f => [f.id, f]));
const segFacts = C.facts.filter(f => f.value && 'extra_km' in f.value && f.value.start);
const stopFacts = C.facts.filter(f => f.value && 'duration_s' in f.value && 'm_from_pickup' in f.value && f.value.lat);
// exempt: true / false / null (undecided — no ruling yet)
const segs = segFacts.map(f => ({ id:f.id, s:isoSec(f.value.start), e:isoSec(f.value.end), km:f.value.extra_km, exempt: (C.findings && !SHOW && C.findings[f.id]) ? fState(C.findings[f.id]) : null, f }));
const stops = stopFacts.map(f => ({ id:f.id, s:isoSec(f.value.start), e:isoSec(f.value.end), lon:f.value.lon, lat:f.value.lat, dur:f.value.duration_s, f }));
const pickupLL = [T.pickup.lon, T.pickup.lat], dropLL = [T.dropoff.lon, T.dropoff.lat];
const segCls = s => s.exempt === null ? 'und' : s.exempt ? 'amb' : 'red';
const segWord = s => s.exempt === null ? (SHOW ? 'awaiting judge' : 'undecided') : s.exempt ? (SHOW ? 'excused' : 'exempt') : (SHOW ? 'not excused' : 'not exempt');
const SEGNAME = Object.fromEntries(segs.map((s, i) => [s.id, 'Detour ' + (i + 1)]));
const segName = id => SHOW ? (SEGNAME[id] || id) : id;
const segShort = id => SHOW ? (SEGNAME[id] ? 'D' + SEGNAME[id].slice(7) : id) : id;
const segColor = s => s.exempt === null ? K.purple : s.exempt ? K.amber : K.red;

function idxAt(t){ let lo = 0, hi = G.length - 1; while (lo < hi) { const m = (lo+hi+1) >> 1; if (G[m][0] <= t) lo = m; else hi = m-1; } return lo; }
function posAt(t){
  if (t <= t0) return { p:[G[0][1],G[0][2]], v:G[0][3], i:0 };
  if (t >= t1) { const g = G[G.length-1]; return { p:[g[1],g[2]], v:g[3], i:G.length-1 }; }
  const i = idxAt(t), a = G[i], b = G[Math.min(i+1, G.length-1)];
  const f = b[0] > a[0] ? (t - a[0]) / (b[0] - a[0]) : 0;
  return { p:[a[1]+(b[1]-a[1])*f, a[2]+(b[2]-a[2])*f], v:a[3]+(b[3]-a[3])*f, i };
}
function headingAt(t){ const i = idxAt(t); for (let k = i; k < G.length-1; k++) { const a=[G[k][1],G[k][2]], b=[G[k+1][1],G[k+1][2]]; if (haver(a,b) > 3) return bearing(a,b); } for (let k = i; k > 0; k--) { const a=[G[k-1][1],G[k-1][2]], b=[G[k][1],G[k][2]]; if (haver(a,b) > 3) return bearing(a,b); } return 0; }
const segCoords = (s, e, upto = Infinity) => { const out = []; for (const g of G) { if (g[0] < s) continue; if (g[0] > e || g[0] > upto) break; out.push([g[1], g[2]]); } if (upto < e && upto >= s) out.push(posAt(upto).p); return out; };
const geoLine = c => ({ type:'Feature', properties:{}, geometry:{ type:'LineString', coordinates: c.length > 1 ? c : [] } });
const geoPt = p => ({ type:'Feature', properties:{}, geometry:{ type:'Point', coordinates:p } });
const fc = feats => ({ type:'FeatureCollection', features: feats });

// ---------------- feed events from data ----------------
const feedEvents = [];
const addFE = (t, kind, html, cls) => { if (t == null) return; feedEvents.push({ t, kind, html, cls }); };
addFE(t0, 'sys', `Driver accepted the booking · ${esc(T.service_type)}`, 'good');
for (const b of C.bands) if (b.band <= 2) addFE(Math.max(t0, b.ws), 'sys', `LTA speed band ${b.band} on ${esc(title(b.road))} (${b.band===1?'0–9':'10–19'} km/h) · severe congestion`, 'bad');
for (const i of C.incidents) addFE(Math.max(t0, i.at), 'sys', `LTA incident · ${esc(i.msg)}`, 'bad');
if (C.weather.rain_mm > 0) addFE(t0, 'sys', `Weather · ${esc(C.weather.description)}, ${C.weather.rain_mm} mm rain`, 'info');
for (const m of C.chat) if (m.t >= t0 && m.t <= t1 + 60) addFE(m.t, 'chat', m, '');
if (T.arrived) addFE(T.arrived, 'sys', `Driver GPS within 200 m of pickup`, 'good');
if (HERE) addFE(HERE, 'sys', T.hereAuto ? `Platform confirmed <b>arrival</b> (auto)` : `Driver tapped <b>I'm Here</b>`, MODE==='no_show' ? 'warn' : 'info');
if (PICK) addFE(PICK, 'sys', `Rider picked up · ${esc(T.pickup.name)}`, 'good');
for (const s of segs) { addFE(s.s, 'sys', `${SHOW ? `<b>${segName(s.id)}</b> begins` : `Entered off-route segment <b>${s.id}</b>`} · +${s.km.toFixed(2)} km · <span class="segword" data-seg="${s.id}">${segWord(s)}</span>`, s.exempt === null ? 'info' : s.exempt ? 'warn' : 'bad'); addFE(s.e, 'sys', `Back on the optimal route (${segName(s.id)} ends)`, ''); }
for (const s of stops) addFE(s.s, 'sys', `Car stationary · ${Math.floor(s.dur/60)} min ${s.dur%60} s${MODE==='no_show' ? ` · ${s.f.value.m_from_pickup} m from pickup` : ''}${SHOW ? '' : ` (${s.id})`}`, 'warn');
if (DROP) addFE(DROP, 'sys', `Drop-off · ${esc(T.dropoff.name)} · fare $${(C.fare.total||0).toFixed(2)}`, 'good');
if (CANCEL) addFE(CANCEL, 'sys', `Cancelled by ${esc(T.cancelled_by)} · cancellation fee $${(C.fare.cancellation_fee||0).toFixed(2)}`, 'bad');
feedEvents.sort((a,b) => a.t - b.t);

// ---------------- HUD ----------------
(function hud(){
  const sel = $('caseSel');
  const groups = [['Demo cases', cases.filter(c => c.group === 'demo' || !c.group)], ["Organisers' sample dataset", cases.filter(c => c.group === 'sample')], [`Benchmark · ${cases.filter(c => c.group === 'benchmark').length} cases`, cases.filter(c => c.group === 'benchmark')], [`Held-out set · ${cases.filter(c => c.group === 'held-out').length} cases`, cases.filter(c => c.group === 'held-out')]];
  for (const [label, list] of groups) { if (!list.length) continue; const g = el('optgroup'); g.label = label; for (const c of list) { const name = (c.group === 'benchmark' || c.group === 'held-out') && c.title ? `${c.case_id} · ${c.title}` : (SHOW ? caseTitle(c.case_id) : c.case_id); const o = el('option', '', name); o.value = c.case_id; o.title = c.type; if (c.case_id === CID) o.selected = true; g.appendChild(o); } sel.appendChild(g); }
  if (!cases.some(c => c.case_id === CID)) { const o = el('option', '', CID); o.value = CID; o.selected = true; sel.appendChild(o); }
  sel.onchange = () => { const q = new URLSearchParams(); q.set('case', sel.value); if (THEME === 'light') q.set('theme', 'light'); location.search = q.toString(); };
  const TYPE = { route_deviation:['Route deviation','amber'], no_show:['No-show','purple'], safety:['Safety','red'] }[C.type] || [C.type, ''];
  $('hudBadges').innerHTML = `<span class="badge ${TYPE[1]}">${TYPE[0]}</span><span class="badge">${SHOW ? esc(caseTitle(C.id)) : esc(C.id) + ' · ' + esc(T.trip_id)}</span><span class="badge">${esc(T.service_type)}</span><span class="badge">${esc(C.weather.description)}${C.weather.rain_mm>0?' · '+C.weather.rain_mm+' mm':''}</span>`
    + (CF ? `<span class="badge cf" title="${esc(controls.counterfactual[CF]||'')}">counterfactual · ${esc(CF)}</span>` : '');
  $('hudStops').innerHTML = `<div class="stop"><i></i><div class="n">${esc(T.pickup.name)}</div><div class="m">${MODE==='no_show' ? 'pickup point · ' + (T.arrived ? 'reached ' + hm(T.arrived) : 'never reached') : 'pickup ' + hm(PICK)}</div></div><div class="stop b"><i></i><div class="n">${esc(T.dropoff.name)}</div><div class="m">${DROP ? 'drop-off ' + hm(DROP) : CANCEL ? 'cancelled ' + hm(CANCEL) + ' by ' + esc(T.cancelled_by) : ''}</div></div>`;
  const f1 = (C.facts.find(f => f.value && (MODE === 'no_show' ? 'nearest_m' in f.value : 'actual_km' in f.value)) || {}).value || {};
  const kv = MODE === 'no_show'
    ? [['Cancellation fee', '$' + (C.fare.cancellation_fee||0).toFixed(2)], ['Closest approach', (f1.nearest_m != null ? f1.nearest_m : '—') + ' m'], ['Pricing', C.fare.pricing || '—']]
    : [['Charged', '$' + (C.fare.total||0).toFixed(2)], ['Driven', (f1.actual_km||0).toFixed(1) + ' km'], ['Optimal', (T.estimated_km||0).toFixed(1) + ' km']];
  $('hudKv').innerHTML = kv.map(([k,v]) => `<div>${k}<b>${v}</b></div>`).join('');
  $('hudStmt').innerHTML = `“${esc(C.statement)}”<span>— filed by ${esc(C.filed_by)}, ${esc(C.filed_at)}</span>`;
  $('clockDate').textContent = T.date;
  renderLegend();
})();
function renderLegend(){
  const L = [['<i></i>', MODE==='no_show' ? 'Driver track' : 'Actual track'], ['<i class="dash"></i>', 'Optimal route (OneMap)']];
  if (MODE==='route') L.push(['<i class="dot"></i>', 'Approach to pickup']);
  if (segs.length) { if (segs.some(s => s.exempt === null)) L.push(['<i style="background:var(--purple);height:4px"></i>', SHOW ? 'Detour · awaiting the judge' : 'Off-route · awaiting ruling']); L.push(['<i class="amb"></i>', SHOW ? 'Detour · excused' : 'Off-route · exempt']); L.push(['<i class="red"></i>', SHOW ? 'Detour · not excused' : 'Off-route · not exempt']); }
  if (C.bands.some(b => b.band <= 2 && b.geometry.length)) L.push(['<i class="cong"></i>', 'LTA severe congestion']);
  if (MODE==='no_show') L.push(['<i class="dash" style="border-color:var(--blue)"></i>', '200 m arrival radius']);
  $('legend').innerHTML = L.map(([i,t]) => `<div class="l">${i}<span>${t}</span></div>`).join('');
}
function actionChip(a){
  if (!SHOW) return `<span class="badge ${a.mode === 'auto' ? 'green' : 'amber'}" title="${esc(a.detail||'')}">${a.mode === 'auto' ? '⚡' : '👤'} ${esc(a.type)}${a.detail ? ' · ' + esc(a.detail) : ''}</span>`;
  if (a.type === 'escalate') return `<span class="badge red" title="${esc(a.detail||'')}">Sent to a human reviewer · no automatic action</span>`;
  const money = /^(refund_full|refund_partial|fee_waived)$/.test(a.type) && a.detail && (a.detail.match(/\$\d+(?:\.\d+)?/)||[])[0];
  const what = (OUTW[a.type] || a.type) + (money ? ' ' + money : '');
  return `<span class="badge ${a.mode === 'auto' ? 'green' : 'amber'}" title="${esc(a.detail||'')}">${esc(what)} → ${a.mode === 'auto' ? (a.type === 'no_action' ? 'auto-cleared · dispute closed' : 'auto-cleared · voucher') : 'human review'}</span>`;
}
function renderEligibility(rec){
  const e = rec && rec.eligibility; const box = $('hudElig'); if (!e) { box.style.display = 'none'; return; }
  const chips = (e.actions||[]).map(a => actionChip(a)).join('');
  box.innerHTML = `<div class="ttl">${SHOW ? 'Outcome' : e.auto ? 'Eligible for automation' : 'Needs a human'}<a href="/receipt.html?run=${encodeURIComponent(RUN_ID)}" target="_blank" rel="noopener">Receipt ↗</a></div><div class="chips">${chips || '<span class="badge">no action</span>'}</div>${(e.reasons||[]).length ? `<div class="wwc" style="margin-bottom:4px">${e.reasons.map(r => SHOW ? `<div title="${esc(r)}">${cite(clip(r, 170))}</div>` : `<div>${esc(r)}</div>`).join('')}</div>` : ''}${(e.what_would_change||[]).length ? `<div class="wwc">${e.what_would_change.map(s => `<div>${cite(SHOW ? clip(s, 140) : s)}</div>`).join('')}</div>` : ''}`;
  box.style.display = 'block';
  receiptBadge(box.querySelector('.ttl'));
}
async function receiptBadge(host){
  if (!host) return;
  try { const r = await api(`/api/runs/${encodeURIComponent(RUN_ID)}/receipt`); const b = el('span', 'badge ' + (r.verified ? 'green' : r.stored ? 'amber' : ''), r.verified ? '✓ receipt verified' : r.stored ? '⚠ receipt mismatch' : 'no stored receipt'); b.title = r.status || ''; b.style.marginLeft = '8px'; b.style.letterSpacing = '0'; b.style.textTransform = 'none'; host.insertBefore(b, host.querySelector('a')); } catch (e) {}
}

// ---------------- map ----------------
const STYLE = THEME === 'light' ? 'https://tiles.openfreemap.org/styles/positron' : 'https://tiles.openfreemap.org/styles/dark';
const map = new maplibregl.Map({ container:'map', style:STYLE, center:[103.85,1.30], zoom:13, attributionControl:false, preserveDrawingBuffer:true, fadeDuration:0 });
let ready = false;
const lineBase = { 'line-cap':'round', 'line-join':'round' };
function panelW(){ return parseInt(css('--panelW')) || 460; }
function fitAll(dur){
  const b = new maplibregl.LngLatBounds();
  for (const g of G) if (MODE === 'no_show' || !PICK || g[0] >= PICK - 60) b.extend([g[1], g[2]]);
  for (const p of C.route) b.extend(p);
  b.extend(pickupLL); b.extend(dropLL);
  if (MODE === 'no_show') { b.extend([pickupLL[0]-0.004, pickupLL[1]-0.004]); b.extend([pickupLL[0]+0.004, pickupLL[1]+0.004]); }
  map.fitBounds(b, { padding: MINI ? { top:84, bottom:100, left:28, right:28 } : innerWidth < 760 ? { top:120, bottom:110, left:20, right:20 } : { top:70, bottom:170, left:430, right:panelW()+60 }, duration:dur||0, maxZoom:15.5 });
}
const segFeature = s => ({ type:'Feature', properties:{ id:s.id, color:segColor(s) }, geometry:{ type:'LineString', coordinates: segCoords(s.s, s.e, now) } });
map.on('style.load', () => {
  K = CLR();
  const dark = THEME !== 'light';
  if (dark) {
    const PAL = { background:'#0e1218', water:'#121c2b', waterway:'#121c2b', landuse_residential:'#11161d', landuse_park:'#121a1a', landcover_wood:'#121a1a', building:'#13181f',
      highway_path:'#1d242e', highway_minor:'#242c38', highway_major_subtle:'#2a3340', highway_major_inner:'#2f3947', highway_motorway_inner:'#3a4556', highway_motorway_subtle:'#2a3340', highway_major_casing:'#0b0e13', highway_motorway_casing:'#0b0e13', railway:'#222a35', railway_transit:'#222a35', railway_minor:'#222a35', road_pier:'#1d242e', road_area_pier:'#1d242e' };
    for (const l of map.getStyle().layers) {
      const c = PAL[l.id]; const prop = l.type === 'fill' ? 'fill-color' : l.type === 'line' ? 'line-color' : l.type === 'background' ? 'background-color' : null;
      if (c && prop) map.setPaintProperty(l.id, prop, c);
      if (l.id === 'building') map.setPaintProperty(l.id, 'fill-outline-color', '#1a2029');
      if (l.type === 'symbol') { map.setPaintProperty(l.id, 'text-color', /place_/.test(l.id) ? '#6f7a8c' : '#5c6677'); map.setPaintProperty(l.id, 'text-halo-color', '#0e1218'); map.setPaintProperty(l.id, 'text-halo-width', 1.2); }
    }
  }
  map.addSource('route', { type:'geojson', data: geoLine(C.route) });
  map.addSource('bands', { type:'geojson', data: fc([]) });
  map.addSource('appr', { type:'geojson', data: geoLine([]) });
  map.addSource('actual', { type:'geojson', data: geoLine([]) });
  map.addSource('segs', { type:'geojson', data: fc([]) });
  map.addSource('gap', { type:'geojson', data: geoLine([]) });
  map.addSource('flash', { type:'geojson', data: fc([]) });
  map.addSource('hl', { type:'geojson', data: fc([]) });
  if (MODE === 'no_show') {
    const circ = []; for (let i = 0; i <= 72; i++) { const a = i/72*2*Math.PI; circ.push([pickupLL[0] + 200*Math.sin(a)/(111320*Math.cos(pickupLL[1]*D2R)), pickupLL[1] + 200*Math.cos(a)/110540]); }
    map.addSource('circle', { type:'geojson', data: { type:'Feature', geometry:{ type:'Polygon', coordinates:[circ] } } });
    map.addLayer({ id:'circle-fill', type:'fill', source:'circle', paint:{ 'fill-color':K.blue, 'fill-opacity':.10 } });
    map.addLayer({ id:'circle-line', type:'line', source:'circle', paint:{ 'line-color':K.blue, 'line-width':1.5, 'line-dasharray':[2,2], 'line-opacity':.9 } });
  }
  const bandColor = ['step', ['get','band'], K.red, 2, K.amber, 3, '#f5b544', 5, K.green];
  map.addLayer({ id:'bands-glow', type:'line', source:'bands', layout:lineBase, paint:{ 'line-color':bandColor, 'line-width':['case', ['<=',['get','band'],2], 22, 10], 'line-opacity':['case', ['<=',['get','band'],2], .25, .10], 'line-blur':4 } });
  map.addLayer({ id:'bands', type:'line', source:'bands', layout:lineBase, paint:{ 'line-color':bandColor, 'line-width':['case', ['<=',['get','band'],2], 9, 5], 'line-opacity':['case', ['<=',['get','band'],2], .45, .25] } });
  map.addLayer({ id:'route-casing', type:'line', source:'route', layout:lineBase, paint:{ 'line-color':K.bg, 'line-width':6, 'line-opacity':.6 } });
  map.addLayer({ id:'route', type:'line', source:'route', layout:{ 'line-cap':'round' }, paint:{ 'line-color':K.blue, 'line-width':3, 'line-dasharray':[1.2,1.8], 'line-opacity':.85 } });
  map.addLayer({ id:'appr', type:'line', source:'appr', layout:{ 'line-cap':'round' }, paint:{ 'line-color':K.muted, 'line-width':2.5, 'line-dasharray':[0.4,2], 'line-opacity':.8 } });
  map.addLayer({ id:'segs-glow', type:'line', source:'segs', layout:lineBase, paint:{ 'line-color':['get','color'], 'line-width':20, 'line-opacity':.22, 'line-blur':4 } });
  map.addLayer({ id:'actual-casing', type:'line', source:'actual', layout:lineBase, paint:{ 'line-color':dark ? '#05070b' : '#ffffff', 'line-width':9, 'line-opacity':.9 } });
  map.addLayer({ id:'actual', type:'line', source:'actual', layout:lineBase, paint:{ 'line-color':dark ? '#f4f6fa' : '#111827', 'line-width':5 } });
  map.addLayer({ id:'segs', type:'line', source:'segs', layout:lineBase, paint:{ 'line-color':['get','color'], 'line-width':5.5 } });
  map.addLayer({ id:'gap', type:'line', source:'gap', paint:{ 'line-color':K.red, 'line-width':2.5, 'line-dasharray':[1,1.6] } });
  map.addLayer({ id:'flash-glow', type:'line', source:'flash', filter:['==','$type','LineString'], layout:lineBase, paint:{ 'line-color':K.blue, 'line-width':26, 'line-blur':5, 'line-opacity':['get','op'] } });
  map.addLayer({ id:'flash', type:'line', source:'flash', filter:['==','$type','LineString'], layout:lineBase, paint:{ 'line-color':'#ffffff', 'line-width':6, 'line-opacity':['get','op'] } });
  map.addLayer({ id:'flash-pt', type:'circle', source:'flash', filter:['==','$type','Point'], paint:{ 'circle-radius':['*', 30, ['get','r']], 'circle-color':K.blue, 'circle-opacity':['*', .35, ['get','op']], 'circle-stroke-color':'#fff', 'circle-stroke-width':2, 'circle-stroke-opacity':['get','op'] } });
  map.addLayer({ id:'hl-glow', type:'line', source:'hl', filter:['==','$type','LineString'], layout:lineBase, paint:{ 'line-color':K.blue, 'line-width':24, 'line-blur':5, 'line-opacity':.35 } });
  map.addLayer({ id:'hl', type:'line', source:'hl', filter:['==','$type','LineString'], layout:lineBase, paint:{ 'line-color':'#fff', 'line-width':5 } });
  map.addLayer({ id:'hl-pt', type:'circle', source:'hl', filter:['==','$type','Point'], paint:{ 'circle-radius':18, 'circle-color':K.blue, 'circle-opacity':.3, 'circle-stroke-color':'#fff', 'circle-stroke-width':2.5 } });
  buildMarkers();
  fitAll(0);
  ready = true;
  const toCourt = Q.get('phase') === 'court';
  setTime(toCourt ? t1 : (MINI && PICK ? Math.max(t0, PICK - 30) : t0), true);   // mini: skip the approach, start just before pickup
  if (AUTORUN) startLiveRun();
  if (toCourt) setTimeout(startCourt, 800);
  else if (MINI && REDUCED) { setTime(t1, true); miniResult(); }
  else if (AUTOPLAY) setTimeout(() => play(true), MINI ? 400 : 900);
});

// ---------------- markers ----------------
const CAR_SVG = `<svg viewBox="0 0 24 34"><defs><linearGradient id="cb" x1="0" x2="0" y1="0" y2="1"><stop offset="0" stop-color="#ffd166"/><stop offset="1" stop-color="#f5a623"/></linearGradient></defs><rect x="2" y="2" width="20" height="30" rx="6" fill="url(#cb)" stroke="#2a1d05" stroke-width="1.2"/><rect x="4.5" y="9" width="15" height="7" rx="2" fill="#1b2230" opacity=".9"/><rect x="4.5" y="22" width="15" height="5" rx="2" fill="#1b2230" opacity=".75"/><rect x="4" y="2.5" width="4" height="2" rx="1" fill="#fff7d6"/><rect x="16" y="2.5" width="4" height="2" rx="1" fill="#fff7d6"/><rect x="4" y="29.5" width="4" height="2" rx="1" fill="#ff3b3b"/><rect x="16" y="29.5" width="4" height="2" rx="1" fill="#ff3b3b"/></svg>`;
const RIDER_SVG = `<svg viewBox="0 0 24 40"><circle cx="12" cy="7" r="5.5" fill="#5b9cff" stroke="#fff" stroke-width="1.5"/><path d="M5 38 V22 a7 7 0 0 1 14 0 V38 Z" fill="#5b9cff" stroke="#fff" stroke-width="1.5" stroke-linejoin="round"/><rect x="7" y="22" width="10" height="16" rx="2" fill="#2f6fd6"/></svg>`;
let carM, riderM, dropM, pickM, hereM, gapM, incM = [], segM = {};
const labelled = [];
const mk = (html, opts) => { const e = el('div', 'mk', html); return new maplibregl.Marker(Object.assign({ element:e }, opts)); };
const lmk = (inner, mode, pref, ll) => { const m = mk(`<div class="lw ${mode}">${inner}</div>`, { anchor:'center' }).setLngLat(ll).addTo(map); m.getElement().classList.add('zero'); const w = m.getElement().firstChild; labelled.push({ m, w, mode, pref }); return m; };
const HUD_R = 395, HUD_B = () => $('hud').getBoundingClientRect().bottom + 10;
function alignLabels(){
  const freeR = innerWidth - panelW() - 40, botMax = innerHeight - 135, hudB = HUD_B();
  const fits = (x0, x1, y0, y1) => x0 >= 16 && x1 <= freeR && y0 >= 12 && y1 <= botMax && !(x0 < HUD_R && y0 < hudB);
  for (const L of labelled) { if (L.w.classList.contains('hidden')) continue; const p = map.project(L.m.getLngLat()); const wd = L.w.offsetWidth || 120, ht = L.w.offsetHeight || 24;
    const side = r => r ? ['side', p.x+15, p.x+15+wd, p.y-ht/2, p.y+ht/2] : ['side ar', p.x-15-wd, p.x-15, p.y-ht/2, p.y+ht/2];
    const top = c => ['top' + (c==='l'?' al':c==='r'?' ar':''), c==='l' ? p.x : c==='r' ? p.x-wd : p.x-wd/2, c==='l' ? p.x+wd : c==='r' ? p.x : p.x+wd/2, p.y-12-ht, p.y-12];
    const bot = c => ['bot' + (c==='l'?' al':c==='r'?' ar':''), c==='l' ? p.x : c==='r' ? p.x-wd : p.x-wd/2, c==='l' ? p.x+wd : c==='r' ? p.x : p.x+wd/2, p.y+12, p.y+12+ht];
    const order = L.mode === 'side' ? [side(L.pref==='l'), side(L.pref!=='l'), bot('c'), bot('l'), bot('r'), top('c'), top('l'), top('r')]
      : L.mode === 'top' ? [top('c'), top('l'), top('r'), bot('c'), bot('l'), bot('r'), side(true), side(false)]
      : [bot('c'), bot('l'), bot('r'), top('c'), top('l'), top('r'), side(true), side(false)];
    const pick = order.find(c => fits(c[1], c[2], c[3], c[4])) || order[0];
    const cls = 'lw ' + pick[0]; if (L.w.className !== cls) L.w.className = cls; }
}
function buildMarkers(){
  carM = mk(`<div class="car"><div class="glow"></div><div class="sring"></div>${CAR_SVG}</div>`, { rotationAlignment:'map', pitchAlignment:'map' }).setLngLat([G[0][1], G[0][2]]).addTo(map);
  carM.getElement().style.zIndex = 5;
  riderM = mk(`<div class="riderfig"><div class="ring"></div><div class="shadow"></div>${RIDER_SVG}<div class="tag">Rider · waiting</div></div>`, { anchor:'bottom', offset:[0,6] }).setLngLat(pickupLL).addTo(map);
  riderM.getElement().style.zIndex = 4;
  mk(`<div class="pin"><div class="dotp"></div></div>`, { anchor:'center' }).setLngLat(pickupLL).addTo(map).getElement().classList.add('zero');
  pickM = lmk(`<div class="plab">Pickup · ${esc(short(T.pickup.name))}<small>${PICK ? hm(PICK) : 'booked'}</small></div>`, MODE === 'no_show' ? 'side' : 'bot', MODE === 'no_show' ? 'r' : 'c', pickupLL);
  mk(`<div class="pin"><div class="dotp" ${MODE==='no_show'?'style="opacity:.5"':''}></div></div>`, { anchor:'center' }).setLngLat(dropLL).addTo(map).getElement().classList.add('zero');
  dropM = lmk(MODE !== 'no_show' ? `<div class="plab">Drop-off · ${esc(short(T.dropoff.name))}<small>${DROP ? hm(DROP) : ''}</small></div>` : `<div class="plab" style="opacity:.6">Destination · ${esc(short(T.dropoff.name))}</div>`, 'bot', 'c', dropLL);
  for (const i of C.incidents) {
    const m = mk(`<div class="inc"><div class="ring"></div><div class="ring b"></div><div class="core">!</div><div class="tip"><b>LTA DataMall · ${esc(i.type)} · ${hm(i.at)}</b>${esc(i.msg)}</div></div>`, { anchor:'center' }).setLngLat([i.lon, i.lat]).addTo(map);
    m.getElement().style.pointerEvents = 'auto'; m._at = i.at; incM.push(m);
  }
  for (const s of segs) {
    const cs = segCoords(s.s, s.e); const mid = cs[Math.floor(cs.length/2)] || pickupLL;
    segM[s.id] = lmk(`<div class="seglab ${segCls(s)}">${segName(s.id)} · +${s.km.toFixed(2)} km · ${segWord(s)}</div>`, 'top', 'c', mid); segM[s.id].getElement().firstChild.classList.add('hidden');
  }
  if (MODE !== 'no_show') for (const st of stops) { st.m = lmk(`<div class="stoppin"><b>${SHOW ? '⏸' : st.id}</b>stopped ${Math.floor(st.dur/60)} min ${st.dur%60?st.dur%60+' s':''}</div>`, 'side', 'l', [st.lon, st.lat]); st.m.getElement().firstChild.classList.add('hidden'); }
  if (MODE === 'no_show' && HERE) {
    const hereF = C.facts.find(f => f.value && f.value.m_from_pickup_at_tap != null);
    const d = hereF ? hereF.value.m_from_pickup_at_tap : Math.round(haver(posAt(HERE).p, pickupLL));
    hereM = lmk(`<div class="herepin"><b>${T.hereAuto ? 'Arrival auto-confirmed' : "I'm Here"}</b> ${T.hereAuto ? '' : 'tapped '}${hm(HERE)} · ${d} m from pickup</div>`, 'side', 'l', posAt(HERE).p); hereM.getElement().firstChild.classList.add('hidden');
    gapM = mk(`<div class="gaplab" style="display:none">0 m</div>`, { anchor:'center' }).setLngLat(pickupLL).addTo(map);
  }
  if (MODE === 'no_show') mk(`<div class="circlab">200 m arrival radius</div>`, { anchor:'top', offset:[0,4] }).setLngLat([pickupLL[0], pickupLL[1] - 200/110540]).addTo(map);
}
// the judge decides exemption: recolour segments live
function applyFindings(findings){
  if (!findings || !findings.length) return;
  for (const f of findings) { const s = segs.find(x => x.id === f.fact_id); if (!s) continue; s.exempt = fState(f); }
  for (const s of segs) { const wrap = segM[s.id] && segM[s.id].getElement().firstChild; const lab = wrap && wrap.firstChild; if (lab) { lab.className = `seglab ${segCls(s)}`; lab.textContent = `${segName(s.id)} · +${s.km.toFixed(2)} km · ${segWord(s)}`; } }
  document.querySelectorAll('#scrubMarks .range[data-seg], #scrubMarks .lbl[data-seg]').forEach(e => { const s = segs.find(x => x.id === e.dataset.seg); if (!s) return; if (e.classList.contains('range')) e.className = 'range ' + segCls(s); else e.style.color = segColor(s); });
  document.querySelectorAll('.segword').forEach(e => { const s = segs.find(x => x.id === e.dataset.seg); if (s) e.textContent = segWord(s); });
  renderLegend();
  if (ready) { map.getSource('segs').setData(fc(segs.filter(s => now >= s.s).map(segFeature))); for (const s of segs) flashFact(s.id); }
}

// ---------------- rain ----------------
const rainC = $('rain'), rx = rainC.getContext('2d'); let drops = [];
const RAIN = C.weather.rain_mm > 0;
function rainInit(){ rainC.width = innerWidth * devicePixelRatio; rainC.height = innerHeight * devicePixelRatio; rainC.style.width = innerWidth+'px'; rainC.style.height = innerHeight+'px'; const n = Math.min(900, 160 + C.weather.rain_mm * 220); drops = []; for (let i = 0; i < n; i++) drops.push({ x:Math.random()*innerWidth, y:Math.random()*innerHeight, l:8+Math.random()*16, s:7+Math.random()*9, a:.12+Math.random()*.3 }); }
function rainDraw(){ rx.setTransform(devicePixelRatio,0,0,devicePixelRatio,0,0); rx.clearRect(0,0,innerWidth,innerHeight); rx.lineCap='round'; rx.lineWidth=1.1; for (const d of drops) { rx.strokeStyle = `rgba(190,215,255,${d.a})`; rx.beginPath(); rx.moveTo(d.x, d.y); rx.lineTo(d.x - d.l*.22, d.y + d.l); rx.stroke(); d.y += d.s; d.x -= d.s*.22; if (d.y > innerHeight) { d.y = -20; d.x = Math.random()*(innerWidth+100); } } }
if (RAIN) { rainC.style.display = 'block'; $('tint').style.display = 'block'; rainInit(); addEventListener('resize', rainInit); }

// ---------------- replay engine ----------------
let now = t0, playing = false, lastWall = 0, heading = 0, follow = false, courtStarted = false;
const shownBubbles = new Set(), shownFeed = new Set();
function setTime(t, force){
  now = Math.min(t1, Math.max(t0, t));
  if (!ready) return;
  const P = posAt(now);
  carM.setLngLat(P.p);
  const tgt = headingAt(now); let d = ((tgt - heading + 540) % 360) - 180; heading = force ? tgt : heading + d * 0.25; carM.setRotation(heading);
  carM.getElement().firstChild.classList.toggle('stopped', P.v < 3);
  const i = P.i; const main = [], appr = [];
  for (let k = 0; k <= i; k++) { const g = G[k]; (MODE !== 'route' || g[0] >= PICK) ? main.push([g[1], g[2]]) : appr.push([g[1], g[2]]); }
  if (MODE === 'route' && now < PICK) appr.push(P.p); else main.push(P.p);
  if (MODE === 'route' && PICK && now >= PICK && main.length) { const pp = posAt(PICK).p; if (main.length < 2 || haver(main[0], pp) > 1) main.unshift(pp); if (appr.length) appr.push(pp); }
  map.getSource('actual').setData(geoLine(main));
  map.getSource('appr').setData(geoLine(appr));
  map.getSource('segs').setData(fc(segs.filter(s => now >= s.s).map(segFeature)));
  for (const s of segs) segM[s.id].getElement().firstChild.classList.toggle('hidden', now < s.s);
  for (const st of stops) if (st.m) st.m.getElement().firstChild.classList.toggle('hidden', now < st.s);
  map.getSource('bands').setData(fc(C.bands.filter(b => b.geometry.length && now >= b.ws && now <= b.we).map(b => ({ type:'Feature', properties:{ band:b.band, road:b.road }, geometry:{ type:'LineString', coordinates:b.geometry } }))));
  for (const m of incM) m.getElement().style.display = now >= m._at ? '' : 'none';
  const r = riderM.getElement().firstChild;
  if (MODE !== 'no_show') { const inCar = PICK && now >= PICK && !(DROP && now >= DROP); r.classList.toggle('gone', !!inCar); if (DROP && now >= DROP) { riderM.setLngLat(dropLL); r.querySelector('.tag').textContent = 'Rider · dropped off'; } else { riderM.setLngLat(pickupLL); r.querySelector('.tag').textContent = 'Rider · waiting'; } }
  else { r.querySelector('.tag').textContent = (CANCEL && now >= CANCEL) ? (T.cancelled_by === 'rider' ? 'Rider · cancelled' : 'Rider · still waiting') : 'Rider · waiting'; }
  if (MODE === 'no_show') {
    if (hereM) hereM.getElement().firstChild.classList.toggle('hidden', now < HERE);
    const gs = stops[0] ? stops[0].s : HERE;
    if (gs != null && now >= gs && gapM) { const dist = Math.round(haver(P.p, pickupLL)); map.getSource('gap').setData(geoLine([P.p, pickupLL])); gapM.setLngLat([(P.p[0]+pickupLL[0])/2, (P.p[1]+pickupLL[1])/2]); gapM.getElement().firstChild.style.display = dist < 100 ? 'none' : ''; gapM.getElement().firstChild.textContent = dist + ' m from pickup'; }
    else { map.getSource('gap').setData(geoLine([])); if (gapM) gapM.getElement().firstChild.style.display = 'none'; }
  }
  $('clock').firstChild.nodeValue = hms(now);
  $('speedo').textContent = Math.round(P.v) + ' km/h';
  const seg = segs.find(s => now >= s.s && now <= s.e), stop = stops.find(s => now >= s.s && now <= s.e);
  $('status').innerHTML = seg ? `<span class="badge ${seg.exempt === null ? 'purple' : seg.exempt ? 'amber' : 'red'}">${segName(seg.id)}</span> off-route · +${seg.km.toFixed(2)} km · ${segWord(seg)}`
    : stop ? `<span class="badge purple">${SHOW ? 'Stopped' : stop.id}</span> stationary ${Math.floor(stop.dur/60)} min ${stop.dur%60} s${MODE==='no_show' ? ' · ' + stop.f.value.m_from_pickup + ' m from pickup' : ''}`
    : MODE === 'route' && PICK && now < PICK ? 'Approaching pickup' : (CANCEL && now >= CANCEL) ? 'Trip cancelled' : (DROP && now >= DROP) ? 'Trip complete' : 'On trip';
  $('scrub').querySelector('.head').style.left = ((now-t0)/(t1-t0)*100) + '%';
  $('scrub').querySelector('.played').style.width = ((now-t0)/(t1-t0)*100) + '%';
  $('scrub').setAttribute('aria-valuenow', Math.round(now - t0)); $('scrub').setAttribute('aria-valuetext', hm(now));
  for (const fe of feedEvents) { const key = fe.t + fe.kind + (fe.html.text || fe.html); if (fe.t <= now) { if (!shownFeed.has(key)) { shownFeed.add(key); feedAdd(fe); if (fe.kind === 'chat' && !force && !shownBubbles.has(key)) { shownBubbles.add(key); bubble(fe.html); } } } else if (shownFeed.has(key)) { shownFeed.delete(key); shownBubbles.delete(key); feedRemove(fe); } }
  if (follow && playing) map.jumpTo({ center:P.p });
}
function frame(w){
  if (RAIN) rainDraw();
  pulse(w);
  if (playing) { const dt = (w - lastWall) / 1000; lastWall = w; setTime(now + dt * SPEED); if (now >= t1) { playing = false; $('play').textContent = '↻ Replay'; if (!LIVE) setPill('idle', 'trip ended'); if (MINI) miniResult(); else { toast('Trip complete · the hearing starts next', 1800); setTimeout(() => startCourt(true), 1900); } } }
  requestAnimationFrame(frame);
}
let flashes = [];
function pulse(w){
  if (!ready) return;
  const k = (Math.sin(w/450) + 1) / 2;
  map.setPaintProperty('bands', 'line-opacity', ['case', ['<=',['get','band'],2], .3 + .45*k, .25]);
  map.setPaintProperty('bands-glow', 'line-opacity', ['case', ['<=',['get','band'],2], .12 + .25*k, .1]);
  alignLabels();
  if (flashes.length) { const t = performance.now(); flashes = flashes.filter(f => t - f.born < 1600); map.getSource('flash').setData(fc(flashes.map(f => { const a = (t - f.born)/1600; const op = a < .15 ? a/.15 : 1 - (a-.15)/.85; return Object.assign({}, f.geo, { properties:{ op: Math.max(0, op), r: .4 + a*.8 } }); }))); }
}
requestAnimationFrame(w => { lastWall = w; frame(w); });
function play(on){ if (on == null) on = !playing; if (on && now >= t1) setTime(t0, true); playing = on; lastWall = performance.now(); $('play').textContent = on ? '❚❚ Pause' : '▶ Play full case'; if (!LIVE) setPill(on ? '' : 'idle', on ? `replaying ${SPEED}×` : 'paused'); if (on) showTab('feed'); }
$('play').onclick = () => play();
$('speeds').onclick = e => { const b = e.target.closest('button'); if (!b) return; SPEED = +b.dataset.s; for (const x of $('speeds').children) x.classList.toggle('on', x === b); if (playing && !LIVE) setPill('', `replaying ${SPEED}×`); };
for (const x of $('speeds').children) x.classList.toggle('on', +x.dataset.s === SPEED);
$('follow').onclick = () => { follow = !follow; $('follow').classList.toggle('on', follow); if (follow) map.easeTo({ center:posAt(now).p, zoom:15.6, duration:900 }); else fitAll(900); };
$('toCourt').onclick = () => { playing = false; $('play').textContent = '↻ Replay'; setTime(t1, true); startCourt(); };
(function scrub(){
  const S = $('scrub'), M = $('scrubMarks'); const pct = t => ((t-t0)/(t1-t0)*100);
  S.setAttribute('aria-valuemin', 0); S.setAttribute('aria-valuemax', Math.round(t1 - t0));
  const tripEl = S.querySelector('.trip'); tripEl.style.left = pct(PICK || t0) + '%'; tripEl.style.width = (pct(DROP || CANCEL || t1) - pct(PICK || t0)) + '%';
  const ticks = []; const tick = (t, lbl, cls='', pr=2) => { if (t != null && t >= t0 && t <= t1) ticks.push({ t, lbl, cls, pr }); };
  tick(t0, 'accepted ' + hm(t0), '', 2); if (HERE) tick(HERE, (T.hereAuto ? 'arrived ' : "I'm Here ") + hm(HERE), '', 3); if (PICK) tick(PICK, 'pickup ' + hm(PICK), '', 1); if (DROP) tick(DROP, 'drop-off ' + hm(DROP), 'end', 1); if (CANCEL) tick(CANCEL, 'cancelled ' + hm(CANCEL), 'end', 1);
  const W = S.getBoundingClientRect().width || 900; const placed = [];
  for (const k of ticks.sort((a,b) => a.pr - b.pr)) { const x = pct(k.t)/100*W; const e = el('div', 'tick ' + k.cls, `<b>${k.lbl}</b>`); e.style.left = pct(k.t) + '%'; e.title = k.lbl; const w = k.lbl.length * 6.2 + 6; const left = k.cls === 'end' ? x - w : x; if (placed.some(([a,b]) => left < b + 8 && left + w > a - 8)) e.querySelector('b').style.display = 'none'; else placed.push([left, left + w]); M.appendChild(e); }
  for (const s of segs) { const e = el('div', 'range ' + segCls(s)); e.dataset.seg = s.id; e.style.left = pct(s.s)+'%'; e.style.width = (pct(s.e)-pct(s.s))+'%'; e.title = segName(s.id); M.appendChild(e); const l = el('div','lbl',segShort(s.id)); l.dataset.seg = s.id; l.style.left = pct((s.s+s.e)/2)+'%'; l.style.color = segColor(s); M.appendChild(l); }
  for (const s of stops) { const e = el('div', 'range stop'); e.style.left = pct(s.s)+'%'; e.style.width = (pct(s.e)-pct(s.s))+'%'; M.appendChild(e); }
  for (const m of C.chat) { if (m.t < t0 || m.t > t1) continue; const e = el('div', 'chat ' + (m.from==='driver'?'d':'') + (flagsOf(m).includes('safety concern') ? ' threat':'')); e.style.left = pct(m.t)+'%'; e.title = `${hm(m.t)} ${m.from}: ${m.text}`; M.appendChild(e); }
  let drag = false; const at = e => { const r = S.getBoundingClientRect(); return t0 + Math.min(1, Math.max(0, (e.clientX - r.left)/r.width)) * (t1 - t0); };
  S.addEventListener('pointerdown', e => { drag = true; S.setPointerCapture(e.pointerId); setTime(at(e), true); });
  S.addEventListener('pointermove', e => { if (drag) setTime(at(e), true); });
  S.addEventListener('pointerup', () => drag = false);
})();
addEventListener('keydown', e => { if (e.target.tagName === 'SELECT' || e.target.tagName === 'INPUT') return; if (e.code === 'Space') { e.preventDefault(); play(); } if (e.key === 'ArrowRight') setTime(now + 30, true); if (e.key === 'ArrowLeft') setTime(now - 30, true); });

// ---------------- feed / bubbles ----------------
const feedEl = $('feed');
// what the judge read that code could not: a safety concern, an evidence gap
function judgeNotes(r){ const out = []; if (r.safety_concern === 'unscreened') out.push(`<div><span class="seglab und" style="animation:none">safety screen not run</span><span>the judge never answered; a person reads the chat</span></div>`); else if (r.safety_concern && r.safety_concern !== 'none') out.push(`<div><span class="seglab red" style="animation:none">safety concern · ${esc(r.safety_concern)}</span><span>${(r.safety_basis||[]).map(b=>cite(b)).join(', ') || 'no basis listed'}</span></div>`); if (r.evidence_status && r.evidence_status !== 'sufficient') out.push(`<div><span class="seglab und" style="animation:none">evidence · ${esc(r.evidence_status)}</span><span>${esc(r.evidence_gap || 'no detail given')}</span></div>`); else if (r.evidence_gap) out.push(`<div><span class="seglab und" style="animation:none">evidence gap</span><span>${esc(r.evidence_gap)}</span></div>`); return out.length ? `<div class="segf">${out.join('')}</div>` : ''; }
function setPill(cls, txt){ const p = $('pill'); p.className = 'pill ' + cls; p.querySelector('span').textContent = txt; }
// nothing in the fact table labels a message; a red mark appears only when the judge's safety screen named this line (safety_basis).
// a hint word is shown as a neutral note: it only tells the reader (and the judge) to read the line in context.
function flagsOf(m){ const f = C.facts.find(x => x.source === 'chat' && x.value && x.value.ts && isoSec(x.value.ts) === m.t && x.value.from === m.from); if (!f) return [];
  const concern = C.ruling && C.ruling.safety_concern && C.ruling.safety_concern !== 'none'; const basis = (concern && C.ruling.safety_basis) || []; const out = []; if (basis.includes(f.id)) out.push('safety concern'); else if (f.value.keyword_hint) out.push('hint word · judge reads it'); return out; }
function feedAdd(fe){
  const emp = feedEl.querySelector('.empty'); if (emp) emp.remove();
  const it = el('div', 'fitem'); it.dataset.key = fe.t + fe.kind + (fe.html.text || fe.html);
  if (fe.kind === 'chat') { const m = fe.html, fl = flagsOf(m), threat = fl.includes('safety concern'); it.classList.toggle('right', m.from === 'driver');
    it.innerHTML = `<div class="t">${hm(m.t)}</div><div class="c"><div class="bub ${esc(m.from)}${threat?' threat':''}"><span class="who">${esc(m.from)}</span>${esc(m.text)}${fl.length?`<div class="flags">${fl.map(x=>`<span class="badge ${x==='safety concern'?'red':'blue'}">${esc(x)}</span>`).join('')}</div>`:''}</div></div>`; }
  else it.innerHTML = `<div class="t">${hm(fe.t)}</div><div class="c"><div class="sys ${fe.cls||''}">${fe.html}</div></div>`;
  feedEl.appendChild(it); feedEl.scrollTop = feedEl.scrollHeight;
}
function feedRemove(fe){ const key = fe.t + fe.kind + (fe.html.text || fe.html); for (const x of feedEl.children) if (x.dataset.key === key) { x.remove(); break; } }
function bubble(m){
  const fl = flagsOf(m), threat = fl.includes('safety concern');
  const inCar = MODE !== 'no_show' && PICK && m.t >= PICK;
  const at = m.from === 'driver' || inCar ? posAt(m.t).p : pickupLL;
  const pp = map.project(at), leftSide = (pp.y < HUD_B() + 40 && pp.x - 250 < HUD_R) || pp.x < (innerWidth - panelW()) / 2;
  const up = at === pickupLL ? -52 : -28;
  const b = mk(`<div class="mbub ${esc(m.from)}${threat?' threat':''}"><span class="w">${esc(m.from)}${threat?' · safety concern':''}</span>${esc(m.text)}</div>`, { anchor: leftSide ? 'bottom-left' : 'bottom-right', offset: leftSide ? [22,up] : [-22,up] }).setLngLat(at).addTo(map);
  b.getElement().style.zIndex = 6;
  const life = Math.max(3500, Math.min(7000, 2500 + m.text.length * 40));
  setTimeout(() => { b.getElement().firstChild.classList.add('out'); setTimeout(() => b.remove(), 500); }, life);
  if (threat) { $('flash').classList.add('on'); setTimeout(() => $('flash').classList.remove('on'), 900); }
}
function toast(txt, ms){ $('toastTxt').textContent = txt; $('toast').classList.add('on'); setTimeout(() => $('toast').classList.remove('on'), ms); }
function showTab(n){ for (const t of document.querySelectorAll('#panel .tab')) { t.classList.toggle('on', t.dataset.tab === n); t.setAttribute('aria-selected', t.dataset.tab === n ? 'true' : 'false'); } $('courtStages').style.display = n === 'court' ? '' : 'none'; $('feed').style.display = n === 'feed' ? '' : 'none'; $('court').style.display = n === 'court' ? '' : 'none'; $('courtbar').style.display = n === 'court' && courtStarted ? '' : 'none'; }
document.querySelectorAll('#panel .tab').forEach(t => { t.onclick = () => showTab(t.dataset.tab); t.onkeydown = e => { if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') { const tabs = [...document.querySelectorAll('#panel .tab')]; const i = tabs.indexOf(t); const nx = tabs[(i + (e.key === 'ArrowRight' ? 1 : tabs.length - 1)) % tabs.length]; nx.focus(); showTab(nx.dataset.tab); e.preventDefault(); } }; });

// ---------------- fact geometry ----------------
function factGeo(id){
  const f = FACT[id]; if (!f) return null; const v = f.value || {};
  if ('extra_km' in v && v.start) return geoLine(segCoords(isoSec(v.start), isoSec(v.end)));
  if (v.lat && v.lon) return geoPt([v.lon, v.lat]);
  if (v.road_name) { const b = C.bands.find(b => b.road === v.road_name && b.geometry.length); return b ? geoLine(b.geometry) : null; }
  if ('idx' in v && v.ts) return geoPt(posAt(isoSec(v.ts)).p);
  if ('actual_km' in v) return geoLine(G.filter(g => !PICK || g[0] >= PICK).map(g => [g[1], g[2]]));
  if ('nearest_m' in v && v.at) return geoPt(posAt(isoSec(v.at)).p);
  if ('driver_pressed_here_at' in v && v.driver_pressed_here_at) return geoPt(posAt(isoSec(v.driver_pressed_here_at)).p);
  if ('cancelled_at' in v && v.cancelled_at) return geoPt(posAt(isoSec(v.cancelled_at)).p);
  return null;
}
function flashFact(id){ const g = factGeo(id); if (!g || !ready) return; flashes.push({ geo:g, born:performance.now() }); }
function hlFact(id){ const g = factGeo(id); if (ready) map.getSource('hl').setData(fc(g ? [g] : [])); }
const clearHl = () => ready && map.getSource('hl').setData(fc([]));
function chip(id){ const isF = /^F\d+$/.test(id); const geo = isF && factGeo(id); const f = FACT[id]; const base = id.replace(/\([a-z]\)$/, ''); const tip = isF ? (f ? f.text : 'unknown fact id') : (POLICY[base] ? base + ' · ' + POLICY[base] : '');
  if (SHOW) { const lab = plainId(id); if (isF && !f) return `<span class="chip plain void" title="${esc(id)} does not exist">evidence ${esc(id)} (does not exist)</span>`; return lab ? `<span class="chip plain ${isF?'f':'p'} ${geo?'geo':''}" data-id="${esc(id)}" title="${esc(id)} · ${esc(tip)}">${esc(lab)}</span>` : `<span class="chip plain p" title="${esc(tip)}">${esc(id)}</span>`; }
  return `<span class="chip ${isF?'f':'p'} ${geo?'geo':''} ${isF && !f ? 'void' : ''}" data-id="${esc(id)}" title="${esc(tip)}">${esc(id)}</span>`; }
const chips = ids => `<div class="chips">${ids.map(i => chip(i)).join('')}</div>`;
document.addEventListener('mouseover', e => { const c = e.target.closest('.chip.geo'); if (c) hlFact(c.dataset.id); });
document.addEventListener('mouseout', e => { if (e.target.closest('.chip.geo')) clearHl(); });
document.addEventListener('click', e => { const c = e.target.closest('.chip.geo'); if (c) flashFact(c.dataset.id); });
const ID_RE = /^(F\d+|(?:RD|NS|SAFE|FARE)-\d+(?:\([a-z]\))?)$/;
const cite = s => esc(s).replace(/\[([^\]]{1,80})\]|\b(F\d+)\b|\b((?:RD|NS|SAFE|FARE)-\d+(?:\([a-z]\))?)/g, (m, br, f, pol) => {
  if (br != null) { const ids = br.split(/[\s,]+|\]\[/).filter(Boolean); return ids.every(i => ID_RE.test(i)) ? (SHOW ? '' : ids.map(i => chip(i)).join(' ')) : m; }
  return chip(f || pol); }).replace(/\s+([.,;:])/g, SHOW ? '$1' : ' $1').replace(/\s{2,}/g, ' ');

// ---------------- court (queue-driven: replayed record or live SSE) ----------------
const courtEl = $('court'); let courtTimer = null, courtDone = false, courtBusy = false, instant = false, seen = 0, expected = 0;
const courtQ = []; let streamDone = false;
const DUR = { intake:2200, facts:2000, tool:900, brief:3200, check:1400, rebuttal:3000, ruling:3600, summary:1800, notify:2600, escalate:2200 };
const durOf = e => /execution trace/i.test(e.title) ? 3000 : /Bad-faith/i.test(e.title) ? 2400 : /Precedent/i.test(e.title) ? 1500 : (DUR[e.kind] || 1500);
const OUT = { refund_partial:'Partial refund', refund_full:'Full refund', no_action:'No refund', fee_waived:'Fee waived', escalate:'Escalated to human review' };
function pushEvent(e){ courtQ.push(e); expected = Math.max(expected, seen + courtQ.length); updateCount(); if (courtStarted && !courtBusy) courtStep(); }
function visibleCount(){ return courtEl.querySelectorAll('.ev.show').length; }
function updateCount(){ if (SHOW) { const shown = visibleCount(); $('courtCount').textContent = `${shown} card${shown===1?'':'s'}${LIVE && !streamDone ? ' · live' : streamDone && !courtQ.length ? ' · done' : ''}`; $('courtProg').style.width = (expected ? seen/expected*100 : 0) + '%'; return; }
  $('courtCount').textContent = `${seen} / ${expected}${LIVE && !streamDone ? ' · live' : ''}`; $('courtProg').style.width = (expected ? seen/expected*100 : 0) + '%'; }
function startCourt(restart = false){
  if (restart && courtStarted && !LIVE) { clearTimeout(courtTimer); courtQ.length = 0; courtDone = false; courtBusy = false; instant = false; seen = 0; expected = 0; streamDone = false; courtStarted = false; }
  if (courtStarted) { showTab('court'); return; }
  courtStarted = true; resetHearingView(); showTab('court'); $('courtbar').style.display = '';
  document.documentElement.style.setProperty('--panelW', '640px'); setTimeout(() => fitAll(700), 520);
  $('toCourt').style.display = 'none';
  if (!RECORD && !LIVE) { $('courtbar').style.display = 'none'; setActiveStage(0); courtEl.innerHTML = `<div class="empty">No run on record for ${esc(RUN_ID)}.<br><br>${controls && controls.live_runs === false ? 'Choose another stored case. Live runs are disabled on this deployment.' : 'Choose another stored case, or press <b>▶ Run live</b> to start a fresh hearing.'}</div>`; setPill('idle', 'no run yet'); return; }
  if (!LIVE) { setPill('', 'court in session · replaying last run'); if (!courtQ.length && RECORD) { RECORD.events.forEach(pushEvent); streamDone = true; } }
  courtStep();
}
let hearingStage = 1, followingHearing = true, jumpingToStage = false, activeHearingStage = 0, hearingScrollTimer;
function setActiveStage(n){
  if (activeHearingStage === n) return;
  activeHearingStage = n;
  for (const b of document.querySelectorAll('#courtStages button')) {
    b.classList.toggle('active', +b.dataset.stage === n);
    if (+b.dataset.stage === n) b.setAttribute('aria-current', 'step'); else b.removeAttribute('aria-current');
  }
}
function resumeHearingFollow(){ followingHearing = true; jumpingToStage = false; clearTimeout(hearingScrollTimer); setActiveStage(hearingStage); }
function resetHearingView(){
  hearingStage = 1; resumeHearingFollow(); courtEl.innerHTML = '';
  toolCard = null; toolSeen.rider.clear(); toolSeen.driver.clear();
  $('skip').disabled = $('skipAll').disabled = false;
  for (const b of document.querySelectorAll('#courtStages button')) { b.disabled = true; b.title = 'This stage has not been reached'; }
}


const CHAPTERS = {
  1: ['Evidence & open questions', 'Code gathers the record and identifies what the judge needs to decide.', '#64748b'],
  2: ['Both sides argue', 'Blue represents the rider. Orange represents the driver. Opening statements come first, then each side responds. CHECKED validates references, not which side is right.', '#2563eb'],
  3: ['Judge proposes a ruling', 'A proposed decision with reasons. It is not the final checked outcome yet.', '#7c3aed'],
  4: ['Code check & final outcome', 'Code checks the proposed ruling. The record then shows the outcome or a hand-off to a person.', '#15803d']
};
function appendChapter(node, event){
  let n = !event ? 4 : event.kind === 'ruling' ? 3 : ['notify', 'escalate', 'summary'].includes(event.kind) ? 4 : ['brief', 'rebuttal'].includes(event.kind) ? 2 : event.kind === 'check' && /Ruling verification/i.test(event.title || '') ? 4 : event.kind === 'check' && /Ruling citation|returned to judge/i.test(event.title || '') ? 3 : ['intake', 'facts', 'tool'].includes(event.kind) ? 1 : hearingStage;
  hearingStage = n;
  let section = courtEl.lastElementChild;
  if (!section || section.dataset.stage !== String(n)) {
    const [title, description, color] = CHAPTERS[n];
    section = el('section', 'chapter', `<header class="chapterHeader"><span class="num">${n}</span><div><h2>${title}</h2><p>${description}</p></div></header><div class="chapterBody"></div>`);
    section.dataset.stage = String(n);
    const previous = courtEl.querySelectorAll('.chapter[data-stage="' + n + '"]').length;
    section.id = 'chapter' + n + (previous ? '-' + (previous + 1) : ''); section.style.setProperty('--chapterColor', color); courtEl.appendChild(section);
  }
  if (event && ['brief', 'rebuttal'].includes(event.kind)) node.prepend(el('div','roundLabel', event.kind === 'brief' ? 'ROUND 1 · OPENING STATEMENT' : 'ROUND 2 · RESPONSE TO THE OTHER SIDE'));
  section.querySelector('.chapterBody').appendChild(node);
  const stageButton = document.querySelector('#courtStages button[data-stage="' + n + '"]');
  stageButton.disabled = false; stageButton.title = 'Open this stage';
  if (followingHearing) setActiveStage(n);
}
for (const b of document.querySelectorAll('#courtStages button')) b.onclick = () => {
  const matches = courtEl.querySelectorAll('.chapter[data-stage="' + b.dataset.stage + '"]');
  const section = matches[matches.length - 1];
  if (!section) return;
  followingHearing = false; jumpingToStage = true; clearTimeout(hearingScrollTimer);
  setActiveStage(+b.dataset.stage);
  courtEl.scrollTo({top:courtEl.scrollTop + section.getBoundingClientRect().top - courtEl.getBoundingClientRect().top - 12, behavior:'auto'});
};
function manualHearingScroll(){ followingHearing = false; jumpingToStage = false; }
courtEl.addEventListener('wheel', manualHearingScroll, {passive:true});
courtEl.addEventListener('touchstart', manualHearingScroll, {passive:true});
courtEl.addEventListener('pointerdown', manualHearingScroll);
courtEl.addEventListener('keydown', e => { if (['ArrowUp','ArrowDown','PageUp','PageDown','Home','End',' '].includes(e.key)) manualHearingScroll(); });
courtEl.addEventListener('scroll', () => {
  if (followingHearing || jumpingToStage) return;
  clearTimeout(hearingScrollTimer);
  hearingScrollTimer = setTimeout(() => {
    if (followingHearing || jumpingToStage) return;
    const sections = [...courtEl.querySelectorAll('.chapter')];
    const line = courtEl.getBoundingClientRect().top + 50;
    const current = sections.filter(s => s.getBoundingClientRect().top <= line).pop() || sections[0];
    if (current) setActiveStage(+current.dataset.stage);
  }, 120);
});

function courtStep(){
  clearTimeout(courtTimer);
  if (!courtQ.length) { courtBusy = false; if (streamDone) courtEnd(); return; }
  courtBusy = true; const e = courtQ.shift(); seen++;
  const node = renderEvent(e, instant); if (node) appendChapter(node, e); if (followingHearing) courtEl.scrollTop = courtEl.scrollHeight; updateCount();
  // story pacing, but never fall behind the stream: shrink the dwell when events are queued up
  const ahead = courtQ.length; const d = instant || !node ? 0 : Math.max(250, durOf(e) / (ahead > 0 ? Math.min(6, 1 + ahead) : 1));
  courtTimer = setTimeout(courtStep, d);
}
function courtEnd(){
  if (courtDone) return; courtDone = true; courtTimer = null; $('skip').disabled = $('skipAll').disabled = true;
  const r = RECORD && RECORD.ruling; setPill('idle', LIVE ? `done · ${MODEL||''} · ${liveElapsed()} s` : 'adjourned');
  if (r) appendChapter(el('div','ev',`<div class="banner ${r.ruling==='escalate'?'esc':'done'}">${r.ruling==='escalate'?'⚠':'✓'} Case ${esc(C.id)} ${r.ruling==='escalate'?(SHOW?'sent to a human reviewer':'escalated to RydeHELP'):'resolved'} · ${OUT[r.ruling]||esc(r.ruling)}${r.amount!=null?' $'+r.amount.toFixed(2):''}</div>`));
  if (RECORD && RECORD.eligibility) { const e = RECORD.eligibility; appendChapter(el('div','ev',`<div class="elig"><b>${SHOW ? 'What happens now' : e.auto ? '⚡ Eligible for automation' : '👤 Needs a human'}</b><div class="chips">${(e.actions||[]).map(a => SHOW ? actionChip(a) : `<span class="badge ${a.mode==='auto'?'green':'amber'}">${esc(a.type)} · ${esc(a.mode)}${a.detail?' · '+esc(a.detail):''}</span>`).join('')}</div>${(e.reasons||[]).map(x => SHOW && x.length > 160 ? `<div class="reasons">${cite(clip(x, 160))}${more('full reason', `<div>${cite(x)}</div>`)}</div>` : `<div class="reasons">${SHOW ? cite(x) : esc(x)}</div>`).join('')}${(e.what_would_change||[]).map(x => `<div class="reasons">↳ ${cite(x)}</div>`).join('')}<div style="margin-top:6px"><a href="/receipt.html?run=${encodeURIComponent(RUN_ID)}" target="_blank" rel="noopener" style="color:var(--blue);font-weight:600;text-decoration:none">Reproducibility receipt ↗</a></div></div>`)); renderEligibility(RECORD); }
  if (followingHearing) courtEl.scrollTop = courtEl.scrollHeight;
}
$('skip').onclick = () => { resumeHearingFollow(); clearTimeout(courtTimer); courtStep(); };
$('skipAll').onclick = () => { resumeHearingFollow(); instant = true; clearTimeout(courtTimer); courtStep(); };
function who(e){ return (SHOW ? WHO_SHOW : { rider:'Rider Advocate', driver:'Driver Advocate', judge:'Judge', verify:'Verifier', system:'System' })[e.actor] || e.actor; }
function head(e, ttl){ return `<div class="hd"><span class="el">${esc(e.elapsed||'')}</span><span class="who ${esc(e.actor)}">${esc(who(e))}</span><span class="ttl">${ttl != null ? ttl : esc(e.title)}</span></div>`; }
function parseNotices(body){ const out = []; const re = /(RIDER|DRIVER):\s*([\s\S]*?)(?=\n\s*(?:RIDER|DRIVER):|$)/g; let m; while ((m = re.exec(body||''))) out.push({ to:m[1].toLowerCase(), text:m[2].trim() }); return out; }
function renderEvent(e, inst){
  if (SHOW) return renderShow(e, inst);
  const w = el('div', 'ev ' + esc(e.kind));
  const tool = e.tool || {};
  switch (e.kind) {
    case 'intake': w.innerHTML = head(e) + voiceCard() + `<div class="card quote">“${esc(C.statement)}”<span>Filed by ${esc(C.filed_by)} · ${esc(C.filed_at)}${C.summary ? ' · ' + esc(C.summary) : ''}</span></div>` + voiceChatCards(); break;
    case 'facts': { if (!/Fact table built/i.test(e.title)) { const lines = (e.body||'').split('\n').filter(Boolean); const warn = /Bad-faith/i.test(e.title);
        w.innerHTML = head(e) + `<div class="card ${warn?'warn':''}">${lines.map(l => `<div class="line">${cite(l)}</div>`).join('')}</div>`;
        if (!inst) w.querySelectorAll('.chip.geo').forEach((c, i) => setTimeout(() => flashFact(c.dataset.id), 150 * i)); break; }
      const groups = {}; for (const f of C.facts) (groups[f.source] = groups[f.source] || []).push(f.id);
      w.innerHTML = head(e) + `<div class="card"><div style="font-size:12px;color:var(--muted);margin-bottom:4px">Computed by code from GPS, chat, fare, LTA traffic, weather and profiles. Agents may only cite these ids.</div><div class="fgroups">${Object.entries(groups).map(([s, ids]) => `<div><b>${esc(s)}</b>${ids.map(i => chip(i)).join(' ')}</div>`).join('')}</div></div>`;
      if (!inst) w.querySelectorAll('.chip.geo').forEach((c, i) => setTimeout(() => { c.classList.add('flash'); flashFact(c.dataset.id); }, 120 * i)); break; }
    case 'tool': { const ret = tool.returned || []; w.innerHTML = head(e, `pulls evidence`) + `<div class="tool"><code>${esc(tool.fn || e.title)}()</code><span class="arr">→</span>${chips(ret)}</div>`;
      if (!inst) w.querySelectorAll('.chip.geo').forEach((c, i) => setTimeout(() => { c.classList.add('flash'); flashFact(c.dataset.id); }, 140 * i)); break; }
    case 'brief': case 'rebuttal': { let b;
      if (e.kind === 'rebuttal' && e.rebuttal && e.rebuttal.points) b = { side:e.rebuttal.side, claims:e.rebuttal.points.map(p => ({ id:'→ ' + p.target_claim_id, assertion:p.response, facts:p.facts, policy:p.policy, void:p.void, void_reason:p.void_reason, concede:p.concede })) };
      else b = e.brief || parseBrief(e.body);
      const n = b.claims.length, v = b.claims.filter(c => c.void).length, cc = b.claims.filter(c => c.concede).length;
      w.innerHTML = head(e) + `<div class="col ${esc(b.side)}"><h4><span class="who ${esc(b.side)}">${esc(b.side)} advocate · ${esc(e.kind)}</span><span class="n">${n} ${e.kind==='rebuttal'?'points':'claims'}${v?` · ${v} void`:''}${cc?` · ${cc} conceded`:''}</span></h4>${b.claims.map((c, i) => `<div class="claim ${c.void?'void':''} ${c.concede?'concede':''}" style="animation-delay:${inst?0:i*90}ms"><span class="id">${esc(c.id)}</span>${c.concede?'<span class="badge green" style="margin-right:6px">concedes</span>':''}<span class="txt">${esc(c.assertion)}</span>${c.void?`<span class="why">✗ ${esc(c.void_reason||'void')}</span>`:''}${chips([...(c.facts||[]), ...(c.policy||[])])}</div>`).join('')}</div>`;
      if (!inst) { const geoIds = [...new Set(b.claims.filter(c => !c.void).flatMap(c => c.facts||[]))].filter(id => factGeo(id)); geoIds.slice(0,5).forEach((id, i) => setTimeout(() => flashFact(id), 250 * i)); }
      break; }
    case 'check': { const lines = (e.body||'').split('\n').filter(Boolean);
      if (/Citation check|Rebuttal check/i.test(e.title)) { const voids = lines.filter(l => /VOID/.test(l)); const bad = voids.length > 0; const unit = /Rebuttal/i.test(e.title) ? 'points' : 'claims';
        w.innerHTML = head(e) + `<div class="verify ${bad?'bad':''}"><span class="stamp">${bad?'STRUCK':'VERIFIED'}</span><div>${bad ? `${voids.length} of ${lines.length} ${unit} void — ${esc((voids[0].split('—')[1]||'').trim())}` : `${lines.length} ${unit} · every citation resolves to a real fact id and a citable clause`}</div></div>`; }
      else if (/Bad-faith/i.test(e.title)) { w.innerHTML = head(e) + `<div class="card warn">${lines.map(l => { const m = l.match(/^([A-Z_]+)\s+\[(\w+),\s*(\w+)\]\s*(.*)$/); return m ? `<div class="line"><span class="badge ${m[3]==='high'?'red':'amber'}">${esc(m[3])}</span> <b class="mono">${esc(m[1])}</b> <span class="muted">${esc(m[2])}</span> · ${cite(m[4])}</div>` : `<div class="line">${cite(l)}</div>`; }).join('')}</div>`; }
      else { w.innerHTML = head(e) + `<div class="card trace">${lines.map((l, i) => { const m = l.match(/^([✓✗?–-])\s*(.*)$/); if (m) { const cls = m[1]==='✓'?'ok':m[1]==='✗'?'no':m[1]==='?'?'ask':'na'; return `<div class="line ${cls}" style="animation-delay:${inst?0:i*110}ms"><i>${m[1]==='-'?'–':m[1]}</i><span>${cite(m[2])}</span></div>`; } return `<div class="line foot">${cite(l)}</div>`; }).join('')}</div>`; }
      break; }
    case 'ruling': { const r = e.ruling || (RECORD && RECORD.ruling) || {}; const esc_ = r.ruling === 'escalate'; const sf = r.segment_findings || [];
      applyFindings(sf);
      w.innerHTML = head(e) + `<div class="ruling"><div class="head"><div><div class="out">${/Proposed/i.test(e.title) ? 'Proposed ruling' : 'Ruling'}</div><div class="amt">${r.amount != null ? '$' + (+r.amount).toFixed(2) : esc(OUT[r.ruling]||r.ruling||'')}${r.amount != null ? `<small>${esc(OUT[r.ruling]||r.ruling)}</small>` : ''}</div></div><div class="conf">model confidence<b>${r.confidence != null ? (+r.confidence).toFixed(2) : '—'}</b><div class="bar"><i data-w="${Math.round((+r.confidence||0)*100)}%"></i></div></div></div>${sf.length ? `<div class="segf">${sf.map(f => `<div><span class="seglab ${fCls(f)}" style="animation:none">${esc(f.fact_id)} · ${fWord(f)}</span><span>${cite(f.reason||'')}${(f.basis||[]).length?` <small>(rests on ${f.basis.map(b=>cite(b)).join(', ')})</small>`:''}</span></div>`).join('')}</div>` : ''}${judgeNotes(r)}<div class="body">${(r.reasoning||'').split(/\n\n+/).map(p => `<p>${cite(p)}</p>`).join('')}</div><div class="act ${esc_?'esc':''}"><b>${esc_?'Action':'Remedy'}:</b> ${cite(r.recommended_action||'')}</div>${(r.rejected_claims||[]).length ? `<div class="rej"><div style="border:0;padding-top:0;font-size:10.5px;letter-spacing:.06em;text-transform:uppercase">Claims rejected</div>${r.rejected_claims.map(c => `<div><b>${esc(c.id)}</b> · ${cite(c.reason)}</div>`).join('')}</div>` : ''}</div>`;
      setTimeout(() => { const b = w.querySelector('.bar i'); if (b) b.style.width = b.dataset.w; }, inst ? 0 : 400);
      break; }
    case 'summary': w.innerHTML = head(e, 'Final') + `<div class="card" style="font-size:12.5px;line-height:1.5">${cite((e.title||'').replace(/^Final:\s*/, ''))}<div style="margin-top:6px;color:var(--muted);font-size:11px">${cite(e.body||'')}</div></div>`; break;
    case 'notify': { if (/Notices sent/i.test(e.title)) { const ns = C.notices.length ? C.notices : parseNotices(e.body); w.innerHTML = head(e) + ns.map(n => `<div class="notice"><div class="to who ${esc(n.to)}">To the ${esc(n.to)}</div>${esc(n.text)}</div>`).join(''); }
      else w.innerHTML = head(e) + `<div class="banner route">⏱ ${esc(e.title)}<span class="sub">${cite(e.body||'')}</span></div>`; break; }
    case 'escalate': w.innerHTML = head(e) + `<div class="banner esc">⚠ ${esc(e.title)} — ${esc(e.body||'')}</div>`; break;
    default: w.innerHTML = head(e) + `<div class="card">${cite(e.body||'')}</div>`;
  }
  return w;
}
// ---------------- judge view: one story card per stage, plain words, no ids ----------------
let toolCard = null; const toolSeen = { rider:new Set(), driver:new Set() };
const TOOLCAT = { get_route_facts:'route & GPS', get_chat_facts:'chat', get_fare_facts:'fare', get_traffic_facts:'traffic', get_profile_facts:'history', get_no_show_facts:'pickup timeline', get_safety_facts:'safety' };
const sideWord = s => s === 'rider' ? "Rider's advocate" : "Driver's advocate";
function card(e, ttl, inner, cls){ const w = el('div', 'ev show k-' + esc(e.kind) + (cls ? ' ' + cls : '')); w.innerHTML = head(e, ttl) + inner; return w; }
function more(label, inner){ return `<details class="more"><summary>${label}</summary>${inner}</details>`; }
function stamp(side, kind, ok, text){ const host = [...courtEl.querySelectorAll(`.ev.show[data-side="${side}"][data-kind="${kind}"]`)].pop(); const v = el('div', 'verify ' + (ok ? '' : 'bad'), `<span class="stamp">${ok ? 'CHECKED' : 'STRUCK'}</span><div>${text}</div>`); if (host) { host.appendChild(v); return null; } return v; }
function traceLine(l, i, inst){
  const m = l.match(/^([✓✗?–-])\s*([A-Z]+-\d+)(?:\s*\(([a-z])\))?\s*(.*?)\s*\[(\w+)\]\s*(.*)$/);
  if (!m) { const f = l.match(/^allowed outcomes:\s*([^;]*)(?:;\s*amount = (.*))?$/); if (f) return `<div class="line foot">Policy allows: <b>${esc(f[1].split(/,\s*/).map(o => OUTW[o] || o).join(' or '))}</b>${f[2] ? ` · amount = ${esc(f[2].replace(/\s*\(distance_fare ÷ distance_km\)/, '').replace(/Σ extra_km of non-exempt segments/, 'extra km of detours not excused'))}` : ''}</div>`;
    const g = l.match(/^flag_account required:\s*(.*)$/); if (g) return `<div class="line foot">Account flag: ${esc(g[1] === 'True' ? 'required' : g[1] === 'False' ? 'not required' : g[1].replace(/\s*\(RD-6[^)]*\)/, ''))}</div>`;
    return `<div class="line foot">${cite(l)}</div>`; }
  const mark = m[1] === '-' ? '–' : m[1], cls = mark === '✓' ? 'ok' : mark === '✗' ? 'no' : mark === '?' ? 'ask' : 'na';
  const WORD = { ok:'Applies', no:'Does not apply', ask:'Judge decides', na:'Not relevant' };
  const subj = m[5] === 'case' ? '' : (SEGNAME[m[5]] ? SEGNAME[m[5]] : (factLabel(FACT[m[5]]) || m[5])) + ': ';
  let elem = m[4].replace(/\s*RULE:.*$/, '').replace(/\s*—.*$/, '').replace(/\s*\(repeated breach → flag_account\)/, ''); if (!elem) elem = CLAUSE[m[2]] || m[2];
  if (m[2] === 'RD-6') elem = 'Repeat offender: ' + elem; if (m[2] === 'RD-1' && /^off-route segment/i.test(elem)) elem = 'Driver left the direct route: ' + elem;
  const tail = mark === '?' ? ' <span class="muted">→ the judge decides</span>' : mark === '–' ? ' <span class="muted">(not needed)</span>' : '';
  return `<div class="line ${cls}" style="animation-delay:${inst?0:i*110}ms" title="${esc(m[2] + (m[3] ? '(' + m[3] + ')' : '') + ' · ' + m[6])}"><b class="word">${WORD[cls]}</b><span>${esc(subj)}${esc(elem)}</span></div>`;
}
function renderShow(e, inst){
  const tool = e.tool || {}; const body = e.body || ''; const lines = body.split('\n').filter(Boolean);
  switch (e.kind) {
    case 'intake': if (/DEMO/.test(e.title)) return card(e, 'Demo: a fault is injected into the AI output', `<div class="card warn">${lines.map(l => `<div class="line">${esc(l.replace(/^\w+:\s*/, ''))}</div>`).join('')}<div class="line muted">Watch the code checks catch it.</div></div>`);
      return card(e, VOICE ? 'Complaint filed by voice' : (VOICE_CHAT.length ? 'Complaint filed · the chat holds a voice message' : 'Complaint filed'), voiceCard() + `<div class="card quote">“${esc(C.statement)}”<span>Filed by the ${esc(C.filed_by)} · ${esc(C.filed_at)}</span></div>` + voiceChatCards());
    case 'facts': {
      if (/Fact table built/i.test(e.title)) {
        const pick = []; const seen = new Set(); const add = f => { if (f && !seen.has(f.id) && pick.length < 5) { seen.add(f.id); pick.push(f); } };
        for (const f of C.facts) if (f.source === 'gps' || f.source === 'timeline') add(f);
        for (const f of C.facts) if (f.value && (f.value.gps_missing || 'gps_gap_s' in f.value)) add(f);
        for (const f of C.facts) if (f.source === 'fare' && f.value && ('excess_amount' in f.value || ('cancellation_fee' in f.value && Object.keys(f.value).length === 1))) add(f);
        const w = card(e, `Evidence computed by code · ${C.facts.length} facts, no AI involved`, `<div class="card">${pick.map(f => `<div class="line geo-line" data-id="${esc(f.id)}" title="${esc(f.id)}">${esc(clip(f.text, 150))}</div>`).join('')}<div class="line muted">+ ${C.facts.length - pick.length} more (fare lines, chat, traffic, weather, history). The advocates may only argue from these.</div></div>`);
        if (!inst) pick.forEach((f, i) => setTimeout(() => flashFact(f.id), 160 * i)); return w; }
      if (/Bad-faith/i.test(e.title)) return card(e, 'Bad-faith signals found by code', `<div class="card warn">${lines.map(l => { const m = l.match(/^F\d+\s+\[\w+\]\s+Bad-faith signal\s+([A-Z_]+)\s+\((\w+),\s*(\w+)\):\s*(.*)$/); return m ? `<div class="line"><span class="badge ${m[3]==='high'?'red':'amber'}">${esc(m[2])} · ${esc(m[3])}</span> <b>${esc(m[1].toLowerCase().replace(/_/g, ' '))}</b> — ${cite(m[4])}</div>` : `<div class="line">${cite(l)}</div>`; }).join('')}</div>`);
      if (/Precedent/i.test(e.title)) { const m = e.title.match(/(\d+) similar case\(s\):\s*(.*)$/); return card(e, 'Similar past cases', `<div class="card"><div class="line">${m ? `${m[1]} similar past case${m[1]==='1'?'':'s'} on file: ${esc(m[2].replace(/(\w+)$/, x => OUTW[x] || x).replace(/×\s*(\w+)/g, (x, o) => '× ' + (OUTW[o] || o)))}` : esc(e.title)} <span class="muted">— shown to the judge for consistency, not as evidence</span></div></div>`); }
      return card(e, null, `<div class="card">${cite(body)}</div>`); }
    case 'tool': {
      const side = e.actor; const cat = TOOLCAT[tool.fn] || (tool.fn || '').replace(/^get_|_facts$/g, ''); toolSeen[side] && toolSeen[side].add(cat);
      const row = s => `<div class="line"><span class="who ${s}">${sideWord(s)}</span> pulls ${[...toolSeen[s]].map(c => `<b>${esc(c)}</b>`).join(', ') || '…'}</div>`;
      if (toolCard) { toolCard.querySelector('.card').innerHTML = row('rider') + row('driver') + `<div class="line muted">Every read is logged; an advocate can only cite what it has read.</div>`; if (!inst) (tool.returned||[]).slice(0,3).forEach((id, i) => setTimeout(() => flashFact(id), 140 * i)); return null; }
      toolCard = card(e, 'Both advocates gather evidence through logged tool calls', `<div class="card">${row('rider')}${row('driver')}<div class="line muted">Every read is logged; an advocate can only cite what it has read.</div></div>`); return toolCard; }
    case 'brief': {
      const b = e.brief || parseBrief(body); const side = b.side; const live = b.claims.filter(c => !c.void), voids = b.claims.filter(c => c.void);
      const ask = '';
      const claim = c => `<div class="claim ${c.void?'void':''}"><span class="txt">${cite(clip(c.assertion, 190))}</span>${c.void ? `<span class="why">✗ struck — ${esc((c.void_reason || 'cites evidence that does not exist').replace(/^SYS-\d+:\s*/, '').replace(/cites (F\d+) — not in the fact table/, 'cites evidence $1, which does not exist'))}</span>` : ''}</div>`;
      const w = card(e, `${sideWord(side)} · case brief · ${b.claims.length} claims`, `<div class="col ${esc(side)}">${ask ? `<div class="ask">Asks for: <b>${esc(ask)}</b></div>` : ''}${live.slice(0, 2).map(claim).join('')}${voids.map(claim).join('')}${live.length > 2 ? more(`${live.length - 2} more claims`, live.slice(2).map(claim).join('')) : ''}${(b.weaknesses||[]).length ? `<div class="weak">Admits: ${cite(clip(b.weaknesses[0], 160))}</div>` : ''}</div>`);
      w.dataset.side = side; w.dataset.kind = 'brief';
      if (!inst) { const geoIds = [...new Set(live.flatMap(c => c.facts||[]))].filter(id => factGeo(id)); geoIds.slice(0,4).forEach((id, i) => setTimeout(() => flashFact(id), 250 * i)); }
      return w; }
    case 'rebuttal': {
      const rb = e.rebuttal; if (!rb) return card(e, null, `<div class="card">${cite(body)}</div>`);
      const side = rb.side, pts = rb.points, cc = pts.filter(p => p.concede && !p.void), ct = pts.filter(p => !p.concede && !p.void), vd = pts.filter(p => p.void);
      const pt = (p, lab) => `<div class="claim ${p.concede?'concede':''} ${p.void?'void':''}">${lab ? `<span class="badge ${p.concede?'green':'blue'}" style="margin-right:6px">${lab}</span>` : ''}<span class="txt">${cite(clip(p.response, 170))}</span>${p.void ? `<span class="why">✗ struck — ${esc(p.void_reason||'')}</span>` : ''}</div>`;
      const w = card(e, `${sideWord(side)} · rebuttal · concedes ${cc.length}, contests ${ct.length}`, `<div class="col ${esc(side)}">${cc.slice(0,1).map(p => pt(p, 'concedes')).join('')}${ct.slice(0,1).map(p => pt(p, 'contests')).join('')}${vd.map(p => pt(p, '')).join('')}${pts.length > (cc.length?1:0) + (ct.length?1:0) + vd.length ? more('all points', pts.map(p => pt(p, p.concede ? 'concedes' : 'contests')).join('')) : ''}</div>`);
      w.dataset.side = side; w.dataset.kind = 'rebuttal'; return w; }
    case 'check': {
      if (/citation check failed/i.test(e.title)) return card(e, 'Judge cited a clause that does not exist — ruling sent back for correction', `<div class="card warn">${lines.map(l => `<div class="line">${cite(l)}</div>`).join('')}</div>`, 'bad');
      if (/Citation check|Rebuttal check/i.test(e.title)) { const side = (e.title.match(/—\s*(\w+)/)||[])[1]; const voids = lines.filter(l => /VOID/.test(l)); const unit = /Rebuttal/i.test(e.title) ? 'points' : 'claims'; const kind = /Rebuttal/i.test(e.title) ? 'rebuttal' : 'brief';
        return stamp(side, kind, !voids.length, voids.length ? `${voids.length} of ${lines.length} ${unit} struck: ${esc((voids[0].split('—')[1]||'cites evidence that does not exist').replace(/^\s*SYS-\d+:\s*/,'').replace(/cites (F\d+)/, 'cites evidence $1, which does not exist').trim())}` : `all ${lines.length} ${unit} cite real evidence and real policy clauses`); }
      if (/Bad-faith screen/i.test(e.title)) return /\b0 signal/.test(e.title) ? card(e, 'Bad-faith screen · nothing suspicious', `<div class="card"><div class="line muted">Timeline, GPS, traffic and history are consistent with both parties' statements.</div></div>`) : card(e, 'Bad-faith screen', `<div class="card warn">${lines.map(l => `<div class="line">${cite(l)}</div>`).join('')}</div>`);
      if (/Policy execution trace/i.test(e.title)) { const settled = lines.filter(l => /^[✓✗]/.test(l)).length, open = lines.filter(l => /^\?/.test(l)).length; return card(e, `Policy applied as code · ${settled} element${settled===1?'':'s'} settled, ${open ? open + ' left to the judge' : 'nothing left to the judge'}`, `<div class="card trace">${lines.map((l, i) => traceLine(l, i, inst)).join('')}</div>`); }
      if (/citation check failed/i.test(e.title)) return card(e, 'Judge cited a clause that does not exist — ruling sent back for correction', `<div class="card warn">${lines.map(l => `<div class="line">${cite(l)}</div>`).join('')}</div>`, 'bad');
      if (/contradicts the policy certificate/i.test(e.title)) return card(e, 'Ruling disagrees with the policy as code — sent back once', `<div class="card warn">${lines.map(l => `<div class="line">${cite(l)}</div>`).join('')}</div>`, 'bad');
      if (/Ruling verification/i.test(e.title)) { const ls = lines.filter(l => !/^model confidence/.test(l)); return card(e, 'Code checks the ruling against the policy', `<div class="card trace">${ls.map(l => { const h = l.match(/^HARD:\s*(.*)$/); if (h) return `<div class="line no"><i>⚠</i><span>${cite(h[1].replace(/→ escalate.*$/, '→ never auto-ruled, a human takes over'))}</span></div>`; const m = l.match(/^([✓✗])\s*(.*)$/); return m ? `<div class="line ${m[1]==='✓'?'ok':'no'}"><i>${m[1]}</i><span>${cite(m[2].replace('ruling consistent with the policy certificate', 'outcome allowed by the policy, amount matches the formula to the cent, every citation is real'))}</span></div>` : `<div class="line foot">${cite(l)}</div>`; }).join('')}</div>`); }
      if (/Precedent consistency/i.test(e.title)) return null;
      return card(e, null, `<div class="card">${lines.map(l => `<div class="line">${cite(l)}</div>`).join('')}</div>`); }
    case 'ruling': { const r = e.ruling || (RECORD && RECORD.ruling) || {}; const esc_ = r.ruling === 'escalate'; const sf = r.segment_findings || []; applyFindings(sf);
      const paras = (r.reasoning||'').split(/\n\n+/).filter(Boolean);
      const w = card(e, /Proposed/i.test(e.title) ? 'Judge proposes a ruling' : 'Ruling', `<div class="ruling"><div class="head"><div><div class="out">${/Proposed/i.test(e.title) ? 'Proposed ruling · not yet verified' : 'Ruling'}</div><div class="amt">${r.amount != null ? '$' + (+r.amount).toFixed(2) : esc(OUTW[r.ruling]||r.ruling||'')}${r.amount != null ? `<small>${esc(OUTW[r.ruling]||r.ruling)}</small>` : ''}</div></div><div class="conf" style="font-size:11px">${/Proposed/i.test(e.title) ? 'awaiting code check' : ''}</div></div>${sf.length ? `<div class="segf">${sf.map(f => `<div><span class="seglab ${fCls(f)}" style="animation:none">${esc(segName(f.fact_id))} · ${fWord(f)}</span><span>${cite(clip(f.reason||'', 170))}</span></div>`).join('')}</div>` : ''}${judgeNotes(r)}<div class="body"><p>${cite(clip(paras[0] || '', 340))}</p>${paras.length > 1 || (paras[0]||'').length > 340 ? more('full reasoning', paras.map(p => `<p>${cite(p)}</p>`).join('')) : ''}</div><div class="act ${esc_?'esc':''}"><b>${esc_?'Action':'Remedy'}:</b> ${cite(stripIds(r.recommended_action||''))}</div>${(r.rejected_claims||[]).length ? `<div class="rej">${more(`${r.rejected_claims.length} claim${r.rejected_claims.length>1?'s':''} rejected`, r.rejected_claims.map(c => `<div>${cite(clip(c.reason, 200))}</div>`).join(''))}</div>` : ''}</div>`);
      setTimeout(() => { const b = w.querySelector('.bar i'); if (b) b.style.width = b.dataset.w; }, inst ? 0 : 400); return w; }
    case 'summary': return null;
    case 'notify': { if (/Notices sent/i.test(e.title)) { const ns = C.notices.length ? C.notices : parseNotices(body); return card(e, 'Plain-language notices to both parties', ns.map(n => `<div class="notice"><div class="to who ${esc(n.to)}">To the ${esc(n.to)}</div>${esc(n.text)}</div>`).join('')); }
      if (/skipped/i.test(e.title)) return card(e, e.title, `<div class="card"><div class="line muted">${esc(body)}</div></div>`);
      const q = (e.title.match(/Routed to (\w+)/)||[])[1]; const Q_ = { auto_resolve:['⚡ Executed automatically', 'done'], review_24h:['👤 Queued for a human reviewer · 24 h service level', 'route'], urgent_safety:['🚨 Urgent safety queue · 2 h service level', 'esc'], review_urgent:['👤 Urgent human review', 'esc'] }[q] || [e.title, 'route'];
      const plainBody = stripIds(body).replace(/\b(refund_partial|refund_full|no_action|fee_waived|escalate|flag_account)\b/g, m => OUTW[m] || m).replace(/at confidence ([\d.]+)/, 'model confidence $1 (diagnostic only)').replace(/execute automatically/, 'the certificate allows automatic execution');
      return card(e, 'Routing', `<div class="banner ${Q_[1]}">${esc(Q_[0])}<span class="sub">${cite(plainBody)}</span></div>`); }
    case 'escalate': return card(e, 'Sent to a human reviewer', `<div class="banner esc">⚠ <span class="txt">${cite(stripIds(body) || e.title)}</span></div>`);
    default: return card(e, null, `<div class="card">${cite(body)}</div>`);
  }
}
document.addEventListener('mouseover', e => { const c = e.target.closest('.geo-line'); if (c) hlFact(c.dataset.id); });
document.addEventListener('mouseout', e => { if (e.target.closest('.geo-line')) clearHl(); });
document.addEventListener('click', e => { const c = e.target.closest('.geo-line'); if (c) flashFact(c.dataset.id); });
function parseBrief(body){ const claims = []; for (const l of (body||'').split('\n')) { const m = l.match(/^(→?\s*[CD]\d+)(\s*\((?:VOID|concede[s]?)\))?:\s*(.*?)\s*(\[[^\]]*\])?\s*(\[[^\]]*\])?\s*$/); if (!m) continue; const ids = ((m[4]||'') + ' ' + (m[5]||'')).replace(/[\[\]]/g,' ').split(/\s+/).filter(Boolean); claims.push({ id:m[1], void:/VOID/.test(m[2]||''), concede:/concede/.test(m[2]||''), assertion:m[3], facts:ids.filter(i => /^F/.test(i)), policy:ids.filter(i => !/^F/.test(i)) }); } return { side: claims[0] && /C\d/.test(claims[0].id) ? 'rider' : 'driver', claims }; }

// ---------------- live run (POST + SSE) ----------------
let LIVE = false, liveT0 = 0, liveTimer = null, ES = null;
const liveElapsed = () => ((Date.now() - liveT0) / 1000).toFixed(0);
function drawerState(){ return { inject: [...document.querySelectorAll('#drawer input[name=inject]:checked')].map(i => i.value), counterfactual: ($('cfSel') && $('cfSel').value) || null }; }
async function startLiveRun(){
  if (LIVE) return;
  const { inject, counterfactual } = drawerState();
  if ((counterfactual || null) !== (CF || null)) {   // a different case transform → reload with the transformed case on the map
    const q = new URLSearchParams(); q.set('case', CID); if (counterfactual) q.set('cf', counterfactual); q.set('autorun', '1'); if (THEME === 'light') q.set('theme', 'light');
    if (inject.length) q.set('inject', inject.join(',')); location.search = q.toString(); return;
  }
  const injectAll = inject.length ? inject : (Q.get('inject') || '').split(',').filter(Boolean);
  LIVE = true; $('runBtn').disabled = true; $('runBtn').textContent = '● Running…'; $('drawer').classList.remove('open');
  // reset the court for the new run
  clearTimeout(courtTimer); courtQ.length = 0; seen = 0; expected = 0; courtDone = false; courtBusy = false; instant = false; streamDone = false; RECORD = null;
  if (courtStarted) resetHearingView();
  $('hudElig').style.display = 'none';
  try {
    const res = await api(`/api/runs/${encodeURIComponent(CID)}`, { method:'POST', headers:{ 'Content-Type':'application/json' }, body: JSON.stringify({ rebuttal:true, inject:injectAll, counterfactual: CF }) });
    RUN_ID = res.run_id || RID0; MODEL = (res.model || MODEL || '').replace(/^[^:]+:/, ''); liveT0 = Date.now();
    setPill('live', `live · ${MODEL || 'model'} · 0 s`); liveTimer = setInterval(() => { if (LIVE) setPill('live', `live · ${MODEL || 'model'} · ${liveElapsed()} s`); }, 1000);
    ES = new EventSource(`/api/runs/${encodeURIComponent(RUN_ID)}/stream`);
    ES.addEventListener('event', ev => { const e = JSON.parse(ev.data); pushEvent(e); if (e.kind === 'ruling' && e.ruling) RECORD = Object.assign({}, RECORD || {}, { ruling: e.ruling }); });
    ES.addEventListener('done', async () => { ES.close(); ES = null; clearInterval(liveTimer); LIVE = false; streamDone = true; $('runBtn').disabled = false; $('runBtn').textContent = '↻ Run again';
      try { RECORD = await api(`/api/runs/${encodeURIComponent(RUN_ID)}`); C.notices = RECORD.notices || []; } catch (e) {}
      setPill('idle', `done · ${MODEL || ''} · ${liveElapsed()} s${courtQ.length ? ' · court catching up' : ''}`);
      if (courtStarted && !courtBusy) courtStep(); });
    ES.onerror = () => { if (ES && ES.readyState === EventSource.CLOSED) { LIVE = false; clearInterval(liveTimer); streamDone = true; $('runBtn').disabled = false; setPill('idle', 'stream closed'); } };
    if (courtStarted) { setPill('live', `live · ${MODEL || 'model'} · 0 s`); if (!courtBusy) courtStep(); }
    else toast('Agents are running · court opens when the trip ends', 2200);
  } catch (err) { LIVE = false; $('runBtn').disabled = false; $('runBtn').textContent = '▶ Run live'; setPill('idle', 'run failed'); toast('Could not start the run: ' + err.message, 3000); }
}
$('runBtn').onclick = startLiveRun;
if (controls && controls.live_runs === false) { for (const id of ['runBtn']) { const b = $(id); if (b) { b.disabled = true; b.title = controls.live_runs_note || 'live runs are off'; b.textContent = 'Stored runs only'; } } }
$('modeBtn').textContent = SHOW ? 'Expert view' : 'Simple view';
$('modeBtn').onclick = () => { const q = new URLSearchParams(location.search); q.set('mode', SHOW ? 'expert' : 'show'); if (courtStarted) q.set('phase', 'court'); location.search = q.toString(); };
// demo drawer
(function drawer(){
  const d = $('drawer');
  d.innerHTML = `<h5>Fault injection · applied to the LLM output, caught by code</h5>${Object.entries(controls.inject||{}).map(([k,v]) => `<label><input type="checkbox" name="inject" value="${esc(k)}" ${(Q.get('inject')||'').split(',').includes(k)?'checked':''}><div>${SHOW ? `<b>${esc(v)}</b>` : `<b>${esc(k)}</b> <span>— ${esc(v)}</span>`}</div></label>`).join('') || '<div class="hint">none available</div>'}
    <h5>Counterfactual audit · transform the case, run again</h5><select id="cfSel"><option value="">— none (real case) —</option>${Object.entries(controls.counterfactual||{}).map(([k,v]) => `<option value="${esc(k)}" ${k===CF?'selected':''}>${SHOW ? esc(v) : esc(k) + ' — ' + esc(v)}</option>`).join('')}</select>
    <div class="row"><div class="hint">A counterfactual reloads the page with the transformed case on the map${SHOW ? '' : ` (run id <b>${esc(CID)}~name</b>)`}, then runs the agents live.</div><button class="btn sm live" id="runBtn2">▶ Run live</button></div>`;
  $('demoBtn').onclick = () => { d.classList.toggle('open'); $('demoBtn').textContent = d.classList.contains('open') ? 'Demo ▴' : 'Demo ▾'; };
  $('runBtn2').onclick = startLiveRun;
  if (controls && controls.live_runs === false) { const b = $('runBtn2'); if (b) { b.disabled = true; b.textContent = 'Stored runs only'; } d.insertAdjacentHTML('afterbegin', `<div class="hint" style="margin-bottom:8px">${esc(controls.live_runs_note || '')}</div>`); }
})();
if (RECORD && Q.get('phase') === 'court' && !SHOW) renderEligibility(RECORD);
setPill('idle', RECORD ? 'last run on record' : 'no run yet');
$('status').textContent = 'Ready';
window.replay = { setTime: t => setTime(t, true), play, startCourt, miniResult, startLiveRun, skipAll: () => $('skipAll').click(), next: () => $('skip').click(), get now(){ return now; }, t0, t1, flashFact, map, hms, get record(){ return RECORD; }, get live(){ return LIVE; }, get queued(){ return courtQ.length; }, get seen(){ return seen; } };
// ---------------- mini mode: result card instead of the court ----------------
function miniResult(){
  if ($('miniResult')) return;
  const r = RECORD && RECORD.ruling, e = RECORD && RECORD.eligibility;
  const d = el('div', '', ''); d.id = 'miniResult';
  if (!r) { d.innerHTML = '<b>Trip ended</b><span>open the case to run the court</span>'; document.body.appendChild(d); return; }
  const money = r.amount != null && /refund/.test(r.ruling) ? ' $' + (+r.amount).toFixed(2) : '';
  const what = (OUTW[r.ruling] || r.ruling) + money;
  const ok = e ? e.auto : !r.escalate;
  d.className = ok ? 'ok' : 'warn';
  d.innerHTML = `<b>${ok ? '✓ Policy check passed' : '⚠ Sent to a person'}</b><span>${esc(what)}${ok ? ' · voucher cleared' : ' · no automatic action'}</span><em>${ok ? 'facts by code · 2 advocates · judge · code check, 23 s' : 'code could not clear it; a reviewer gets the prepared file'}</em>`;
  document.body.appendChild(d); requestAnimationFrame(() => d.classList.add('in'));
}
})().catch(err => { console.error(err); const s = document.getElementById('status'); if (s) s.textContent = 'Load failed: ' + err.message; document.getElementById('pill').querySelector('span').textContent = 'error'; });
