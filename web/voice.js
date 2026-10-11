// Voice intake: record in the browser (16 kHz mono WAV), transcribe on the server, file the text as the complaint
// of a demo case and open the court. The court never sees audio — only the text, exactly like a typed complaint.
const el = id => document.getElementById(id);
const TOKEN = new URLSearchParams(location.search).get('token') || '';
const headers = TOKEN ? { 'X-Demo-Token': TOKEN } : {};
let ctx = null, source = null, proc = null, chunks = [], stream = null, wavBlob = null;

function encodeWav(samples, rate) {
  const buf = new ArrayBuffer(44 + samples.length * 2), v = new DataView(buf);
  const str = (o, s) => { for (let i = 0; i < s.length; i++) v.setUint8(o + i, s.charCodeAt(i)); };
  str(0, 'RIFF'); v.setUint32(4, 36 + samples.length * 2, true); str(8, 'WAVE'); str(12, 'fmt ');
  v.setUint32(16, 16, true); v.setUint16(20, 1, true); v.setUint16(22, 1, true); v.setUint32(24, rate, true);
  v.setUint32(28, rate * 2, true); v.setUint16(32, 2, true); v.setUint16(34, 16, true); str(36, 'data');
  v.setUint32(40, samples.length * 2, true);
  for (let i = 0; i < samples.length; i++) { const s = Math.max(-1, Math.min(1, samples[i])); v.setInt16(44 + i * 2, s < 0 ? s * 0x8000 : s * 0x7FFF, true); }
  return new Blob([buf], { type: 'audio/wav' });
}

function downsample(input, inRate, outRate) {
  if (outRate >= inRate) return input;
  const ratio = inRate / outRate, n = Math.floor(input.length / ratio), out = new Float32Array(n);
  for (let i = 0; i < n; i++) { const a = Math.floor(i * ratio), b = Math.floor((i + 1) * ratio); let s = 0, c = 0; for (let j = a; j < b && j < input.length; j++) { s += input[j]; c++; } out[i] = c ? s / c : 0; }
  return out;
}

async function startRec() {
  stream = await navigator.mediaDevices.getUserMedia({ audio: true });
  ctx = new (window.AudioContext || window.webkitAudioContext)();
  source = ctx.createMediaStreamSource(stream);
  proc = ctx.createScriptProcessor(4096, 1, 1);
  chunks = [];
  proc.onaudioprocess = e => chunks.push(new Float32Array(e.inputBuffer.getChannelData(0)));
  source.connect(proc); proc.connect(ctx.destination);
  el('rec').textContent = '■ Stop'; el('status').textContent = 'Recording… speak the complaint, then press Stop (up to 60 s).';
}

async function stopRec() {
  proc.disconnect(); source.disconnect(); stream.getTracks().forEach(t => t.stop());
  const total = chunks.reduce((n, c) => n + c.length, 0), all = new Float32Array(total); let o = 0;
  for (const c of chunks) { all.set(c, o); o += c.length; }
  wavBlob = encodeWav(downsample(all, ctx.sampleRate, 16000), 16000);
  await ctx.close(); ctx = null;
  el('rec').textContent = '● Record'; el('player').src = URL.createObjectURL(wavBlob); el('player').hidden = false;
  el('status').textContent = `Clip ready (${(total / 48000).toFixed(1)} s). Press Transcribe.`; el('transcribe').disabled = false;
}

el('rec').onclick = () => (ctx ? stopRec() : startRec()).catch(e => { el('status').textContent = 'Microphone unavailable: ' + e.message; });
el('file').onchange = () => { const f = el('file').files[0]; if (!f) return; wavBlob = f; el('player').src = URL.createObjectURL(f); el('player').hidden = false; el('status').textContent = `${f.name} loaded. Press Transcribe.`; el('transcribe').disabled = false; };

el('transcribe').onclick = async () => {
  if (!wavBlob) return;
  el('transcribe').disabled = true; el('status').textContent = 'Transcribing with Tencent Cloud ASR…';
  const fd = new FormData(); fd.append('audio', wavBlob, wavBlob.name || 'clip.wav'); fd.append('lang', el('lang').value);
  try {
    const r = await fetch('/api/intake/voice', { method: 'POST', body: fd, headers });
    const d = await r.json();
    if (!r.ok) throw new Error(d.detail || r.statusText);
    el('text').value = d.text; el('engine').textContent = `${d.engine} · ${d.audio_s}s · request ${d.request_id}`;
    el('status').textContent = 'Transcript ready. Edit it if the recogniser misheard, then file it.'; el('run').disabled = !d.text;
  } catch (e) { el('status').textContent = 'Transcription failed: ' + e.message; }
  finally { el('transcribe').disabled = false; }
};

el('run').onclick = async () => {
  const cid = el('case').value, statement = el('text').value.trim();
  if (!statement) return;
  el('run').disabled = true; el('status').textContent = 'Filing the complaint and opening the court…';
  try {
    const r = await fetch(`/api/runs/${encodeURIComponent(cid)}`, { method: 'POST', headers: { 'Content-Type': 'application/json', ...headers }, body: JSON.stringify({ statement }) });
    const d = await r.json();
    if (!r.ok) throw new Error(d.detail || r.statusText);
    location.href = `/replay.html?case=${encodeURIComponent(cid)}&run=${encodeURIComponent(d.run_id)}&phase=court`;
  } catch (e) { el('status').textContent = 'Could not start the court: ' + e.message; el('run').disabled = false; }
};
