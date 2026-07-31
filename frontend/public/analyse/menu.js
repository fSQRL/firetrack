// Burger de navigation partagé par les pages d'analyses (statique, zéro dépendance)
// + suivi Matomo (le même que la carte, site id 4)
(function () {
  var _paq = window._paq = window._paq || [];
  _paq.push(['trackPageView']);
  _paq.push(['enableLinkTracking']);
  (function () {
    var u = '//www.matomo.harari.ovh/';
    _paq.push(['setTrackerUrl', u + 'matomo.php']);
    _paq.push(['setSiteId', '4']);
    var d = document, g = d.createElement('script'), s = d.getElementsByTagName('script')[0];
    g.async = true; g.src = u + 'matomo.js'; s.parentNode.insertBefore(g, s);
  })();
  const style = document.createElement('style');
  style.textContent = `
    .ft-burger { position: fixed; top: 12px; left: 12px; z-index: 50;
      border: 1px solid #39414d; background: rgba(20,24,31,.92); color: #e8ecf2;
      border-radius: 8px; padding: 7px 12px; font-size: 16px; cursor: pointer;
      font-family: system-ui, sans-serif; }
    .ft-overlay { position: fixed; inset: 0; z-index: 49; background: rgba(0,0,0,.45); display: none; }
    .ft-nav { position: fixed; top: 0; left: 0; bottom: 0; z-index: 51; width: min(300px, 85vw);
      background: #1a1f27; border-right: 1px solid #2a313c; padding: 16px;
      font-family: system-ui, sans-serif; display: none; overflow-y: auto; }
    .ft-nav h3 { margin: 4px 0 12px; font-size: 15px; color: #e8ecf2; font-family: Georgia, serif; }
    .ft-nav a { display: block; padding: 10px 12px; margin-bottom: 6px; border-radius: 8px;
      color: #cdd5de; text-decoration: none; font-size: 14px; border: 1px solid transparent; }
    .ft-nav a:hover { background: #2a313c; }
    .ft-nav a.cur { border-color: #ff7a30; color: #fff; }
    .ft-nav .sep { margin: 10px 0 6px; font-size: 10.5px; letter-spacing: 1.5px;
      text-transform: uppercase; color: #6b7683; }
    body { padding-top: 34px; }
    .pubdate { font-family: system-ui, sans-serif; font-size: 12.5px; color: #93a0ae; margin: 2px 0 0; }
    .changelog { margin-top: 44px; border-top: 1px solid #2a313c; padding-top: 12px;
      font-family: system-ui, sans-serif; font-size: 12.5px; color: #93a0ae; }
    .changelog b { color: #cdd5de; font-weight: 600; }
    .changelog ul { margin: 6px 0 0; padding-left: 18px; }
  `;
  document.head.appendChild(style);

  const LINKS = [
    ['/', 'La carte interactive'],
    ['sep', 'Analyses'],
    ['/analyse/', 'Toutes les analyses'],
    ['/analyse/zones/', 'Des zones privilégiées ?'],
    ['/analyse/norias/', 'Le rendement des norias'],
    ['/analyse/a400m/', 'A400M et Canadair'],
    ['/analyse/front/', 'Les largages et le front'],
    ['/analyse/vent/', 'Le feu et le vent'],
    ['/analyse/renforts/', 'La montée en puissance des renforts'],
    ['/analyse/air/', "La fumée et l'air qu'on a respiré"],
  ];
  const here = location.pathname.replace(/index\.html$/, '');
  const nav = document.createElement('nav');
  nav.className = 'ft-nav';
  nav.innerHTML = '<h3>Fire Tracker</h3>' + LINKS.map(([href, label]) =>
    href === 'sep' ? `<div class="sep">${label}</div>`
      : `<a href="${href}" class="${here === href ? 'cur' : ''}">${label}</a>`
  ).join('');
  const overlay = document.createElement('div');
  overlay.className = 'ft-overlay';
  const btn = document.createElement('button');
  btn.className = 'ft-burger';
  btn.textContent = '☰';
  btn.setAttribute('aria-label', 'Menu');
  const toggle = (show) => {
    nav.style.display = show ? 'block' : 'none';
    overlay.style.display = show ? 'block' : 'none';
  };
  btn.addEventListener('click', () => toggle(nav.style.display !== 'block'));
  overlay.addEventListener('click', () => toggle(false));
  document.body.append(btn, overlay, nav);

  // dans les articles, les liens s'ouvrent dans un nouvel onglet
  // (sauf la navigation interne entre analyses : hrefs relatifs "../")
  document.querySelectorAll('main a').forEach((a) => {
    const h = a.getAttribute('href') || '';
    if (!h.startsWith('../') && !h.startsWith('#')) {
      a.target = '_blank';
      a.rel = 'noopener';
    }
  });
})();
