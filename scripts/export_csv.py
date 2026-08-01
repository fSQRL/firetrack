#!/usr/bin/env python3
"""Exporte toutes les données de l'application en CSV lisibles, dans open-data/.

Fichiers produits :
  - appareils.csv                     la flotte suivie (hex, immatriculation, nom, type, photo)
  - positions_YYYY-MM-DD.csv          les trajectoires, un fichier par jour (UTC)
  - feux.csv                          les détections satellites de feu (NASA FIRMS)
  - vent.csv                          le vent horaire au centre de la zone (Open-Meteo)
  - qualite_air.csv                   l'indice européen de qualité de l'air (grille CAMS)
  - jours_ingeres.csv                 la provenance des archives de trajectoires

Relancer simplement :  python scripts/export_csv.py
"""
import csv
import gzip
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "canadair.db"
OUT = ROOT / "open-data"


def iso(ts):
    return datetime.fromtimestamp(ts, timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def write(name, header, rows):
    """CSV simple, ou CSV gzippé si le nom finit en .gz (gros volumes : positions)."""
    path = OUT / name
    opener = (lambda: gzip.open(path, "wt", newline="", encoding="utf-8")) if name.endswith(".gz") \
        else (lambda: open(path, "w", newline="", encoding="utf-8"))
    with opener() as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)
    print(f"  {name} : {path.stat().st_size / 1e6:.2f} Mo")


def main():
    OUT.mkdir(exist_ok=True)
    db = sqlite3.connect(DB_PATH)

    write("appareils.csv",
          ["hex_icao", "immatriculation", "nom", "type_appareil", "photo_url", "photo_page", "photo_credit"],
          db.execute("SELECT hex, registration, name, type, photo_src, photo_link, photo_credit"
                     " FROM aircraft ORDER BY name"))

    # positions : un fichier par jour UTC (fichiers volumineux sinon)
    days = [r[0] for r in db.execute("SELECT DISTINCT date(ts,'unixepoch') FROM positions ORDER BY 1")]
    for day in days:
        rows = db.execute("""
            SELECT p.hex, a.registration, a.name, p.ts, p.lat, p.lon,
                   p.alt_ft, p.on_ground, p.gs_kt, p.track_deg
            FROM positions p LEFT JOIN aircraft a ON a.hex = p.hex
            WHERE date(p.ts,'unixepoch') = ? ORDER BY p.ts""", (day,))
        write(f"positions_{day}.csv.gz",
              ["hex_icao", "immatriculation", "nom", "horodatage_utc", "latitude", "longitude",
               "altitude_pieds", "au_sol", "vitesse_sol_noeuds", "cap_degres"],
              ([h, r, n, iso(ts), la, lo, alt, g, gs, trk] for h, r, n, ts, la, lo, alt, g, gs, trk in rows))

    write("feux.csv",
          ["horodatage_detection_utc", "latitude", "longitude", "puissance_frp_megawatts", "satellite", "jour_nuit"],
          ([iso(ts), la, lo, frp, sat, dn] for ts, la, lo, frp, sat, dn in
           db.execute("SELECT ts, lat, lon, frp, satellite, daynight FROM fires ORDER BY ts")))

    write("vent.csv",
          ["horodatage_utc", "vitesse_vent_kmh", "direction_origine_vent_degres"],
          ([iso(ts), s, d] for ts, s, d in
           db.execute("SELECT ts, speed_kmh, dir_deg FROM wind ORDER BY ts")))

    write("qualite_air.csv",
          ["horodatage_utc", "latitude", "longitude", "indice_qualite_air_europeen"],
          ([iso(ts), la, lo, aqi] for ts, la, lo, aqi in
           db.execute("SELECT ts, lat, lon, aqi FROM air ORDER BY ts, lat, lon")))

    write("jours_ingeres.csv",
          ["jour", "archive_source", "ingere_le_utc", "nombre_points"],
          db.execute("SELECT day, tag, ingested_at, positions FROM ingested_days ORDER BY day"))

    print("Export terminé dans", OUT)


if __name__ == "__main__":
    main()
