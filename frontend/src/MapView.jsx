import { useEffect, useRef } from 'react';
import maplibregl from 'maplibre-gl';
import 'maplibre-gl/dist/maplibre-gl.css';
import { positionAt, trailBefore, trailSegmentsBefore, fullTrack } from './interp.js';

// Traînée : ce que l'avion a parcouru pendant ~8 s réelles de lecture (borné 15 min – 2 h),
// pour rester visible aux grandes vitesses de lecture.
function trailWindow(speed) {
  return Math.min(2 * 3600, Math.max(15 * 60, (speed || 60) * 8));
}

// Fenêtre de visibilité d'un point chaud FIRMS autour de son heure de détection.
// Les satellites ne passent que vers ~01h30 et ~13h30 locales : on fait persister
// la détection ~10 h pour couvrir l'intervalle entre deux passages.
const FIRE_BEFORE_S = 30 * 60;
const FIRE_AFTER_S = 10 * 3600;

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

export default function MapView({ aircraft, fires, t, speed, selectedHex, persist, onSelect }) {
  const containerRef = useRef(null);
  const mapRef = useRef(null);
  const readyRef = useRef(false);
  const markersRef = useRef(new Map()); // hex -> {marker, path}
  const canvasRef = useRef(null);

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
    ctx.lineWidth = 2.5;
    ctx.lineCap = 'round';
    ctx.lineJoin = 'round';
    ctx.globalAlpha = 0.9;
    for (const a of aircraft) {
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
      map.addSource('fires', { type: 'geojson', data: EMPTY });
      map.addSource('fulltrack', { type: 'geojson', data: EMPTY });
      map.addSource('trails', { type: 'geojson', data: EMPTY });
      map.addLayer({
        id: 'fires-glow', type: 'circle', source: 'fires',
        paint: {
          'circle-color': '#ff5a00',
          'circle-blur': 1,
          'circle-radius': ['interpolate', ['linear'], ['get', 'frp'], 0, 8, 50, 16, 300, 30],
          'circle-opacity': ['*', 0.5, ['get', 'fade']],
        },
      });
      map.addLayer({
        id: 'fires-core', type: 'circle', source: 'fires',
        paint: {
          'circle-color': '#ffc02e',
          'circle-radius': ['interpolate', ['linear'], ['get', 'frp'], 0, 2.5, 50, 4.5, 300, 8],
          'circle-opacity': ['get', 'fade'],
        },
      });
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
  propsRef.current = { aircraft, fires, t, speed, selectedHex, persist };
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

    // --- Feux : GeoJSON, mis à jour toutes les 60 s simulées seulement ---
    const firesKey = `${fires?.length ?? 0}|${Math.floor(t / 60)}`;
    if (firesKeyRef.current !== firesKey) {
      firesKeyRef.current = firesKey;
      const fireFeats = [];
      for (const [ts, lat, lon, frp] of fires ?? []) {
        if (t < ts - FIRE_BEFORE_S || t > ts + FIRE_AFTER_S) continue;
        const fade = t < ts ? 1 - (ts - t) / FIRE_BEFORE_S : 1 - (t - ts) / FIRE_AFTER_S;
        fireFeats.push({
          type: 'Feature',
          geometry: { type: 'Point', coordinates: [lon, lat] },
          properties: { frp: frp ?? 5, fade: Math.max(0.15, fade) },
        });
      }
      map.getSource('fires')?.setData({ type: 'FeatureCollection', features: fireFeats });
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

  useEffect(refresh, [aircraft, fires, t, selectedHex, persist]);

  return (
    <div className="map-wrap">
      <div ref={containerRef} className="map" />
      <canvas ref={canvasRef} className="trail-canvas" />
    </div>
  );
}
