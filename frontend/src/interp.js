// Un point exporté par le backend : [ts, lat, lon, alt_ft, on_ground, gs_kt, track_deg, flags]
export const TS = 0, LAT = 1, LON = 2, ALT = 3, GROUND = 4, GS = 5, TRACK = 6, FLAGS = 7;

// Au-delà de ce trou entre deux points, on considère l'avion "hors couverture" (pas d'interpolation)
const MAX_GAP_S = 600;

/** Index du dernier point dont le ts est <= t (recherche binaire), ou -1. */
export function indexAt(points, t) {
  let lo = 0, hi = points.length - 1, res = -1;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    if (points[mid][TS] <= t) { res = mid; lo = mid + 1; } else { hi = mid - 1; }
  }
  return res;
}

function lerpAngle(a, b, f) {
  let d = ((b - a + 540) % 360) - 180;
  return (a + d * f + 360) % 360;
}

/** Cap géographique (°) du déplacement p0 -> p1. */
function geoBearing(lat1, lon1, lat2, lon2) {
  const r = Math.PI / 180;
  const y = Math.sin((lon2 - lon1) * r) * Math.cos(lat2 * r);
  const x = Math.cos(lat1 * r) * Math.sin(lat2 * r)
    - Math.sin(lat1 * r) * Math.cos(lat2 * r) * Math.cos((lon2 - lon1) * r);
  return (Math.atan2(y, x) / r + 360) % 360;
}

/** Position interpolée à l'instant t, ou null si l'avion n'est pas en vol suivi à cet instant. */
export function positionAt(points, t) {
  const i = indexAt(points, t);
  if (i < 0 || i >= points.length - 1) return null;
  const p0 = points[i], p1 = points[i + 1];
  if (p1[TS] - p0[TS] > MAX_GAP_S) return null;
  const f = (t - p0[TS]) / (p1[TS] - p0[TS] || 1);
  // Nez de l'avion : cap géométrique du segment réellement parcouru (plus fiable
  // que le champ track ADS-B, parfois absent ou en retard) ; fallback sur track.
  const moved = Math.abs(p1[LAT] - p0[LAT]) + Math.abs(p1[LON] - p0[LON]) > 1e-5;
  let track;
  if (moved) track = geoBearing(p0[LAT], p0[LON], p1[LAT], p1[LON]);
  else if (p0[TRACK] != null && p1[TRACK] != null) track = lerpAngle(p0[TRACK], p1[TRACK], f);
  else track = p0[TRACK] ?? 0;
  return {
    lat: p0[LAT] + (p1[LAT] - p0[LAT]) * f,
    lon: p0[LON] + (p1[LON] - p0[LON]) * f,
    alt: p0[ALT],
    ground: !!p0[GROUND],
    gs: p0[GS],
    track,
  };
}

/** Comme fullTrack, mais limité aux points <= t, dernier segment terminé à la position interpolée. */
export function trailSegmentsBefore(points, t) {
  const i = indexAt(points, t);
  if (i < 0) return [];
  const segments = fullTrack(points.slice(0, i + 1));
  const pos = positionAt(points, t);
  if (pos) {
    if (segments.length) segments[segments.length - 1].push([pos.lon, pos.lat]);
    else segments.push([[points[i][LON], points[i][LAT]], [pos.lon, pos.lat]]);
  }
  return segments;
}

/**
 * Coordonnées [lon, lat] de la traînée : les `windowS` dernières secondes avant t,
 * coupée aux trous de couverture, terminée par la position interpolée.
 */
export function trailBefore(points, t, windowS) {
  const i = indexAt(points, t);
  if (i < 0) return [];
  const coords = [];
  for (let j = i; j >= 0 && points[j][TS] >= t - windowS; j--) {
    if (j < i && points[j + 1][TS] - points[j][TS] > MAX_GAP_S) break;
    coords.unshift([points[j][LON], points[j][LAT]]);
  }
  const pos = positionAt(points, t);
  if (pos) coords.push([pos.lon, pos.lat]);
  return coords;
}

/** Tracé complet de la journée, découpé en segments aux trous de couverture. */
export function fullTrack(points) {
  const segments = [];
  let seg = [];
  for (let j = 0; j < points.length; j++) {
    if (j > 0 && points[j][TS] - points[j - 1][TS] > MAX_GAP_S && seg.length) {
      if (seg.length > 1) segments.push(seg);
      seg = [];
    }
    seg.push([points[j][LON], points[j][LAT]]);
  }
  if (seg.length > 1) segments.push(seg);
  return segments;
}

/** Plage [premier ts, dernier ts] couverte par au moins un avion, ou null. */
export function timeRange(aircraft) {
  let min = Infinity, max = -Infinity;
  for (const a of aircraft) {
    if (!a.points.length) continue;
    min = Math.min(min, a.points[0][TS]);
    max = Math.max(max, a.points[a.points.length - 1][TS]);
  }
  return min === Infinity ? null : [min, max];
}
