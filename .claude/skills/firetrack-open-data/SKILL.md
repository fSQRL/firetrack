---
name: firetrack-open-data
description: Manipuler, analyser ou vérifier les données Fire Tracker (feux de Gironde/Landes 2026) : CSV du dossier open-data/ ou base SQLite data/canadair.db. Utiliser dès qu'une question porte sur les trajectoires d'avions, les détections de feu, le vent, la qualité de l'air, les statistiques par appareil, ou la régénération/extension des exports.
---

# Données Fire Tracker

Deux accès aux mêmes données : les **CSV de `open-data/`** (lisibles, partage) et la
**base SQLite `data/canadair.db`** (requêtes lourdes : préférer SQL, la table `positions`
dépasse les 2 millions de lignes). Régénérer les CSV : `python scripts/export_csv.py`.

## Dictionnaire

| Fichier CSV | Table SQLite | Clé | Contenu |
|---|---|---|---|
| `appareils.csv` | `aircraft` | `hex_icao` | flotte suivie (96 appareils), photos |
| `positions_YYYY-MM-DD.csv.gz` (1/jour UTC, gzippé) | `positions` | `hex+horodatage` | trajectoires |
| `feux.csv` | `fires` | `ts+lat+lon+satellite` | détections satellites NASA FIRMS |
| `vent.csv` | `wind` | `ts` | vent horaire au point 44.6N/-1.0E |
| `qualite_air.csv` | `air` | `ts+lat+lon` | indice européen, grille 20 points |
| `jours_ingeres.csv` | `ingested_days` | `jour` | traçabilité des archives |

Colonnes positions : `hex_icao, immatriculation, nom, horodatage_utc (ISO ms),
latitude, longitude, altitude_pieds (vide si inconnue/au sol), au_sol (0/1),
vitesse_sol_noeuds, cap_degres`. En SQLite : `ts` = epoch Unix (secondes, REAL),
`alt_ft`, `on_ground`, `gs_kt`, `track_deg`, `flags` (bit 2 = nouveau segment de vol).

## Pièges à connaître (source d'erreurs classiques)

- **Tout est en UTC** ; heure de Paris = UTC+2 en été. Toujours le préciser dans un résultat.
- **`vent` et `qualite_air` contiennent ~24 h de PRÉVISION** au-delà du dernier relevé
  observé : pour des statistiques "réelles", tronquer à `MAX(ts)` de `positions` ou `fires`.
- Les trajectoires incluent des **vols hors zone** (transits, missions ailleurs : ex. A400M).
  Zone d'intérêt Gironde/Landes : `lat 43.4-45.6, lon -1.6-0.2`. Le site web applique ce
  filtre à l'export JSON ; les CSV/SQLite, non.
- Les **feux n'existent qu'aux passages satellites** (VIIRS ~01h30/13h30 locales,
  MODIS ~10h30/21h30, résolution 375 m/1 km) ; nuages = détections manquantes. Ne jamais
  interpréter une absence de détection comme une absence de feu.
- Points d'un même appareil espacés de ~1-30 s en vol ; un trou > 10 min = hors couverture
  ou au sol. Certains hex sont anonymes (`348650`, `009343`) : immatriculation inconnue.
- `satellite` dans feux : `N`=Suomi-NPP, `N20`/`N21`=NOAA-20/21, `T`/`A`=Terra/Aqua (MODIS).

## Recettes

Largages/écopages estimés (heuristique du site) : passages en vol < 400 ft à vitesse
> 60 kt, groupés à < 120 s, hors abords (< 180 s) d'un contact au sol :

```sql
-- points "en action" par appareil un jour donné (approximation simple)
SELECT a.name, COUNT(*) FROM positions p JOIN aircraft a USING (hex)
WHERE date(p.ts,'unixepoch')='2026-07-26' AND p.alt_ft<400 AND p.on_ground=0 AND p.gs_kt>60
GROUP BY 1 ORDER BY 2 DESC;
```

Activité quotidienne par appareil (heures de vol ≈ points × pas moyen) :

```sql
SELECT date(ts,'unixepoch') jour, a.name, COUNT(*) pts,
       time(MIN(ts),'unixepoch') debut_utc, time(MAX(ts),'unixepoch') fin_utc
FROM positions p JOIN aircraft a USING (hex)
WHERE p.lat BETWEEN 43.4 AND 45.6 AND p.lon BETWEEN -1.6 AND 0.2
GROUP BY 1,2 ORDER BY 1,3 DESC;
```

Corrélation feu/vent : joindre `fires` et `wind` sur l'heure
(`CAST(f.ts/3600 AS INT)*3600 = w.ts`). Distance approx. en km :
`111*(lat2-lat1)` et `78*(lon2-lon1)` (cos 44.6° ≈ 0.71).

## Étendre les données

- Nouvelles journées : le pipeline (`backend/cli.py`) alimente SQLite (voir README racine),
  puis `python scripts/export_csv.py` régénère les CSV.
- Ajouter un champ aux CSV : modifier `scripts/export_csv.py` (noms de colonnes en français
  lisible, horodatages ISO UTC) **et** documenter dans `open-data/README.md`.

## Publication de résultats

Toute réutilisation publique doit porter les attributions : trajectoires
© adsb.lol contributors (ODbL, les dérivés restent ODbL), feux "We acknowledge the use of
data from NASA FIRMS", météo/air Open-Meteo (CC BY 4.0) + Copernicus CAMS.
