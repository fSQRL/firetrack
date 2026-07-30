#!/usr/bin/env python3
"""Le feu et le vent : chronologie, rotation du vent et direction de propagation.

Piège (skill firetrack-open-data) : la table wind contient de la PRÉVISION au-delà du
dernier relevé observé : on tronque au dernier ts de feux. Le vent est le vent ambiant
modélisé à 10 m : un grand feu convectif crée en plus son propre vent local (non mesuré ici).
Produit graphiques + stats dans frontend/public/analyse/vent/.
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
OUT = ROOT / "frontend" / "public" / "analyse" / "vent"
OUT.mkdir(parents=True, exist_ok=True)
db = sqlite3.connect(ROOT / "data" / "canadair.db")

t_min = datetime(2026, 7, 22, tzinfo=timezone.utc).timestamp()  # début de l'épisode
t_max = db.execute("SELECT MAX(ts) FROM fires").fetchone()[0]
wind = db.execute("SELECT ts, speed_kmh, dir_deg FROM wind WHERE ts BETWEEN ? AND ? ORDER BY ts",
                  (t_min, t_max)).fetchall()
fires = db.execute("SELECT ts, lat, lon, COALESCE(frp,5) FROM fires WHERE ts >= ? ORDER BY ts",
                   (t_min,)).fetchall()

# FRP total par passage satellite (regroupement des détections à < 20 min)
passes = []
for ts, la, lo, frp in fires:
    if passes and ts - passes[-1]["ts_fin"] < 1200:
        passes[-1]["frp"] += frp
        passes[-1]["ts_fin"] = ts
    else:
        passes.append({"ts": ts, "ts_fin": ts, "frp": frp})

plt.rcParams.update({"figure.facecolor": "#14181f", "axes.facecolor": "#1a1f27",
                     "axes.edgecolor": "#39414d", "text.color": "#e8ecf2",
                     "axes.labelcolor": "#e8ecf2", "xtick.color": "#aeb8c4",
                     "ytick.color": "#aeb8c4", "font.size": 11})


def daylab(ts):
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%d/%m")


# 1. chronologie : vent (couleur = direction) et intensité du feu par passage
fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 7), sharex=True,
                               gridspec_kw={"height_ratios": [1, 1.2]})
wts = [w[0] for w in wind]
sc = ax1.scatter(wts, [w[1] for w in wind], c=[w[2] for w in wind], cmap="hsv",
                 vmin=0, vmax=360, s=14)
ax1.plot(wts, [w[1] for w in wind], color="#39414d", lw=.8, zorder=0)
cb = fig.colorbar(sc, ax=ax1, pad=.01)
cb.set_ticks([0, 90, 180, 270, 360]); cb.set_ticklabels(["N", "E", "S", "O", "N"])
cb.set_label("le vent vient du...", color="#e8ecf2")
ax1.set_ylabel("Vent (km/h)")
ax1.set_title("Huit jours de vent... et la réponse du feu", color="#fff")
ax2.bar([p["ts"] for p in passes], [p["frp"] / 1000 for p in passes], width=9000,
        color="#ff7a30")
ax2.set_ylabel("Puissance du feu par passage satellite (GW)")
days = sorted({date.fromtimestamp(p["ts"]) for p in passes})
ticks = [datetime(d.year, d.month, d.day, 12, tzinfo=timezone.utc).timestamp() for d in days]
ax2.set_xticks(ticks); ax2.set_xticklabels([d.strftime("%d/%m") for d in days])
for d in days:
    x = datetime(d.year, d.month, d.day, tzinfo=timezone.utc).timestamp()
    for ax in (ax1, ax2):
        ax.axvline(x, color="#2a313c", lw=.8)
fig.tight_layout(); fig.savefig(OUT / "chronologie.png", dpi=110); plt.close(fig)

# 2. le vent pousse, le feu suit : vecteurs quotidiens (feu nord / Médoc)
SPLIT = 44.62
cent = {}
for d in days:
    t0 = datetime(d.year, d.month, d.day, tzinfo=timezone.utc).timestamp()
    pts = [(la, lo, f) for ts, la, lo, f in fires if t0 <= ts < t0 + 86400 and la > SPLIT]
    if pts:
        w = sum(p[2] for p in pts)
        cent[d] = (sum(p[0] * p[2] for p in pts) / w, sum(p[1] * p[2] for p in pts) / w)
wind_day = {}
for ts, s, dr in wind:
    d = date.fromtimestamp(ts)
    wind_day.setdefault(d, []).append((s, dr))
fig, ax = plt.subplots(figsize=(9.5, 5))
pairs = [(a, b) for a, b in zip(days, days[1:]) if a in cent and b in cent]
for k, (a, b) in enumerate(pairs):
    # vecteur vent moyen du jour a (vers où il souffle)
    sp = np.mean([s for s, _ in wind_day[a]])
    ang = np.deg2rad(np.mean([dr for _, dr in wind_day[a]]) + 180)
    ax.annotate("", xy=(k + 0.38 * np.sin(ang) * sp / 16, 1 + 0.38 * np.cos(ang) * sp / 16),
                xytext=(k, 1), arrowprops=dict(color="#4f8dff", width=2.2, headwidth=9))
    # vecteur déplacement du feu a -> b
    dlat = (cent[b][0] - cent[a][0]) * 111
    dlon = (cent[b][1] - cent[a][1]) * 78
    n = max((dlat**2 + dlon**2) ** .5, .01)
    ax.annotate("", xy=(k + 0.38 * dlon / max(n, 4), 0 + 0.38 * dlat / max(n, 4)),
                xytext=(k, 0), arrowprops=dict(color="#ff7a30", width=2.2, headwidth=9))
    ax.text(k, -0.62, f"{a.strftime('%d/%m')}", ha="center", fontsize=9, color="#aeb8c4")
    ax.text(k, 0.48, f"{n:.1f} km", ha="center", fontsize=8, color="#93a0ae")
ax.text(-0.8, 1, "le vent\npousse vers", ha="right", va="center", fontsize=10, color="#4f8dff")
ax.text(-0.8, 0, "le feu\nse déplace vers", ha="right", va="center", fontsize=10, color="#ff7a30")
ax.set_xlim(-2.2, len(pairs)); ax.set_ylim(-0.9, 1.75)
ax.axis("off")
ax.set_title("Jour après jour : le foyer du Médoc suit la rotation du vent (flèches = directions, nord en haut)",
             color="#fff")
fig.tight_layout(); fig.savefig(OUT / "vent_vs_propagation.png", dpi=110); plt.close(fig)

# 3. cycle diurne : vent et feu par heure de la journée
h_wind = {}
for ts, s, dr in wind:
    h_wind.setdefault(datetime.fromtimestamp(ts, timezone.utc).hour, []).append(s)
h_fire = {}
for p in passes:
    h_fire.setdefault(datetime.fromtimestamp(p["ts"], timezone.utc).hour, []).append(p["frp"])
fig, ax = plt.subplots(figsize=(9, 4.8))
hh = list(range(24))
loc = [(h + 2) % 24 for h in hh]
wv = [np.mean(h_wind.get(h, [np.nan])) for h in hh]
order = np.argsort(loc)
ax.plot(np.array(loc)[order], np.array(wv)[order], "o-", color="#4f8dff", label="vent moyen (km/h)")
ax2 = ax.twinx()
fv = [np.mean(h_fire[h]) / 1000 if h in h_fire else np.nan for h in hh]
ax2.plot(np.array(loc)[order], np.array(fv)[order], "s", color="#ff7a30", ms=8,
         label="feu moyen au passage satellite (GW)")
ax2.tick_params(colors="#ff7a30")
ax.set_xlabel("Heure de la journée (heure de Paris)")
ax.set_ylabel("Vent (km/h)", color="#4f8dff")
ax2.set_ylabel("Feu (GW)", color="#ff7a30")
ax.set_title("Le cycle quotidien : brise d'après-midi, feu d'après-midi", color="#fff")
fig.tight_layout(); fig.savefig(OUT / "cycle_diurne.png", dpi=110); plt.close(fig)

# stats
by_day = {}
for d in days:
    sel = [p for p in passes if date.fromtimestamp(p["ts"]) == d]
    by_day[str(d)] = {
        "frp_total_gw": round(sum(p["frp"] for p in sel) / 1000, 1),
        "vent_moyen_kmh": round(float(np.mean([s for s, _ in wind_day.get(d, [(np.nan, 0)])])), 1),
        "vent_max_kmh": round(float(np.max([s for s, _ in wind_day.get(d, [(np.nan, 0)])])), 1),
        "vent_direction_moyenne_deg": round(float(np.mean([dr for _, dr in wind_day.get(d, [(0, np.nan)])]))),
    }
stats = {"genere_le_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
         "par_jour": by_day}
(OUT / "stats.json").write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(stats, ensure_ascii=False, indent=2))
