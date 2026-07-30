#!/usr/bin/env python3
"""La fumée et l'air qu'on a respiré : indice européen heure par heure, lieu par lieu.

Piège (skill firetrack-open-data) : la table air contient de la prévision au-delà du
dernier relevé : tronqué au dernier ts de feux. Résolution du modèle CAMS ~11 km :
les pics locaux dans le panache sont sous-estimés (dit dans la page).
Produit graphiques + stats dans frontend/public/analyse/air/.
"""
import json
import sqlite3
from datetime import datetime, timezone, date
from pathlib import Path

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "frontend" / "public" / "analyse" / "air"
OUT.mkdir(parents=True, exist_ok=True)
db = sqlite3.connect(ROOT / "data" / "canadair.db")

t_min = datetime(2026, 7, 22, tzinfo=timezone.utc).timestamp()
t_max = db.execute("SELECT MAX(ts) FROM fires").fetchone()[0]

PLACES = {"Bordeaux": (44.8, -0.6), "Zone du feu / nord Bassin": (44.8, -1.0),
          "Sud des Landes": (44.4, -1.0), "Témoin est (Entre-deux-Mers)": (44.8, -0.2)}
COLORS = {"Bordeaux": "#ff5d47", "Zone du feu / nord Bassin": "#ff9a30",
          "Sud des Landes": "#ffd23e", "Témoin est (Entre-deux-Mers)": "#7fa8e0"}

series = {}
for name, (la, lo) in PLACES.items():
    series[name] = db.execute("""SELECT ts, aqi FROM air WHERE lat=? AND lon=? AND ts BETWEEN ? AND ?
        ORDER BY ts""", (la, lo, t_min, t_max)).fetchall()

plt.rcParams.update({"figure.facecolor": "#14181f", "axes.facecolor": "#1a1f27",
                     "axes.edgecolor": "#39414d", "text.color": "#e8ecf2",
                     "axes.labelcolor": "#e8ecf2", "xtick.color": "#aeb8c4",
                     "ytick.color": "#aeb8c4", "font.size": 10.5})

# 1. chronologie de l'indice, nuits grisées
fig, ax = plt.subplots(figsize=(10, 5.6))
days = [date(2026, 7, d) for d in range(22, 30)]
for d in days:  # nuits locales ~22h-8h = 20h-6h UTC
    n0 = datetime(d.year, d.month, d.day, 20, tzinfo=timezone.utc).timestamp()
    ax.axvspan(n0, n0 + 10 * 3600, color="#0d1118", zorder=0)
for name, rows in series.items():
    ax.plot([r[0] for r in rows], [r[1] for r in rows], color=COLORS[name], lw=1.8, label=name)
for lvl, lab in [(50, "moyen"), (80, "mauvais"), (100, "très mauvais")]:
    ax.axhline(lvl, color="#39414d", lw=.8)
    ax.text(t_min, lvl + 1.5, lab, fontsize=8, color="#6b7683")
ticks = [datetime(d.year, d.month, d.day, 12, tzinfo=timezone.utc).timestamp() for d in days]
ax.set_xticks(ticks); ax.set_xticklabels([d.strftime("%d/%m") for d in days])
ax.set_ylabel("Indice européen de qualité de l'air")
ax.set_title("Huit jours d'air : les bandes sombres sont les nuits", color="#fff")
ax.legend(facecolor="#1a1f27", edgecolor="#39414d", labelcolor="#e8ecf2", fontsize=9)
fig.tight_layout(); fig.savefig(OUT / "chronologie_aqi.png", dpi=110); plt.close(fig)

# 2. profil horaire moyen : le paradoxe nocturne
fig, ax = plt.subplots(figsize=(9, 4.8))
for name in ["Bordeaux", "Zone du feu / nord Bassin"]:
    by_h = {}
    for ts, aqi in series[name]:
        h = (datetime.fromtimestamp(ts, timezone.utc).hour + 2) % 24
        by_h.setdefault(h, []).append(aqi)
    hh = sorted(by_h)
    ax.plot(hh, [np.mean(by_h[h]) for h in hh], "o-", color=COLORS[name], label=name)
ax.set_xticks(range(0, 25, 2))
ax.set_xlabel("Heure de la journée (heure de Paris)")
ax.set_ylabel("Indice moyen sur l'épisode")
ax.set_title("Le paradoxe : l'air est pire la nuit qu'aux heures des flammes", color="#fff")
ax.legend(facecolor="#1a1f27", edgecolor="#39414d", labelcolor="#e8ecf2", fontsize=9)
fig.tight_layout(); fig.savefig(OUT / "profil_horaire.png", dpi=110); plt.close(fig)

# 3. heures d'air dégradé par jour et par lieu
fig, ax = plt.subplots(figsize=(9.5, 5))
x = np.arange(len(days))
w = 0.2
for k, (name, rows) in enumerate(series.items()):
    hrs = []
    for d in days:
        t0 = datetime(d.year, d.month, d.day, tzinfo=timezone.utc).timestamp()
        hrs.append(sum(1 for ts, a in rows if t0 <= ts < t0 + 86400 and a is not None and a > 50))
    ax.bar(x + (k - 1.5) * w, hrs, w, color=COLORS[name], label=name)
ax.set_xticks(x); ax.set_xticklabels([d.strftime("%d/%m") for d in days])
ax.set_ylabel("Heures avec un air dégradé (indice > 50)")
ax.set_title("Combien d'heures d'air dégradé, chaque jour", color="#fff")
ax.legend(facecolor="#1a1f27", edgecolor="#39414d", labelcolor="#e8ecf2", fontsize=9)
fig.tight_layout(); fig.savefig(OUT / "heures_degradees.png", dpi=110); plt.close(fig)

# stats
def peak(rows):
    ts, aqi = max(rows, key=lambda r: r[1] or 0)
    return {"aqi": aqi, "quand_utc": datetime.fromtimestamp(ts, timezone.utc).isoformat(timespec="minutes")}

stats = {
    "genere_le_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    "pics": {n: peak(r) for n, r in series.items()},
    "heures_degradees_total": {n: sum(1 for _, a in r if a and a > 50) for n, r in series.items()},
    "heures_tres_mauvais_total": {n: sum(1 for _, a in r if a and a > 100) for n, r in series.items()},
}
(OUT / "stats.json").write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(stats, ensure_ascii=False, indent=2))
