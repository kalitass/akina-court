/* Akina Court · human review UI (/human-review.html?case=B-0011). Question card first: complaint → the one open question →
   map + what is settled (left) and why / evidence / more / decision (right). Every amount shown comes from the server
   (/api/human-review/{id}: option amounts; /preview: the decision's ruling); the page never computes or sends an amount for
   an adopted option. Without ?case= the page lists the human-review queue. */
(function () {
  'use strict';
  var Q = new URLSearchParams(location.search), CID = Q.get('case');
  var LIGHT = !!(window.AKINA_THEME && window.AKINA_THEME.light);
  var app = document.getElementById('app');
  var WHO = {rider: 'Rider', driver: 'Driver', system: 'System'};
  var TYPE = {route_deviation: 'Route deviation', no_show: 'No-show fee', fare_dispute: 'Surge pricing', safety: 'Safety'};
  var QUEUE = {review_24h: 'Review · 24 h', urgent_safety: 'Urgent safety · 2 h', auto_resolve: 'Auto'};
  var KIND = {segment_scope: 'Is the segment covered by the agreement?', safety: 'Safety finding', decision: 'Outcome of the case'};
  var TOKEN_KEY = 'akinaDemoToken';

  function esc(s) { return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) { return {'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]; }); }
  function money(a) { return a == null ? '—' : '$' + Number(a).toFixed(2); }
  function t(ts) { return ts ? Date.parse(ts) : null; }
  function hm(ts) { var m = /T(\d\d:\d\d)/.exec(ts || ''); return m ? m[1] : ''; }
  function css(v) { return getComputedStyle(document.documentElement).getPropertyValue(v).trim(); }
  function step(n, s) { return '<span class="stepn">' + n + '</span>' + s; }
  function api(path, opts) {
    return fetch(path, opts).then(function (r) {
      return r.text().then(function (txt) { var j = null; try { j = JSON.parse(txt); } catch (e) {} return {ok: r.ok, status: r.status, body: j, text: txt}; });
    });
  }
  function detail(r) { return (r.body && (typeof r.body.detail === 'string' ? r.body.detail : JSON.stringify(r.body.detail))) || r.text || ('HTTP ' + r.status); }
  function slaText(due) {
    if (!due) return '';
    var ms = Date.parse(due) - Date.now(), h = Math.floor(Math.abs(ms) / 3600e3), m = Math.floor(Math.abs(ms) % 3600e3 / 60e3);
    return ms >= 0 ? '⏱ ' + h + ' h ' + String(m).padStart(2, '0') + ' m left' : '⏱ overdue by ' + h + ' h ' + String(m).padStart(2, '0') + ' m';
  }

  /* ------------------------------------------------------------------ no case: the queue */
  function renderQueue() {
    document.title = 'Human review queue · Akina Court';
    api('/api/human-review').then(function (r) {
      if (!r.ok) { app.innerHTML = '<div class="notice"><h1>Human review queue</h1><p>' + esc(detail(r)) + '</p></div>'; return; }
      app.innerHTML = '<div class="notice" style="margin-bottom:10px"><h1>Cases waiting for a person</h1><p>Only cases the court escalated reach this page (the "Needs a human" tab of the <a href="/ops.html">ops page</a>). Each one has a single open question; code has settled the rest.</p></div>'
        + '<ul class="qlist">' + r.body.map(function (c) {
          var st = c.status === 'decided' ? '<span class="badge ok">decided</span>' : c.status === 'awaiting_evidence' ? '<span class="badge hr">awaiting evidence</span>' : '';
          return '<li><a class="id" href="/human-review.html?case=' + encodeURIComponent(c.case_id) + '">' + esc(c.case_id) + '</a><div class="t"><a href="/human-review.html?case=' + encodeURIComponent(c.case_id) + '">' + esc(c.title) + '</a><small>' + esc(TYPE[c.dispute_type] || c.dispute_type) + ' · “' + esc(c.statement) + '”</small></div>'
            + '<div class="r"><span class="badge ' + (c.queue === 'urgent_safety' ? 'red' : 'hr') + '">' + esc(QUEUE[c.queue] || c.queue) + '</span> ' + st + '<br>' + esc(slaText(c.due_at)) + '</div></li>';
        }).join('') + '</ul>';
    });
  }

  /* ------------------------------------------------------------------ geometry */
  function geo(C, F) {
    var g = (C.gps || []).map(function (p) { return {t: t(p.ts), ll: [p.lon, p.lat]}; }).filter(function (p) { return p.t != null; });
    var tr = C.trip || {};
    var span = [t(tr.pickup_at) || (g[0] && g[0].t), t(tr.dropoff_at) || t(tr.cancelled_at) || (g.length ? g[g.length - 1].t : null)];
    var segs = [], stops = [], chat = [];
    F.facts.forEach(function (f) {
      var v = f.value || {};
      if (v.extra_km != null && v.start) segs.push({id: f.id, s: t(v.start), e: t(v.end), km: v.extra_km, start: v.start, end: v.end});
      if (v.duration_s != null && v.lat != null) stops.push({id: f.id, ll: [v.lon, v.lat], dur: v.duration_s, m: v.m_from_pickup});
      if (v.idx != null && v.from && v.ts && v.kind !== 'call') chat.push({id: f.id, t: t(v.ts), ts: v.ts, from: v.from, text: (/[“"](.+)[”"]/.exec(f.text) || [0, f.text])[1]});
    });
    var here = F.facts.filter(function (f) { return f.value && f.value.driver_pressed_here_at; })[0];
    return {g: g, span: span, segs: segs, stops: stops, chat: chat, route: ((C.route || {}).polyline || []).map(function (p) { return [p[1], p[0]]; }),
      pickup: tr.pickup, dropoff: tr.dropoff, noShow: C.dispute.type === 'no_show', here: here ? {t: t(here.value.driver_pressed_here_at), ts: here.value.driver_pressed_here_at, m: here.value.m_from_pickup_at_tap} : null,
      times: {pickup: tr.pickup_at, dropoff: tr.dropoff_at || tr.cancelled_at}};
  }
  function segCoords(G, s, e) { return G.g.filter(function (p) { return p.t >= s && p.t <= e; }).map(function (p) { return p.ll; }); }
  function posAt(G, ts) { var b = G.g[0]; for (var i = 0; i < G.g.length; i++) { if (G.g[i].t <= ts) b = G.g[i]; else break; } return b ? b.ll : [G.pickup.lon, G.pickup.lat]; }
  function actual(G) { return G.g.filter(function (p) { return G.noShow ? p.t <= G.span[1] : (p.t >= G.span[0] - 1000 && p.t <= G.span[1]); }).map(function (p) { return p.ll; }); }
  function approach(G) { return G.noShow ? [] : G.g.filter(function (p) { return p.t <= G.span[0]; }).map(function (p) { return p.ll; }); }
  function colorKey(st) { return st === 'exempt' ? 'amber' : st === 'counts' ? 'red' : 'purple'; }
  function word(st) { return st === 'exempt' ? 'exempt' : st === 'counts' ? 'counts' : 'undetermined'; }
  function circle(ll, r) { var c = []; for (var i = 0; i <= 72; i++) { var a = i / 72 * 2 * Math.PI; c.push([ll[0] + r * Math.sin(a) / (111320 * Math.cos(ll[1] * Math.PI / 180)), ll[1] + r * Math.cos(a) / 110540]); } return c; }

  /* ------------------------------------------------------------------ map: MapLibre over an SVG drawing of the same geometry */
  function mountMap(host, G, o) {
    var state = Object.assign({}, o.base), answers = {};
    function segState(s) { return answers[s.id] || state[s.id] || 'undetermined'; }
    var tools = document.createElement('div'); tools.className = 'mtools';
    var leg = document.createElement('div'); leg.className = 'mleg';
    var track = LIGHT ? '#111827' : '#f4f6fa';
    leg.innerHTML = (G.noShow ? '<span><i style="background:' + track + '"></i>Driver approach</span><span><i style="background:var(--blue);opacity:.35;height:10px;width:10px;border-radius:50%"></i>Pickup 200 m radius</span>'
        : '<span><i class="dash"></i>Optimal route</span><span><i style="background:' + track + '"></i>Actual path</span>')
      + (G.segs.length ? '<span><i style="background:var(--purple)"></i>Undetermined</span><span><i style="background:var(--red)"></i>Counts</span><span><i style="background:var(--amber)"></i>Exempt</span>' : '')
      + (G.chat.length && !G.noShow ? '<span>💬 Where a message was sent</span>' : '');
    var apiObj = {setAnswers: function () {}};
    var focus = o.focus && o.focus.start ? {s: t(o.focus.start), e: t(o.focus.end || o.focus.start)} : null;
    var under = document.createElement('div'); under.className = 'under';
    host.appendChild(under); host.appendChild(tools); host.appendChild(leg);
    var drawSvg = function (el) { svgMap(el, G, segState, focus); };
    drawSvg(under);
    function tool(lbl, fn, on) { var b = document.createElement('button'); b.type = 'button'; b.textContent = lbl; if (on) b.className = 'on'; b.onclick = function () { Array.prototype.forEach.call(tools.querySelectorAll('button[data-fit]'), function (x) { x.className = ''; }); b.className = 'on'; fn(); }; b.setAttribute('data-fit', '1'); tools.appendChild(b); }
    function fallbackOnly(map) { try { if (map) map.remove(); } catch (e) {} host.innerHTML = ''; var d = document.createElement('div'); d.className = 'under'; host.appendChild(d); host.appendChild(tools); host.appendChild(leg); drawSvg(d); apiObj.setAnswers = function (a) { answers = a || {}; d.innerHTML = ''; drawSvg(d); }; tools.querySelectorAll('button[data-fit]').forEach(function (b) { b.remove(); }); }
    apiObj.setAnswers = function (a) { answers = a || {}; under.innerHTML = ''; drawSvg(under); };
    if (!window.maplibregl) { fallbackOnly(null); return apiObj; }
    var map;
    try {
      map = new maplibregl.Map({container: host, style: LIGHT ? 'https://tiles.openfreemap.org/styles/positron' : 'https://tiles.openfreemap.org/styles/dark',
        center: [G.pickup.lon, G.pickup.lat], zoom: 12, attributionControl: false, fadeDuration: 0, cooperativeGestures: true});
    } catch (e) { fallbackOnly(null); return apiObj; }
    map.addControl(new maplibregl.NavigationControl({showCompass: false}), 'top-right');
    var rendered = false, styled = false, fitWhich = null, K, labels = {};
    map.on('load', function () { rendered = true; if (under.parentNode) under.parentNode.removeChild(under); map.resize(); if (fitWhich) fit(fitWhich); });
    setTimeout(function () { if (!rendered) fallbackOnly(map); }, 8000);      /* Safari file:// or blocked tiles: keep the drawing */
    if (window.ResizeObserver) { var lastW = 0; new ResizeObserver(function () { var w = host.clientWidth; if (Math.abs(w - lastW) < 2) return; lastW = w; try { map.resize(); if (styled && fitWhich) fit(fitWhich); } catch (e) {} }).observe(host); }
    function bounds(which) {
      var b = new maplibregl.LngLatBounds(), pts = [];
      if (which === 'focus' && focus) { pts = segCoords(G, focus.s - 120e3, focus.e + 60e3); G.chat.forEach(function (m) { if (m.t <= focus.e && m.t >= focus.s - 600e3) pts.push(posAt(G, m.t)); }); }
      if (which === 'pickup' || (which === 'focus' && pts.length < 2 && G.noShow)) { pts = actual(G); pts.push([G.pickup.lon, G.pickup.lat]); }
      if (pts.length < 2) { pts = actual(G).concat(G.noShow ? [] : G.route); pts.push([G.pickup.lon, G.pickup.lat]); if (!G.noShow && G.dropoff) pts.push([G.dropoff.lon, G.dropoff.lat]); }
      pts.forEach(function (p) { b.extend(p); });
      return b;
    }
    function fit(which, dur) { fitWhich = which; map.fitBounds(bounds(which), {padding: {top: 56, bottom: 80, left: 70, right: 70}, duration: dur || 0, maxZoom: 16}); }
    function segsData() { return {type: 'FeatureCollection', features: G.segs.map(function (s) { return {type: 'Feature', properties: {color: K[colorKey(segState(s))]}, geometry: {type: 'LineString', coordinates: segCoords(G, s.s, s.e)}}; })}; }
    function line(c) { return {type: 'Feature', properties: {}, geometry: {type: 'LineString', coordinates: c}}; }
    map.on('style.load', function () {
      styled = true;
      K = {blue: css('--blue'), amber: css('--amber'), red: css('--red'), purple: css('--purple'), muted: css('--muted'), bg: css('--bg')};
      if (!LIGHT) {
        var PAL = {background: '#0e1218', water: '#121c2b', waterway: '#121c2b', landuse_residential: '#11161d', landuse_park: '#121a1a', landcover_wood: '#121a1a', building: '#13181f',
          highway_path: '#1d242e', highway_minor: '#242c38', highway_major_subtle: '#2a3340', highway_major_inner: '#2f3947', highway_motorway_inner: '#3a4556', highway_motorway_subtle: '#2a3340', highway_major_casing: '#0b0e13', highway_motorway_casing: '#0b0e13', railway: '#222a35', railway_transit: '#222a35', railway_minor: '#222a35'};
        map.getStyle().layers.forEach(function (l) {
          var c = PAL[l.id], prop = l.type === 'fill' ? 'fill-color' : l.type === 'line' ? 'line-color' : l.type === 'background' ? 'background-color' : null;
          try { if (c && prop) map.setPaintProperty(l.id, prop, c);
            if (l.type === 'symbol') { map.setPaintProperty(l.id, 'text-color', /place_/.test(l.id) ? '#6f7a8c' : '#7b8596'); map.setPaintProperty(l.id, 'text-halo-color', '#0e1218'); map.setPaintProperty(l.id, 'text-halo-width', 1.2); } } catch (e) {}
        });
      }
      var lb = {'line-cap': 'round', 'line-join': 'round'};
      map.addSource('route', {type: 'geojson', data: line(G.route)});
      map.addSource('appr', {type: 'geojson', data: line(approach(G))});
      map.addSource('actual', {type: 'geojson', data: line(actual(G))});
      map.addSource('segs', {type: 'geojson', data: segsData()});
      if (G.noShow) {
        map.addSource('circle', {type: 'geojson', data: {type: 'Feature', geometry: {type: 'Polygon', coordinates: [circle([G.pickup.lon, G.pickup.lat], 200)]}}});
        map.addLayer({id: 'circle-fill', type: 'fill', source: 'circle', paint: {'fill-color': K.blue, 'fill-opacity': .12}});
        map.addLayer({id: 'circle-line', type: 'line', source: 'circle', paint: {'line-color': K.blue, 'line-width': 1.5, 'line-dasharray': [2, 2]}});
        map.addLayer({id: 'route', type: 'line', source: 'route', layout: {'line-cap': 'round'}, paint: {'line-color': K.blue, 'line-width': 2, 'line-dasharray': [1.2, 1.8], 'line-opacity': .35}});
      } else {
        map.addLayer({id: 'route-casing', type: 'line', source: 'route', layout: lb, paint: {'line-color': K.bg, 'line-width': 6, 'line-opacity': .6}});
        map.addLayer({id: 'route', type: 'line', source: 'route', layout: {'line-cap': 'round'}, paint: {'line-color': K.blue, 'line-width': 3, 'line-dasharray': [1.2, 1.8], 'line-opacity': .85}});
      }
      map.addLayer({id: 'appr', type: 'line', source: 'appr', layout: {'line-cap': 'round'}, paint: {'line-color': K.muted, 'line-width': 2.5, 'line-dasharray': [0.4, 2], 'line-opacity': .8}});
      map.addLayer({id: 'segs-glow', type: 'line', source: 'segs', layout: lb, paint: {'line-color': ['get', 'color'], 'line-width': 20, 'line-opacity': .22, 'line-blur': 4}});
      map.addLayer({id: 'actual-casing', type: 'line', source: 'actual', layout: lb, paint: {'line-color': LIGHT ? '#ffffff' : '#05070b', 'line-width': 9, 'line-opacity': .9}});
      map.addLayer({id: 'actual', type: 'line', source: 'actual', layout: lb, paint: {'line-color': track, 'line-width': 5}});
      map.addLayer({id: 'segs', type: 'line', source: 'segs', layout: lb, paint: {'line-color': ['get', 'color'], 'line-width': 5.5}});
      function mk(html, ll, anchor, off) { var d = document.createElement('div'); d.innerHTML = html; return new maplibregl.Marker({element: d.firstChild, anchor: anchor || 'center', offset: off || [0, 0]}).setLngLat(ll).addTo(map); }
      mk('<div class="pin"><div class="dotp"></div></div>', [G.pickup.lon, G.pickup.lat]);
      mk('<div class="plab">Pickup · ' + esc(G.pickup.name) + (G.times.pickup ? '<small>' + hm(G.times.pickup) + '</small>' : '') + '</div>', [G.pickup.lon, G.pickup.lat], 'top');
      if (!G.noShow && G.dropoff) {
        mk('<div class="pin"><div class="dotp"></div></div>', [G.dropoff.lon, G.dropoff.lat]);
        mk('<div class="plab">Drop-off · ' + esc(G.dropoff.name) + (G.times.dropoff ? '<small>' + hm(G.times.dropoff) + '</small>' : '') + '</div>', [G.dropoff.lon, G.dropoff.lat], 'top');
      }
      G.segs.forEach(function (s) {
        var cs = segCoords(G, s.s, s.e), mid = cs[Math.floor(cs.length / 2)];
        if (!mid) return;
        labels[s.id] = mk('<div class="seglab"></div>', mid, 'bottom');
      });
      paintLabels();
      var lastT = -1e15, stack = 0, at = null;
      if (!G.noShow) G.chat.forEach(function (m) {
        stack = m.t - lastT < 240e3 ? stack + 1 : 0; lastT = m.t; if (!stack) at = posAt(G, m.t);
        var long = (o.basis || []).indexOf(m.id) >= 0;
        mk('<div class="cpin ' + m.from + (long ? ' long' : '') + '" title="' + esc(m.text) + '"><b>💬 ' + hm(m.ts) + ' ' + WHO[m.from] + '</b>' + esc(long ? '“' + m.text + '”' : (m.text.length > 34 ? m.text.slice(0, 34) + '…' : m.text)) + '</div>', at, 'left', [0, stack * (long ? 64 : 30)]);
      });
      G.stops.forEach(function (s) { mk('<div class="stoppin"><b>' + s.id + '</b>stopped ' + Math.round(s.dur / 60) + ' min' + (G.noShow && s.m != null ? ' · ' + s.m + ' m from pickup' : '') + '</div>', s.ll, 'left'); });
      if (G.noShow && G.here) {
        mk('<div class="herepin"><b>I\'m Here</b>' + hm(G.here.ts) + (G.here.m != null ? ' · ' + G.here.m + ' m from pickup' : '') + '</div>', posAt(G, G.here.t), 'left', [0, -30]);
        mk('<div class="circlab">200 m arrival radius</div>', [G.pickup.lon, G.pickup.lat - 210 / 110540], 'top');
      }
      map.resize();
      fit(focus ? 'focus' : (G.noShow ? 'pickup' : 'all'));
    });
    function paintLabels() {
      G.segs.forEach(function (s) { var m = labels[s.id]; if (!m) return; var st = segState(s);
        var el = m.getElement(); el.classList.remove('amb', 'red', 'und'); el.classList.add({amber: 'amb', red: 'red', purple: 'und'}[colorKey(st)]);   /* keep MapLibre's own marker classes */
        el.textContent = s.id + ' · ' + hm(s.start) + '–' + hm(s.end) + ' · +' + s.km.toFixed(2) + ' km · ' + word(st); });
    }
    apiObj.setAnswers = function (a) {
      answers = a || {};
      if (under.parentNode) { under.innerHTML = ''; drawSvg(under); }
      if (!styled) return;
      map.getSource('segs').setData(segsData()); paintLabels();
    };
    if (focus) tool(G.noShow ? 'Pickup' : 'Question', function () { fit('focus', 600); }, true);
    tool('Whole trip', function () { fit('all', 600); }, !focus);
    var rp = document.createElement('a'); rp.className = 'btn sm'; rp.style.cssText = 'padding:3px 9px;font:700 11px var(--mono);border-radius:999px;background:var(--panel)';
    rp.href = '/replay.html?case=' + encodeURIComponent(CID); rp.target = '_blank'; rp.rel = 'noopener'; rp.textContent = 'Open in replay ↗'; tools.appendChild(rp);
    return apiObj;
  }

  /* the same geometry without a basemap (shown until MapLibre has drawn, and instead of it when tiles never load) */
  function svgMap(host, G, segState, focus) {
    var W = host.clientWidth || (host.parentNode && host.parentNode.clientWidth) || 640, H = host.clientHeight || 430;
    var pts = actual(G).concat(G.noShow ? [[G.pickup.lon, G.pickup.lat]] : G.route);
    if (!pts.length) return;
    var minx = 1e9, maxx = -1e9, miny = 1e9, maxy = -1e9;
    pts.forEach(function (p) { minx = Math.min(minx, p[0]); maxx = Math.max(maxx, p[0]); miny = Math.min(miny, p[1]); maxy = Math.max(maxy, p[1]); });
    var kx = Math.cos(((miny + maxy) / 2) * Math.PI / 180), side = 90, top = 50, bottom = 90;      /* room for the tools and the legend */
    var sc = Math.min((W - 2 * side) / ((maxx - minx) * kx || 1e-6), (H - top - bottom) / ((maxy - miny) || 1e-6));
    var ox = (W - (maxx - minx) * kx * sc) / 2, oy = (H - top - bottom - (maxy - miny) * sc) / 2;
    var X = function (p) { return ox + (p[0] - minx) * kx * sc; }, Y = function (p) { return H - bottom - oy - (p[1] - miny) * sc; };
    var CX = function (x) { return Math.max(70, Math.min(W - 70, x)).toFixed(1); };
    var path = function (c) { return c.map(function (p, i) { return (i ? 'L' : 'M') + X(p).toFixed(1) + ' ' + Y(p).toFixed(1); }).join(''); };
    var s = '<svg width="100%" height="' + H + '" viewBox="0 0 ' + W + ' ' + H + '" style="display:block" role="img" aria-label="Trip drawing: optimal route, actual path and off-route segments">';
    if (G.noShow) { var c = circle([G.pickup.lon, G.pickup.lat], 200); s += '<path d="' + path(c) + 'Z" fill="var(--blue)" fill-opacity=".12" stroke="var(--blue)" stroke-dasharray="4 4"/>'; }
    if (G.route.length) s += '<path d="' + path(G.route) + '" fill="none" stroke="var(--blue)" stroke-width="3" stroke-dasharray="4 6" opacity="' + (G.noShow ? .35 : .85) + '"/>';
    s += '<path d="' + path(actual(G)) + '" fill="none" stroke="' + (LIGHT ? '#ffffff' : '#05070b') + '" stroke-width="8" stroke-linejoin="round" stroke-linecap="round" opacity=".9"/>';
    s += '<path d="' + path(actual(G)) + '" fill="none" stroke="' + (LIGHT ? '#111827' : '#f4f6fa') + '" stroke-width="4" stroke-linejoin="round" stroke-linecap="round"/>';
    G.segs.forEach(function (sg) { var cs = segCoords(G, sg.s, sg.e), mid = cs[Math.floor(cs.length / 2)], k = colorKey(segState(sg));
      if (cs.length < 2) return;
      s += '<path d="' + path(cs) + '" fill="none" stroke="var(--' + k + ')" stroke-width="5" stroke-linejoin="round" stroke-linecap="round"/>';
      if (mid) s += '<text x="' + CX(X(mid)) + '" y="' + (Y(mid) - 10).toFixed(1) + '" text-anchor="middle" fill="var(--' + k + ')" font-size="11" font-weight="700" font-family="var(--mono)" stroke="var(--bg)" stroke-width="3" paint-order="stroke">' + sg.id + ' · +' + sg.km.toFixed(2) + ' km · ' + word(segState(sg)) + '</text>'; });
    [[G.pickup, 'Pickup'], G.noShow ? null : [G.dropoff, 'Drop-off']].forEach(function (p) { if (!p || !p[0]) return; var q = [p[0].lon, p[0].lat];
      s += '<circle cx="' + X(q).toFixed(1) + '" cy="' + Y(q).toFixed(1) + '" r="5" fill="var(--ink)"/><text x="' + (X(q) + 8).toFixed(1) + '" y="' + (Y(q) + 4).toFixed(1) + '" fill="var(--ink2)" font-size="11">' + p[1] + ' · ' + esc(p[0].name) + '</text>'; });
    if (!G.noShow) G.chat.forEach(function (m, i) { var q = posAt(G, m.t); s += '<text x="' + (X(q) + 8).toFixed(1) + '" y="' + (Y(q) - 6 + i * 14).toFixed(1) + '" fill="var(--blue)" font-size="11">💬 ' + hm(m.ts) + ' ' + WHO[m.from] + '</text>'; });
    if (G.noShow && G.here) { var q = posAt(G, G.here.t); s += '<text x="' + (X(q) + 8).toFixed(1) + '" y="' + (Y(q) - 8).toFixed(1) + '" fill="var(--purple)" font-size="11" font-weight="700">I\'m Here</text>'; }
    s += '</svg>';
    host.innerHTML = s + '<div class="fallback">drawing without a basemap</div>';
  }

  /* ------------------------------------------------------------------ page blocks */
  function evidenceList(items, F) {
    return '<ul class="ev-list">' + items.map(function (e) {
      return '<li><span class="t">' + esc(e.at || '—') + '</span><div><span class="who ' + e.who + '">' + WHO[e.who] + '</span><span class="chip" title="' + esc((F[e.fact_id] || {}).text || '') + '">' + e.fact_id + '</span>'
        + (e.quote ? '<q>' + esc(e.text) + '</q>' : esc(e.text)) + (e.at === 'after the trip' ? '<span class="meta">written after the trip, not part of the chat</span>' : '') + '</div></li>';
    }).join('') + '</ul>';
  }
  function settledBox(P) {
    var rows = P.settled.map(function (s) {
      var val = (s.finding ? '<b>' + esc(s.finding) + '</b>' : '') + (s.amount != null ? ' · ' + money(s.amount) : '');
      return '<li><span class="t">' + esc(s.subject) + '</span><div>' + esc(s.label) + ' → ' + val + ' <span class="muted small">(' + (s.by === 'code' ? 'measured by code' : 'found by the court, verified') + ')</span>' + (s.detail ? '<span class="meta">' + esc(s.detail.length > 220 ? s.detail.slice(0, 219) + '…' : s.detail) + '</span>' : '') + '</div></li>';
    }).join('');
    return '<div class="box"><div class="k">Already settled · not yours to decide<span class="r muted">code or the court, checked</span></div>'
      + (rows ? '<ul class="ev-list">' + rows + '</ul>' : '<div class="small muted">Nothing else on this case is settled; the question above is the whole case.</div>')
      + (P.settled_amount ? '<div class="small" style="margin-top:6px">Refund already fixed outside the open question: <b>' + money(P.settled_amount) + '</b></div>' : '') + '</div>';
  }
  function sidesBox(P, Fx) {
    var sides = (P.questions[0] && Object.keys(P.questions[0].sides).length ? P.questions[0].sides : P.sides);
    var side = function (k) { var s = sides[k]; if (!s) return ''; return '<div class="side ' + k + '"><div class="h">' + k + '\'s advocate</div>' + esc(s.line)
      + '<div class="small muted" style="margin-top:4px">asks: ' + esc(s.outcome || '—') + (s.amount != null ? ' ' + money(s.amount) : '') + (s.ground ? ' · ground: ' + esc(s.ground) + (s.ground_brief && s.ground_brief !== s.ground ? ' (brief: ' + esc(s.ground_brief) + ')' : '') : '') + '</div>'
      + (s.weaknesses.length ? '<div class="small" style="margin-top:6px"><b>Admits against itself</b><ul>' + s.weaknesses.map(function (w) { return '<li>' + esc(w) + '</li>'; }).join('') + '</ul></div>' : '') + '</div>'; };
    var ctx = P.context.map(function (id) { return '<li><span class="t">' + id + '</span><div>' + esc((Fx[id] || {}).text || '') + '</div></li>'; }).join('');
    return '<div class="box"><details><summary>Both sides (one line each + what they admit)</summary><div class="sides">' + side('rider') + side('driver') + '</div></details>'
      + '<details><summary>Fare &amp; 90-day history</summary><ul class="ev-list">' + ctx + '</ul></details></div>';
  }
  function linksBox(P) {
    var L = P.links, a = function (h, s) { return '<a class="btn sm" target="_blank" rel="noopener" href="' + esc(h) + '">' + s + ' ↗</a>'; };
    return '<div class="box"><div class="k">' + step(3, 'See more') + '<span class="r muted">only if the evidence is not enough</span></div><div class="links">'
      + a(L.court, 'AI court replay') + a(L.trip, 'Trip replay') + a(L.facts, 'Facts') + a(L.policy, 'Policy') + a(L.receipt, 'Receipt') + '</div></div>';
  }

  /* ------------------------------------------------------------------ decision panel */
  function suggestions(P) {
    var q = P.questions[0], out = [];
    if (q.kind === 'segment_scope') {
      var w = q.title.split(':')[0];
      out.push({to: 'driver', item: 'Which road did you drive during ' + w + '? A screenshot of your navigation for that stretch, if you have one.'});
      out.push({to: 'platform', item: 'The navigation log for ' + w + ', if the road names on record are incomplete.'});
      out.push({to: 'rider', item: 'What did you agree to before the detour, in your own words?'});
    } else if (q.kind === 'decision') {
      var gap = P.evidence_gap ? P.evidence_gap.gap : '';
      if (/GPS/i.test(gap)) {
        var win = /between (\d\d:\d\d(?::\d\d)?) and (\d\d:\d\d(?::\d\d)?)/.exec(gap), span = win ? ' (' + win[1] + '–' + win[2] + ')' : '';
        out.push({to: 'platform', item: 'The missing GPS points for the gap in the trace' + span + ', or the platform\'s location log for that time.'});
        out.push({to: 'driver', item: 'Your phone\'s location history for that time' + span + ', if you have it.'});
        out.push({to: 'rider', item: 'Where you were waiting, and when you saw or heard from the driver, in your own words.'});
      } else if (gap) {
        out.push({to: 'platform', item: 'The missing record the court names: ' + gap});
        out.push({to: 'rider', item: 'Your account of what happened, with times.'});
        out.push({to: 'driver', item: 'Your account of what happened, with times.'});
      } else {
        out.push({to: 'platform', item: 'Only if something on record is unclear: the fare breakdown and the in-app notices sent for this trip.'});
      }
    } else {
      out.push({to: 'platform', item: 'In-trip safety report, SOS or call logs, and any in-cabin recording for the trip.'});
      out.push({to: 'rider', item: 'A written account of what was said or done, with times.'});
      out.push({to: 'driver', item: 'A written account of what was said or done, with times.'});
    }
    return out;
  }

  function decisionPanel(host, P, mapApi) {
    var qs = P.questions, anyAdopt = qs.some(function (q) { return q.adoptable && q.options.length; });
    var gapIds = P.evidence_gap && P.evidence_gap.facts.length ? ' (' + P.evidence_gap.facts.join(', ') + ')' : '';
    var subj = qs[0].kind === 'segment_scope' ? qs[0].subject + ' on the map' : qs[0].kind === 'decision' ? 'the record' + gapIds : (P.safety_basis.length ? P.safety_basis.join(', ') : 'the record');
    var sug = suggestions(P);
    var st = {mode: null, choices: {}, findings: {}, reason: '', cites: [], manual: false, amount: '', ask: sug[0].to, picked: {}, extra: '', due: 48, onTimeout: 'decide_on_record',
      checked: false, confirmAcct: false, confirmAmt: false, preview: null, previewErr: '', busy: false, result: null, error: ''};
    var timer = null;
    function opt(q, id) { return q.options.filter(function (o) { return o.id === id; })[0]; }
    function picks() { return st.mode === 'adopt' ? st.choices : st.findings; }
    function needsAcct() { var p = picks(); return qs.some(function (q) { var o = opt(q, p[q.id]); return o && o.requires_confirmation; }); }
    function items() { var a = sug.filter(function (s, i) { return s.to === st.ask && st.picked[i]; }).map(function (s) { return s.item; }); if (st.extra.trim()) a.push(st.extra.trim()); return a; }
    function body() {
      var b = {outcome: {adopt: 'adopt_option', own: 'own_judgment', evidence: 'request_evidence'}[st.mode], reviewer: 'reviewer', checked: st.checked, confirm_account_action: st.confirmAcct};
      if (st.mode === 'adopt') b.choices = st.choices;
      if (st.mode === 'own') { b.findings = st.findings; b.reason = st.reason; b.cited_facts = st.cites; if (st.manual && st.amount !== '') b.amount_override = {amount: +st.amount, confirmed: st.confirmAmt}; }
      if (st.mode === 'evidence') b.request = {to: st.ask, items: items(), due_in_hours: +st.due, on_timeout: st.onTimeout};
      return b;
    }
    function validate() {
      if (!st.mode) return 'choose one of the three outcomes';
      if (st.mode !== 'evidence' && qs.some(function (q) { return !picks()[q.id]; })) return st.mode === 'adopt' ? 'pick an option' : 'choose your finding';
      if (st.mode === 'own') {
        if (st.reason.trim().length < 15) return 'the reason needs at least 15 characters';
        if (!st.cites.length) return 'cite at least one fact';
        if (st.manual && st.amount === '') return 'enter the amount';
        if (st.manual && !st.confirmAmt) return 'confirm the manual amount';
      }
      if (st.mode === 'evidence' && !items().length) return 'ask for at least one item';
      if (needsAcct() && !st.confirmAcct) return 'confirm the account action';
      if (!st.checked) return 'tick the check above';
      return '';
    }
    function sync() {
      var a = {};
      qs.forEach(function (q) { if (q.kind !== 'segment_scope') return; var o = opt(q, picks()[q.id]); if (st.mode !== 'evidence' && o) a[q.subject] = o.finding; });
      mapApi.setAnswers(a);
    }
    function refreshPreview() {
      clearTimeout(timer);
      var ready = st.mode && (st.mode === 'evidence' ? items().length : qs.every(function (q) { return picks()[q.id]; }));
      if (!ready) { st.preview = null; st.previewErr = ''; paintPreview(); return; }
      timer = setTimeout(function () {
        var b = body(); b.checked = true; b.confirm_account_action = true; if (b.amount_override) b.amount_override.confirmed = true;
        if (st.mode === 'own') { if (b.reason.trim().length < 15) b.reason = 'preview only: reason not written yet'; if (!b.cited_facts.length) b.cited_facts = [P.basis[0] || Object.keys(P.facts)[0]]; }
        api('/api/human-review/' + encodeURIComponent(P.case_id) + '/preview', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(b)}).then(function (r) {
          st.preview = r.ok ? r.body : null; st.previewErr = r.ok ? '' : detail(r); paintPreview();
        });
      }, 150);
    }
    function paintPreview() {
      var el = host.querySelector('#pv'); if (!el) return;
      var h = '';
      if (st.preview && st.preview.ruling) {
        var R = st.preview.ruling;
        h += '<div class="total"><span class="k">After you submit</span><span class="small muted">' + esc(R.ruling) + (R.flag_account ? ' + account flag' : '') + (st.preview.formula_amount != null && R.amount != null && Math.abs(st.preview.formula_amount - R.amount) > .005 ? ' · formula ' + money(st.preview.formula_amount) : '') + '</span><span class="n">' + (R.amount != null ? money(R.amount) : 'no refund') + '</span></div>';
      }
      if (st.preview && st.preview.notices) h += '<details' + (st.mode === 'evidence' ? ' open' : '') + '><summary>Notice preview for both parties</summary><div class="nprev"><b>Rider:</b> ' + esc(st.preview.notices.rider) + '\n\n<b>Driver:</b> ' + esc(st.preview.notices.driver) + '</div></details>';
      if (st.previewErr) h += '<div class="errline">' + esc(st.previewErr) + '</div>';
      el.innerHTML = h;
    }
    function optionCards(q, chosen, adoptMode) {
      var h = '';
      q.options.forEach(function (o) {
        var dis = adoptMode && !q.adoptable;
        h += '<label class="opt' + (chosen === o.id ? ' on' : '') + '"' + (dis ? ' style="opacity:.55;cursor:not-allowed"' : '') + '><input type="radio" name="' + (adoptMode ? 'a' : 'f') + '-' + q.id + '" data-q="' + q.id + '" value="' + o.id + '"' + (chosen === o.id ? ' checked' : '') + (dis ? ' disabled' : '') + '><div><div class="ol">' + esc(o.label)
          + (o.lean ? '<span class="tag">rule requires</span>' : '') + (o.proposed ? '<span class="tag prop">proposed wording</span>' : '') + (o.flag_account ? '<span class="tag acct">account flag</span>' : '') + '</div><div class="os">' + esc(o.detail) + '</div></div>'
          + '<div class="amt">' + (o.amount != null ? money(o.amount) + '<small>to the rider</small>' : '<small>' + (o.ruling === 'no_action' ? 'no refund' : esc(o.ruling)) + '</small>') + '</div></label>';
      });
      return h;
    }
    function render() {
      var h = '<h3>' + step(4, 'Your decision') + ' <span class="badge pur">' + qs.length + ' question' + (qs.length > 1 ? 's' : '') + '</span></h3>';
      if (P.status === 'awaiting_evidence' && P.pending_request) { var R = P.pending_request; h += '<div class="done wait">Awaiting evidence from <b>' + esc(R.request.to) + '</b> until ' + esc(String(R.due_at).slice(0, 16).replace('T', ' ')) + ' UTC: ' + esc(R.request.items.join('; ')) + '. You can still decide now.</div>'; }
      if (P.status === 'decided' && P.decision) h += '<div class="done">Decided by ' + esc(P.decision.reviewer) + ' (' + esc(P.decision.outcome) + '): <b>' + esc(P.decision.ruling.ruling) + ' ' + (P.decision.ruling.amount != null ? money(P.decision.ruling.amount) : '') + '</b>. A new decision is recorded on top; the history is kept.</div>';
      h += '<div class="modes">'
        + '<button type="button" data-mode="adopt" aria-pressed="' + (st.mode === 'adopt') + '"' + (anyAdopt ? '' : ' disabled title="The record cannot support any of the options; write your own judgment or ask for evidence"') + '>① Adopt an option<small>' + (anyAdopt ? 'pick one; code prices it' : 'no option the record supports') + '</small></button>'
        + '<button type="button" data-mode="own" aria-pressed="' + (st.mode === 'own') + '">② My own judgment<small>finding + reason</small></button>'
        + '<button type="button" data-mode="evidence" aria-pressed="' + (st.mode === 'evidence') + '">③ Request evidence<small>keep the case open</small></button></div>';
      if (st.mode === 'adopt' || st.mode === 'own') {
        qs.forEach(function (q) {
          if (qs.length > 1 || st.mode === 'own') h += '<div class="qsub">' + (q.kind === 'decision' ? '' : esc(q.id) + ' · ') + esc(KIND[q.kind] || q.kind) + (st.mode === 'own' ? ' · your finding' : '') + '</div>';
          h += optionCards(q, picks()[q.id], st.mode === 'adopt');
          if (q.vocabulary === 'proposed') h += '<div class="small muted">The policy has no outcome vocabulary for a safety finding; these four are a proposal, recorded as safety_concern / flag_account.</div>';
        });
        if (st.mode === 'adopt' && qs.some(function (q) { return q.kind === 'segment_scope'; })) h += '<div class="small muted" style="margin-top:4px">Amounts are computed by code: counted off-route km × the trip\'s per-km rate (RD-2), the same rule as the policy check.</div>';
        if (st.mode === 'adopt' && qs.some(function (q) { return q.kind === 'decision'; })) h += '<div class="small muted" style="margin-top:4px">Amounts are computed by code with the same formula as the policy check. The record is complete: the system stopped only because this outcome needs a person to approve it.</div>';
      }
      if (st.mode === 'own') {
        h += '<label class="f" for="rsn">Reason (required, at least 15 characters)</label><textarea id="rsn" data-k="reason" placeholder="What you saw and why you decided this way: it is kept with the precedent">' + esc(st.reason) + '</textarea>';
        h += '<label class="f">Facts you rely on (at least one; ids are checked)</label><div class="cite">' + Object.keys(P.facts).map(function (f) { return '<button type="button" data-cite="' + f + '" aria-pressed="' + (st.cites.indexOf(f) >= 0) + '" title="' + esc(P.facts[f].text) + '">' + f + '</button>'; }).join('') + '</div>';
        h += '<label class="check"><input type="checkbox" data-k="manual"' + (st.manual ? ' checked' : '') + '>Use a different amount from the formula</label>';
        if (st.manual) {
          h += '<label class="f" for="amt">Amount (SGD)</label><input id="amt" type="number" step="0.01" min="0" data-k="amount" value="' + esc(st.amount) + '">';
          h += '<label class="check warn"><input type="checkbox" data-k="confirmAmt"' + (st.confirmAmt ? ' checked' : '') + '>Second confirmation: this amount differs from what the formula gives, and I mean it</label>';
        }
      }
      if (st.mode === 'evidence') {
        h += '<div class="row2"><div><label class="f" for="ask">Ask</label><select id="ask" data-k="ask">' + ['rider', 'driver', 'platform'].map(function (x) { return '<option value="' + x + '"' + (st.ask === x ? ' selected' : '') + '>' + x + '</option>'; }).join('') + '</select></div>'
          + '<div><label class="f" for="due">Due within</label><select id="due" data-k="due">' + [24, 48, 72].map(function (x) { return '<option value="' + x + '"' + (+st.due === x ? ' selected' : '') + '>' + x + ' hours</option>'; }).join('') + '</select></div></div>';
        if (qs[0].kind === 'decision' && qs[0].adoptable && !P.evidence_gap) h += '<div class="small muted" style="margin-top:6px">No evidence is needed here: the record is complete and the stop is only the approval limit. You can approve or reject the outcome above instead.</div>';
        h += '<div class="reqs" style="margin-top:6px">' + sug.map(function (s, i) { return s.to === st.ask ? '<label><input type="checkbox" data-req="' + i + '"' + (st.picked[i] ? ' checked' : '') + '><span><span class="to">' + s.to + '</span>' + esc(s.item) + '</span></label>' : ''; }).join('') + '</div>';
        h += '<label class="f" for="ext">Anything else (optional)</label><input id="ext" type="text" data-k="extra" value="' + esc(st.extra) + '" placeholder="what exactly you need">';
        h += '<label class="f" for="tmo">If nothing arrives in time</label><select id="tmo" data-k="onTimeout"><option value="decide_on_record"' + (st.onTimeout === 'decide_on_record' ? ' selected' : '') + '>Back to my queue; decide on the record</option><option value="close_no_action"' + (st.onTimeout === 'close_no_action' ? ' selected' : '') + '>Close with no change</option></select>';
        h += '<div class="small muted" style="margin-top:6px">The case is not closed: its status becomes <b>awaiting_evidence</b> and the queue item stays open with the new due time.</div>';
      }
      if (st.mode) {
        h += '<div id="pv"></div>';
        if (needsAcct()) h += '<label class="check warn"><input type="checkbox" data-k="confirmAcct"' + (st.confirmAcct ? ' checked' : '') + '>Second confirmation: this refers the account for review</label>';
        h += '<label class="check"><input type="checkbox" data-k="checked"' + (st.checked ? ' checked' : '') + '>I checked ' + esc(subj) + ' and the quoted messages</label>';
        var err = validate();
        h += '<div class="submit"><button type="button" class="btn primary" data-k="submit"' + (err || st.busy ? ' disabled' : '') + '>' + (st.mode === 'evidence' ? 'Send the request' : 'Submit decision') + '</button>' + (err ? '<span class="errline">' + esc(err) + '</span>' : '') + (st.error ? '<span class="errline">' + esc(st.error) + '</span>' : '') + '</div>';
      }
      if (st.result) h += '<div class="done' + (st.result.status === 'awaiting_evidence' ? ' wait' : '') + '"><b>' + (st.result.status === 'awaiting_evidence' ? 'Request sent; the case stays open (awaiting_evidence).' : 'Decision recorded.') + '</b> Stored record:</div><pre class="code">' + esc(JSON.stringify(st.result, null, 2)) + '</pre>';
      host.innerHTML = h;
      wire(); paintPreview();
    }
    function updateSubmit() {
      var b = host.querySelector('[data-k=submit]'); if (!b) return;
      var err = validate(), line = host.querySelector('.submit .errline');
      b.disabled = !!err || st.busy;
      if (line) line.textContent = err || st.error; else if (err) b.insertAdjacentHTML('afterend', '<span class="errline">' + esc(err) + '</span>');
    }
    function submit() {
      st.busy = true; st.error = ''; render();
      var go = function (tok) {
        var hd = {'Content-Type': 'application/json'}; if (tok) hd['X-Demo-Token'] = tok;
        return api('/api/human-review/' + encodeURIComponent(P.case_id), {method: 'POST', headers: hd, body: JSON.stringify(body())});
      };
      var tok = null; try { tok = sessionStorage.getItem(TOKEN_KEY); } catch (e) {}
      go(tok).then(function (r) {
        if (r.status === 401) { var t2 = prompt('This demo needs the reviewer token (X-Demo-Token):'); if (t2) { try { sessionStorage.setItem(TOKEN_KEY, t2); } catch (e) {} return go(t2); } }
        return r;
      }).then(function (r) {
        st.busy = false;
        if (r.ok) { st.result = r.body; P.status = r.body.status; } else st.error = detail(r);
        render();
      });
    }
    function wire() {
      host.querySelectorAll('[data-mode]').forEach(function (b) { b.onclick = function () { if (b.disabled) return; st.mode = b.getAttribute('data-mode'); st.checked = false; st.confirmAcct = false; st.result = null; st.error = ''; sync(); render(); refreshPreview(); }; });
      host.querySelectorAll('input[type=radio][data-q]').forEach(function (r) { r.onchange = function () { picks()[r.getAttribute('data-q')] = r.value; st.confirmAcct = false; sync(); render(); refreshPreview(); }; });
      host.querySelectorAll('[data-cite]').forEach(function (b) { b.onclick = function () { var f = b.getAttribute('data-cite'), i = st.cites.indexOf(f); if (i >= 0) st.cites.splice(i, 1); else st.cites.push(f); render(); }; });
      host.querySelectorAll('[data-req]').forEach(function (c) { c.onchange = function () { st.picked[+c.getAttribute('data-req')] = c.checked; render(); refreshPreview(); }; });
      host.querySelectorAll('[data-k]').forEach(function (el) {
        var k = el.getAttribute('data-k');
        if (k === 'submit') { el.onclick = submit; return; }
        if (el.type === 'checkbox') { el.onchange = function () { st[k] = el.checked; if (k === 'manual' && !el.checked) { st.amount = ''; st.confirmAmt = false; } render(); if (k === 'manual') refreshPreview(); }; return; }
        var commit = function () { st[k] = el.value; if (k === 'amount') st.confirmAmt = false; updateSubmit(); };
        if (el.tagName === 'SELECT') el.onchange = function () { commit(); if (k === 'ask') st.picked = {}; render(); refreshPreview(); };
        else { el.oninput = commit; el.onchange = function () { commit(); render(); refreshPreview(); }; }
      });
    }
    render();
  }

  /* ------------------------------------------------------------------ the case */
  function renderNotReviewable(r) {
    var auto = /cleared automatically/.test(detail(r));
    app.innerHTML = '<div class="notice"><h1>' + (auto ? 'This case was cleared automatically; no human review' : (r.status === 404 ? 'No stored run for ' + esc(CID) : 'Not on the human-review queue')) + '</h1>'
      + '<p>' + (auto ? 'The court\'s ruling passed the policy check and was cleared without a person, so nothing on this case waits for a reviewer. An account flag on a cleared case goes to Ryde\'s account review, not to this page.' : esc(detail(r))) + '</p><div class="links">'
      + (r.status !== 404 ? '<a class="btn sm" href="/replay.html?case=' + encodeURIComponent(CID) + '">Trip replay ↗</a><a class="btn sm" href="/receipt.html?run=' + encodeURIComponent(CID) + '">Receipt ↗</a>' : '')
      + '<a class="btn sm" href="/human-review.html">Human review queue</a></div></div>';
  }

  function renderCase() {
    Promise.all([api('/api/human-review/' + encodeURIComponent(CID)), api('/api/cases/' + encodeURIComponent(CID)), api('/api/cases/' + encodeURIComponent(CID) + '/facts'), api('/api/cases')]).then(function (rs) {
      var r = rs[0];
      if (!r.ok) { renderNotReviewable(r); return; }
      if (!rs[1].ok || !rs[2].ok) { app.innerHTML = '<div class="notice"><p>Could not load the case: ' + esc(detail(rs[1].ok ? rs[2] : rs[1])) + '</p></div>'; return; }
      var P = r.body, C = rs[1].body, F = rs[2].body, list = rs[3].ok ? rs[3].body : [];
      var title = ((list.filter(function (c) { return c.case_id === CID; })[0] || {}).title) || TYPE[P.dispute_type];
      document.title = CID + ' · Human review · Akina Court';
      var G = geo(C, F), base = {};
      P.settled.forEach(function (s) { if (/^F\d+$/.test(s.subject)) base[s.subject] = s.finding; });
      var q0 = P.questions[0], others = P.settled.filter(function (s) { return /^F\d+$/.test(s.subject); }).length;
      var qhead = 'You need to decide ' + P.questions.length + ' question' + (P.questions.length > 1 ? 's' : '') + (others ? ' · ' + others + ' segment' + (others > 1 ? 's' : '') + ' settled' : '') + (P.settled_amount ? ' (' + money(P.settled_amount) + ')' : '');
      var filed = new Date(P.filed_at).toLocaleString('en-GB', {timeZone: 'Asia/Singapore', day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit'});
      var sla = slaText(P.due_at);
      var h = '<div class="chead"><span class="ttl">' + esc(title) + '</span><span class="cid">' + esc(CID) + ' · ' + esc(TYPE[P.dispute_type] || P.dispute_type) + ' · ' + esc(P.service_type || '') + '</span>'
        + '<span class="badge ' + (P.queue === 'urgent_safety' ? 'red' : 'hr') + '">' + esc(QUEUE[P.queue] || P.queue) + '</span>' + (sla ? '<span class="sla ' + (/overdue/.test(sla) ? 'c-red' : 'c-amber') + '">' + esc(sla) + '</span>' : '')
        + (P.safety_concern === 'suspected' || P.safety_concern === 'confirmed' ? '<span class="badge red">Safety concern · ' + esc(P.safety_concern) + '</span>' : '')
        + (P.status !== 'open' ? '<span class="badge ' + (P.status === 'decided' ? 'ok' : 'hr') + '">' + esc(P.status.replace('_', ' ')) + '</span>' : '') + '</div>';
      h += '<div class="quote">“' + esc(P.statement) + '”<span class="who">' + (P.filed_by === 'rider' ? 'Rider' : 'Driver') + '\'s original complaint · filed ' + esc(filed) + ' · ' + esc(P.trip_summary) + '</span></div>';
      h += '<div class="qcard"><div class="qh">' + esc(qhead) + '</div>' + P.questions.map(function (q) { return '<div class="qt">' + esc(q.title) + '</div>'; }).join('') + '</div>';
      h += '<div class="grid2"><div class="left"><div class="map" id="map"></div>' + settledBox(P) + sidesBox(P, P.facts) + '</div><div class="right">';
      var why = P.questions.map(function (q) { return q.escalation_reasons.map(function (w, i) { return '<p' + (i ? ' class="small"' : '') + '>' + esc(w) + '</p>'; }).join(''); }).join('');
      if (P.evidence_gap) why += '<div class="gapnote"><b>Evidence ' + esc(P.evidence_gap.status) + ':</b> ' + esc(P.evidence_gap.gap) + (q0.adoptable ? '' : ' The options below cannot be adopted as they stand: write your own judgment, or ask for the missing record.') + '</div>';
      h += '<div class="box"><div class="k">' + step(1, 'Reason for escalation') + '</div><div class="why">' + why + '</div></div>';
      h += '<div class="box"><div class="k">' + step(2, 'Evidence on this question') + '<span class="r muted">' + P.questions.reduce(function (n, q) { return n + q.evidence.length; }, 0) + ' items · verbatim</span></div>'
        + P.questions.map(function (q) { return evidenceList(q.evidence, P.facts); }).join('') + '</div>';
      h += linksBox(P) + '<div class="dp" id="dp"></div></div></div>';
      app.innerHTML = h;
      var basis = [];
      P.questions.forEach(function (q) { q.evidence.forEach(function (e) { if (e.quote) basis.push(e.fact_id); }); });
      var m = mountMap(document.getElementById('map'), G, {focus: q0.focus, basis: basis, base: base});
      decisionPanel(document.getElementById('dp'), P, m);
    });
  }

  if (CID) renderCase(); else renderQueue();
})();
