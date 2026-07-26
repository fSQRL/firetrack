const SPEEDS = [30, 60, 120, 300, 600, 1800, 3600];

function fmtDay(day) {
  const d = new Date(`${day}T12:00:00Z`);
  if (Number.isNaN(d.getTime())) return day; // ex. jeu de données "demo"
  return d.toLocaleDateString('fr-FR', { weekday: 'short', day: 'numeric', month: 'short' });
}

export default function Timeline({
  days, day, onDay, range, t, onScrub,
  playing, onTogglePlay, speed, onSpeed,
  persist, onPersist,
}) {
  return (
    <div className="timeline">
      <div className="timeline-row">
        <select className="day-select" value={day ?? ''} onChange={(e) => onDay(e.target.value)}>
          {days.length > 1 && <option value="all">Tous les jours</option>}
          {days.map((d) => <option key={d} value={d}>{fmtDay(d)}</option>)}
        </select>
        <button className="btn play" onClick={onTogglePlay} disabled={!range}>
          {playing ? '⏸' : '▶'}
        </button>
        <button
          className="btn speed"
          onClick={() => onSpeed(SPEEDS[(SPEEDS.indexOf(speed) + 1) % SPEEDS.length])}
        >
          ×{speed}
        </button>
        <label className="btn persist" title="Garder le tracé complet des avions affiché">
          <input type="checkbox" checked={persist} onChange={(e) => onPersist(e.target.checked)} />
          Tracés
        </label>
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
