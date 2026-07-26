# Étude de faisabilité — Suivi des Canadairs en Gironde

> Objectif : une page web animée montrant les allers-retours des Canadairs de la Sécurité Civile
> au-dessus de la Gironde, avec une timeline permettant de remonter plusieurs jours en arrière
> et de visualiser le tracé de chaque appareil.
>
> Recherche effectuée le 26/07/2026.

---

## 1. D'où viennent les données ? (Flightradar24 est-il la source ?)

**Non, Flightradar24 n'est pas la source initiale.** La source primaire est le transpondeur
**ADS-B** embarqué dans chaque avion : il diffuse en clair, en continu, position GPS, altitude,
vitesse, cap et identifiant (code hex ICAO + callsign). N'importe qui avec un récepteur à ~15 €
(clé SDR) peut capter ces signaux.

Flightradar24, comme ses concurrents, ne fait qu'**agréger** les données de milliers de
récepteurs hébergés par des bénévoles. Plusieurs réseaux agrègent donc *les mêmes signaux* :

| Réseau | Modèle | Données historiques |
|---|---|---|
| [Flightradar24](https://www.flightradar24.com) | Commercial | API payante (abonnement) |
| [ADS-B Exchange](https://www.adsbexchange.com/products/historical-data/) | Commercial (racheté) | Payant |
| [OpenSky Network](https://opensky-network.org) | Académique, gratuit | ~30 jours via API, plus via accès chercheur |
| [adsb.lol](https://www.adsb.lol) | **Open source, gratuit, ODbL** | **Archive quotidienne complète sur GitHub** |
| [airplanes.live](https://airplanes.live/api-guide/) | Communautaire, gratuit | Live surtout, historique limité |

Point important : les avions de la Sécurité Civile (avions d'État) sont **visibles et non
filtrés** sur ces réseaux — les fiches [F-ZBFP](https://www.flightradar24.com/data/aircraft/f-zbfp),
[F-ZBFS](https://www.flightradar24.com/data/aircraft/f-zbfs),
[F-ZBME](https://www.flightradar24.com/data/aircraft/f-zbme) existent publiquement sur FR24.

---

## 2. La flotte à suivre

La Sécurité Civile opère ses **Canadair CL-415** depuis la base de **Nîmes-Garons**, avec des
détachements estivaux ("pélicandromes") dont **Bordeaux-Mérignac** pour les feux en
Nouvelle-Aquitaine (cf. les grands feux de Gironde).

- **Immatriculations** : série `F-ZB..` — F-ZBEG, F-ZBEO, F-ZBEU, F-ZBEZ, F-ZBFN, F-ZBFP,
  F-ZBFQ, F-ZBFS, F-ZBFV, F-ZBFW, F-ZBFX, F-ZBFY, F-ZBME, F-ZBMF, F-ZBMG (12 en service actuellement)
- **Callsigns** : `PELICAN xx` (ex. Pélican 31 = F-ZBFP, Pélican 32 = F-ZBFS, Pélican 44 = F-ZBME)
- **Codes hex ICAO** : chaque appareil a un code hex 24 bits fixe (plage française `3Bxxxx`).
  C'est la **clé d'identification** dans toutes les données ADS-B.
  → À récupérer une fois pour toutes via la base tar1090/adsb.lol (`/v2/reg/F-ZBME`) ou les
  fiches FR24 ; à figer dans un fichier de config du projet.
- Bonus possible : les **Dash 8 Q400MR** (callsign `MILAN xx`) qui larguent du retardant,
  souvent engagés aux côtés des Canadairs en Gironde.

---

## 3. Comparaison des sources pour l'historique

### ✅ Option recommandée : adsb.lol (gratuit, open data, ODbL)

- **Archive historique quotidienne** publiée sur GitHub :
  [adsblol/globe_history_2026](https://github.com/adsblol/globe_history_2026)
  (une release par jour, vérifiée à jour au 25/07/2026 ; années précédentes :
  [2025](https://github.com/adsblol/globe_history_2025), [2024](https://github.com/adsblol/globe_history_2024)).
- Chaque release = une archive tar contenant **un fichier JSON gzippé par avion**
  (`traces/xx/trace_full_<hex>.json`) avec la trace complète de la journée.
- On peut donc remonter **de plusieurs jours, mois ou années** — bien au-delà du besoin.
- Licence ODbL : réutilisation libre avec attribution. Parfait pour une page web publique.
- **Inconvénient** : les archives quotidiennes sont volumineuses (plusieurs Go, en tar
  multi-parties). Il faut un **pipeline de pré-traitement** : télécharger la release du jour,
  extraire uniquement les ~15 fichiers correspondant aux hex des Canadairs, jeter le reste.
- API live gratuite en complément : `https://api.adsb.lol/v2/...` (pour le "temps réel" éventuel).

### 🆗 Option d'appoint : OpenSky Network (gratuit, inscription requise)

- [API REST](https://openskynetwork.github.io/opensky-api/rest.html) gratuite :
  `/flights/aircraft` (liste des vols d'un appareil) et `/tracks` (trajectoire).
- **Limité à ~30 jours en arrière**, endpoint `/tracks` étiqueté "expérimental", résolution
  de trace plus grossière que readsb.
- Utile en secours ou pour valider les données, pas comme source principale.

### ❌ Écartées

- **Flightradar24 API** : historique disponible mais **payant** (abonnement), CGU restrictives
  pour la republication sur une page web publique.
- **ADS-B Exchange** : les données historiques sont un [produit payant](https://www.adsbexchange.com/products/historical-data/).
- **airplanes.live** : bonne API live (`https://api.airplanes.live/v2/`), mais pas d'archive
  historique publique téléchargeable comparable à adsb.lol.

---

## 4. Format des données (traces readsb / adsb.lol)

Format documenté dans [readsb README-json.md](https://github.com/wiedehopf/readsb/blob/dev/README-json.md) :

```jsonc
{
  "icao": "3b7b95",          // code hex de l'avion
  "timestamp": 1753488000,    // époque Unix de référence (début de journée)
  "trace": [
    // [secondes_depuis_timestamp, lat, lon, altitude_ft|"ground"|null,
    //  vitesse_sol_kt, cap_deg, flags, taux_vertical_fpm, {détails}...]
    [34.5, 44.8213, -0.7154, 1200, 160.4, 245.3, 0, -640, ...],
    ...
  ]
}
```

- Un point garanti toutes les **~30 s** minimum, bien plus dense en manœuvre → largement
  suffisant pour animer les norias d'écopage (lac de Biscarrosse/Hourtin ↔ zone de feu).
- Le bit `flags & 2` marque le **début d'un nouveau "leg"** (séparation atterrissage/décollage)
  → permet de découper automatiquement les rotations.
- Altitude `"ground"` → l'avion est au sol (ou à l'écopage, quasi niveau de l'eau).

---

## 5. Faisabilité & architecture proposée

**Verdict : totalement faisable, gratuitement, avec des données libres.**

```
[GitHub adsb.lol releases]                      (1 fois/jour, script ou cron)
        │  télécharger la release du jour
        ▼
[Pipeline d'extraction]  → garder traces des ~15 hex Canadairs (+ Milan ?)
        │  filtrer bbox Gironde élargie, découper en legs, simplifier
        ▼
[Fichiers statiques JSON par jour]   ex: data/2026-07-25/f-zbme.json  (quelques Ko/jour/avion)
        │
        ▼
[Page web statique]
   • Carte : MapLibre GL JS (ou Leaflet) — fond OSM
   • Animation : deck.gl TripsLayer (traînées animées) ou animation canvas maison
   • Timeline : slider de date + curseur horaire, lecture/pause, vitesse x1–x300
   • Tracé coloré par avion, marqueur orienté selon le cap
```

Points d'attention :
- **Volume de téléchargement** du pipeline : plusieurs Go/jour à extraire → à faire côté
  serveur/CI (GitHub Actions possible), jamais côté navigateur. Une fois filtré, le résultat
  est minuscule.
- **Couverture** : la Gironde est bien couverte par les récepteurs communautaires ; de rares
  trous à très basse altitude (largage/écopage) peuvent hacher la trace — l'interpolation
  dans l'animation les lissera.
- **Attribution** obligatoire : "Data © adsb.lol contributors (ODbL)".
- Les releases adsb.lol paraissent avec ~1 jour de décalage → le "jour courant" peut être
  complété par l'API live si besoin.

---

## 6. Prochaines étapes proposées

1. **Constituer la table hex ↔ immatriculation ↔ Pélican xx** (une requête par avion sur
   l'API adsb.lol ou la base tar1090).
2. **Prototype du pipeline** : télécharger la release d'un jour de feu connu, extraire les
   traces Canadair, vérifier la densité des points en Gironde.
3. **Prototype carte** : afficher un jour de traces avec timeline.
4. Automatiser (cron/GitHub Actions) + page finale.

---

## 7. Afficher les zones de feu (Gironde & Landes)

> Recherche du 26/07/2026 — objectif : afficher les "flammes" sur la carte, synchronisées
> avec la timeline, en Gironde et dans les Landes.

### ✅ Source recommandée : NASA FIRMS (points chauds satellites)

[FIRMS](https://firms.modaps.eosdis.nasa.gov/api/) détecte les **points chauds actifs**
(anomalies thermiques) par satellite — instruments **VIIRS 375 m** (archive depuis 2012)
et MODIS 1 km.

- **API gratuite** (simple `MAP_KEY` à demander, gratuit) :
  `https://firms.modaps.eosdis.nasa.gov/api/area/csv/[MAP_KEY]/[SOURCE]/[bbox w,s,e,n]/[nb_jours]/[date]`
  → CSV/JSON de points avec **lat/lon, date + heure d'acquisition, intensité (FRP), jour/nuit**.
  Sources : `VIIRS_SNPP_NRT` (temps quasi réel) / `VIIRS_SNPP_SP` (qualité science, ~5 mois de recul).
  Historique par plage de dates (max 10 jours par requête), limite ~5000 req/10 min.
- **Parfait pour notre usage** : chaque point est horodaté → on peut faire apparaître/disparaître
  les flammes en phase avec la timeline. Une bbox Gironde+Landes ramène très peu de points → léger.
- **Limites** : 2 à 4 passages satellite/jour (l'heure de détection est celle du survol, pas du
  départ de feu), résolution 375 m, faux positifs possibles (torchères, hangars chauds).

### 🆗 En complément : EFFIS (contours des surfaces brûlées)

L'[EFFIS](https://forest-fire.emergency.copernicus.eu/applications/data-and-services)
(Copernicus) publie quotidiennement les **périmètres des zones brûlées** et ses propres points
chauds, accessibles en **WMS** (couches avec paramètre `TIME`) — données libres.
Les extractions vectorielles historiques passent par un formulaire de demande, mais des
[projets tiers](https://github.com/LuisSevillano/effis_current_situation) vectorisent le WMS en
GeoJSON. Utile pour dessiner la **tache brûlée** (polygone) en plus des flammes ponctuelles.

### Autres pistes (métadonnées, pas d'affichage temps réel)

- **[BDIFF](https://bdiff.agriculture.gouv.fr/)** : base officielle française des incendies de
  forêt (commune, date, surface) — déclaratif, publié avec retard ; utile pour titrer/valider
  un épisode, pas pour la carte.
- **Copernicus EMS** : cartographies d'urgence activées sur les grands feux (ex. Landiras 2022),
  périmètres précis mais uniquement pour les événements majeurs.

### Intégration proposée

1. Commande `fires` dans le CLI : requête FIRMS sur la bbox Gironde+Landes pour les jours
   ingérés → table SQLite `fires(lat, lon, ts, frp, satellite)` → inclus dans l'export JSON.
2. Frontend : couche de points "flammes" (halo orange/rouge, taille ∝ FRP) qui s'affichent
   quand `|t - ts_détection| < quelques heures`.
3. (Option v2) polygone EFFIS de la surface brûlée en fond.

---

## 8. Afficher la fumée et sa direction

> Recherche du 26/07/2026. Trois approches possibles, de la plus simple à la plus lourde.

### ✅ Recommandé : fumée simulée à partir du vent (Open-Meteo)

Il n'existe pas de flux temps réel simple "panache de fumée" pour la France, mais on peut la
**simuler de façon très convaincante** : on connaît les foyers (FIRMS, avec intensité FRP) et
on peut récupérer le **vent historique heure par heure** au point du feu.

- **[Open-Meteo Historical API](https://open-meteo.com/en/docs/historical-weather-api)** :
  gratuit, **sans clé**, licence CC BY 4.0. Réanalyse ERA5 depuis 1940, ~10 km de résolution,
  variables `wind_speed_10m` + `wind_direction_10m` heure par heure.
  Testé sur la Gironde au 23/07/2026 : réponse instantanée, données complètes.
- **Rendu proposé** : particules de fumée émises par chaque foyer sur le canvas overlay
  (déjà en place pour flammes et traînées), poussées selon le vecteur vent de l'heure simulée,
  avec grossissement/dilution au fil de la dérive. Quantité liée au FRP du foyer.
- **Pipeline** : commande `wind` dans le CLI (une requête par jour ingéré, stockée en SQLite,
  incluse dans l'export). Aucune dépendance, aucune clé.
- **Limites** : c'est une simulation plausible (direction et force réelles du vent), pas la
  photographie exacte du panache.

### 🆗 Alternative : imagerie satellite réelle (NASA GIBS)

[NASA GIBS](https://nasa-gibs.github.io/gibs-api-docs/) sert en **tuiles XYZ/WMTS gratuites**
les mosaïques quotidiennes **VIIRS/MODIS en vraies couleurs**, où les panaches de fumée sont
réellement visibles (résolution 250-375 m, une image par jour, dispo en ~3-5 h).
On peut l'ajouter en **couche d'opacité réglable** sur la carte, datée selon le jour de la
timeline. Réel mais statique (1 image/jour) et l'image couvre tout (nuages compris).

### ❌ Écarté : Copernicus CAMS

Le service atmosphère de Copernicus modélise les aérosols/PM2.5 des feux (résolution ~40 km,
NetCDF, inscription + API lourde) : trop grossier et trop complexe pour ce besoin.

### Verdict

Approche 1 (vent + particules) pour l'animation vivante synchronisée à la timeline,
avec l'option 2 (couche GIBS "vue satellite du jour") en bonus activable dans le menu.

---

## 9. Indice de pollution de l'air (et son évolution par lieu)

> Recherche du 26/07/2026, testée sur l'épisode des 22-25/07.

### ✅ Open-Meteo Air Quality API

Même fournisseur que le vent : **gratuit, sans clé**, basé sur le modèle Copernicus **CAMS
Europe** (~11 km de résolution), heure par heure.

- Endpoint : `https://air-quality-api.open-meteo.com/v1/air-quality`
- Variables utiles : `pm2_5`, `pm10`, `european_aqi` (indice européen 0-100+),
  plus ozone, NO2, etc.
- **Multi-points en une seule requête** (listes `latitude=,,&longitude=,,`) : parfait pour
  suivre l'évolution selon les lieux, voire construire une grille pour une carte de chaleur.
- Historique et prévision (archive dispo sur plusieurs années).
- **Testé sur le 24/07** (pic du feu) : zone du feu PM2.5 max 12,6 µg/m³ (AQI 55) contre
  6,9 à Bordeaux : le gradient spatial est bien visible.

### ⚠️ Limite importante

C'est un **modèle** (~11 km) : il lisse fortement les pics locaux de fumée. Au cœur du
panache, les vraies valeurs mesurées peuvent être bien plus élevées que ce que CAMS annonce.
Pour des **mesures réelles** station par station, l'organisme régional
[ATMO Nouvelle-Aquitaine](https://www.atmo-nouvelleaquitaine.org/) publie l'indice ATMO
quotidien par commune en open data, mais ses stations sont rares hors agglomération
(aucune au cœur du massif forestier).

### Intégration possible

1. Commande `air` dans le CLI : grille de points (ex. 6×6 sur Gironde+Landes) requêtée en un
   appel, stockée en SQLite, exportée par jour.
2. Frontend : couche de chaleur (cercles colorés selon l'AQI européen, vert → rouge) qui
   évolue avec la timeline, ou simple pastille "qualité de l'air" au point du feu.

---

## Sources

- [adsb.lol — Historical data](https://www.adsb.lol/docs/open-data/historical/)
- [adsblol/globe_history_2026 (releases quotidiennes)](https://github.com/adsblol/globe_history_2026)
- [readsb — format JSON des traces](https://github.com/wiedehopf/readsb/blob/dev/README-json.md)
- [OpenSky Network — REST API](https://openskynetwork.github.io/opensky-api/rest.html)
- [ADS-B Exchange — Historical data (payant)](https://www.adsbexchange.com/products/historical-data/)
- [airplanes.live — API guide](https://airplanes.live/api-guide/)
- [Flightradar24 — flotte Sécurité Civile](https://www.flightradar24.com/data/airlines/fru/fleet)
- [Wikipedia — Canadair CL-415](https://en.wikipedia.org/wiki/Canadair_CL-415)
- [NASA FIRMS — API](https://firms.modaps.eosdis.nasa.gov/api/) · [tutoriel API](https://firms.modaps.eosdis.nasa.gov/content/academy/data_api/firms_api_use.html) · [archive](https://firms.modaps.eosdis.nasa.gov/download/)
- [EFFIS — Data and services](https://forest-fire.emergency.copernicus.eu/applications/data-and-services)
- [BDIFF — base des incendies de forêt](https://bdiff.agriculture.gouv.fr/)
- [Open-Meteo — Historical Weather API](https://open-meteo.com/en/docs/historical-weather-api)
- [Open-Meteo — Air Quality API](https://open-meteo.com/en/docs/air-quality-api)
- [ATMO Nouvelle-Aquitaine](https://www.atmo-nouvelleaquitaine.org/)
- [NASA GIBS — API docs](https://nasa-gibs.github.io/gibs-api-docs/) · [Earthdata GIBS](https://www.earthdata.nasa.gov/engage/open-data-services-software/earthdata-developer-portal/gibs-api)
- [AerialFire — The Amphibious Firefighters of the French Civil Security](https://aerialfiremag.com/2026/03/01/the-amphibious-firefighters-of-the-french-civil-security/)
