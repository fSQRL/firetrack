# Canadairs en Gironde : suivi & animation

Page web animée des rotations des avions de lutte contre les incendies (Canadair, Dash,
Air Tractor, A400M...) en Gironde et dans les Landes, avec timeline multi-jours, feux
satellites, fumée simulée par le vent réel et vue satellite NASA.
Voir [RECHERCHE_DONNEES.md](RECHERCHE_DONNEES.md) pour l'étude des sources.

## Architecture : 100 % statique à la publication

```
[CLI backend (cron)] --> SQLite (data/canadair.db) --> JSON statiques (frontend/public/data/)
                                                            |
[Navigateur visiteur] <-- HTML/JS/CSS statiques (dist/) <---+
```

- **Aucun backend ne tourne pour servir le site.** SQLite n'est utilisé que par le CLI au
  moment de la récupération des données ; le site ne sert que des fichiers statiques
  (build Vite + JSON pré-générés).
- **Appels réseau du pipeline** (uniquement quand on lance les commandes) : GitHub/adsb.lol,
  NASA FIRMS, Open-Meteo, hexdb.io/adsbdb.com, planespotters.net, airplanes.live.
- **Appels réseau du navigateur visiteur** : tuiles OpenStreetMap, tuiles NASA GIBS (si la vue
  satellite est cochée), vignettes photos planespotters (hotlink). Aucune API à soi, aucune clé
  côté client.

## Backend (pipeline CLI)

Python **sans aucune dépendance** (stdlib uniquement), base SQLite.

```
python backend/cli.py fleet              # résout la flotte de fleet.json (hex ICAO)
python backend/cli.py ingest             # vols de la veille (défaut) depuis adsb.lol (~4 Go streamés)
python backend/cli.py ingest 2026-07-25  # un jour précis ; --force pour ré-ingérer
python backend/cli.py today              # traces live des ~24 dernières heures (jour courant)
python backend/cli.py fires              # points chauds NASA FIRMS (bbox Gironde+Landes)
python backend/cli.py wind               # vent horaire Open-Meteo (pour la fumée)
python backend/cli.py discover           # ajoute les moyens aériens détectés en vol autour du feu
python backend/cli.py photos             # photos des appareils (planespotters.net, en cache)
python backend/cli.py export 2026-07-25  # écrit frontend/public/data/2026-07-25.json + index.json
python backend/cli.py status             # résumé de la base
```

Toutes les commandes sont **idempotentes** : `ingest` saute un jour déjà ingéré, `fires`/`wind`
dédoublonnent, `export` réécrit. On peut donc les relancer sans risque.

### Cron

Les archives adsb.lol du jour J paraissent le lendemain à une heure variable. Plutôt qu'un
passage unique, planifier plusieurs tentatives : les passages où les données sont déjà là
ne refont rien.

Les scripts `scripts/live.sh` (jour courant) et `scripts/daily.sh` (consolidation de la veille)
enchaînent les commandes et redirigent **tout** (sorties et erreurs) vers le log :

```cron
# jour courant : traces live + feux + vent, toutes les 30 minutes
*/30 * * * * /path/flight/scripts/live.sh >> /var/log/firetrack.log 2>&1

# consolidation de la veille : tentatives multiples, la première qui trouve la release travaille
0 6,9,12,18 * * * /path/flight/scripts/daily.sh >> /var/log/firetrack.log 2>&1

# pendant un épisode de feu : détection des moyens aériens engagés (hélicos, avions loués...)
*/10 * * * * cd /path/flight && python3 backend/cli.py discover >> /var/log/firetrack.log 2>&1
```

(un `chmod +x scripts/*.sh` après le clone ; attention, ne pas mettre `cmd1 && cmd2 >> log`
directement en crontab : la redirection ne capturerait que la dernière commande)

Optionnel : `GITHUB_TOKEN` en variable d'environnement pour éviter la limite anonyme de
l'API GitHub (60 req/h, largement suffisant en pratique).

## Flotte

- **Statique** : [backend/fleet.json](backend/fleet.json) : Pélican (CL-415), Milan (Dash 8),
  Abel (Air Tractor), Beechcraft de coordination, A400M (hex militaires explicites via le
  champ `hex`). Ajouter une ligne puis relancer `fleet`.
- **Dynamique** : `discover` interroge l'API live autour du feu et ajoute tout bombardier
  d'eau détecté (callsigns `PELICAN/MILAN/ABEL/TRACT/DRAGON/CHARLIE/CTM`, types
  `CL2T/AT8T/DH8D/A400/EC45/H60`... sous 15 000 ft). Indispensable pour les appareils loués
  sous immat étrangère et les renforts européens RescEU.
- Limite connue : certains hélicoptères légers (ex. Charlie 33, AS350 du SDIS 33) n'émettent
  pas d'ADS-B et resteront invisibles.

## Frontend

```
npm run dev --prefix frontend      # dev sur http://localhost:5173
npm run build --prefix frontend    # build de production dans frontend/dist/
node frontend/scripts/check.mjs    # diagnostic headless (console + état + screenshot)
```

## Déploiement (VPS)

1. Sur le VPS : cloner le projet, puis **copier les données déjà récupérées en local**
   (aucune re-collecte nécessaire, tout est dans des fichiers) :

```bash
rsync -av data/canadair.db  vps:/path/flight/data/
rsync -av frontend/public/data/  vps:/path/flight/frontend/public/data/
rsync -av backend/firms_key.txt vps:/path/flight/backend/   # gitignoré, donc absent du clone
```

   Le cron reprendra ensuite tout seul : `ingest` saute les jours déjà en base.
2. Servir **uniquement** `frontend/dist/` (nginx, caddy...). Ne jamais exposer `backend/`
   (contient `firms_key.txt`) ni `data/` (la base SQLite).
3. **Important** : le build fige `public/data/` dans `dist/`. Pour que les exports quotidiens
   soient visibles sans rebuild, servir `/data/` directement depuis `frontend/public/data/` :

```nginx
location / { root /path/flight/frontend/dist; }
location /data/ { alias /path/flight/frontend/public/data/; }
```

(ou ajouter `npm run build` à la fin du cron, au choix)

## Sécurité

- Seul secret : la clé NASA FIRMS (`backend/firms_key.txt`, gitignoré ; ou env `FIRMS_MAP_KEY`).
  Gratuite et à faible enjeu (5000 req/10 min).
- Le site publié est statique : pas de base exposée, pas d'API à protéger, pas de données
  personnelles (les positions ADS-B sont publiques).
- `backend/cli.py` contient un email de contact dans le User-Agent planespotters (exigé par
  leur API) : à changer si le dépôt devient public et que ça dérange.

## Attribution

Data © [adsb.lol](https://www.adsb.lol) contributors
([ODbL 1.0](https://opendatacommons.org/licenses/odbl/1-0/)) · Feux
[NASA FIRMS](https://firms.modaps.eosdis.nasa.gov) · Météo
[Open-Meteo](https://open-meteo.com) (CC BY 4.0) · Fond
[OpenStreetMap](https://www.openstreetmap.org) · Imagerie [NASA GIBS](https://www.earthdata.nasa.gov) ·
Photos [planespotters.net](https://www.planespotters.net)
