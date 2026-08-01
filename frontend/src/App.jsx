import { useCallback, useEffect, useRef, useState } from 'react';
import MapView from './MapView.jsx';
import Timeline from './Timeline.jsx';
import { indexAt, positionAt, timeRange, nearestActivityTs, countActionPasses } from './interp.js';

// Départ par défaut de la timeline : 23/07 15h17 heure de Paris (13h17 UTC)
const START_T = Date.UTC(2026, 6, 23, 13, 17, 0) / 1000;

// Altitude du soleil (°) au-dessus de l'horizon — approximation astronomique standard
function sunAltitude(tSec, lat = 44.84, lon = -0.58) { // Bordeaux
  const rad = Math.PI / 180;
  const days = (tSec - 946728000) / 86400; // jours depuis J2000
  const g = ((357.529 + 0.98560028 * days) % 360) * rad;
  const q = (280.459 + 0.98564736 * days) % 360;
  const L = (q + 1.915 * Math.sin(g) + 0.02 * Math.sin(2 * g)) * rad;
  const e = 23.439 * rad;
  const RA = Math.atan2(Math.cos(e) * Math.sin(L), Math.cos(L));
  const dec = Math.asin(Math.sin(e) * Math.sin(L));
  const gmst = (18.697374558 + 24.06570982441908 * days) % 24;
  const H = ((gmst + lon / 15) * 15) * rad - RA;
  return Math.asin(
    Math.sin(lat * rad) * Math.sin(dec) + Math.cos(lat * rad) * Math.cos(dec) * Math.cos(H)
  ) / rad;
}

// 0 en plein jour -> 0.45 en pleine nuit, transition sur le crépuscule civil
function nightOpacity(tSec) {
  const alt = sunAltitude(tSec);
  if (alt >= 2) return 0;
  if (alt <= -8) return 0.45;
  return 0.45 * (2 - alt) / 10;
}

const COLORS = [
  '#ff5d47', '#ffb020', '#3ecf5b', '#28c8d8', '#4f8dff', '#b06dff',
  '#ff6ac2', '#c9d425', '#ff8b38', '#00b894', '#8fa8ff', '#e35d6a',
];

export default function App() {
  const [days, setDays] = useState([]);
  const [aircraft, setAircraft] = useState([]);
  const [fires, setFires] = useState([]);
  const [wind, setWind] = useState([]);
  const [air, setAir] = useState([]);
  const [satellite, setSatellite] = useState(false);
  const [airQ, setAirQ] = useState(false);
  const [followHex, setFollowHex] = useState(null);
  const [range, setRange] = useState(null);
  const [dataEnd, setDataEnd] = useState(null); // fin des données réelles (au-delà : prévision)
  const [t, setT] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(300);
  const [selectedHex, setSelectedHex] = useState(null);
  const [error, setError] = useState(null);
  const [menuOpen, setMenuOpen] = useState(false);
  const [shareOpen, setShareOpen] = useState(false);
  const [copied, setCopied] = useState(null); // 'site' | 'moment'
  const [loading, setLoading] = useState({ done: 0, total: 1 }); // barre de chargement initial

  // Liste des jours disponibles
  useEffect(() => {
    fetch('/data/index.json')
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))))
      .then(({ days }) => {
        setDays(days);
        if (!days.length) setError('Aucune donnée : lancer le pipeline (ingest + export).');
      })
      .catch(() => { setError('Aucune donnée : lancer le pipeline (ingest + export).'); setLoading(null); });
  }, []);

  // Chargement de tous les jours disponibles, fusionnés en une timeline continue
  useEffect(() => {
    const wanted = days.filter((d) => /^\d{4}-/.test(d));
    if (!wanted.length) { setLoading(null); return; }
    setPlaying(false);
    setLoading({ done: 0, total: wanted.length });
    Promise.all(wanted.map((d) =>
      fetch(`/data/${d}.json`)
        .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))))
        .then((json) => {
          setLoading((l) => (l ? { ...l, done: l.done + 1 } : l));
          return json;
        })
    ))
      .then((loaded) => {
        // fusion par appareil (les jours sont chargés dans l'ordre chronologique)
        const byHex = new Map();
        const allFires = [], allWind = [], allAir = [];
        for (const data of loaded) {
          for (const a of data.aircraft) {
            const cur = byHex.get(a.hex);
            if (cur) cur.points = cur.points.concat(a.points);
            else byHex.set(a.hex, { ...a });
          }
          allFires.push(...(data.fires ?? []));
          allWind.push(...(data.wind ?? []));
          allAir.push(...(data.air ?? []));
        }
        const data = {
          aircraft: [...byHex.values()],
          fires: allFires.sort((a, b) => a[0] - b[0]),
          wind: allWind.sort((a, b) => a[0] - b[0]),
          air: allAir.sort((a, b) => a[0] - b[0]),
        };
        const list = data.aircraft.map((a, i) => ({ ...a, color: COLORS[i % COLORS.length] }));
        setAircraft(list);
        const fs = data.fires ?? [];
        setFires(fs);
        setWind(data.wind ?? []);
        // dédoublonnage air (les fichiers jour se recouvrent de 24 h pour la prévision)
        const seenAir = new Set();
        setAir((data.air ?? []).filter((r) => {
          const k = `${r[0]}|${r[1]}|${r[2]}`;
          if (seenAir.has(k)) return false;
          seenAir.add(k);
          return true;
        }));
        // plage : vols + détections de feu (le feu peut précéder le premier décollage)
        let r = timeRange(list);
        if (fs.length) {
          const fmin = fs[0][0], fmax = fs[fs.length - 1][0];
          r = r ? [Math.min(r[0], fmin), Math.max(r[1], fmax)] : [fmin, fmax];
        }
        // mode Prévision : +24 h au-delà des données réelles, uniquement si le site est "à jour"
        // (pas de prévision sur une archive consultée bien plus tard)
        if (r) {
          setDataEnd(r[1]);
          const live = Date.now() / 1000 - r[1] < 36 * 3600;
          if (live) r = [r[0], r[1] + 24 * 3600];
        } else {
          setDataEnd(null);
        }
        setRange(r);
        if (r) {
          const first = firstLoadRef.current;
          firstLoadRef.current = false;
          // lien profond ?t=<epoch secondes> prioritaire (sans lecture auto),
          // sinon départ par défaut au START_T avec lecture automatique
          const urlT = Number(new URLSearchParams(window.location.search).get('t'));
          if (first && urlT >= r[0] && urlT <= r[1]) {
            setT(urlT);
          } else {
            setT(first && START_T >= r[0] && START_T < r[1] ? START_T : r[0]);
            if (first) autoplayRef.current = true; // lecture au moment de fermer le disclaimer
          }
        } else {
          setT(0);
        }
        setError(r ? null : 'Aucun vol enregistré.');
        // chargement fini : le disclaimer reste affiché jusqu'à fermeture par l'utilisateur
        setLoading((l) => (l ? { ...l, ready: true } : l));
      })
      .catch((e) => { setError(`Erreur de chargement : ${e.message}`); setLoading(null); });
  }, [days]);

  const firstLoadRef = useRef(true);
  const autoplayRef = useRef(false);

  // Horloge de lecture
  const tRef = useRef(t);
  tRef.current = t;
  useEffect(() => {
    if (!playing || !range) return;
    let raf, last = performance.now();
    const tick = (now) => {
      // borne le pas de temps : une frame lente (ou un retour d'onglet) ne doit
      // pas faire bondir la timeline
      const dt = Math.min((now - last) / 1000, 0.1);
      const next = tRef.current + dt * speed;
      last = now;
      if (next >= range[1]) {
        setT(range[1]);
        setPlaying(false);
        return;
      }
      setT(next);
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [playing, speed, range]);

  const onSelect = useCallback((hex) => {
    setFollowHex(null); // tout changement de sélection met fin au suivi
    setSelectedHex((cur) => (cur === hex ? null : hex));
  }, []);

  // partage : le site, ou le moment précis de la timeline (lien profond ?t=)
  const doShare = useCallback((kind) => {
    const url = kind === 'moment'
      ? `${window.location.origin}/?t=${Math.round(t)}`
      : `${window.location.origin}/`;
    if (navigator.share) {
      navigator.share({ title: 'Fire Tracker', url }).catch(() => {});
      setShareOpen(false);
    } else {
      navigator.clipboard.writeText(url).then(() => {
        setCopied(kind);
        setTimeout(() => setCopied(null), 2000);
      });
    }
  }, [t]);

  // saut temporel au double-clic sur la carte (borné à la plage de données)
  const [jumpFlash, setJumpFlash] = useState(null); // {side, label}
  const rangeRef = useRef(range);
  rangeRef.current = range;
  const jumpTimerRef = useRef(null);
  const onJump = useCallback((delta) => {
    const r = rangeRef.current;
    if (!r) return;
    setT((cur) => Math.min(r[1], Math.max(r[0], cur + delta)));
    setJumpFlash({ side: delta < 0 ? 'left' : 'right', label: delta < 0 ? '−10 min' : '+10 min' });
    clearTimeout(jumpTimerRef.current);
    jumpTimerRef.current = setTimeout(() => setJumpFlash(null), 700);
  }, []);

  // Disponibilité de l'image satellite NASA pour le jour affiché : une seule tuile
  // sonde par jour (mise en cache), l'imagerie du jour même arrive souvent en cours d'après-midi
  const satDayStr = range ? new Date(t * 1000).toISOString().slice(0, 10) : null;
  const [satAvailable, setSatAvailable] = useState(null);
  const satCacheRef = useRef({});
  useEffect(() => {
    if (!satDayStr) return;
    const cached = satCacheRef.current[satDayStr];
    if (cached !== undefined) { setSatAvailable(cached); return; }
    let stale = false;
    fetch(`https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/VIIRS_SNPP_CorrectedReflectance_TrueColor/default/${satDayStr}/GoogleMapsCompatible_Level9/6/23/31.jpg`)
      .then((r) => {
        satCacheRef.current[satDayStr] = r.ok;
        if (!stale) setSatAvailable(r.ok);
      })
      .catch(() => { if (!stale) setSatAvailable(null); });
    return () => { stale = true; };
  }, [satDayStr]);

  // dernière détection satellite de feu à l'instant t (les feux sont triés par ts)
  const lastFireIdx = fires.length ? indexAt(fires, t) : -1;
  const lastFireTs = lastFireIdx >= 0 ? fires[lastFireIdx][0] : null;

  const selected = aircraft.find((a) => a.hex === selectedHex);
  const selectedPos = selected ? positionAt(selected.points, t) : null;

  // passages en action (écopages/largages estimés) : total de la journée affichée
  const dayStart = Math.floor(t / 86400) * 86400;
  const passes = selected ? countActionPasses(selected.points, dayStart, dayStart + 86400) : 0;

  // suivre l'avion : si absent à l'instant t, on saute d'abord à sa prochaine activité
  const onFollow = useCallback(() => {
    if (!selected) return;
    if (followHex === selected.hex) { setFollowHex(null); return; }
    if (!positionAt(selected.points, t)) {
      const ts = nearestActivityTs(selected.points, t);
      if (ts == null) return;
      setT(ts);
    }
    setFollowHex(selected.hex);
  }, [selected, followHex, t]);

  // Légende : les avions en vol à l'instant t passent en tête
  const legendList = aircraft
    .map((a) => ({ ...a, active: positionAt(a.points, t) != null }))
    .sort((a, b) => (b.active - a.active) || a.name.localeCompare(b.name));

  // Scroll de la légende à la molette et au doigt/souris (drag)
  const dragRef = useRef(null);
  const legendHandlers = {
    onWheel: (e) => { e.currentTarget.scrollLeft += e.deltaY + e.deltaX; },
    onPointerDown: (e) => {
      dragRef.current = { x: e.clientX, sl: e.currentTarget.scrollLeft, moved: false };
    },
    onPointerMove: (e) => {
      const d = dragRef.current;
      if (!d) return;
      const dx = e.clientX - d.x;
      if (Math.abs(dx) > 5) d.moved = true;
      if (d.moved) e.currentTarget.scrollLeft = d.sl - dx;
    },
    onPointerUp: () => { setTimeout(() => { dragRef.current = null; }, 0); },
    onPointerLeave: () => { dragRef.current = null; },
  };

  return (
    <div className="app">
      <MapView
        aircraft={aircraft} fires={fires} wind={wind} air={airQ ? air : null} t={t} speed={speed}
        dataEnd={dataEnd}
        selectedHex={selectedHex} onSelect={onSelect}
        satelliteDay={satellite && satAvailable ? satDayStr : null}
        onJump={onJump}
        followHex={followHex} onFollowEnd={() => setFollowHex(null)}
      />
      {jumpFlash && (
        <div className={`jump-flash ${jumpFlash.side}`}>
          {jumpFlash.side === 'left' ? '⏪' : '⏩'} {jumpFlash.label}
        </div>
      )}
      <div className="night" style={{ opacity: range ? nightOpacity(t) : 0 }} />

      {dataEnd && t > dataEnd && <div className="forecast-veil" />}

      {range && (
        <div className="bigclock">
          {new Date(t * 1000).toLocaleDateString('fr-FR', {
            weekday: 'short', day: 'numeric', month: 'short', timeZone: 'Europe/Paris',
          })}
          <span className="bigclock-time">
            {new Date(t * 1000).toLocaleTimeString('fr-FR', {
              hour: '2-digit', minute: '2-digit', second: '2-digit', timeZone: 'Europe/Paris',
            })}
          </span>
          {dataEnd && t > dataEnd && (
            <span className="forecast-badge">
              PRÉVISION +{Math.max(1, Math.round((t - dataEnd) / 3600))} h ·
              fiabilité {t - dataEnd < 6 * 3600 ? 'bonne' : 'moyenne'}
            </span>
          )}
        </div>
      )}

      <header className="topbar">
        <button className="burger" onClick={() => setMenuOpen(true)} aria-label="Menu">☰</button>
        {selected && (
          <div className="detail">
            {selected.photo && (
              <a href={selected.photo.link} target="_blank" rel="noreferrer" className="detail-photo">
                <img src={selected.photo.src} alt={selected.registration} />
                <span className="photo-credit">© {selected.photo.credit} · planespotters.net</span>
              </a>
            )}
            <div className="detail-text">
              <b>{selected.name}</b> · {selected.registration}
              {selected.type && selected.type !== '?' && ` · ${selected.type}`}
              <br />
              {selectedPos && !selectedPos.ground && selectedPos.alt != null && `${selectedPos.alt} ft`}
              {selectedPos?.gs != null && ` · ${Math.round(selectedPos.gs * 1.852)} km/h`}
              {selectedPos?.ground && 'au sol'}
              {!selectedPos && 'hors couverture'}
              <br />
              <span className="detail-passes">
                Largages / écopages estimés ce jour : <b>{passes}</b>
              </span>
            </div>
            <button className="detail-follow" onClick={onFollow}>
              {followHex === selected.hex
                ? '◉ Ne plus suivre'
                : selectedPos ? '🎯 Suivre cet avion' : '🎯 Aller à son prochain vol'}
            </button>
            <button className="detail-close" onClick={() => setSelectedHex(null)} aria-label="Fermer">✕</button>
          </div>
        )}
      </header>

      {menuOpen && (
        <div className="menu-overlay" onClick={() => setMenuOpen(false)}>
          <nav className="menu" onClick={(e) => e.stopPropagation()}>
            <button className="menu-close" onClick={() => setMenuOpen(false)} aria-label="Fermer">✕</button>
            <h2>Fire Tracker</h2>
            <a className="menu-item" href="/">La carte interactive</a>
            <div className="menu-group">Analyses</div>
            <a className="menu-item" href="/analyse/zones/">Des zones privilégiées ?</a>
            <a className="menu-item" href="/analyse/norias/">Le rendement des norias</a>
            <a className="menu-item" href="/analyse/a400m/">A400M et Canadair</a>
            <a className="menu-item" href="/analyse/front/">Les largages et le front</a>
            <a className="menu-item" href="/analyse/vent/">Le feu et le vent</a>
            <a className="menu-item" href="/analyse/renforts/">La montée en puissance des renforts</a>
            <a className="menu-item" href="/analyse/air/">La fumée et l'air qu'on a respiré</a>
            <a className="menu-item" href="/analyse/">Toutes les analyses</a>

            <details className="menu-sec">
              <summary>Avertissement</summary>
              <p className="menu-text">
                <b>Ceci est une reconstitution, pas un outil d'alerte.</b> Les trajectoires
                sont rejouées avec un décalage et les zones de feu sont approximatives
                (détection satellite, fumée simulée). Si vous êtes concerné par un incendie,
                informez-vous uniquement auprès des sources officielles :
              </p>
              <ul className="menu-text">
                <li><a href="https://www.gironde.gouv.fr" target="_blank" rel="noreferrer">Préfecture de la Gironde</a> (compte X <a href="https://x.com/PrefAquitaine33" target="_blank" rel="noreferrer">@PrefAquitaine33</a>)</li>
                <li><a href="https://www.landes.gouv.fr" target="_blank" rel="noreferrer">Préfecture des Landes</a> (compte X <a href="https://x.com/Prefecture40" target="_blank" rel="noreferrer">@Prefecture40</a>)</li>
                <li>Numéro d'information incendies : <b><a href="tel:0970809040">09 70 80 90 40</a></b></li>
                <li>Les alertes <b>FR-Alert</b> et les consignes de votre mairie</li>
                <li>Urgences : <b>112</b> ou <b>18</b> (personnes sourdes ou malentendantes : 114)</li>
              </ul>
            </details>

            <details className="menu-sec">
              <summary>Données</summary>
              <ul className="menu-text">
                <li>
                  <b>Trajectoires des avions</b> : signaux ADS-B agrégés par{' '}
                  <a href="https://www.adsb.lol" target="_blank" rel="noreferrer">adsb.lol</a>{' '}
                  (données ouvertes, licence ODbL) et{' '}
                  <a href="https://airplanes.live" target="_blank" rel="noreferrer">airplanes.live</a>.
                  La journée en cours est rafraîchie toutes les 30 minutes.
                </li>
                <li>
                  <b>Zones de feu</b> : points chauds satellites VIIRS et MODIS,{' '}
                  <a href="https://firms.modaps.eosdis.nasa.gov" target="_blank" rel="noreferrer">NASA FIRMS</a>
                  {' '}(6 à 8 passages par jour, contours approximatifs).
                </li>
                <li>
                  <b>Qualité de l'air</b> : indice européen{' '}
                  <a href="https://atmosphere.copernicus.eu/" target="_blank" rel="noreferrer">Copernicus CAMS</a>
                  {' '}via l'<a href="https://open-meteo.com/en/docs/air-quality-api" target="_blank" rel="noreferrer">API Open-Meteo</a>.
                </li>
                <li>
                  <b>Fond de carte</b> :{' '}
                  <a href="https://www.openstreetmap.org" target="_blank" rel="noreferrer">OpenStreetMap</a>.
                </li>
                <li>
                  <b>Transparence</b> : le code source de l'application et l'intégralité des
                  données en CSV sont publics sur{' '}
                  <a href="https://github.com/guillaumebdx/firetrack" target="_blank" rel="noreferrer">GitHub</a>.
                </li>
              </ul>
            </details>

            <details className="menu-sec">
              <summary>Crédits</summary>
              <p className="menu-text">
                Guillaume HARARI
                <br />
                Merci à <a href="https://x.com/nox33" target="_blank" rel="noreferrer">NoX</a> pour
                son aide précieuse à l'identification des appareils engagés.
                <br />
                <span className="menu-hint">
                  Vibe codé avec{' '}
                  <a href="https://claude.com/claude-code" target="_blank" rel="noreferrer">Claude Code</a>
                </span>
              </p>
            </details>
          </nav>
        </div>
      )}

      {shareOpen && (
        <div className="share-overlay" onClick={() => setShareOpen(false)}>
          <div className="share-modal" onClick={(e) => e.stopPropagation()}>
            <h2>Partager</h2>
            <button className="share-choice" onClick={() => doShare('site')}>
              <b>{copied === 'site' ? 'Lien copié !' : 'Le site'}</b>
              <span>firetrack.harari.ovh, la carte s'ouvre au début du replay</span>
            </button>
            <button className="share-choice" onClick={() => doShare('moment')}>
              <b>{copied === 'moment' ? 'Lien copié !' : 'Ce moment précis'}</b>
              <span>
                La carte s'ouvrira le{' '}
                {new Date(t * 1000).toLocaleDateString('fr-FR', {
                  weekday: 'long', day: 'numeric', month: 'long', timeZone: 'Europe/Paris',
                })} à{' '}
                {new Date(t * 1000).toLocaleTimeString('fr-FR', {
                  hour: '2-digit', minute: '2-digit', timeZone: 'Europe/Paris',
                })}
              </span>
            </button>
            <button className="share-close" onClick={() => setShareOpen(false)}>Fermer</button>
          </div>
        </div>
      )}

      {error && <div className="banner">{error}</div>}

      {loading && (
        <div className="loader-overlay">
          <div className="loader-card">
            <h2>Fire Tracker</h2>
            <p>
              Cette carte interactive rejoue, heure par heure, les moyens aériens engagés
              contre les feux de Gironde et des Landes. Elle s'appuie exclusivement sur des
              données ouvertes : signaux des transpondeurs des avions, détections thermiques
              des satellites de la NASA et relevés de vent Open-Meteo.
            </p>
            <p>
              Elle est fournie à titre d'information : en cas d'incendie, seules les
              communications officielles (préfectures, FR-Alert) font foi. Les zones de feu
              reposent sur 6 à 8 passages satellite par jour et peuvent être temporairement
              masquées par la couverture nuageuse.
            </p>
            <div className="loader-bar">
              <div style={{ width: `${Math.round((loading.done / loading.total) * 100)}%` }} />
            </div>
            <div className="loader-label">
              {loading.ready
                ? 'Données chargées.'
                : `Chargement des journées... ${loading.done}/${loading.total}`}
            </div>
            {loading.ready && (
              <button
                className="loader-close"
                onClick={() => {
                  setLoading(null);
                  if (autoplayRef.current) { autoplayRef.current = false; setPlaying(true); }
                }}
              >
                Accéder à la carte ✕
              </button>
            )}
          </div>
        </div>
      )}

      <footer className="bottombar">
        <div className="legend" {...legendHandlers}>
          {legendList.map((a) => (
            <button
              key={a.hex}
              className={`chip ${selectedHex === a.hex ? 'sel' : ''} ${a.active ? '' : 'off'}`}
              onClick={() => { if (!dragRef.current?.moved) onSelect(a.hex); }}
            >
              <span className="dot" style={{ background: a.color }} />
              {a.name.replace('Pélican', 'P.')}
            </button>
          ))}
        </div>
        <Timeline
          range={range} t={t} onScrub={setT}
          playing={playing} onTogglePlay={() => setPlaying((p) => !p)}
          speed={speed} onSpeed={setSpeed}
          satellite={satellite} onSatellite={setSatellite} satAvailable={satAvailable}
          airQ={airQ} onAirQ={setAirQ}
          lastFireTs={lastFireTs} dataEnd={dataEnd}
          onShare={() => { setPlaying(false); setShareOpen(true); }}
        />
      </footer>
    </div>
  );
}
