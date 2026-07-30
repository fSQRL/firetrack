#!/usr/bin/env python3
"""Analyse spatiale : les interventions aériennes ont-elles couvert les foyers
proportionnellement à leur intensité ?

Produit graphiques + stats dans frontend/public/analyse/.
Méthode (voir skill firetrack-open-data pour les pièges) :
  - grille de ~5 km sur la zone Gironde/Landes (lat 43.4-45.6, lon -1.6-0.2)
  - intensité feu par cellule = somme des puissances radiatives (FRP, MW) détectées
  - intervention par cellule = points de trajectoire "en action" (< 400 ft, > 60 kt, en vol),
    hors abords de l'aéroport de Mérignac (trafic de piste) et hors lacs (écopage compté à part)
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
OUT = ROOT / "frontend" / "public" / "analyse" / "zones"
OUT.mkdir(parents=True, exist_ok=True)
db = sqlite3.connect(ROOT / "data" / "canadair.db")

LAT0, LAT1, LON0, LON1 = 43.4, 45.6, -1.6, 0.2
CELL = 0.05  # ~5.5 km en latitude
KM_LAT, KM_LON = 111.0, 78.0  # km par degré à cette latitude

AIRPORTS = [("Mérignac (aéroport)", 44.828, -0.715, 4.5), ("Cazaux (base)", 44.533, -1.125, 3.0)]
LAKES = [("Lac d'Hourtin-Carcans", 45.13, -1.07, 5.5), ("Lac de Lacanau", 44.98, -1.135, 3.5),
         ("Lac de Cazaux-Sanguinet", 44.50, -1.13, 5.5), ("Lac de Biscarrosse-Parentis", 44.35, -1.17, 4.5)]
TOWNS = [("Saumos", 44.845, -0.925), ("Lacanau", 44.98, -1.08), ("Hourtin", 45.19, -1.06),
         ("Carcans", 45.08, -1.05), ("Le Porge", 44.87, -1.09), ("Andernos", 44.74, -1.10),
         ("Marcheprime", 44.69, -0.85), ("Cestas", 44.74, -0.68), ("St-Médard", 44.90, -0.72),
         ("Ste-Hélène", 44.96, -0.88), ("Salaunes", 44.84, -0.84), ("Biscarrosse", 44.39, -1.16),
         ("Sanguinet", 44.48, -1.07), ("Parentis", 44.35, -1.07), ("Ychoux", 44.33, -0.95)]


def km(lat_a, lon_a, lat_b, lon_b):
    return ((lat_a - lat_b) * KM_LAT) ** 2 + ((lon_a - lon_b) * KM_LON) ** 2


def near(lat, lon, places):
    return any(km(lat, lon, la, lo) < r * r for _, la, lo, r in places)


def town_of(lat, lon):
    name, best = None, 1e9
    for n, la, lo in TOWNS:
        d = km(lat, lon, la, lo)
        if d < best:
            name, best = n, d
    return name if best < 12 * 12 else "zone isolée"


# ---- feux (détections réelles uniquement, dans la zone) ----
fires = db.execute("""SELECT ts, lat, lon, COALESCE(frp, 5) FROM fires
    WHERE lat BETWEEN ? AND ? AND lon BETWEEN ? AND ?""", (LAT0, LAT1, LON0, LON1)).fetchall()

# ---- points "en action" (largage/écopage) ----
# Seuil à 1000 ft (et non 400) : la couverture des récepteurs sous 400 ft est très
# inégale entre le nord et le sud de la zone, ce qui biaiserait la comparaison.
action = db.execute("""SELECT p.ts, p.lat, p.lon, a.name FROM positions p JOIN aircraft a USING (hex)
    WHERE p.lat BETWEEN ? AND ? AND p.lon BETWEEN ? AND ?
      AND p.alt_ft < 1000 AND p.on_ground = 0 AND p.gs_kt > 60""", (LAT0, LAT1, LON0, LON1)).fetchall()

drops = [(ts, la, lo, n) for ts, la, lo, n in action if not near(la, lo, AIRPORTS) and not near(la, lo, [l for l in LAKES])]
scoops = [(ts, la, lo, n) for ts, la, lo, n in action if near(la, lo, [l for l in LAKES])]

# ---- grilles ----
nlat, nlon = int((LAT1 - LAT0) / CELL), int((LON1 - LON0) / CELL)
g_fire = np.zeros((nlat, nlon))
g_drop = np.zeros((nlat, nlon))
for ts, la, lo, frp in fires:
    g_fire[min(int((la - LAT0) / CELL), nlat - 1), min(int((lo - LON0) / CELL), nlon - 1)] += frp
for ts, la, lo, n in drops:
    g_drop[min(int((la - LAT0) / CELL), nlat - 1), min(int((lo - LON0) / CELL), nlon - 1)] += 1

# ---- corrélation sur les cellules actives ----
mask = (g_fire > 0) | (g_drop > 0)
f, d = g_fire[mask], g_drop[mask]
r_all = np.corrcoef(np.log1p(f), np.log1p(d))[0, 1]
fire_cells = g_fire > 50  # cellules avec un feu significatif
covered = float((g_drop[fire_cells] > 0).mean()) if fire_cells.any() else 0.0

# ---- zones nommées : part du feu vs part des largages ----
zone_fire, zone_drop = {}, {}
for i in range(nlat):
    for j in range(nlon):
        if g_fire[i, j] == 0 and g_drop[i, j] == 0:
            continue
        t = town_of(LAT0 + (i + 0.5) * CELL, LON0 + (j + 0.5) * CELL)
        zone_fire[t] = zone_fire.get(t, 0) + g_fire[i, j]
        zone_drop[t] = zone_drop.get(t, 0) + g_drop[i, j]
tot_f, tot_d = sum(zone_fire.values()), sum(zone_drop.values())
zones = []
for t in set(zone_fire) | set(zone_drop):
    pf = 100 * zone_fire.get(t, 0) / tot_f
    pd = 100 * zone_drop.get(t, 0) / tot_d
    if pf > 1 or pd > 1:
        zones.append({"zone": t, "part_feu_pct": round(pf, 1), "part_largages_pct": round(pd, 1),
                      "indice_couverture": round(pd / pf, 2) if pf > 0.2 else None})
zones.sort(key=lambda z: -z["part_feu_pct"])

# ---- évolution quotidienne nord (Médoc/Saumos) vs sud (Biscarrosse) ----
SPLIT = 44.62
days = sorted({datetime.fromtimestamp(ts, timezone.utc).strftime("%d/%m") for ts, *_ in fires})
def daily(rows, north):
    out = {}
    for ts, la, lo, *_ in rows:
        if (la > SPLIT) != north:
            continue
        d = datetime.fromtimestamp(ts, timezone.utc).strftime("%d/%m")
        out[d] = out.get(d, 0) + (rows is fires and _[0] or 1)  # frp pour feux, 1 pour action
    return [out.get(d, 0) for d in days]
fire_n, fire_s = daily(fires, True), daily(fires, False)
drop_n, drop_s = daily(drops, True), daily(drops, False)

# ================= GRAPHIQUES =================
plt.rcParams.update({"figure.facecolor": "#14181f", "axes.facecolor": "#1a1f27",
                     "axes.edgecolor": "#39414d", "text.color": "#e8ecf2",
                     "axes.labelcolor": "#e8ecf2", "xtick.color": "#aeb8c4",
                     "ytick.color": "#aeb8c4", "font.size": 11})

# 1. carte feux vs largages
fig, ax = plt.subplots(figsize=(9, 11))
ys, xs = np.nonzero(g_drop)
ax.scatter(LON0 + (xs + .5) * CELL, LAT0 + (ys + .5) * CELL, s=np.clip(g_drop[ys, xs] * 0.6, 6, 350),
           c="#28c8d8", alpha=.5, marker="s", label="Largages (taille = nb de passages bas)")
ys, xs = np.nonzero(g_fire)
ax.scatter(LON0 + (xs + .5) * CELL, LAT0 + (ys + .5) * CELL, s=np.clip(g_fire[ys, xs] / 6, 8, 420),
           c="#ff7a30", alpha=.8, edgecolors="#a03000", linewidths=.5,
           label="Foyers détectés (taille = intensité FRP)")
for n, la, lo, r in LAKES:
    ax.add_patch(plt.Circle((lo, la), r / KM_LON, color="#4f8dff", alpha=.15))
    ax.annotate(n.replace("Lac d", "L. d").replace("Lac de ", "L. "), (lo, la), color="#7fa8e0",
                fontsize=8, ha="center")
for n, la, lo in TOWNS:
    ax.plot(lo, la, ".", color="#93a0ae", ms=3)
    ax.annotate(n, (lo, la), xytext=(3, 3), textcoords="offset points", fontsize=8, color="#cdd5de")
ax.set_xlim(-1.45, -0.4); ax.set_ylim(44.2, 45.35)
ax.set_title("Où ça brûlait vs où les avions sont intervenus (22-29 juillet)", color="#fff", pad=12)
ax.legend(loc="lower left", facecolor="#1a1f27", edgecolor="#39414d", labelcolor="#e8ecf2")
ax.set_aspect(KM_LAT / KM_LON)
fig.tight_layout(); fig.savefig(OUT / "carte_feux_vs_largages.png", dpi=110); plt.close(fig)

# 2. corrélation cellule par cellule
fig, ax = plt.subplots(figsize=(8, 6))
sel = mask
ax.scatter(np.log1p(g_fire[sel]), np.log1p(g_drop[sel]), s=14, c="#ffb020", alpha=.6)
ax.set_xlabel("Intensité du feu dans la cellule (log FRP)")
ax.set_ylabel("Passages de largage (log nombre)")
ax.set_title(f"Chaque point = une cellule de ~5 km : corrélation r = {r_all:.2f}", color="#fff")
fig.tight_layout(); fig.savefig(OUT / "correlation_cellules.png", dpi=110); plt.close(fig)

# 3. évolution quotidienne nord/sud
fig, axes = plt.subplots(2, 1, figsize=(9, 7), sharex=True)
for ax, fi, dr, title in [(axes[0], fire_n, drop_n, "Feu nord (Médoc : Saumos, Lacanau...)"),
                          (axes[1], fire_s, drop_s, "Feu sud (Biscarrosse, Sanguinet...)")]:
    x = np.arange(len(days))
    ax.bar(x - .2, np.array(fi) / max(max(fire_n + fire_s), 1), .4, color="#ff7a30", label="Intensité feu (normalisée)")
    ax.bar(x + .2, np.array(dr) / max(max(drop_n + drop_s), 1), .4, color="#28c8d8", label="Largages (normalisés)")
    ax.set_title(title, color="#fff", fontsize=11)
    ax.set_xticks(x); ax.set_xticklabels(days)
axes[0].legend(facecolor="#1a1f27", edgecolor="#39414d", labelcolor="#e8ecf2")
fig.suptitle("Jour par jour : le feu (orange) et la réponse aérienne (bleu)", color="#fff")
fig.tight_layout(); fig.savefig(OUT / "evolution_quotidienne.png", dpi=110); plt.close(fig)

# 4. top zones : part du feu vs part des largages
top = [z for z in zones if z["part_feu_pct"] > 1][:10]
fig, ax = plt.subplots(figsize=(9, 6))
x = np.arange(len(top))
ax.bar(x - .2, [z["part_feu_pct"] for z in top], .4, color="#ff7a30", label="Part du feu total (%)")
ax.bar(x + .2, [z["part_largages_pct"] for z in top], .4, color="#28c8d8", label="Part des largages (%)")
ax.set_xticks(x); ax.set_xticklabels([z["zone"] for z in top], rotation=30, ha="right")
ax.set_title("Par secteur : ce qui a brûlé vs ce qui a été arrosé", color="#fff")
ax.legend(facecolor="#1a1f27", edgecolor="#39414d", labelcolor="#e8ecf2")
fig.tight_layout(); fig.savefig(OUT / "zones_feu_vs_largages.png", dpi=110); plt.close(fig)

# 5. écopage par lac
lake_counts = {}
for ts, la, lo, n in scoops:
    for ln, lla, llo, r in LAKES:
        if km(la, lo, lla, llo) < r * r:
            lake_counts[ln] = lake_counts.get(ln, 0) + 1
            break
fig, ax = plt.subplots(figsize=(8, 4.5))
names = sorted(lake_counts, key=lake_counts.get)
ax.barh(names, [lake_counts[n] for n in names], color="#4f8dff")
ax.set_title("Points de passage bas au-dessus des lacs (écopages)", color="#fff")
fig.tight_layout(); fig.savefig(OUT / "ecopage_lacs.png", dpi=110); plt.close(fig)

stats = {
    "genere_le_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    "correlation_log_feu_largages": round(float(r_all), 2),
    "cellules_feu_significatif": int(fire_cells.sum()),
    "part_cellules_feu_couvertes_pct": round(covered * 100, 1),
    "nb_detections_feu": len(fires),
    "nb_points_largage": len(drops),
    "nb_points_ecopage": len(scoops),
    "ecopages_par_lac": lake_counts,
    "zones": zones,
}
(OUT / "stats.json").write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(stats, ensure_ascii=False, indent=2))
