import { useCallback, useEffect, useRef, useState } from 'react';
import MapView from './MapView.jsx';
import Timeline from './Timeline.jsx';
import { positionAt, timeRange } from './interp.js';

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
  const [day, setDay] = useState(null);
  const [aircraft, setAircraft] = useState([]);
  const [fires, setFires] = useState([]);
  const [range, setRange] = useState(null);
  const [t, setT] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(300);
  const [selectedHex, setSelectedHex] = useState(null);
  const [error, setError] = useState(null);
  const [menuOpen, setMenuOpen] = useState(false);
  const [persist, setPersist] = useState(true);

  // Liste des jours disponibles
  useEffect(() => {
    fetch('/data/index.json')
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))))
      .then(({ days }) => {
        setDays(days);
        setDay(days.length > 1 ? 'all' : days[days.length - 1] ?? null);
        if (!days.length) setError('Aucune donnée : lancer le pipeline (ingest + export).');
      })
      .catch(() => setError('Aucune donnée : lancer le pipeline (ingest + export).'));
  }, []);

  // Chargement du jour sélectionné — ou de tous les jours fusionnés ("all")
  useEffect(() => {
    if (!day) return;
    setPlaying(false);
    const wanted = day === 'all' ? days.filter((d) => /^\d{4}-/.test(d)) : [day];
    Promise.all(wanted.map((d) =>
      fetch(`/data/${d}.json`).then((r) => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))))
    ))
      .then((loaded) => {
        // fusion par appareil (les jours sont chargés dans l'ordre chronologique)
        const byHex = new Map();
        const allFires = [];
        for (const data of loaded) {
          for (const a of data.aircraft) {
            const cur = byHex.get(a.hex);
            if (cur) cur.points = cur.points.concat(a.points);
            else byHex.set(a.hex, { ...a });
          }
          allFires.push(...(data.fires ?? []));
        }
        const data = { aircraft: [...byHex.values()], fires: allFires.sort((a, b) => a[0] - b[0]) };
        const list = data.aircraft.map((a, i) => ({ ...a, color: COLORS[i % COLORS.length] }));
        setAircraft(list);
        const fs = data.fires ?? [];
        setFires(fs);
        // plage : vols + détections de feu (le feu peut précéder le premier décollage)
        let r = timeRange(list);
        if (fs.length) {
          const fmin = fs[0][0], fmax = fs[fs.length - 1][0];
          r = r ? [Math.min(r[0], fmin), Math.max(r[1], fmax)] : [fmin, fmax];
        }
        setRange(r);
        if (r) {
          // premier chargement : démarrer au 22/07 13h (si couvert) et lire automatiquement
          const first = firstLoadRef.current;
          firstLoadRef.current = false;
          const start = first && START_T >= r[0] && START_T < r[1] ? START_T : r[0];
          setT(start);
          if (first) setPlaying(true);
        } else {
          setT(0);
        }
        setError(r ? null : `Aucun vol enregistré le ${day}.`);
      })
      .catch((e) => setError(`Erreur de chargement : ${e.message}`));
  }, [day, days]);

  const firstLoadRef = useRef(true);

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
    setSelectedHex((cur) => (cur === hex ? null : hex));
  }, []);

  const selected = aircraft.find((a) => a.hex === selectedHex);
  const selectedPos = selected ? positionAt(selected.points, t) : null;

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
      <MapView aircraft={aircraft} fires={fires} t={t} speed={speed} selectedHex={selectedHex} persist={persist} onSelect={onSelect} />
      <div className="night" style={{ opacity: range ? nightOpacity(t) : 0 }} />

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
            </div>
            <button className="detail-close" onClick={() => setSelectedHex(null)} aria-label="Fermer">✕</button>
          </div>
        )}
      </header>

      {menuOpen && (
        <div className="menu-overlay" onClick={() => setMenuOpen(false)}>
          <nav className="menu" onClick={(e) => e.stopPropagation()}>
            <button className="menu-close" onClick={() => setMenuOpen(false)} aria-label="Fermer">✕</button>
            <h2>Canadairs en Gironde</h2>
            <p className="menu-text">
              Rejouez les allers-retours des avions de lutte contre les incendies
              (Canadair, Dash, Air Tractor…) en Gironde et dans les Landes, jour par jour.
            </p>
            <h3>Données</h3>
            <ul className="menu-text">
              <li>
                <b>Trajectoires des avions</b> : signaux ADS-B agrégés par{' '}
                <a href="https://www.adsb.lol" target="_blank" rel="noreferrer">adsb.lol</a>{' '}
                (données ouvertes, licence ODbL, contributions communautaires) et{' '}
                <a href="https://airplanes.live" target="_blank" rel="noreferrer">airplanes.live</a>.
              </li>
              <li>
                <b>Zones de feu</b> : points chauds satellites VIIRS,{' '}
                <a href="https://firms.modaps.eosdis.nasa.gov" target="_blank" rel="noreferrer">NASA FIRMS</a>
                {' '}(2 à 4 passages par jour, les contours affichés sont approximatifs).
              </li>
              <li>
                <b>Fond de carte</b> :{' '}
                <a href="https://www.openstreetmap.org" target="_blank" rel="noreferrer">OpenStreetMap</a>.
              </li>
            </ul>
            <h3>Mise à jour</h3>
            <p className="menu-text">
              Le site se met à jour <b>une fois par jour</b> avec les vols de la veille :
              les trajectoires sont publiées par adsb.lol en archive quotidienne, disponible
              le lendemain. C'est pourquoi la timeline s'arrête à la fin de la dernière
              journée complète : la journée en cours apparaîtra demain.
            </p>
            <h3>Crédits</h3>
            <p className="menu-text">Guillaume HARARI</p>
          </nav>
        </div>
      )}

      {error && <div className="banner">{error}</div>}

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
          days={days} day={day} onDay={setDay}
          range={range} t={t} onScrub={setT}
          playing={playing} onTogglePlay={() => setPlaying((p) => !p)}
          speed={speed} onSpeed={setSpeed}
          persist={persist} onPersist={setPersist}
        />
      </footer>
    </div>
  );
}
