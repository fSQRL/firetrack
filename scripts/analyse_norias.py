#!/usr/bin/env python3
"""Analyse du rendement des norias : cadence des rotations écopage/largage.

Méthode (pièges : voir skill firetrack-open-data) :
  - "passage en action" = groupe de points < 500 ft, > 60 kt, en vol, groupés à < 120 s
  - classé ÉCOPAGE si au-dessus d'un lac, écarté si près d'un aéroport, sinon LARGAGE
  - rotation = intervalle entre deux largages consécutifs d'un même appareil (3-90 min ;
    jusqu'à 4 h pour l'A400M qui recharge en base)
Produit graphiques + stats dans frontend/public/analyse/norias/.
"""
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "frontend" / "public" / "analyse" / "norias"
OUT.mkdir(parents=True, exist_ok=True)
db = sqlite3.connect(ROOT / "data" / "canadair.db")

LAT0, LAT1, LON0, LON1 = 43.4, 45.6, -1.6, 0.2
KM_LAT, KM_LON = 111.0, 78.0
AIRPORTS = [(44.828, -0.715, 4.5), (44.533, -1.125, 3.0)]
LAKES = {"Lac d'Hourtin-Carcans": (45.13, -1.07, 5.5), "Lac de Lacanau": (44.98, -1.135, 3.5),
         "Lac de Cazaux-Sanguinet": (44.50, -1.13, 5.5), "Lac de Biscarrosse-Parentis": (44.35, -1.17, 4.5)}


def near(lat, lon, la, lo, r):
    return ((lat - la) * KM_LAT) ** 2 + ((lon - lo) * KM_LON) ** 2 < r * r


def classify(lat, lon):
    for la, lo, r in AIRPORTS:
        if near(lat, lon, la, lo, r):
            return "airport", None
    for name, (la, lo, r) in LAKES.items():
        if near(lat, lon, la, lo, r):
            return "scoop", name
    return "drop", None


rows = db.execute("""SELECT p.hex, a.name, a.type, p.ts, p.lat, p.lon FROM positions p
    JOIN aircraft a USING (hex)
    WHERE p.lat BETWEEN ? AND ? AND p.lon BETWEEN ? AND ?
      AND p.alt_ft < 500 AND p.on_ground = 0 AND p.gs_kt > 60
      AND a.registration NOT IN ('LX-LGG','LX-LQD','LX-LGM','F-HSIF','F-HSOX','ZZ507')
    ORDER BY p.hex, p.ts""", (LAT0, LAT1, LON0, LON1)).fetchall()

# groupes de passages bas -> événements classés
events = []  # (hex, name, type, kind, lake, ts_debut)
cur = None
for hex_, name, typ, ts, lat, lon in rows:
    if cur and cur["hex"] == hex_ and ts - cur["end"] < 120:
        cur["end"] = ts
        cur["lats"].append(lat)
        cur["lons"].append(lon)
        continue
    if cur:
        kind, lake = classify(np.mean(cur["lats"]), np.mean(cur["lons"]))
        if kind != "airport":
            events.append((cur["hex"], cur["name"], cur["type"], kind, lake, cur["start"]))
    cur = {"hex": hex_, "name": name, "type": typ, "start": ts, "end": ts, "lats": [lat], "lons": [lon]}
if cur:
    kind, lake = classify(np.mean(cur["lats"]), np.mean(cur["lons"]))
    if kind != "airport":
        events.append((cur["hex"], cur["name"], cur["type"], kind, lake, cur["start"]))

# rotations = intervalles largage -> largage
by_ac = {}
for hex_, name, typ, kind, lake, ts in events:
    by_ac.setdefault((hex_, name, typ), []).append((kind, lake, ts))

stats_ac = []
scoop_lakes = {}
scoop_to_drop = []
for (hex_, name, typ), evs in by_ac.items():
    drops = [ts for k, l, ts in evs if k == "drop"]
    scoops = [(l, ts) for k, l, ts in evs if k == "scoop"]
    for l, ts in scoops:
        scoop_lakes[l] = scoop_lakes.get(l, 0) + 1
    cap = 240 * 60 if typ == "A400" else 90 * 60
    cycles = [b - a for a, b in zip(drops, drops[1:]) if 180 <= b - a <= cap]
    # temps écopage -> largage suivant (branche "attaque" de la noria)
    for l, s_ts in scoops:
        nxt = min((d for d in drops if d > s_ts), default=None)
        if nxt and nxt - s_ts < 40 * 60:
            scoop_to_drop.append(nxt - s_ts)
    if len(drops) >= 3:
        stats_ac.append({
            "nom": name, "type": typ, "largages": len(drops), "ecopages": len(scoops),
            "cycle_median_min": round(float(np.median(cycles)) / 60, 1) if cycles else None,
            "cycles_mesures": len(cycles),
        })
stats_ac.sort(key=lambda s: -s["largages"])

drops_all = [(name, typ, ts) for (h, name, typ), evs in by_ac.items() for k, l, ts in evs if k == "drop"]

# ================= GRAPHIQUES =================
plt.rcParams.update({"figure.facecolor": "#14181f", "axes.facecolor": "#1a1f27",
                     "axes.edgecolor": "#39414d", "text.color": "#e8ecf2",
                     "axes.labelcolor": "#e8ecf2", "xtick.color": "#aeb8c4",
                     "ytick.color": "#aeb8c4", "font.size": 11})
TYPE_COLOR = {"CL-415": "#ff5d47", "DASH8": "#ffb020", "AT8T": "#3ecf5b", "A400": "#4f8dff",
              "PUMA": "#b06dff", "H53": "#b06dff", "H60": "#b06dff", "AS32": "#b06dff"}

# 1. cadence par appareil
top = [s for s in stats_ac if s["cycle_median_min"]][:12]
fig, ax = plt.subplots(figsize=(9, 6.5))
names = [s["nom"] for s in top][::-1]
vals = [s["cycle_median_min"] for s in top][::-1]
cols = [TYPE_COLOR.get(s["type"], "#93a0ae") for s in top][::-1]
bars = ax.barh(names, vals, color=cols)
for b, s in zip(bars, top[::-1]):
    ax.text(b.get_width() + 0.4, b.get_y() + b.get_height() / 2, f'{s["cycle_median_min"]:.0f} min',
            va="center", fontsize=9, color="#cdd5de")
ax.set_xlabel("Durée médiane d'une rotation (minutes entre deux largages)")
ax.set_title("La cadence de chaque appareil", color="#fff")
fig.tight_layout(); fig.savefig(OUT / "cadence_par_appareil.png", dpi=110); plt.close(fig)

# 2. journée type : rythme horaire des largages
fig, ax = plt.subplots(figsize=(9, 4.5))
hours = [datetime.fromtimestamp(ts, timezone.utc).hour + 2 for _, _, ts in drops_all]  # heure de Paris
ax.hist([h % 24 for h in hours], bins=range(25), color="#ff7a30", rwidth=0.85)
ax.set_xticks(range(0, 25, 2))
ax.set_xlabel("Heure de la journée (heure de Paris)")
ax.set_ylabel("Largages")
ax.set_title("Le rythme d'une journée de feu : tous largages confondus", color="#fff")
fig.tight_layout(); fig.savefig(OUT / "rythme_journee.png", dpi=110); plt.close(fig)

# 3. la plus belle noria : trajectoire du jour le plus productif
best = max(((h, n, t) for (h, n, t) in by_ac), key=lambda k: len([1 for kk, l, ts in by_ac[k] if kk == "drop"]))
best_hex, best_name, _ = best
day_counts = {}
for k, l, ts in by_ac[best]:
    if k == "drop":
        d = datetime.fromtimestamp(ts, timezone.utc).date()
        day_counts[d] = day_counts.get(d, 0) + 1
best_day = max(day_counts, key=day_counts.get)
d0 = datetime(best_day.year, best_day.month, best_day.day, tzinfo=timezone.utc).timestamp()
traj = db.execute("""SELECT ts, lat, lon FROM positions WHERE hex=? AND ts BETWEEN ? AND ?
    AND lat BETWEEN 44.6 AND 45.2 AND lon BETWEEN -1.4 AND -0.6 ORDER BY ts""",
                  (best_hex, d0, d0 + 86400)).fetchall()
fig, ax = plt.subplots(figsize=(9, 7))
la = [r[1] for r in traj]; lo = [r[2] for r in traj]; tt = [r[0] for r in traj]
sc = ax.scatter(lo, la, c=tt, cmap="plasma", s=3)
for name, (lla, llo, r) in LAKES.items():
    ax.add_patch(plt.Circle((llo, lla), r / KM_LON, color="#4f8dff", alpha=.25))
fday = db.execute("SELECT lat, lon FROM fires WHERE ts BETWEEN ? AND ?", (d0 - 43200, d0 + 86400)).fetchall()
ax.scatter([f[1] for f in fday], [f[0] for f in fday], c="#ff7a30", s=5, alpha=.25, label="foyers détectés")
cb = fig.colorbar(sc, ax=ax, shrink=.7)
cb.set_ticks([tt[0], tt[-1]])
cb.set_ticklabels([datetime.fromtimestamp(x, timezone.utc).strftime("%Hh%M") for x in (tt[0], tt[-1])])
cb.set_label("heure (UTC)", color="#e8ecf2")
n_drops = day_counts[best_day]
ax.set_title(f"{best_name}, le {best_day.strftime('%d/%m')} : {n_drops} largages dans la journée",
             color="#fff")
# zoom sur la zone de travail réelle (percentiles de la trajectoire)
ax.set_xlim(np.percentile(lo, 1) - 0.04, np.percentile(lo, 99) + 0.04)
ax.set_ylim(np.percentile(la, 1) - 0.03, np.percentile(la, 99) + 0.03)
ax.set_aspect(KM_LAT / KM_LON)
ax.legend(facecolor="#1a1f27", edgecolor="#39414d", labelcolor="#e8ecf2", loc="lower right")
fig.tight_layout(); fig.savefig(OUT / "noria_exemple.png", dpi=110); plt.close(fig)

# 4. écopages par lac
fig, ax = plt.subplots(figsize=(8, 4))
names = sorted(scoop_lakes, key=scoop_lakes.get)
ax.barh(names, [scoop_lakes[n] for n in names], color="#4f8dff")
ax.set_title("Où les avions ont fait le plein : écopages par lac", color="#fff")
fig.tight_layout(); fig.savefig(OUT / "ecopages_par_lac.png", dpi=110); plt.close(fig)

# ================= STATS =================
all_cycles = [c for (h, n, t), evs in by_ac.items()
              for a, b in zip([ts for k, l, ts in evs if k == "drop"][:-1],
                              [ts for k, l, ts in evs if k == "drop"][1:])
              for c in [b - a] if 180 <= c <= 90 * 60]
photos = {n: db.execute("SELECT photo_src, photo_credit FROM aircraft WHERE name=?", (n,)).fetchone()
          for n in [s["nom"] for s in stats_ac[:6]]}
stats = {
    "genere_le_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    "nb_largages_detectes": len(drops_all),
    "nb_ecopages_detectes": sum(scoop_lakes.values()),
    "cycle_median_global_min": round(float(np.median(all_cycles)) / 60, 1),
    "ecopage_vers_largage_median_min": round(float(np.median(scoop_to_drop)) / 60, 1) if scoop_to_drop else None,
    "ecopages_par_lac": scoop_lakes,
    "meilleure_journee": {"appareil": best_name, "jour": str(best_day), "largages": n_drops},
    "par_appareil": stats_ac[:15],
    "photos": {n: {"src": p[0], "credit": p[1]} if p else None for n, p in photos.items()},
}
(OUT / "stats.json").write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(stats, ensure_ascii=False, indent=2))
