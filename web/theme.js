/* Akina Court · theme switch. Loaded synchronously in <head> so the page never flashes the wrong theme.
   One saved preference: localStorage "style" = "mono" (light) or anything else (dark). ?style=mono|dark overrides for one load. */
(function () {
  var q = new URLSearchParams(location.search), st = q.get('style');
  try { if (st === null) st = localStorage.getItem('style') || ''; } catch (e) { st = st || ''; }
  if (st !== 'mono') st = '';
  if (st) document.documentElement.dataset.style = st;
  var light = st === 'mono' || q.get('theme') === 'light';
  window.AKINA_THEME = {
    style: st,
    light: light,
    toggle: function () {
      try { localStorage.setItem('style', light ? 'dark' : 'mono'); } catch (e) {}
      var u = new URL(location.href); u.searchParams.delete('style'); u.searchParams.delete('theme'); location.href = u.toString();
    },
    /* wire a button: label shows the theme you would switch to */
    bind: function (el, labels) {
      if (!el) return; labels = labels || ['Light', 'Dark'];
      el.textContent = light ? labels[1] : labels[0]; el.onclick = window.AKINA_THEME.toggle;
    }
  };
  document.addEventListener('DOMContentLoaded', function () {
    /* the shared site header: wire its theme button, mark the current page */
    window.AKINA_THEME.bind(document.querySelector('header.site button.theme'));
    document.querySelectorAll('header.site nav a').forEach(function (a) {
      if (a.pathname === location.pathname && !a.hash) a.setAttribute('aria-current', 'page');
    });
    /* embedded map replays carry the theme through their query string */
    if (light) document.querySelectorAll('iframe[src*="replay.html"]').forEach(function (f) { if (f.src.indexOf('theme=') < 0) f.src += (f.src.indexOf('?') < 0 ? '?' : '&') + 'theme=light'; });
  });
})();
