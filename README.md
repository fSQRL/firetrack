# Canadairs en Gironde — suivi & animation

Page web animée des allers-retours des Canadairs de la Sécurité Civile, avec timeline pour
remonter dans le temps. Données ouvertes [adsb.lol](https://www.adsb.lol) (ODbL).
Voir [RECHERCHE_DONNEES.md](RECHERCHE_DONNEES.md) pour l'étude des sources.

## Backend (pipeline)

CLI Python **sans aucune dépendance** (stdlib uniquement), base **SQLite** (`data/canadair.db`).

```
python backend/cli.py fleet              # 1 fois : résout immatriculations -> codes hex (hexdb.io)
python backend/cli.py ingest             # ingère la journée d'hier (défaut)
python backend/cli.py ingest 2026-07-25  # ingère un jour précis
python backend/cli.py discover           # ajoute les moyens aériens détectés en vol autour du feu
python backend/cli.py fires              # points chauds NASA FIRMS d'hier (Gironde+Landes)
python backend/cli.py fires 2026-07-19 --days 7   # plage de dates (découpée par 5 j, limite API)
python backend/cli.py photos             # photos des appareils (planespotters.net, mises en cache)
python backend/cli.py export 2026-07-25  # écrit frontend/public/data/2026-07-25.json
python backend/cli.py status             # résumé de la base
```

`ingest` télécharge en streaming la release quotidienne adsb.lol (~4 Go parcourus, rien
d'écrit sur disque à part la base) et n'en garde que les traces de la flotte. Les données d'un
jour J sont publiées le lendemain (J+1). Options : `--force` (ré-ingérer), `--source` (variante
de release, défaut `prod-0`).

### Cron

```cron
# tous les jours à 06h00 : ingérer la veille (avions + feux) puis exporter
0 6 * * * cd /path/flight && python backend/cli.py ingest && python backend/cli.py fires && python backend/cli.py export $(date -d yesterday +\%F)
```

Sous Windows : Planificateur de tâches avec la même commande. Optionnel : définir
`GITHUB_TOKEN` pour éviter la limite de l'API GitHub anonyme (60 req/h — largement suffisant
pour 1 ingestion/jour).

## Flotte

Deux mécanismes complémentaires :

- **Statique** : [backend/fleet.json](backend/fleet.json) — CL-415 "Pélican", Dash 8 "Milan",
  avions de coordination (immats F-ZB..). Ajouter une ligne puis relancer `fleet`.
- **Dynamique** : `discover` interroge l'API live (airplanes.live) autour du feu et ajoute tout
  bombardier d'eau détecté (callsigns `PELICAN/MILAN/TRACT/DRAGON/CTM`, types `CL2T/AT8T/DH8D/
  A400/EC45`... sous 15 000 ft). Indispensable pour les avions loués sous immat étrangère
  (Air Tractor VH-..) et les hélicos. Pendant un épisode de feu, le lancer régulièrement :

```cron
*/10 * * * * cd /path/flight && python backend/cli.py discover
```

Les hex découverts un jour J sont récupérés en trace complète par l'`ingest` de J (publié à J+1).

## Feux (NASA FIRMS)

La commande `fires` interroge l'API [NASA FIRMS](https://firms.modaps.eosdis.nasa.gov/api/)
(points chauds satellites VIIRS, bbox Gironde+Landes). Clé gratuite à mettre dans
`backend/firms_key.txt` (ou variable d'env `FIRMS_MAP_KEY`). Limite : 5000 req/10 min,
plage max 10 jours par requête, archive dispo depuis 2012 (sources SP au-delà de ~2 mois).

## Attribution

Data © [adsb.lol](https://www.adsb.lol) contributors, licence
[ODbL 1.0](https://opendatacommons.org/licenses/odbl/1-0/).
