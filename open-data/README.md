# Open data : Fire Tracker (feux de Gironde et des Landes, juillet 2026)

Extraction CSV de toutes les données utilisées par https://firetrack.harari.ovh
Régénérer : `python scripts/export_csv.py` (depuis la racine du projet).

> 🤖 Pour analyser ces données avec Claude Code : un skill dédié existe :
> [`.claude/skills/firetrack-open-data/`](../.claude/skills/firetrack-open-data/SKILL.md)
> (dictionnaire, pièges UTC/prévision/zone, recettes SQL, licences).

## Fichiers

| Fichier | Contenu | Colonnes |
|---|---|---|
| `appareils.csv` | La flotte suivie | hex ICAO, immatriculation, nom affiché, type, photo (URL, page, crédit) |
| `positions_YYYY-MM-DD.csv.gz` | Trajectoires, un fichier par jour UTC (CSV gzippé : lisible tel quel par pandas, R, Excel après décompression) | hex, immat, nom, horodatage UTC, latitude, longitude, altitude (pieds), au sol (0/1), vitesse sol (nœuds), cap (degrés) |
| `feux.csv` | Détections satellites de feu | horodatage du passage satellite UTC, position, puissance radiative (MW), satellite, jour/nuit |
| `vent.csv` | Vent horaire au point 44.6N 1.0W | horodatage UTC, vitesse (km/h), direction d'origine (degrés) |
| `qualite_air.csv` | Indice européen de qualité de l'air, grille de 20 points | horodatage UTC, position, indice |
| `jours_ingeres.csv` | Traçabilité des archives de trajectoires | jour, archive source, date d'ingestion, nombre de points |

## Notes

- Horodatages en **UTC** (heure de Paris = UTC+2 en été).
- Les positions couvrent la zone Gironde/Landes élargie et les trajets complets des appareils
  suivis ; certaines traces incluent des vols hors zone (transits, autres missions).
- Les détections de feu ont la résolution du capteur (375 m VIIRS, 1 km MODIS) et n'existent
  qu'aux passages satellites ; les nuages peuvent masquer des foyers.
- Vent et qualité de l'air incluent ~24 h de **prévision** au-delà du dernier relevé observé.

## Sources et licences

- Trajectoires : © [adsb.lol](https://www.adsb.lol) contributors,
  [ODbL 1.0](https://opendatacommons.org/licenses/odbl/1-0/) : cette extraction est une base
  dérivée, elle-même partagée sous ODbL avec attribution.
- Feux : [NASA FIRMS](https://firms.modaps.eosdis.nasa.gov) (VIIRS/MODIS), domaine public avec
  mention "We acknowledge the use of data from NASA FIRMS".
- Vent et qualité de l'air : [Open-Meteo](https://open-meteo.com) (CC BY 4.0),
  modèle [Copernicus CAMS](https://atmosphere.copernicus.eu/) pour l'air.
- Photos : liens vers [planespotters.net](https://www.planespotters.net), © photographes crédités.
