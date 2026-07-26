import { useMemo } from 'react';

const SPEEDS = [30, 60, 120, 300, 600, 1800, 3600];

const parisDay = (ts) => new Date(ts * 1000).toLocaleDateString('en-CA', { timeZone: 'Europe/Paris' });

// Segments journaliers de la plage (bornes aux minuits, heure de Paris), en % de la timeline.
// Dérivé de range : s'adapte automatiquement quand de nouveaux jours sont ingérés.
function daySegments(range) {
  if (!range) return [];
  const [t0, t1] = range;
  const span = t1 - t0;
  const segs = [];
  let segStart = t0;
  let ts = t0;
  while (ts < t1) {
    const next = Math.min(ts + 3600, t1);
    if (parisDay(next) !== parisDay(segStart) || next >= t1) {
      // affine la frontière de minuit à la minute près
      let lo = ts, hi = next;
      while (next < t1 && hi - lo > 60) {
        const mid = (lo + hi) / 2;
        if (parisDay(mid) === parisDay(segStart)) lo = mid; else hi = mid;
      }
      const end = next >= t1 ? t1 : hi;
      segs.push({
        key: parisDay(segStart),
        left: ((segStart - t0) / span) * 100,
        width: ((end - segStart) / span) * 100,
        label: new Date(segStart * 1000).toLocaleDateString('fr-FR', {
          weekday: 'short', day: 'numeric', timeZone: 'Europe/Paris',
        }),
        short: new Date(segStart * 1000).toLocaleDateString('fr-FR', {
          day: 'numeric', timeZone: 'Europe/Paris',
        }),
      });
      segStart = end;
    }
    ts = next;
  }
  return segs;
}

export default function Timeline({
  range, t, onScrub,
  playing, onTogglePlay, speed, onSpeed,
}) {
  const segments = useMemo(() => daySegments(range), [range]);
  return (
    <div className="timeline">
      <div className="timeline-row">
        <button className="btn play" onClick={onTogglePlay} disabled={!range}>
          {playing ? '⏸' : '▶'}
        </button>
        <button
          className="btn speed"
          onClick={() => onSpeed(SPEEDS[(SPEEDS.indexOf(speed) + 1) % SPEEDS.length])}
        >
          ×{speed}
        </button>
      </div>
      <div className="ruler">
        {segments.map((s) => (
          <div key={s.key} className="ruler-seg" style={{ left: `${s.left}%`, width: `${s.width}%` }}>
            <span>{s.width > 14 ? s.label : s.short}</span>
          </div>
        ))}
      </div>
      <input
        className="scrub"
        type="range"
        min={range ? range[0] : 0}
        max={range ? range[1] : 1}
        step={5}
        value={range ? t : 0}
        disabled={!range}
        onChange={(e) => onScrub(Number(e.target.value))}
      />
    </div>
  );
}
