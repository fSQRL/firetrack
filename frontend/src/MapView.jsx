import { useEffect, useRef } from 'react';
import maplibregl from 'maplibre-gl';
import 'maplibre-gl/dist/maplibre-gl.css';
import { positionAt, trailBefore, trailSegmentsBefore, fullTrack, windAt } from './interp.js';

// Traînée : ce que l'avion a parcouru pendant ~8 s réelles de lecture (borné 15 min – 2 h),
// pour rester visible aux grandes vitesses de lecture.
function trailWindow(speed) {
  return Math.min(2 * 3600, Math.max(15 * 60, (speed || 60) * 8));
}

// Fenêtre de visibilité d'un point chaud FIRMS autour de son heure de détection.
// Les satellites ne passent que vers ~01h30-04h30 et ~13h30-16h locales : il faut
// ~14 h de persistance pour que le passage de l'après-midi (dernier vers ~16h)
// tienne jusqu'au passage nocturne suivant, sans trou vers 2h-4h du matin.
const FIRE_BEFORE_S = 30 * 60;
const FIRE_AFTER_S = 14 * 3600;

// Silhouette d'avion (SVG, nez vers le haut) — marqueur DOM : mise à jour synchrone,
// contrairement aux couches symbol de MapLibre qui replacent les icônes en différé.
const PLANE_PATH = '<path d="M24 6 L28 16 L28 20 L45 28 L45 33 L28 29 L27 37 L33 41 L33 44 '
  + 'L24 42 L15 44 L15 41 L21 37 L20 29 L3 33 L3 28 L20 20 L20 16 Z"/>';

// Hélicoptère vu de dessus : pales en croix, cellule, poutre et rotor de queue
const HELI_PATHS = '<path d="M13 7 L15.5 4.5 L35 24 L32.5 26.5 Z"/>'
  + '<path d="M35 7 L32.5 4.5 L13 24 L15.5 26.5 Z"/>'
  + '<path d="M24 8 C29 8 30 14 30 19 C30 26 27 29 24 29 C21 29 18 26 18 19 C18 14 19 8 24 8 Z"/>'
  + '<path d="M22.5 28 L25.5 28 L25 41 L23 41 Z"/>'
  + '<path d="M17 39.5 L31 39.5 L31 42.5 L17 42.5 Z"/>';

// Types ICAO d'hélicoptères (EC45=H145, H125, AS3B=Super Puma...)
function isHelicopter(type) {
  const t = (type || '').toUpperCase();
  return ['EC45', 'EC35', 'EC30', 'EC55', 'EC75', 'H125', 'H135', 'H145', 'H160', 'H225',
    'AS50', 'AS55', 'AS3B', 'AS32', 'S76', 'B06', 'B412', 'B429', 'A109', 'A139', 'A189']
    .includes(t) || t.startsWith('EC1') || t.startsWith('R4');
}

function planeElement(color, heli) {
  const el = document.createElement('div');
  el.className = 'plane-marker';
  el.innerHTML = `<svg width="26" height="26" viewBox="0 0 48 48" fill="${color}"`
    + ` stroke="#14181f" stroke-width="2" stroke-linejoin="round">`
    + (heli ? HELI_PATHS : PLANE_PATH) + '</svg>';
  return el;
}

const MAP_STYLE = {
  version: 8,
  sources: {
    osm: {
      type: 'raster',
      tiles: ['https://tile.openstreetmap.org/{z}/{x}/{y}.png'],
      tileSize: 256,
      attribution: '© OpenStreetMap | Data © adsb.lol (ODbL)',
    },
  },
  layers: [{ id: 'osm', type: 'raster', source: 'osm' }],
};

const EMPTY = { type: 'FeatureCollection', features: [] };

// Imagerie satellite quotidienne NASA GIBS (vraies couleurs VIIRS, panache de fumée visible)
const GIBS_URL = 'https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/'
  + 'VIIRS_SNPP_CorrectedReflectance_TrueColor/default/{day}/GoogleMapsCompatible_Level9/{z}/{y}/{x}.jpg';

const SMOKE_PUFFS = 10;      // bouffées par foyer
const SMOKE_MAX_FIRES = 60;  // seuls les foyers les plus intenses émettent de la fumée

// Sprite de bouffée de fumée (dégradé radial gris, pré-rendu une fois)
let smokeSprite = null;
function getSmokeSprite() {
  if (smokeSprite) return smokeSprite;
  const c = document.createElement('canvas');
  c.width = c.height = 64;
  const cx = c.getContext('2d');
  const g = cx.createRadialGradient(32, 32, 4, 32, 32, 30);
  g.addColorStop(0, 'rgba(115, 115, 120, 0.6)');
  g.addColorStop(1, 'rgba(115, 115, 120, 0)');
  cx.fillStyle = g;
  cx.fillRect(0, 0, 64, 64);
  return (smokeSprite = c);
}

export default function MapView({ aircraft, fires, wind, t, speed, selectedHex, persist, satelliteDay, onSelect }) {
  const containerRef = useRef(null);
  const mapRef = useRef(null);
  const readyRef = useRef(false);
  const markersRef = useRef(new Map()); // hex -> {marker, svg}
  const canvasRef = useRef(null);
  const visFiresRef = useRef([]); // feux visibles à l'instant t (cache, rebâti toutes les 60 s simulées)
  const visSmokeRef = useRef([]); // sous-ensemble des foyers les plus intenses, émetteurs de fumée
  const fireSpritesRef = useRef(null); // 3 frames de flamme découpées depuis /flames.png

  // Sprite sheet des flammes : 3 frames côte à côte. Le fond noir éventuel est
  // converti en transparence (alpha = luminance) au chargement.
  useEffect(() => {
    const img = new Image();
    img.onload = () => {
      const fw = Math.floor(img.width / 3), fh = img.height;
      fireSpritesRef.current = [0, 1, 2].map((i) => {
        const c = document.createElement('canvas');
        c.width = fw;
        c.height = fh;
        const cx = c.getContext('2d');
        cx.drawImage(img, -i * fw, 0);
        const d = cx.getImageData(0, 0, fw, fh);
        const px = d.data;
        for (let j = 0; j < px.length; j += 4) {
          px[j + 3] = Math.min(px[j + 3], Math.max(px[j], px[j + 1], px[j + 2]));
        }
        cx.putImageData(d, 0, 0);
        return c;
      });
    };
    img.src = '/flames.png';
  }, []);

  // Les flammes dansent même en pause : petit tick de redessin permanent (~8 fps,
  // la fluidité pendant la lecture vient déjà du refresh à chaque frame)
  useEffect(() => {
    const id = setInterval(() => drawTrails(), 130);
    return () => clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Traînées récentes dessinées sur un canvas overlay : synchronisées à la frame près
  // avec les marqueurs (les sources GeoJSON de MapLibre sont retuilées en asynchrone).
  function drawTrails() {
    const canvas = canvasRef.current;
    const map = mapRef.current;
    if (!canvas || !map) return;
    const { aircraft, t, speed, selectedHex } = propsRef.current;
    const w = canvas.clientWidth, h = canvas.clientHeight;
    if (!w || !h) return;
    // dpr borné : sur mobile, le pinch-zoom peut gonfler devicePixelRatio et faire
    // dépasser la taille maximale de canvas ("Canvas exceeds max size")
    const dpr = Math.min(window.devicePixelRatio || 1, 2, 8192 / Math.max(w, h));
    const cw = Math.round(w * dpr), ch = Math.round(h * dpr);
    if (canvas.width !== cw || canvas.height !== ch) {
      canvas.width = cw;
      canvas.height = ch;
    }
    const ctx = canvas.getContext('2d');
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);

    // --- Flammes (sprites animés, taille ∝ intensité FRP, ancrées au sol) ---
    const sprites = fireSpritesRef.current;
    const nowMs = performance.now();
    const frame = Math.floor(nowMs / 150);
    for (let i = 0; i < visFiresRef.current.length; i++) {
      const [lon, lat, frp, fade] = visFiresRef.current[i];
      const p = map.project([lon, lat]);
      if (p.x < -40 || p.y < -60 || p.x > w + 40 || p.y > h + 40) continue;
      const s = (14 + 22 * Math.min(1, frp / 150)) * (1 + 0.07 * Math.sin(nowMs / 90 + i * 2.7));
      ctx.globalAlpha = fade;
      if (sprites) {
        ctx.drawImage(sprites[(frame + i) % 3], p.x - s / 2, p.y - s * 1.25, s, s * 1.35);
      } else {
        // fallback tant que /flames.png n'existe pas
        ctx.fillStyle = '#ff6a00';
        ctx.beginPath();
        ctx.arc(p.x, p.y, s / 3, 0, Math.PI * 2);
        ctx.fill();
      }
    }
    ctx.globalAlpha = 1;

    // --- Fumée : bouffées dérivant sous le vent réel de l'heure simulée ---
    const wv = windAt(propsRef.current.wind, t);
    if (wv && visSmokeRef.current.length) {
      const smoke = getSmokeSprite();
      const rad = Math.PI / 180;
      const spd = Math.max(wv.speed, 3);                    // km/h, plancher par vent calme
      const lenKm = Math.min(120, Math.max(8, spd * 6));    // panache = ~6 h de dérive
      const travelS = (lenKm / spd) * 3600;                 // durée de parcours du panache (s)
      const heading = (wv.dir + 180) * rad;                 // le vent "vient de" dir : fumée vers dir+180
      // échelle géographique : px par km à ce zoom (la fumée garde sa taille réelle)
      const p0 = map.project([-1, 44.6]);
      const p1 = map.project([-1, 44.6 + 1 / 111]);
      const pxPerKm = Math.hypot(p1.x - p0.x, p1.y - p0.y);
      const rnd = (n) => { const x = Math.sin(n) * 43758.5453; return x - Math.floor(x); }; // bruit stable
      for (let i = 0; i < visSmokeRef.current.length; i++) {
        const [lon, lat, frp, fade] = visSmokeRef.current[i];
        const strength = Math.min(1, frp / 150);
        // chaque foyer a son propre panache : cap dévié (±10°), longueur variable (60-130 %)
        const head = heading + (rnd(i * 7.13) - 0.5) * 20 * rad;
        const fLen = lenKm * (0.6 + 0.7 * rnd(i * 3.77));
        const m1 = rnd(i * 5.31) * 6.28, m2 = rnd(i * 9.02) * 6.28; // phases du méandre
        for (let k = 0; k < SMOKE_PUFFS; k++) {
          const ph = (((t / travelS) + k / SMOKE_PUFFS + i * 0.137) % 1 + 1) % 1;
          const distKm = ph * fLen;
          // le panache serpente : méandre commun à toutes les bouffées du foyer
          // (deux sinusoïdes superposées), pas d'éventail symétrique
          const side = (Math.sin(m1 + distKm * 0.11) + 0.5 * Math.sin(m2 + distKm * 0.31))
            * 0.13 * distKm;
          const dLat = (Math.cos(head) * distKm - Math.sin(head) * side) / 111;
          const dLon = (Math.sin(head) * distKm + Math.cos(head) * side)
            / (111 * Math.cos(lat * rad));
          const p = map.project([lon + dLon, lat + dLat]);
          // bouffées irrégulières : gonflement en dérivant + jitter de taille
          const szKm = (0.6 + 0.4 * distKm) * (0.6 + 0.6 * strength) * (0.65 + 0.7 * rnd(i * 13.7 + k * 2.9));
          const sz = Math.max(7, szKm * pxPerKm);
          if (p.x < -sz || p.y < -sz || p.x > w + sz || p.y > h + sz) continue;
          ctx.globalAlpha = fade * (0.28 + 0.2 * rnd(i * 2.1 + k * 4.3)) * (1 - ph * 0.75);
          ctx.drawImage(smoke, p.x - sz / 2, p.y - sz / 2, sz, sz);
        }
      }
      ctx.globalAlpha = 1;
    }

    // --- Traînées des avions ---
    ctx.lineWidth = 2.5;
    ctx.lineCap = 'round';
    ctx.lineJoin = 'round';
    ctx.globalAlpha = 0.9;
    for (const a of aircraft) {
      // avion absent (atterri / hors couverture) : sa ligne disparaît d'un coup
      if (!positionAt(a.points, t)) continue;
      const coords = trailBefore(a.points, t, trailWindow(speed));
      if (coords.length < 2) continue;
      const dim = selectedHex && selectedHex !== a.hex;
      ctx.strokeStyle = dim ? '#8892a0' : a.color;
      ctx.beginPath();
      for (let i = 0; i < coords.length; i++) {
        const p = map.project(coords[i]);
        if (i === 0) ctx.moveTo(p.x, p.y); else ctx.lineTo(p.x, p.y);
      }
      ctx.stroke();
    }
  }

  useEffect(() => {
    const map = new maplibregl.Map({
      container: containerRef.current,
      style: MAP_STYLE,
      center: [-0.7, 44.65], // Gironde
      zoom: 8,
      attributionControl: false,
    });
    map.addControl(new maplibregl.AttributionControl({ compact: true }), 'top-right');
    mapRef.current = map;
    map.on('load', () => {
      map.addSource('fulltrack', { type: 'geojson', data: EMPTY });
      map.addSource('trails', { type: 'geojson', data: EMPTY });
      map.addLayer({
        id: 'fulltrack', type: 'line', source: 'fulltrack',
        paint: { 'line-color': ['get', 'color'], 'line-width': 1.5, 'line-opacity': 0.45 },
      });
      map.addLayer({
        id: 'trails', type: 'line', source: 'trails',
        layout: { 'line-cap': 'round', 'line-join': 'round' },
        paint: { 'line-color': ['get', 'color'], 'line-width': 2.5, 'line-opacity': 0.9 },
      });
      readyRef.current = true;
      refresh();
    });
    map.on('move', drawTrails);
    map.on('resize', drawTrails);
    return () => { readyRef.current = false; markersRef.current.clear(); map.remove(); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // refs pour que refresh() lise toujours les dernières props sans réinitialiser la carte
  const propsRef = useRef({});
  propsRef.current = { aircraft, fires, wind, t, speed, selectedHex, persist };

  // Couche satellite NASA GIBS, datée selon le jour affiché par la timeline
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !readyRef.current) return;
    if (map.getLayer('gibs')) map.removeLayer('gibs');
    if (map.getSource('gibs')) map.removeSource('gibs');
    if (!satelliteDay) return;
    map.addSource('gibs', {
      type: 'raster',
      tiles: [GIBS_URL.replace('{day}', satelliteDay)],
      tileSize: 256,
      maxzoom: 9,
      attribution: 'NASA GIBS',
    });
    map.addLayer(
      { id: 'gibs', type: 'raster', source: 'gibs', paint: { 'raster-opacity': 0.8 } },
      'fulltrack' // sous les tracés et tout le reste
    );
  }, [satelliteDay]);
  const trailsKeyRef = useRef('');
  const firesKeyRef = useRef('');
  const trackKeyRef = useRef('');
  const onSelectRef = useRef(onSelect);
  onSelectRef.current = onSelect;

  function refresh() {
    if (!readyRef.current) return;
    const map = mapRef.current;
    const { aircraft, fires, t, selectedHex, persist } = propsRef.current;

    // --- Avions (marqueurs DOM) : à chaque frame ---
    const markers = markersRef.current;
    const seen = new Set();
    const inFlight = new Map(); // hex -> pos, réutilisé par le bloc persistant
    for (const a of aircraft) {
      const pos = positionAt(a.points, t);
      if (!pos) continue;
      seen.add(a.hex);
      inFlight.set(a.hex, pos);
      const color = selectedHex && selectedHex !== a.hex ? '#8892a0' : a.color;
      let m = markers.get(a.hex);
      if (!m) {
        const el = planeElement(color, isHelicopter(a.type));
        el.addEventListener('click', (e) => { e.stopPropagation(); onSelectRef.current?.(a.hex); });
        const marker = new maplibregl.Marker({ element: el, rotationAlignment: 'map', pitchAlignment: 'map' })
          .setLngLat([pos.lon, pos.lat])
          .addTo(map);
        m = { marker, svg: el.querySelector('svg') };
        markers.set(a.hex, m);
      }
      m.marker.setLngLat([pos.lon, pos.lat]).setRotation(pos.track);
      if (m.svg.getAttribute('fill') !== color) m.svg.setAttribute('fill', color);
    }
    for (const [hex, m] of markers) {
      if (!seen.has(hex)) { m.marker.remove(); markers.delete(hex); }
    }

    // --- Traînées récentes : canvas, à chaque frame ---
    drawTrails();

    // --- Feux : liste des visibles recalculée toutes les 60 s simulées seulement ---
    const firesKey = `${fires?.length ?? 0}|${Math.floor(t / 60)}`;
    if (firesKeyRef.current !== firesKey) {
      firesKeyRef.current = firesKey;
      const vis = [];
      for (const [ts, lat, lon, frp] of fires ?? []) {
        if (t < ts - FIRE_BEFORE_S || t > ts + FIRE_AFTER_S) continue;
        const fade = t < ts ? 1 - (ts - t) / FIRE_BEFORE_S : 1 - (t - ts) / FIRE_AFTER_S;
        vis.push([lon, lat, frp ?? 5, Math.max(0.15, fade)]);
      }
      visFiresRef.current = vis;
      visSmokeRef.current = [...vis].sort((a, b) => b[2] - a[2]).slice(0, SMOKE_MAX_FIRES);
    }

    // --- Tracés persistants : uniquement le vol en cours des avions en l'air,
    //     GeoJSON mis à jour toutes les 30 s simulées (la tête mobile est au canvas) ---
    const trailsKey = persist
      ? `${selectedHex}|${aircraft.length}|${Math.floor(t / 30)}`
      : 'off';
    if (trailsKeyRef.current !== trailsKey) {
      trailsKeyRef.current = trailsKey;
      const trails = [];
      if (persist) {
        for (const a of aircraft) {
          if (!inFlight.has(a.hex)) continue; // au sol / atterri : la ligne s'efface
          const segs = trailSegmentsBefore(a.points, t);
          const cur = segs[segs.length - 1]; // le vol en cours seulement
          if (cur && cur.length > 1) {
            trails.push({
              type: 'Feature',
              geometry: { type: 'LineString', coordinates: cur },
              properties: { color: selectedHex && selectedHex !== a.hex ? '#8892a0' : a.color },
            });
          }
        }
      }
      map.getSource('trails')?.setData({ type: 'FeatureCollection', features: trails });
    }

    // --- Tracé complet de l'avion sélectionné : ne dépend pas de t ---
    const trackKey = `${selectedHex}|${aircraft.length}`;
    if (trackKeyRef.current !== trackKey) {
      trackKeyRef.current = trackKey;
      const tracks = [];
      const sel = aircraft.find((a) => a.hex === selectedHex);
      if (sel) {
        for (const seg of fullTrack(sel.points)) {
          tracks.push({
            type: 'Feature',
            geometry: { type: 'LineString', coordinates: seg },
            properties: { color: sel.color },
          });
        }
      }
      map.getSource('fulltrack')?.setData({ type: 'FeatureCollection', features: tracks });
    }
  }

  useEffect(refresh, [aircraft, fires, wind, t, selectedHex, persist]);

  return (
    <div className="map-wrap">
      <div ref={containerRef} className="map" />
      <canvas ref={canvasRef} className="trail-canvas" />
    </div>
  );
}
