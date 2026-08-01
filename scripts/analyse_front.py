#!/usr/bin/env python3
"""Les largages arrêtent-ils le front ? Persistance du feu à J+1 selon les largages à J.

Méthode :
  - grille de 5 km, par jour : intensité feu (somme FRP) et passages de largage (< 1000 ft)
  - pour chaque cellule en feu un jour J : ratio FRP(J+1)/FRP(J)
  - comparaison par niveau de largages, STRATIFIÉE par intensité initiale (le biais de
    sélection est massif : on largue précisément là où le feu menace de croître)
Produit graphiques + stats dans frontend/public/analyse/front/.
"""
import json
import sqlite3
from datetime import datetime, timezone, date, timedelta
from pathlib import Path

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "frontend" / "public" / "analyse" / "front"
OUT.mkdir(parents=True, exist_ok=True)
db = sqlite3.connect(ROOT / "data" / "canadair.db")

LAT0, LAT1, LON0, LON1 = 43.4, 45.6, -1.6, 0.2
CELL = 0.05
KM_LAT, KM_LON = 111.0, 78.0
nlat, nlon = int((LAT1 - LAT0) / CELL), int((LON1 - LON0) / CELL)
AIRPORTS = [(44.828, -0.715, 4.5), (44.533, -1.125, 3.0)]
LAKES = [(45.13, -1.07, 5.5), (44.98, -1.135, 3.5), (44.50, -1.13, 5.5), (44.35, -1.17, 4.5)]
DAYS = [date(2026, 7, d) for d in range(22, 32)]


def near_any(lat, lon, places):
    return any(((lat - la) * KM_LAT) ** 2 + ((lon - lo) * KM_LON) ** 2 < r * r for la, lo, r in places)


def day_ts(d):
    return datetime(d.year, d.month, d.day, tzinfo=timezone.utc).timestamp()


def grid_of(rows, weight=False):
    g = np.zeros((nlat, nlon))
    for la, lo, *w in rows:
        i, j = min(int((la - LAT0) / CELL), nlat - 1), min(int((lo - LON0) / CELL), nlon - 1)
        g[i, j] += w[0] if weight else 1
    return g


fire_g, drop_g = {}, {}
for d in DAYS:
    t0, t1 = day_ts(d), day_ts(d) + 86400
    fire_g[d] = grid_of(db.execute(
        "SELECT lat, lon, COALESCE(frp,5) FROM fires WHERE ts>=? AND ts<?", (t0, t1)), weight=True)
    rows = db.execute("""SELECT p.lat, p.lon FROM positions p JOIN aircraft a USING (hex)
        WHERE p.ts>=? AND p.ts<? AND p.alt_ft<1000 AND p.on_ground=0 AND p.gs_kt>60
          AND p.lat BETWEEN ? AND ? AND p.lon BETWEEN ? AND ?
          AND a.registration NOT IN ('LX-LGG','LX-LQD','LX-LGM','F-HSIF','F-HSOX','ZZ507')""",
        (t0, t1, LAT0, LAT1, LON0, LON1)).fetchall()
    rows = [(la, lo) for la, lo in rows if not near_any(la, lo, AIRPORTS) and not near_any(la, lo, LAKES)]
    drop_g[d] = grid_of(rows)

# échantillon : cellule-jour en feu -> devenir à J+1
samples = []
for d, dn in zip(DAYS[:-1], DAYS[1:]):
    f0, f1, dr = fire_g[d], fire_g[dn], drop_g[d]
    for i, j in zip(*np.nonzero(f0 >= 30)):
        samples.append({"frp0": f0[i, j], "frp1": f1[i, j], "drops": dr[i, j],
                        "ratio": f1[i, j] / f0[i, j]})

frp0 = np.array([s["frp0"] for s in samples])
terciles = np.percentile(frp0, [33, 66])
GROUPS = [("0 largage", lambda n: n == 0), ("1-49", lambda n: 1 <= n < 50), ("50+", lambda n: n >= 50)]
STRATA = [("feu modéré", lambda f: f < terciles[0]), ("feu fort", lambda f: terciles[0] <= f < terciles[1]),
          ("feu extrême", lambda f: f >= terciles[1])]

ext_table = {}  # (strate, groupe) -> (taux extinction %, n)
for sname, sf in STRATA:
    for gname, gf in GROUPS:
        sel = [s for s in samples if sf(s["frp0"]) and gf(s["drops"])]
        if len(sel) >= 5:
            ext = 100 * np.mean([s["ratio"] < 0.15 for s in sel])
            ext_table[(sname, gname)] = (round(float(ext)), len(sel))

overall = {g: (round(100 * float(np.mean([s["ratio"] < 0.15 for s in samples if gf(s["drops"])]))),
              sum(1 for s in samples if gf(s["drops"]))) for g, gf in GROUPS}

plt.rcParams.update({"figure.facecolor": "#14181f", "axes.facecolor": "#1a1f27",
                     "axes.edgecolor": "#39414d", "text.color": "#e8ecf2",
                     "axes.labelcolor": "#e8ecf2", "xtick.color": "#aeb8c4",
                     "ytick.color": "#aeb8c4", "font.size": 11})

# 1. taux d'extinction par strate x groupe
fig, ax = plt.subplots(figsize=(9, 5.5))
x = np.arange(len(STRATA))
w = 0.26
for k, (gname, _) in enumerate(GROUPS):
    vals = [ext_table.get((sname, gname), (np.nan,))[0] for sname, _ in STRATA]
    ns = [ext_table.get((sname, gname), (0, 0))[1] for sname, _ in STRATA]
    bars = ax.bar(x + (k - 1) * w, vals, w, label=f"{gname} le jour J",
                  color=["#93a0ae", "#28c8d8", "#4f8dff"][k])
    for b, n in zip(bars, ns):
        if not np.isnan(b.get_height()):
            ax.text(b.get_x() + b.get_width() / 2, b.get_height() + 1.2, f"n={n}",
                    ha="center", fontsize= 8, color="#6b7683")
ax.set_xticks(x); ax.set_xticklabels([s for s, _ in STRATA])
ax.set_ylabel("Cellules quasi éteintes le lendemain (%)")
ax.set_title("Le feu s'éteint-il plus souvent là où on a largué ?", color="#fff")
ax.legend(facecolor="#1a1f27", edgecolor="#39414d", labelcolor="#e8ecf2")
fig.tight_layout(); fig.savefig(OUT / "taux_extinction.png", dpi=110); plt.close(fig)

# 2. carte du front est : 24 -> 25 juillet
d24, d25 = date(2026, 7, 24), date(2026, 7, 25)
fig, ax = plt.subplots(figsize=(9, 8))
f24, f25, dr24 = fire_g[d24], fire_g[d25], drop_g[d24]
ys, xs = np.nonzero(dr24)
ax.scatter(LON0 + (xs + .5) * CELL, LAT0 + (ys + .5) * CELL, s=np.clip(dr24[ys, xs] * .9, 8, 380),
           marker="s", c="#28c8d8", alpha=.45, label="Largages du 24")
ys, xs = np.nonzero(f24)
ax.scatter(LON0 + (xs + .5) * CELL, LAT0 + (ys + .5) * CELL, s=np.clip(f24[ys, xs] / 5, 8, 380),
           c="#ff7a30", alpha=.8, label="Feu du 24")
ys, xs = np.nonzero(f25)
ax.scatter(LON0 + (xs + .5) * CELL, LAT0 + (ys + .5) * CELL, s=np.clip(f25[ys, xs] / 5, 8, 380),
           facecolors="none", edgecolors="#ffe14f", linewidths=1.6, label="Feu du 25 (contours)")
for n, la, lo in [("Le Porge", 44.87, -1.09), ("Ste-Hélène", 44.96, -0.88), ("Salaunes", 44.84, -0.84),
                  ("Saumos", 44.845, -0.925), ("St-Médard", 44.90, -0.72), ("Lacanau", 44.98, -1.08),
                  ("Andernos", 44.74, -1.10), ("Marcheprime", 44.69, -0.85)]:
    ax.plot(lo, la, ".", color="#93a0ae", ms=3)
    ax.annotate(n, (lo, la), xytext=(4, 3), textcoords="offset points", fontsize=8.5, color="#cdd5de")
ax.set_xlim(-1.25, -0.6); ax.set_ylim(44.62, 45.05)
ax.set_aspect(KM_LAT / KM_LON)
ax.set_title("Feu du Médoc, 24 → 25 juillet : le mur de largages à l'est", color="#fff")
ax.legend(loc="lower left", facecolor="#1a1f27", edgecolor="#39414d", labelcolor="#e8ecf2")
fig.tight_layout(); fig.savefig(OUT / "front_est_24_25.png", dpi=110); plt.close(fig)

# 3. progression est du feu jour par jour (longitude max des cellules en feu au nord)
edges = []
for d in DAYS:
    g = fire_g[d]
    ys, xs = np.nonzero(g[int((44.7 - LAT0) / CELL):int((45.05 - LAT0) / CELL), :] >= 30)
    edges.append(LON0 + (xs.max() + .5) * CELL if len(xs) else np.nan)
fig, ax = plt.subplots(figsize=(9, 4.6))
labels = [d.strftime("%d/%m") for d in DAYS]
ax.plot(labels, edges, "o-", color="#ff7a30", lw=2.2)
km = [(e - edges[0]) * KM_LON if not np.isnan(e) else np.nan for e in edges]
for xlbl, e, k in zip(labels, edges, km):
    if not np.isnan(e):
        ax.annotate(f"+{k:.0f} km", (xlbl, e), xytext=(0, 8), textcoords="offset points",
                    ha="center", fontsize=8.5, color="#93a0ae")
ax.set_ylabel("Longitude du bord est du feu (Médoc)")
ax.set_title("La progression vers Bordeaux : stoppée après le 25", color="#fff")
fig.tight_layout(); fig.savefig(OUT / "progression_est.png", dpi=110); plt.close(fig)

stats = {
    "genere_le_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    "cellules_jour_etudiees": len(samples),
    "seuil_extinction": "FRP(J+1) < 15 % de FRP(J)",
    "extinction_globale_par_groupe": {g: {"taux_pct": v[0], "n": v[1]} for g, v in overall.items()},
    "extinction_stratifiee": {f"{s} | {g}": {"taux_pct": v[0], "n": v[1]} for (s, g), v in ext_table.items()},
}
(OUT / "stats.json").write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(stats, ensure_ascii=False, indent=2))
