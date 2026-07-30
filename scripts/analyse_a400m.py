#!/usr/bin/env python3
"""Analyse comparée A400M / Canadair / Dash 8 : deux doctrines de largage.

Réutilise la méthode "norias" (passages bas hors lacs/aéroports = largages) et ajoute :
  - volumes estimés par capacité constructeur (ordres de grandeur assumés)
  - profils d'altitude et de vitesse au moment du largage
  - chronologie quotidienne par type
Produit graphiques + stats dans frontend/public/analyse/a400m/.
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
OUT = ROOT / "frontend" / "public" / "analyse" / "a400m"
OUT.mkdir(parents=True, exist_ok=True)
db = sqlite3.connect(ROOT / "data" / "canadair.db")

LAT0, LAT1, LON0, LON1 = 43.4, 45.6, -1.6, 0.2
KM_LAT, KM_LON = 111.0, 78.0
AIRPORTS = [(44.828, -0.715, 4.5), (44.533, -1.125, 3.0)]
LAKES = [(45.13, -1.07, 5.5), (44.98, -1.135, 3.5), (44.50, -1.13, 5.5), (44.35, -1.17, 4.5)]

# capacités constructeur (litres par largage) : ordres de grandeur assumés
CAPACITY = {"A400": 20000, "DASH8": 10000, "CL-415": 6000}
LABEL = {"A400": "A400M (retardant)", "DASH8": "Dash 8 Milan (retardant)", "CL-415": "Canadair (eau)"}
COLOR = {"A400": "#4f8dff", "DASH8": "#ffb020", "CL-415": "#ff5d47"}


def near_any(lat, lon, places):
    return any(((lat - la) * KM_LAT) ** 2 + ((lon - lo) * KM_LON) ** 2 < r * r for la, lo, r in places)


rows = db.execute("""SELECT a.type, a.name, p.ts, p.lat, p.lon, p.alt_ft, p.gs_kt
    FROM positions p JOIN aircraft a USING (hex)
    WHERE a.type IN ('A400','DASH8','CL-415')
      AND p.lat BETWEEN ? AND ? AND p.lon BETWEEN ? AND ?
      AND p.alt_ft < 500 AND p.on_ground = 0 AND p.gs_kt > 60
    ORDER BY a.name, p.ts""", (LAT0, LAT1, LON0, LON1)).fetchall()

# groupes -> largages (avec alt/vitesse minimales du passage)
events = []
cur = None
for typ, name, ts, lat, lon, alt, gs in rows:
    if cur and cur["name"] == name and ts - cur["end"] < 120:
        cur["end"] = ts
        cur["pts"].append((lat, lon, alt, gs))
        continue
    if cur:
        events.append(cur)
    cur = {"typ": typ, "name": name, "start": ts, "end": ts, "pts": [(lat, lon, alt, gs)]}
if cur:
    events.append(cur)

drops = []
for e in events:
    la = float(np.mean([p[0] for p in e["pts"]]))
    lo = float(np.mean([p[1] for p in e["pts"]]))
    if near_any(la, lo, AIRPORTS) or near_any(la, lo, LAKES):
        continue
    alts = [p[2] for p in e["pts"] if p[2] is not None]
    gss = [p[3] for p in e["pts"] if p[3] is not None]
    drops.append({"typ": e["typ"], "name": e["name"], "ts": e["start"],
                  "alt_min": min(alts) if alts else None, "gs": float(np.median(gss)) if gss else None})

days = sorted({datetime.fromtimestamp(d["ts"], timezone.utc).strftime("%d/%m") for d in drops})

# stats par type. Piège : les porteurs de retardant font plusieurs PASSES dans une même
# mission (l'A400M largue ses 20 t en plusieurs racetracks). On regroupe donc les passes
# distantes de < 25 min en "sorties" : le volume est compté par sortie, pas par passe.
# Le Canadair, lui, ré-écope entre chaque passe : chaque passe = un plein de 6 000 L.
def sorties_of(tss, gap=25 * 60):
    tss = sorted(tss)
    n = 1 if tss else 0
    starts = tss[:1]
    for a, b in zip(tss, tss[1:]):
        if b - a > gap:
            n += 1
            starts.append(b)
    return n, starts

per_type = {}
pleins_ts = {}
for t in CAPACITY:
    dd = [d for d in drops if d["typ"] == t]
    by_name = {}
    for d in dd:
        by_name.setdefault(d["name"], []).append(d["ts"])
    cycles, sorties, sortie_starts = [], 0, []
    cap_s = 240 * 60 if t == "A400" else 90 * 60
    for tss in by_name.values():
        n, starts = sorties_of(tss)
        sorties += n
        sortie_starts += starts
        if t == "CL-415":  # le Canadair ré-écope entre chaque passe : cycle = passe à passe
            cycles += [b - a for a, b in zip(sorted(tss), sorted(tss)[1:]) if 180 <= b - a <= 90 * 60]
        else:  # retardant : cycle = sortie à sortie (recharge en base entre les deux)
            cycles += [b - a for a, b in zip(sorted(starts), sorted(starts)[1:]) if 600 <= b - a <= cap_s]
    unit = len(dd) if t == "CL-415" else sorties  # pleins largués
    pleins_ts.setdefault(t, [d["ts"] for d in dd] if t == "CL-415" else sortie_starts)
    active_days = len({datetime.fromtimestamp(d["ts"], timezone.utc).date() for d in dd})
    per_type[t] = {
        "passes_de_largage": len(dd),
        "sorties": sorties,
        "appareils": len(by_name),
        "jours_actifs": active_days,
        "cycle_median_min": round(float(np.median(cycles)) / 60, 1) if cycles else None,
        "pleins_largues": unit,
        "volume_estime_m3": round(unit * CAPACITY[t] / 1000),
        "volume_par_jour_actif_m3": round(unit * CAPACITY[t] / 1000 / max(active_days, 1)),
        "alt_largage_mediane_ft": round(float(np.median([d["alt_min"] for d in dd if d["alt_min"] is not None]))),
        "vitesse_mediane_kt": round(float(np.median([d["gs"] for d in dd if d["gs"] is not None]))),
    }

plt.rcParams.update({"figure.facecolor": "#14181f", "axes.facecolor": "#1a1f27",
                     "axes.edgecolor": "#39414d", "text.color": "#e8ecf2",
                     "axes.labelcolor": "#e8ecf2", "xtick.color": "#aeb8c4",
                     "ytick.color": "#aeb8c4", "font.size": 11})

# 1. chronologie quotidienne des volumes estimés
fig, ax = plt.subplots(figsize=(9, 5.5))
x = np.arange(len(days))
bottom = np.zeros(len(days))
for t in ["CL-415", "DASH8", "A400"]:
    vols = []
    for day in days:
        n = sum(1 for ts in pleins_ts.get(t, []) if
                datetime.fromtimestamp(ts, timezone.utc).strftime("%d/%m") == day)
        vols.append(n * CAPACITY[t] / 1000)
    ax.bar(x, vols, bottom=bottom, color=COLOR[t], label=LABEL[t])
    bottom += np.array(vols)
ax.set_xticks(x); ax.set_xticklabels(days)
ax.set_ylabel("Volume largué estimé (m³)")
ax.set_title("Qui a versé quoi, jour par jour", color="#fff")
ax.legend(facecolor="#1a1f27", edgecolor="#39414d", labelcolor="#e8ecf2")
fig.tight_layout(); fig.savefig(OUT / "volumes_par_jour.png", dpi=110); plt.close(fig)

# 2. le compromis cadence / volume
fig, ax = plt.subplots(figsize=(8.5, 6))
for t, s in per_type.items():
    if not s["cycle_median_min"]:
        continue
    ax.scatter(s["cycle_median_min"], CAPACITY[t] / 1000, s=s["pleins_largues"] * 3.5,
               c=COLOR[t], alpha=.85, edgecolors="#fff", linewidths=.6)
    ax.annotate(f'{LABEL[t]}\n{s["pleins_largues"]} pleins largués', (s["cycle_median_min"], CAPACITY[t] / 1000),
                xytext=(12, 6), textcoords="offset points", fontsize=10, color="#e8ecf2")
ax.set_xlabel("Rotation médiane (minutes entre deux pleins largués)")
ax.set_ylabel("Volume par plein (m³)")
ax.set_xscale("log")
ax.set_xlim(4, 400); ax.set_ylim(0, 23)
ax.set_xticks([5, 10, 30, 60, 120, 240])
ax.set_xticklabels(["5", "10", "30", "60", "120", "240"])
ax.set_title("Le compromis : larguer souvent, ou larguer gros (taille = nb de largages)", color="#fff")
fig.tight_layout(); fig.savefig(OUT / "cadence_vs_volume.png", dpi=110); plt.close(fig)

# 3. profil du largage : altitude et vitesse
fig, axes = plt.subplots(1, 2, figsize=(9.5, 4.6))
data_alt = [[d["alt_min"] for d in drops if d["typ"] == t and d["alt_min"] is not None] for t in CAPACITY]
data_gs = [[d["gs"] for d in drops if d["typ"] == t and d["gs"] is not None] for t in CAPACITY]
for ax_, data, lab in [(axes[0], data_alt, "Altitude minimale au largage (pieds)"),
                       (axes[1], data_gs, "Vitesse au largage (nœuds)")]:
    bp = ax_.boxplot(data, tick_labels=["A400M", "Dash 8", "Canadair"], patch_artist=True, showfliers=False)
    for patch, t in zip(bp["boxes"], CAPACITY):
        patch.set_facecolor(COLOR[t]); patch.set_alpha(.8)
    for el in ("medians",):
        plt.setp(bp[el], color="#14181f")
    for el in ("whiskers", "caps"):
        plt.setp(bp[el], color="#93a0ae")
    ax_.set_title(lab, fontsize=11, color="#fff")
fig.suptitle("La signature du geste : comment chacun largue", color="#fff")
fig.tight_layout(); fig.savefig(OUT / "profil_largage.png", dpi=110); plt.close(fig)

# 4. cumul des volumes estimés
fig, ax = plt.subplots(figsize=(9, 5))
for t in ["CL-415", "DASH8", "A400"]:
    cum, tot = [], 0
    for day in days:
        n = sum(1 for ts in pleins_ts.get(t, []) if
                datetime.fromtimestamp(ts, timezone.utc).strftime("%d/%m") == day)
        tot += n * CAPACITY[t] / 1000
        cum.append(tot)
    ax.plot(days, cum, "o-", color=COLOR[t], label=LABEL[t], lw=2.2)
ax.set_ylabel("Volume cumulé estimé (m³)")
ax.set_title("La course au volume sur l'épisode", color="#fff")
ax.legend(facecolor="#1a1f27", edgecolor="#39414d", labelcolor="#e8ecf2")
fig.tight_layout(); fig.savefig(OUT / "volumes_cumules.png", dpi=110); plt.close(fig)

stats = {
    "genere_le_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    "capacites_assumees_litres": CAPACITY,
    "par_type": per_type,
}
(OUT / "stats.json").write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(stats, ensure_ascii=False, indent=2))
