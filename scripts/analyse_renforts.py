#!/usr/bin/env python3
"""La montée en puissance des renforts : qui est arrivé quand, et qui a fait quoi.

Trois cercles : moyens nationaux (Sécurité civile + armées françaises), flotte louée pour
la saison (Australie, Espagne, Afrique du Sud), renforts d'États européens (RescEU et
accords bilatéraux : Slovaquie, Suède, Allemagne, Luxembourg, Pologne).
Produit graphiques + stats dans frontend/public/analyse/renforts/.
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
OUT = ROOT / "frontend" / "public" / "analyse" / "renforts"
OUT.mkdir(parents=True, exist_ok=True)
db = sqlite3.connect(ROOT / "data" / "canadair.db")

LAT0, LAT1, LON0, LON1 = 43.4, 45.6, -1.6, 0.2
KM_LAT, KM_LON = 111.0, 78.0
AIRPORTS = [(44.828, -0.715, 4.5), (44.533, -1.125, 3.0)]
LAKES = [(45.13, -1.07, 5.5), (44.98, -1.135, 3.5), (44.50, -1.13, 5.5), (44.35, -1.17, 4.5)]

COUNTRY = {  # hex -> (pays, catégorie)
    **{h: ("France", "national") for h in
       ["3b7b6f", "3b7b6e", "3b7b6d", "3b7b6c", "3b7b76", "3b7b75", "3b7b74", "3b7b73",
        "3b7b72", "3b7b71", "3b7b70", "3b7b6b", "3b7b3f", "3b7b3e", "3b7b3d", "3b7b3a",
        "3b7b39", "3b7b3c", "3b7b3b", "3b7b38", "3b7b37", "3b7b40", "3b7b41", "3b7b43",
        "009343"] + [f"3b77{x:02x}" for x in range(0x5a, 0x6f)]},
    **{h: ("Australie", "loué") for h in ["7caeb4", "7c49bc", "7cad89", "7c4753"]},
    "3464d9": ("Espagne", "loué"), "348650": ("Espagne", "loué"),
    "00a113": ("Afrique du Sud", "loué"),
    "505d0b": ("Slovaquie", "renfort UE"), "505847": ("Slovaquie", "renfort UE"),
    "4ab50f": ("Suède", "renfort UE"), "4ab50e": ("Suède", "renfort UE"),
    "3e9555": ("Allemagne", "renfort UE"), "3f62f6": ("Allemagne", "renfort UE"),
    "4d0123": ("Luxembourg", "renfort UE"), "4d0129": ("Luxembourg", "renfort UE"),
    "48d691": ("Pologne", "renfort UE"), "48ea09": ("Pologne", "renfort UE"),
}
FLAG = {"France": "FR", "Australie": "AU", "Espagne": "ES", "Afrique du Sud": "ZA",
        "Slovaquie": "SK", "Suède": "SE", "Allemagne": "DE", "Luxembourg": "LU", "Pologne": "PL"}
CAT_COLOR = {"national": "#4f8dff", "loué": "#3ecf5b", "renfort UE": "#ffb020"}
COUNTRY_COLOR = {"France": "#4f8dff", "Australie": "#3ecf5b", "Espagne": "#e0b400",
                 "Afrique du Sud": "#2fb886", "Slovaquie": "#ff5d47", "Suède": "#59c1e8",
                 "Allemagne": "#c9a34e", "Luxembourg": "#8fd0ff", "Pologne": "#ff8b8b"}


def near_any(lat, lon, places):
    return any(((lat - la) * KM_LAT) ** 2 + ((lon - lo) * KM_LON) ** 2 < r * r for la, lo, r in places)


rows = db.execute("""SELECT p.hex, a.name, p.ts, p.lat, p.lon, p.alt_ft, p.gs_kt, p.on_ground
    FROM positions p JOIN aircraft a USING (hex)
    WHERE p.lat BETWEEN ? AND ? AND p.lon BETWEEN ? AND ?
    ORDER BY p.ts""", (LAT0, LAT1, LON0, LON1)).fetchall()

DAYS = [date(2026, 7, d) for d in range(22, 30)]
presence = {}   # (hex, name) -> set(day)
drops_day = {}  # (day, pays, cat) -> nb de points en action
for hex_, name, ts, la, lo, alt, gs, gnd in rows:
    if hex_ not in COUNTRY:
        continue
    d = date.fromtimestamp(ts)
    if d not in DAYS:
        continue
    presence.setdefault((hex_, name), set()).add(d)
    if (alt is not None and alt < 1000 and not gnd and (gs or 0) > 60
            and not near_any(la, lo, AIRPORTS) and not near_any(la, lo, LAKES)):
        pays, cat = COUNTRY[hex_]
        drops_day[(d, pays, cat)] = drops_day.get((d, pays, cat), 0) + 1

plt.rcParams.update({"figure.facecolor": "#14181f", "axes.facecolor": "#1a1f27",
                     "axes.edgecolor": "#39414d", "text.color": "#e8ecf2",
                     "axes.labelcolor": "#e8ecf2", "xtick.color": "#aeb8c4",
                     "ytick.color": "#aeb8c4", "font.size": 10.5})

# 1. frise des arrivées : chaque appareil étranger, ses jours de présence en zone
foreign = sorted(((h, n) for h, n in presence if COUNTRY[h][0] != "France"),
                 key=lambda k: (min(presence[k]), COUNTRY[k[0]][0]))
fig, ax = plt.subplots(figsize=(9.5, 0.42 * len(foreign) + 1.6))
for y, (h, n) in enumerate(foreign):
    pays, cat = COUNTRY[h]
    days_present = sorted(presence[(h, n)])
    ax.barh(y, len(days_present) - 0.6 if len(days_present) > 1 else 0.5,
            left=DAYS.index(days_present[0]) - 0.2, height=0.62,
            color=COUNTRY_COLOR[pays], alpha=.9)
    ax.text(-0.45, y, f"{n}  ({FLAG[pays]})", ha="right", va="center", fontsize=9)
ax.set_yticks([])
ax.set_xticks(range(len(DAYS))); ax.set_xticklabels([d.strftime("%d/%m") for d in DAYS])
ax.set_xlim(-4.6, len(DAYS) - 0.4)
ax.invert_yaxis()
ax.set_title("L'arrivée des renforts : présence en zone, appareil par appareil", color="#fff")
fig.tight_layout(); fig.savefig(OUT / "frise_arrivees.png", dpi=110); plt.close(fig)

# 2. part quotidienne du travail par catégorie
fig, ax = plt.subplots(figsize=(9.5, 5.2))
x = np.arange(len(DAYS))
bottom = np.zeros(len(DAYS))
for cat in ["national", "loué", "renfort UE"]:
    tot = [sum(v for (d, p, c), v in drops_day.items() if d == day and c == cat) for day in DAYS]
    day_tot = [max(sum(v for (d, p, c), v in drops_day.items() if d == day), 1) for day in DAYS]
    share = [100 * a / b for a, b in zip(tot, day_tot)]
    ax.bar(x, share, bottom=bottom, color=CAT_COLOR[cat],
           label={"national": "Moyens français", "loué": "Flotte louée (AU/ES/ZA)",
                  "renfort UE": "Renforts d'États européens"}[cat])
    bottom += np.array(share)
ax.set_xticks(x); ax.set_xticklabels([d.strftime("%d/%m") for d in DAYS])
ax.set_ylabel("Part de l'activité de largage (%)")
ax.set_title("Qui a porté l'effort, jour après jour", color="#fff")
ax.legend(facecolor="#1a1f27", edgecolor="#39414d", labelcolor="#e8ecf2", loc="lower left")
fig.tight_layout(); fig.savefig(OUT / "part_quotidienne.png", dpi=110); plt.close(fig)

# 3. totaux par pays
tot_pays = {}
for (d, p, c), v in drops_day.items():
    tot_pays[p] = tot_pays.get(p, 0) + v
fig, ax = plt.subplots(figsize=(9, 4.8))
names = sorted(tot_pays, key=tot_pays.get)
ax.barh(names, [tot_pays[n] for n in names], color=[COUNTRY_COLOR[n] for n in names])
for i, n in enumerate(names):
    ax.text(tot_pays[n] + max(tot_pays.values()) * .01, i, str(tot_pays[n]),
            va="center", fontsize=9, color="#cdd5de")
ax.set_xlabel("Points de passage en action (largages) sur l'épisode")
ax.set_title("La contribution de chaque pavillon", color="#fff")
fig.tight_layout(); fig.savefig(OUT / "totaux_pays.png", dpi=110); plt.close(fig)

stats = {
    "genere_le_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    "arrivees": {n: str(min(presence[(h, n)])) for h, n in foreign},
    "activite_par_pays": tot_pays,
    "part_etrangere_par_jour_pct": {
        str(day): round(100 * sum(v for (d, p, c), v in drops_day.items() if d == day and p != "France")
                        / max(sum(v for (d, p, c), v in drops_day.items() if d == day), 1))
        for day in DAYS},
}
(OUT / "stats.json").write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(stats, ensure_ascii=False, indent=2))
