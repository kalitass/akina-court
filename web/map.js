/* Case map + timeline for the court page. Pure functions over API JSON (Case, FactTable, Ruling|null).
   Visual language approved 2026-09-30: dark actual track, dashed blue optimal route, amber = exempt deviation,
   red = not-exempt deviation, grey-dashed = under review; no-show: 200 m circle + distance line; safety: chat pins. */
const RydeMap = (() => {
  const ll = p => [p[1], p[0]];
  const hm = s => (s || '').slice(11, 16);
  const tsec = iso => { const [h, m, s] = iso.slice(11, 19).split(':').map(Number); return h * 3600 + m * 60 + s; };
  const spd = v => v < 10 ? '#dc2626' : v < 20 ? '#ef6c00' : v < 50 ? '#fbbf24' : '#16a34a';
  function haver(a, b) { const R = 6371000, dl = (b[1] - a[1]) * Math.PI / 180, dn = (b[0] - a[0]) * Math.PI / 180, x = Math.sin(dl / 2) ** 2 + Math.cos(a[1] * Math.PI / 180) * Math.cos(b[1] * Math.PI / 180) * Math.sin(dn / 2) ** 2; return 2 * R * Math.asin(Math.sqrt(x)); }

  function mount(el, kase, table, opts = {}) {
    const T = kase.trip, mode = kase.dispute.type === 'no_show' ? 'no_show' : kase.dispute.type === 'safety' ? 'safety' : 'route';
    const gps = kase.gps;
    const t0 = tsec(mode === 'no_show' ? T.accepted_at : T.pickup_at), t1 = tsec(mode === 'no_show' ? T.cancelled_at : T.dropoff_at);
    const trip = mode === 'no_show' ? gps : gps.filter(p => p.ts >= T.pickup_at);
    const appr = mode === 'no_show' ? [] : gps.filter(p => p.ts <= T.pickup_at);
    const coords = trip.map(p => [p.lon, p.lat]);
    const cum = [0]; for (let i = 1; i < coords.length; i++) cum.push(cum[i - 1] + haver(coords[i - 1], coords[i]));
    const total = cum[cum.length - 1] || 1;
    const stops = []; let last = -1; for (let i = 0; i < trip.length; i++) { const pr = Math.min(1, cum[i] / total); if (pr <= last) continue; last = pr; stops.push(pr, spd(trip[i].speed_kmh)); }
    const facts = table.facts;
    const isSeg = f => f.value && 'extra_km' in f.value && f.value.start;
    const isStop = f => f.value && 'duration_s' in f.value && 'm_from_pickup' in f.value;
    const segFacts = facts.filter(isSeg), stopFacts = facts.filter(isStop);
    let findings = {};   // fact_id -> exempt|null
    const segWin = f => [tsec(f.value.start), tsec(f.value.end)];
    const segCoords = f => { const [a, b] = segWin(f); return trip.filter(p => { const t = tsec(p.ts); return t >= a && t <= b; }).map(p => [p.lon, p.lat]); };
    const posAt = iso => { const t = tsec(iso); let b = gps[0]; for (const p of gps) if (Math.abs(tsec(p.ts) - t) < Math.abs(tsec(b.ts) - t)) b = p; return [b.lon, b.lat]; };
    const pickup = [T.pickup.lat, T.pickup.lon], dropoff = [T.dropoff.lat, T.dropoff.lon];

    const map = new maplibregl.Map({ container: el, style: 'https://tiles.openfreemap.org/styles/positron', center: [103.85, 1.30], zoom: 13, attributionControl: false, preserveDrawingBuffer: true });
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'top-left');
    let ready = false;
    const segState = () => ({ type: 'FeatureCollection', features: segFacts.map(f => ({ type: 'Feature', properties: { id: f.id, state: findings[f.id] === true ? 'exempt' : findings[f.id] === false ? 'bad' : 'review', label: `${f.id} · +${f.value.extra_km.toFixed(2)} km` + (findings[f.id] === true ? ' · exempt' : findings[f.id] === false ? ' · not exempt' : ' · under review') }, geometry: { type: 'LineString', coordinates: segCoords(f) } })) });
    const segLabels = () => ({ type: 'FeatureCollection', features: segState().features.map(f => ({ type: 'Feature', properties: f.properties, geometry: { type: 'Point', coordinates: f.geometry.coordinates[Math.floor(f.geometry.coordinates.length / 2)] || [0, 0] } })) });
    const SEGCOL = ['match', ['get', 'state'], 'exempt', '#f59e0b', 'bad', '#dc2626', '#6b7280'];
    const SEGLBL = ['match', ['get', 'state'], 'exempt', '#92400e', 'bad', '#991b1b', '#374151'];

    map.on('style.load', () => {
      map.addSource('bands', { type: 'geojson', data: { type: 'FeatureCollection', features: kase.traffic.speed_bands.filter(b => b.geometry).map(b => ({ type: 'Feature', properties: { road: b.road_name, band: b.speed_band, label: `${b.road_name.replace(/\w\S*/g, w => w[0] + w.slice(1).toLowerCase())} · LTA band ${b.speed_band}` }, geometry: { type: 'LineString', coordinates: b.geometry.map(ll) } })) } });
      map.addSource('route', { type: 'geojson', data: { type: 'Feature', geometry: { type: 'LineString', coordinates: kase.route.polyline.map(ll) } } });
      map.addSource('appr', { type: 'geojson', data: { type: 'Feature', geometry: { type: 'LineString', coordinates: appr.map(p => [p.lon, p.lat]) } } });
      map.addSource('actual', { type: 'geojson', lineMetrics: true, data: { type: 'Feature', geometry: { type: 'LineString', coordinates: coords } } });
      map.addSource('segs', { type: 'geojson', data: segState() });
      map.addSource('seglbl', { type: 'geojson', data: segLabels() });
      map.addSource('hl', { type: 'geojson', data: { type: 'FeatureCollection', features: [] } });
      map.addSource('cursor', { type: 'geojson', data: { type: 'FeatureCollection', features: [] } });
      map.addLayer({ id: 'bands', type: 'line', source: 'bands', layout: { visibility: 'none' }, paint: { 'line-color': '#7c3aed', 'line-width': 10, 'line-opacity': .3 } });
      if (mode === 'no_show') {
        const circ = () => { const [lat, lon] = pickup; const o = []; for (let i = 0; i <= 64; i++) { const a = i / 64 * 2 * Math.PI; o.push([lon + 200 * Math.sin(a) / (111320 * Math.cos(lat * Math.PI / 180)), lat + 200 * Math.cos(a) / 110540]); } return o; };
        map.addSource('circle', { type: 'geojson', data: { type: 'Feature', geometry: { type: 'Polygon', coordinates: [circ()] } } });
        map.addLayer({ id: 'circle-fill', type: 'fill', source: 'circle', paint: { 'fill-color': '#1a73e8', 'fill-opacity': .08 } });
        map.addLayer({ id: 'circle-line', type: 'line', source: 'circle', paint: { 'line-color': '#1a73e8', 'line-width': 2, 'line-dasharray': [2, 2] } });
        map.addSource('gap', { type: 'geojson', data: { type: 'FeatureCollection', features: stopFacts.map(f => ({ type: 'Feature', properties: { label: `${f.value.m_from_pickup} m` }, geometry: { type: 'LineString', coordinates: [[f.value.lon, f.value.lat], ll(pickup)] } })) } });
        map.addLayer({ id: 'gap', type: 'line', source: 'gap', paint: { 'line-color': '#dc2626', 'line-width': 2, 'line-dasharray': [1, 1.5] } });
        map.addLayer({ id: 'gaplbl', type: 'symbol', source: 'gap', layout: { 'symbol-placement': 'line-center', 'text-field': ['get', 'label'], 'text-font': ['Noto Sans Bold'], 'text-size': 12, 'text-offset': [0, -.9] }, paint: { 'text-color': '#dc2626', 'text-halo-color': '#fff', 'text-halo-width': 2 } });
      }
      map.addLayer({ id: 'route-casing', type: 'line', source: 'route', paint: { 'line-color': '#fff', 'line-width': 6 } });
      map.addLayer({ id: 'route', type: 'line', source: 'route', layout: { 'line-cap': 'round' }, paint: { 'line-color': '#1a73e8', 'line-width': 3, 'line-dasharray': [1.4, 1.6] } });
      map.addLayer({ id: 'appr', type: 'line', source: 'appr', layout: { visibility: mode === 'route' ? 'none' : 'visible', 'line-cap': 'round' }, paint: { 'line-color': '#9ca3af', 'line-width': 2.5, 'line-dasharray': [0.5, 2] } });
      map.addLayer({ id: 'actual-casing', type: 'line', source: 'actual', layout: { 'line-cap': 'round', 'line-join': 'round' }, paint: { 'line-color': '#fff', 'line-width': 9 } });
      map.addLayer({ id: 'segs-outline', type: 'line', source: 'segs', layout: { visibility: 'none', 'line-cap': 'round', 'line-join': 'round' }, paint: { 'line-color': SEGLBL, 'line-width': 10 } });
      map.addLayer({ id: 'actual', type: 'line', source: 'actual', layout: { 'line-cap': 'round', 'line-join': 'round' }, paint: { 'line-color': '#111827', 'line-width': 5 } });
      map.addLayer({ id: 'actual-speed', type: 'line', source: 'actual', layout: { visibility: 'none', 'line-cap': 'round', 'line-join': 'round' }, paint: { 'line-width': 5.5, 'line-gradient': ['interpolate', ['linear'], ['line-progress'], ...stops] } });
      map.addLayer({ id: 'segs', type: 'line', source: 'segs', layout: { 'line-cap': 'round', 'line-join': 'round' }, paint: { 'line-color': SEGCOL, 'line-width': 5, 'line-dasharray': ['match', ['get', 'state'], 'review', ['literal', [1, 1]], ['literal', [1, 0]]] } });
      map.addLayer({ id: 'bandlbl', type: 'symbol', source: 'bands', layout: { visibility: 'none', 'symbol-placement': 'line-center', 'text-field': ['get', 'label'], 'text-font': ['Noto Sans Bold'], 'text-size': 10.5, 'text-offset': [0, 1.4], 'text-allow-overlap': true }, paint: { 'text-color': '#5b21b6', 'text-halo-color': '#fff', 'text-halo-width': 2 } });
      map.addLayer({ id: 'hl-glow', type: 'line', source: 'hl', layout: { 'line-cap': 'round', 'line-join': 'round' }, paint: { 'line-color': '#1a73e8', 'line-width': 22, 'line-opacity': .25, 'line-blur': 3 } });
      map.addLayer({ id: 'hl-line', type: 'line', source: 'hl', layout: { 'line-cap': 'round', 'line-join': 'round' }, paint: { 'line-color': '#0b3d91', 'line-width': 6 } });
      map.addLayer({ id: 'seglbl', type: 'symbol', source: 'seglbl', layout: { 'text-field': ['get', 'label'], 'text-font': ['Noto Sans Bold'], 'text-size': 12, 'text-offset': [0, -1.6], 'text-anchor': 'bottom', 'text-allow-overlap': true }, paint: { 'text-color': SEGLBL, 'text-halo-color': '#fff', 'text-halo-width': 2 } });
      const marks = { type: 'FeatureCollection', features: [
        { type: 'Feature', properties: { kind: 'pickup', label: mode === 'no_show' ? 'Pickup point' : 'Pickup ' + hm(T.pickup_at) }, geometry: { type: 'Point', coordinates: ll(pickup) } },
        ...(mode === 'no_show' ? [] : [{ type: 'Feature', properties: { kind: 'dropoff', label: 'Drop-off ' + hm(T.dropoff_at) }, geometry: { type: 'Point', coordinates: ll(dropoff) } }]),
        ...stopFacts.map(f => ({ type: 'Feature', properties: { kind: 'stop', glyph: 'P', label: `${f.id} stop ${Math.round(f.value.duration_s / 60)} min` }, geometry: { type: 'Point', coordinates: [f.value.lon, f.value.lat] } })),
        ...facts.filter(f => f.source === 'traffic' && f.value && 'reported_at' in f.value).map(f => ({ type: 'Feature', properties: { kind: 'inc', glyph: '!', label: `${f.id} ${f.value.type} ${hm(f.value.reported_at)}` }, geometry: { type: 'Point', coordinates: [f.value.lon, f.value.lat] } })),
        ...(mode === 'no_show' && T.driver_pressed_here_at ? [{ type: 'Feature', properties: { kind: 'here', glyph: '✓', label: `${T.arrival_confirmed_by === 'platform_auto' ? 'Arrival auto-confirmed' : '"I\'m Here"'} ${hm(T.driver_pressed_here_at)}` }, geometry: { type: 'Point', coordinates: posAt(T.driver_pressed_here_at) } }] : []),
        ...(mode === 'no_show' ? [{ type: 'Feature', properties: { kind: 'start', label: 'Accepted ' + hm(T.accepted_at) }, geometry: { type: 'Point', coordinates: [gps[0].lon, gps[0].lat] } }, { type: 'Feature', properties: { kind: 'end', label: `${T.cancelled_by} cancelled ${hm(T.cancelled_at)}` }, geometry: { type: 'Point', coordinates: [gps[gps.length - 1].lon, gps[gps.length - 1].lat] } }] : []),
        ...(mode === 'safety' ? kase.chat.map(m => ({ type: 'Feature', properties: { kind: (m.sender || m.from) === 'driver' ? 'chatd' : 'chatr', glyph: '💬', label: `${hm(m.ts)} ${m.sender || m.from}: ${m.text.length > 28 ? m.text.slice(0, 28) + '…' : m.text}` }, geometry: { type: 'Point', coordinates: posAt(m.ts) } })) : []) ] };
      map.addSource('marks', { type: 'geojson', data: marks });
      map.addLayer({ id: 'marks-c', type: 'circle', source: 'marks', paint: { 'circle-radius': ['match', ['get', 'kind'], 'pickup', 7, 'dropoff', 7, 'start', 5, 'end', 6, 9], 'circle-color': ['match', ['get', 'kind'], 'pickup', '#fff', 'dropoff', '#111827', 'stop', '#dc2626', 'here', '#7c3aed', 'start', '#9ca3af', 'end', '#111827', 'chatd', '#dc2626', 'chatr', '#1a73e8', '#f97316'], 'circle-stroke-color': ['match', ['get', 'kind'], 'pickup', '#111827', '#fff'], 'circle-stroke-width': 2.5 } });
      map.addLayer({ id: 'marks-g', type: 'symbol', source: 'marks', filter: ['has', 'glyph'], layout: { 'text-field': ['get', 'glyph'], 'text-font': ['Noto Sans Bold'], 'text-size': 11, 'text-allow-overlap': true }, paint: { 'text-color': '#fff' } });
      map.addLayer({ id: 'marks-l', type: 'symbol', source: 'marks', layout: { 'text-field': ['get', 'label'], 'text-font': ['Noto Sans Bold'], 'text-size': 12, 'text-offset': ['match', ['get', 'kind'], 'here', ['literal', [0, -1.5]], 'end', ['literal', [1.3, 0]], 'chatd', ['literal', [1.3, 0]], 'chatr', ['literal', [-1.3, 0]], ['literal', [0, 1.3]]], 'text-anchor': ['match', ['get', 'kind'], 'here', 'bottom', 'end', 'left', 'chatd', 'left', 'chatr', 'right', 'top'], 'text-allow-overlap': true }, paint: { 'text-color': '#111827', 'text-halo-color': '#fff', 'text-halo-width': 2 } });
      map.addLayer({ id: 'hl-pt-glow', type: 'circle', source: 'hl', filter: ['==', '$type', 'Point'], paint: { 'circle-radius': 26, 'circle-color': '#1a73e8', 'circle-opacity': .18 } });
      map.addLayer({ id: 'hl-pt', type: 'circle', source: 'hl', filter: ['==', '$type', 'Point'], paint: { 'circle-radius': 16, 'circle-opacity': 0, 'circle-stroke-color': '#1a73e8', 'circle-stroke-width': 3 } });
      map.addLayer({ id: 'cursor', type: 'circle', source: 'cursor', paint: { 'circle-radius': 7, 'circle-color': '#111827', 'circle-stroke-color': '#fff', 'circle-stroke-width': 2.5 } });
      map.on('mousemove', 'actual', e => { let best = null, bd = 1e9; for (const p of trip) { const dd = haver([e.lngLat.lng, e.lngLat.lat], [p.lon, p.lat]); if (dd < bd) { bd = dd; best = p; } } if (best && bd < 80 && opts.onHover) opts.onHover(`${best.ts.slice(11, 19)}  ${best.speed_kmh} km/h`); });
      ready = true; fitAll(0);
    });
    function fitAll(dur) { const b = new maplibregl.LngLatBounds(); coords.forEach(c => b.extend(c)); if (mode === 'no_show') { const [lat, lon] = pickup; b.extend([lon - .003, lat - .003]); b.extend([lon + .003, lat + .003]); } else kase.route.polyline.forEach(p => b.extend(ll(p))); map.fitBounds(b, { padding: opts.padding || { top: 60, bottom: 40, left: 40, right: 40 }, duration: dur || 0 }); }
    function dim(on) { ['actual', 'actual-speed', 'route', 'segs', 'segs-outline'].forEach(l => map.getLayer(l) && map.setPaintProperty(l, 'line-opacity', on ? .25 : 1)); ['seglbl', 'marks-l', 'bandlbl'].forEach(l => map.getLayer(l) && map.setPaintProperty(l, 'text-opacity', on ? .35 : 1)); }
    const api = {
      map, mode, t0, t1, trip, segFacts, stopFacts,
      setFindings(list) { findings = {}; for (const sf of (list || [])) findings[sf.fact_id] = (sf.finding ? (sf.finding === 'exempt' ? true : sf.finding === 'counts' ? false : null) : sf.exempt); if (ready) { map.getSource('segs').setData(segState()); map.getSource('seglbl').setData(segLabels()); } },
      setSpeedMode(on) { if (!ready) return; const v = on ? 'visible' : 'none', nv = on ? 'none' : 'visible'; ['actual-speed', 'segs-outline', 'bandlbl'].forEach(l => map.setLayoutProperty(l, 'visibility', v)); ['actual', 'segs'].forEach(l => map.setLayoutProperty(l, 'visibility', nv)); },
      highlight(f) { if (!ready) return; const v = f.value || {}; let feats = [], bb = new maplibregl.LngLatBounds();
        if (isSeg(f)) { const cs = segCoords(f); feats = [{ type: 'Feature', properties: {}, geometry: { type: 'LineString', coordinates: cs } }]; cs.forEach(c => bb.extend(c)); }
        else if (v.lat && v.lon) { feats = [{ type: 'Feature', properties: {}, geometry: { type: 'Point', coordinates: [v.lon, v.lat] } }]; bb.extend([v.lon, v.lat]); }
        else if (v.road_name) { const bd = kase.traffic.speed_bands.find(b => b.road_name === v.road_name && b.geometry); if (!bd) return false; feats = [{ type: 'Feature', properties: {}, geometry: { type: 'LineString', coordinates: bd.geometry.map(ll) } }]; bd.geometry.forEach(p => bb.extend(ll(p))); }
        else if (f.source === 'gps' || f.source === 'timeline') { feats = [{ type: 'Feature', properties: {}, geometry: { type: 'LineString', coordinates: coords } }]; coords.forEach(c => bb.extend(c)); }
        else return false;
        map.getSource('hl').setData({ type: 'FeatureCollection', features: feats }); dim(true);
        if (feats[0].geometry.type === 'Point') map.flyTo({ center: feats[0].geometry.coordinates, zoom: 16.5, duration: 700 }); else map.fitBounds(bb, { padding: 80, duration: 700, maxZoom: 16.5 });
        return true; },
      clear() { if (!ready) return; map.getSource('hl').setData({ type: 'FeatureCollection', features: [] }); dim(false); fitAll(700); },
      cursorAt(t) { if (!ready) return null; let b = trip[0]; for (const p of trip) if (Math.abs(tsec(p.ts) - t) < Math.abs(tsec(b.ts) - t)) b = p; map.getSource('cursor').setData({ type: 'FeatureCollection', features: [{ type: 'Feature', properties: {}, geometry: { type: 'Point', coordinates: [b.lon, b.lat] } }] }); return b; },
      cursorOff() { if (ready) map.getSource('cursor').setData({ type: 'FeatureCollection', features: [] }); },
      resize() { map.resize(); }
    };
    return api;
  }

  // ---- timeline (SVG) ----
  function timeline(svg, kase, table, api, sel, onScrub) {
    const T = kase.trip; const mode = api.mode; const t0 = api.t0, t1 = api.t1;
    const W = svg.clientWidth || 900, H = svg.clientHeight || 64; const L = 44, R = W - 12, y = 40, h = 12;
    const x = t => L + (t - t0) / (t1 - t0) * (R - L); const hmm = t => `${String(Math.floor(t / 3600)).padStart(2, '0')}:${String(Math.floor(t % 3600 / 60)).padStart(2, '0')}`;
    let s = `<rect x="${L}" y="${y}" width="${R - L}" height="${h}" rx="3" fill="#cbd5e1"/>`;
    for (const f of api.segFacts) { const a = tsec(f.value.start), b = tsec(f.value.end); const on = !sel || sel === f.id; const st = api.findings && api.findings[f.id]; s += `<rect x="${x(a)}" y="${y}" width="${x(b) - x(a)}" height="${h}" rx="3" fill="${st === true ? '#f59e0b' : st === false ? '#dc2626' : '#6b7280'}" opacity="${on ? 1 : .3}"/><text x="${(x(a) + x(b)) / 2}" y="${y + h + 12}" font-size="10" text-anchor="middle" fill="#374151">${f.id} ${hmm(a)}–${hmm(b)}</text>`; }
    for (const f of api.stopFacts) { const a = tsec(f.value.start), b = tsec(f.value.end); const on = !sel || sel === f.id; s += `<rect x="${x(a)}" y="${y - 3}" width="${Math.max(3, x(b) - x(a))}" height="${h + 6}" rx="2" fill="#7f1d1d" opacity="${on ? 1 : .3}"/><text x="${x(a)}" y="${y - 6}" font-size="10" text-anchor="middle" fill="#7f1d1d">${f.id} stop</text>`; }
    let lastX = -1e9, row = 0; const pre = [];
    for (const m of kase.chat) { const t = tsec(m.ts); if (t < t0) { pre.push(m); continue; } const px = x(t); row = (px - lastX < 70) ? row + 1 : 0; lastX = px; const dy = row * 11; s += `<line x1="${px}" y1="${y - 14 - dy}" x2="${px}" y2="${y}" stroke="#2563eb" stroke-width="2"/><text x="${px + (row ? 4 : 0)}" y="${y - 16 - dy}" font-size="10" text-anchor="${row ? 'start' : 'middle'}" fill="#2563eb">${m.sender || m.from} ${hm(m.ts)}</text>`; }
    if (pre.length) s += `<text x="${L}" y="${y - 16}" font-size="10" fill="#2563eb">chat before pickup: ${pre.map(m => hm(m.ts) + ' ' + (m.sender || m.from)).join(' · ')}</text>`;
    if (mode === 'no_show') { const mk = (ts, txt, col, dy) => { if (!ts) return; const t = tsec(ts); s += `<line x1="${x(t)}" y1="${y}" x2="${x(t)}" y2="${y + h + 4 + dy}" stroke="${col}" stroke-width="2.5"/><text x="${x(t)}" y="${y + h + 24 + dy}" font-size="10" text-anchor="middle" fill="${col}" font-weight="600">${txt} ${hmm(t)}</text>`; }; mk(T.driver_arrived_at, 'in 200 m', '#1a73e8', 0); mk(T.driver_pressed_here_at, T.arrival_confirmed_by === 'platform_auto' ? 'auto-arrival' : "I'm Here", '#7c3aed', T.driver_arrived_at && Math.abs(tsec(T.driver_pressed_here_at) - tsec(T.driver_arrived_at)) < 120 ? 12 : 0); }
    s += `<text x="${L}" y="${y + h + 12}" font-size="10" fill="#111827">${hmm(t0)} ${mode === 'no_show' ? 'accepted' : 'pickup'}</text><text x="${R}" y="${y + h + 12}" font-size="10" fill="#111827" text-anchor="end">${mode === 'no_show' ? T.cancelled_by + ' cancelled' : 'drop-off'} ${hmm(t1)}</text>`;
    s += `<line id="scrub" x1="${L}" y1="${y - 4}" x2="${L}" y2="${y + h + 4}" stroke="#111827" stroke-width="2" opacity="0"/>`;
    svg.innerHTML = s;
    svg.onmousemove = e => { const r = svg.getBoundingClientRect(); const px = e.clientX - r.left; if (px < L || px > R) return; const t = t0 + (px - L) / (R - L) * (t1 - t0); const p = api.cursorAt(t); const sc = svg.querySelector('#scrub'); sc.setAttribute('x1', px); sc.setAttribute('x2', px); sc.setAttribute('opacity', 1); if (p && onScrub) onScrub(`${p.ts.slice(11, 19)}  ${p.speed_kmh} km/h`); };
    svg.onmouseleave = () => { api.cursorOff(); const sc = svg.querySelector('#scrub'); if (sc) sc.setAttribute('opacity', 0); };
  }
  return { mount, timeline, tsec, hm };
})();
