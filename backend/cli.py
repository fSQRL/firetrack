#!/usr/bin/env python3
"""Pipeline CLI — suivi des Canadairs (Sécurité Civile) via les données ouvertes adsb.lol.

Zéro dépendance : stdlib uniquement. Pensé pour être lancé par un cron.

Commandes :
    fleet                Résout les immatriculations de fleet.json en codes hex ICAO (hexdb.io).
    ingest [DATE]        Télécharge la release adsb.lol du jour DATE (défaut : hier) et
                         stocke en SQLite les traces des avions de la flotte.
    export DATE          Exporte les traces d'un jour en JSON (pour le frontend).
    status               Résumé de ce qui est en base.
"""
import argparse
import gzip
import json
import os
import sqlite3
import sys
import tarfile
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

# logs en temps réel sous cron/redirection + UTF-8 même sur console Windows cp1252
sys.stdout.reconfigure(line_buffering=True, encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "canadair.db"
EXPORT_DIR = ROOT / "frontend" / "public" / "data"
FLEET_PATH = Path(__file__).resolve().parent / "fleet.json"

GITHUB_RELEASE_URL = "https://api.github.com/repos/adsblol/globe_history_{year}/releases/tags/{tag}"
HEXDB_URL = "https://hexdb.io/reg-hex?reg={reg}"

# Vent horaire historique (Open-Meteo, gratuit sans clé) au centre de la zone feu
OPEN_METEO_URL = ("https://archive-api.open-meteo.com/v1/archive?latitude=44.6&longitude=-1.0"
                  "&start_date={start}&end_date={end}"
                  "&hourly=wind_speed_10m,wind_direction_10m&timezone=UTC")
# l'archive ERA5 a quelques jours de retard : l'API forecast couvre le jour courant
OPEN_METEO_FORECAST_URL = ("https://api.open-meteo.com/v1/forecast?latitude=44.6&longitude=-1.0"
                           "&past_days=2&forecast_days=1"
                           "&hourly=wind_speed_10m,wind_direction_10m&timezone=UTC")

# Qualité de l'air (Open-Meteo/CAMS) : grille de points sur la zone, indice européen horaire
AIR_GRID = [(la, lo) for la in (43.6, 44.0, 44.4, 44.8, 45.2) for lo in (-1.4, -1.0, -0.6, -0.2)]
AIR_URL = ("https://air-quality-api.open-meteo.com/v1/air-quality?latitude={lats}&longitude={lons}"
           "&hourly=european_aqi&start_date={start}&end_date={end}&timezone=UTC")

# NASA FIRMS (points chauds satellites) — bbox Gironde + Landes (w,s,e,n)
FIRMS_URL = "https://firms.modaps.eosdis.nasa.gov/api/area/csv/{key}/{source}/{bbox}/{days}/{day}"
FIRMS_BBOX = "-1.6,43.4,0.2,45.6"
# VIIRS passe vers ~01h30/13h30 locales ; MODIS (Terra/Aqua) ajoute des passages
# vers ~10h30/21h30 : les quatre sources couvrent mieux la journée
FIRMS_NRT = ["VIIRS_SNPP_NRT", "VIIRS_NOAA20_NRT", "VIIRS_NOAA21_NRT", "MODIS_NRT"]
FIRMS_SP = ["VIIRS_SNPP_SP", "VIIRS_NOAA20_SP", "MODIS_SP"]
FIRMS_MAX_RANGE = 5  # l'API n'accepte que des plages de 1 à 5 jours
FIRMS_KEY_FILE = Path(__file__).resolve().parent / "firms_key.txt"

# Découverte live des moyens aériens engagés (les avions loués ont des immats étrangères)
AIRPLANES_LIVE_POINT = "https://api.airplanes.live/v2/point/{lat}/{lon}/{radius}"
FIRE_CALLSIGNS = ("PELICAN", "MILAN", "DRAGON", "TRACT", "ABEL", "CHARLIE", "CTM", "COTAM", "BOMB",
                  "PUMA", "MORA", "OMBH", "BLADE")
FIRE_TYPES = {"CL2T", "AT8T", "A400", "DH8D", "EC45", "H125", "AS50", "EC30", "AS3B", "S2P", "B350",
              "H60", "S70", "UH60", "B412"}
MAX_DISCOVER_ALT_FT = 15000  # écarte les liners en croisière au-dessus de la zone

SCHEMA = """
CREATE TABLE IF NOT EXISTS aircraft (
    hex          TEXT PRIMARY KEY,
    registration TEXT NOT NULL UNIQUE,
    name         TEXT NOT NULL,
    type         TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS positions (
    hex       TEXT NOT NULL,
    ts        REAL NOT NULL,          -- epoch Unix (s)
    lat       REAL NOT NULL,
    lon       REAL NOT NULL,
    alt_ft    INTEGER,                -- NULL si inconnu ou au sol
    on_ground INTEGER NOT NULL DEFAULT 0,
    gs_kt     REAL,
    track_deg REAL,
    flags     INTEGER NOT NULL DEFAULT 0,  -- flags readsb (bit 2 = nouveau leg)
    PRIMARY KEY (hex, ts)
);
CREATE INDEX IF NOT EXISTS idx_positions_ts ON positions (ts);
CREATE TABLE IF NOT EXISTS fires (
    lat       REAL NOT NULL,
    lon       REAL NOT NULL,
    ts        REAL NOT NULL,           -- epoch Unix (s) du passage satellite
    frp       REAL,                    -- intensité (Fire Radiative Power, MW)
    satellite TEXT NOT NULL,
    daynight  TEXT,
    PRIMARY KEY (lat, lon, ts, satellite)
);
CREATE INDEX IF NOT EXISTS idx_fires_ts ON fires (ts);
CREATE TABLE IF NOT EXISTS wind (
    ts        REAL PRIMARY KEY,       -- epoch Unix (s), pas horaire
    speed_kmh REAL,
    dir_deg   REAL                    -- direction d'où vient le vent (météo)
);
CREATE TABLE IF NOT EXISTS air (
    ts   REAL NOT NULL,               -- epoch Unix (s), pas horaire
    lat  REAL NOT NULL,
    lon  REAL NOT NULL,
    aqi  REAL,                        -- indice européen de qualité de l'air
    PRIMARY KEY (ts, lat, lon)
);
CREATE TABLE IF NOT EXISTS ingested_days (
    day         TEXT PRIMARY KEY,     -- YYYY-MM-DD
    tag         TEXT NOT NULL,
    ingested_at TEXT NOT NULL,
    positions   INTEGER NOT NULL
);
"""


def get_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB_PATH, timeout=30)
    db.execute("PRAGMA journal_mode=WAL")  # permet lecture/écriture concurrentes entre commandes
    db.executescript(SCHEMA)
    # migrations légères (colonnes ajoutées après coup)
    for col in ("photo_src", "photo_link", "photo_credit"):
        try:
            db.execute(f"ALTER TABLE aircraft ADD COLUMN {col} TEXT")
        except sqlite3.OperationalError:
            pass
    return db


def http_get(url, timeout=30, ua=None, extra_headers=None):
    headers = {"User-Agent": ua or "canadair-gironde-pipeline"}
    if extra_headers:
        headers.update(extra_headers)
    token = os.environ.get("GITHUB_TOKEN")
    if token and "api.github.com" in url:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers)
    return urllib.request.urlopen(req, timeout=timeout)


# ---------------------------------------------------------------- fleet

def cmd_fleet(args):
    fleet = json.loads(FLEET_PATH.read_text(encoding="utf-8"))["aircraft"]
    db = get_db()
    known = {reg: hex_ for hex_, reg in db.execute("SELECT hex, registration FROM aircraft")}
    for ac in fleet:
        reg = ac["registration"]
        if reg in known:
            print(f"  {reg} -> {known[reg]} (déjà en base)")
            continue
        if "hex" in ac:  # hex fourni explicitement (immat. militaires absentes de hexdb)
            db.execute(
                "INSERT OR IGNORE INTO aircraft (hex, registration, name, type) VALUES (?, ?, ?, ?)",
                (ac["hex"].lower(), reg, ac["name"], ac["type"]),
            )
            print(f"  {reg} -> {ac['hex']} (hex explicite)")
            continue
        try:
            with http_get(HEXDB_URL.format(reg=reg)) as resp:
                hex_ = resp.read().decode().strip().lower()
        except Exception as e:
            print(f"  {reg} -> ERREUR hexdb.io : {e}", file=sys.stderr)
            continue
        if not (len(hex_) == 6 and all(c in "0123456789abcdef" for c in hex_)):
            print(f"  {reg} -> réponse invalide de hexdb.io : {hex_!r}", file=sys.stderr)
            continue
        db.execute(
            "INSERT INTO aircraft (hex, registration, name, type) VALUES (?, ?, ?, ?)",
            (hex_, reg, ac["name"], ac["type"]),
        )
        print(f"  {reg} -> {hex_} ({ac['name']})")
    db.commit()
    n = db.execute("SELECT COUNT(*) FROM aircraft").fetchone()[0]
    print(f"Flotte en base : {n} appareils.")


# ---------------------------------------------------------------- ingest

class MultiPartStream:
    """Lit séquentiellement plusieurs URLs comme un seul flux (tar découpé en .aa/.ab/...)."""

    def __init__(self, urls, log_every=500 * 1024 * 1024):
        self.urls = list(urls)
        self.resp = None
        self.total = 0
        self.log_every = log_every
        self._next_log = log_every

    def read(self, n=-1):
        buf = b""
        while n < 0 or len(buf) < n:
            if self.resp is None:
                if not self.urls:
                    break
                url = self.urls.pop(0)
                print(f"  téléchargement : {url.rsplit('/', 1)[-1]}")
                self.resp = http_get(url, timeout=120)
            chunk = self.resp.read(n - len(buf) if n >= 0 else 1024 * 1024)
            if not chunk:
                self.resp.close()
                self.resp = None
                continue
            buf += chunk
        self.total += len(buf)
        if self.total >= self._next_log:
            print(f"  ... {self.total / 1e9:.1f} Go lus")
            self._next_log += self.log_every
        return buf


def release_asset_urls(day, source):
    tag = f"v{day:%Y.%m.%d}-planes-readsb-{source}"
    url = GITHUB_RELEASE_URL.format(year=day.year, tag=tag)
    try:
        with http_get(url) as resp:
            release = json.load(resp)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            sys.exit(f"Release introuvable : {tag} (les données paraissent avec ~1 jour de décalage)")
        raise
    urls = [a["browser_download_url"] for a in sorted(release["assets"], key=lambda a: a["name"])
            if ".tar" in a["name"]]
    size = sum(a["size"] for a in release["assets"] if ".tar" in a["name"])
    return tag, urls, size


def parse_trace(raw, hex_, db):
    """Insère les points d'un fichier trace_full readsb. Retourne le nb de points."""
    data = json.loads(raw)
    base = data["timestamp"]
    rows = []
    for p in data.get("trace", []):
        secs, lat, lon, alt = p[0], p[1], p[2], p[3]
        gs = p[4] if len(p) > 4 else None
        track = p[5] if len(p) > 5 else None
        flags = p[6] if len(p) > 6 else 0
        on_ground = 1 if alt == "ground" else 0
        alt_ft = alt if isinstance(alt, (int, float)) else None
        rows.append((hex_, base + secs, lat, lon, alt_ft, on_ground, gs, track, flags or 0))
    db.executemany(
        "INSERT OR IGNORE INTO positions (hex, ts, lat, lon, alt_ft, on_ground, gs_kt, track_deg, flags)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        rows,
    )
    return len(rows)


def cmd_ingest(args):
    day = date.fromisoformat(args.date) if args.date else date.today() - timedelta(days=1)
    db = get_db()
    fleet = {hex_: reg for hex_, reg in db.execute("SELECT hex, registration FROM aircraft")}
    if not fleet:
        sys.exit("Aucun appareil en base : lancer d'abord `cli.py fleet`.")
    if not args.force and db.execute("SELECT 1 FROM ingested_days WHERE day = ?", (day.isoformat(),)).fetchone():
        print(f"{day} déjà ingéré (utiliser --force pour refaire).")
        return

    tag, urls, size = release_asset_urls(day, args.source)
    print(f"Ingestion {day} — {tag} — {len(urls)} fichier(s), {size / 1e9:.1f} Go à parcourir")
    wanted = {f"trace_full_{h}.json" for h in fleet}

    stream = MultiPartStream(urls)
    total_points = 0
    found = []
    tar = tarfile.open(fileobj=stream, mode="r|")
    for member in tar:
        fname = member.name.rsplit("/", 1)[-1]
        if fname not in wanted:
            continue
        hex_ = fname[len("trace_full_"):-len(".json")]
        raw = tar.extractfile(member).read()
        if raw[:2] == b"\x1f\x8b":
            raw = gzip.decompress(raw)
        n = parse_trace(raw, hex_, db)
        db.commit()  # transactions courtes : ne pas verrouiller la base pendant toute l'ingestion
        total_points += n
        found.append((fleet[hex_], n))
        print(f"  ✔ {fleet[hex_]} ({hex_}) : {n} points")
    tar.close()

    db.execute(
        "INSERT OR REPLACE INTO ingested_days (day, tag, ingested_at, positions) VALUES (?, ?, ?, ?)",
        (day.isoformat(), tag, datetime.now(timezone.utc).isoformat(timespec="seconds"), total_points),
    )
    db.commit()
    absent = len(fleet) - len(found)
    print(f"Terminé : {total_points} points, {len(found)} appareil(s) vus, {absent} sans vol ce jour-là.")


# ---------------------------------------------------------------- today

# Trace live des dernières ~24 h par avion (même serveur que la carte globe.adsb.lol,
# même format readsb que l'archive : le dédoublonnage se fait par la clé primaire)
LIVE_TRACE_URL = "https://globe.adsb.lol/data/traces/{sub}/trace_full_{hex}.json"
LIVE_HEADERS = {"Referer": "https://globe.adsb.lol/", "Accept-Encoding": "gzip"}


def cmd_today(args):
    db = get_db()
    fleet = db.execute("SELECT hex, registration FROM aircraft ORDER BY registration").fetchall()
    total, seen = 0, 0
    errors = 0
    for hex_, reg in fleet:
        url = LIVE_TRACE_URL.format(sub=hex_[-2:], hex=hex_)
        try:
            with http_get(url, timeout=45, ua="Mozilla/5.0 (FireTracker)", extra_headers=LIVE_HEADERS) as resp:
                raw = resp.read()
        except urllib.error.HTTPError as e:
            if e.code in (404, 403):
                continue  # avion pas vu ces dernières 24 h
            print(f"  ✗ {reg} : HTTP {e.code}, on continue", file=sys.stderr)
            errors += 1
            continue
        except Exception as e:  # timeout, réseau... : ne jamais faire échouer tout le lot
            print(f"  ✗ {reg} : {type(e).__name__} ({e}), on continue", file=sys.stderr)
            errors += 1
            continue
        if raw[:2] == b"\x1f\x8b":
            raw = gzip.decompress(raw)
        n = parse_trace(raw, hex_, db)
        db.commit()
        if n:
            print(f"  ✔ {reg} ({hex_}) : {n} points sur ~24 h")
            seen += 1
            total += n
    msg = f"Live : {total} points, {seen} appareil(s) vus"
    if errors:
        msg += f", {errors} erreur(s) réseau ignorée(s)"
    print(msg + ".")


# ---------------------------------------------------------------- discover

def cmd_discover(args):
    url = AIRPLANES_LIVE_POINT.format(lat=args.lat, lon=args.lon, radius=args.radius)
    with http_get(url, timeout=30) as resp:
        data = json.load(resp)
    db = get_db()
    added = 0
    for ac in data.get("ac", []):
        flight = (ac.get("flight") or "").strip().upper()
        typ = (ac.get("t") or "").upper()
        alt = ac.get("alt_baro")
        low = alt == "ground" or (isinstance(alt, (int, float)) and alt < MAX_DISCOVER_ALT_FT)
        if not low or not (flight.startswith(FIRE_CALLSIGNS) or typ in FIRE_TYPES):
            continue
        hex_ = ac["hex"].lower()
        if db.execute("SELECT 1 FROM aircraft WHERE hex = ?", (hex_,)).fetchone():
            continue
        reg = (ac.get("r") or "").strip() or hex_
        name = flight or reg
        db.execute("INSERT OR IGNORE INTO aircraft (hex, registration, name, type) VALUES (?, ?, ?, ?)",
                   (hex_, reg, name, typ or "?"))
        print(f"  + {name:<10} {reg:<10} {hex_}  {typ or '?'}")
        added += 1
    db.commit()
    print(f"Découverte ({args.lat}, {args.lon}, {args.radius} nm) : {added} nouvel(s) appareil(s).")


# ---------------------------------------------------------------- fires

def firms_key():
    key = os.environ.get("FIRMS_MAP_KEY")
    if not key and FIRMS_KEY_FILE.exists():
        key = FIRMS_KEY_FILE.read_text().strip()
    if not key:
        sys.exit("Clé FIRMS manquante : renseigner backend/firms_key.txt ou FIRMS_MAP_KEY.")
    return key


def cmd_fires(args):
    import csv
    import io

    start = date.fromisoformat(args.date) if args.date else date.today() - timedelta(days=1)
    key = firms_key()
    db = get_db()
    total = 0
    remaining, day = args.days, start
    while remaining > 0:
        ndays = min(remaining, FIRMS_MAX_RANGE)
        # NRT couvre ~les 2 derniers mois ; au-delà, les données science (SP) prennent le relais
        sources = FIRMS_NRT if (date.today() - day).days < 60 else FIRMS_SP
        for source in sources:
            url = FIRMS_URL.format(key=key, source=source, bbox=FIRMS_BBOX, days=ndays, day=day.isoformat())
            with http_get(url, timeout=60) as resp:
                text = resp.read().decode("utf-8")
            if text.startswith("Invalid"):  # l'API renvoie 200 avec un message d'erreur en clair
                sys.exit(f"Erreur FIRMS ({source}) : {text.strip()[:200]}")
            rows = []
            for r in csv.DictReader(io.StringIO(text)):
                hhmm = r["acq_time"].zfill(4)
                ts = datetime.fromisoformat(f"{r['acq_date']}T{hhmm[:2]}:{hhmm[2:]}:00+00:00").timestamp()
                rows.append((float(r["latitude"]), float(r["longitude"]), ts,
                             float(r["frp"]) if r.get("frp") else None,
                             r.get("satellite", "?"), r.get("daynight")))
            db.executemany("INSERT OR IGNORE INTO fires VALUES (?, ?, ?, ?, ?, ?)", rows)
            print(f"  {day} +{ndays}j {source}: {len(rows)} détections")
            total += len(rows)
        day += timedelta(days=ndays)
        remaining -= ndays
    db.commit()
    print(f"FIRMS {start} → {day - timedelta(days=1)} : {total} détections (bbox Gironde+Landes).")


# ---------------------------------------------------------------- wind

def cmd_wind(args):
    start = date.fromisoformat(args.date) if args.date else date.today() - timedelta(days=1)
    end = start + timedelta(days=args.days - 1)
    def fetch_rows(url):
        with http_get(url, timeout=60) as resp:
            h = json.load(resp)["hourly"]
        rows = []
        for time_s, spd, deg in zip(h["time"], h["wind_speed_10m"], h["wind_direction_10m"]):
            if spd is None:
                continue
            ts = datetime.fromisoformat(time_s + ":00+00:00").timestamp()
            if start_ts <= ts < end_ts:
                rows.append((ts, spd, deg))
        return rows

    start_ts = datetime(start.year, start.month, start.day, tzinfo=timezone.utc).timestamp()
    end_ts = start_ts + args.days * 86400
    rows = fetch_rows(OPEN_METEO_URL.format(start=start.isoformat(), end=end.isoformat()))
    if len(rows) < args.days * 24:  # l'archive est en retard : compléter avec le forecast
        rows += fetch_rows(OPEN_METEO_FORECAST_URL)
    db = get_db()
    db.executemany("INSERT OR REPLACE INTO wind VALUES (?, ?, ?)", rows)
    db.commit()
    print(f"Vent {start} → {end} : {len(rows)} relevés horaires (Open-Meteo).")


# ---------------------------------------------------------------- air

def cmd_air(args):
    start = date.fromisoformat(args.date) if args.date else date.today() - timedelta(days=1)
    end = start + timedelta(days=args.days - 1)
    url = AIR_URL.format(
        lats=",".join(str(la) for la, _ in AIR_GRID),
        lons=",".join(str(lo) for _, lo in AIR_GRID),
        start=start.isoformat(), end=end.isoformat(),
    )
    with http_get(url, timeout=60) as resp:
        locs = json.load(resp)
    db = get_db()
    rows = []
    for (la, lo), loc in zip(AIR_GRID, locs):
        h = loc["hourly"]
        for time_s, aqi in zip(h["time"], h["european_aqi"]):
            if aqi is None:
                continue
            ts = datetime.fromisoformat(time_s + ":00+00:00").timestamp()
            rows.append((ts, la, lo, aqi))
    db.executemany("INSERT OR REPLACE INTO air VALUES (?, ?, ?, ?)", rows)
    db.commit()
    print(f"Air {start} → {end} : {len(rows)} relevés ({len(AIR_GRID)} points de grille).")


# ---------------------------------------------------------------- photos

PLANESPOTTERS_UA = "CanadairsGironde/0.1 (+mailto:angledroit@gmail.com)"
PLANESPOTTERS_URL = "https://api.planespotters.net/pub/photos/{kind}/{value}"


def cmd_photos(args):
    import time

    db = get_db()
    rows = db.execute(
        "SELECT hex, registration FROM aircraft WHERE photo_src IS NULL" if not args.force
        else "SELECT hex, registration FROM aircraft"
    ).fetchall()
    found = 0
    for hex_, reg in rows:
        photo = None
        for kind, value in (("hex", hex_), ("reg", reg)):
            try:
                with http_get(PLANESPOTTERS_URL.format(kind=kind, value=value),
                              timeout=30, ua=PLANESPOTTERS_UA) as resp:
                    photos = json.load(resp).get("photos") or []
            except Exception as e:
                print(f"  {reg}: erreur planespotters ({kind}) : {e}", file=sys.stderr)
                continue
            if photos:
                p = photos[0]
                thumb = p.get("thumbnail_large") or p.get("thumbnail") or {}
                photo = (thumb.get("src"), p.get("link"), p.get("photographer"))
                break
        if photo:
            db.execute("UPDATE aircraft SET photo_src=?, photo_link=?, photo_credit=? WHERE hex=?",
                       (*photo, hex_))
            found += 1
            print(f"  ✔ {reg} : photo de {photo[2]}")
        else:
            print(f"  – {reg} : pas de photo")
        time.sleep(1)  # courtoisie API
    db.commit()
    print(f"Photos : {found}/{len(rows)} trouvées.")


# ---------------------------------------------------------------- export

def cmd_export(args):
    day = date.fromisoformat(args.date)
    start = datetime(day.year, day.month, day.day, tzinfo=timezone.utc).timestamp()
    end = start + 86400
    db = get_db()
    out = {"day": day.isoformat(), "attribution": "Data © adsb.lol contributors (ODbL)", "aircraft": []}
    for hex_, reg, name, typ, psrc, plink, pcredit in db.execute(
            "SELECT hex, registration, name, type, photo_src, photo_link, photo_credit"
            " FROM aircraft ORDER BY name"):
        points = db.execute(
            "SELECT ts, lat, lon, alt_ft, on_ground, gs_kt, track_deg, flags FROM positions"
            " WHERE hex = ? AND ts >= ? AND ts < ? ORDER BY ts",
            (hex_, start, end),
        ).fetchall()
        # ne garder que les appareils passés par la zone Gironde/Landes ce jour-là
        # (les A400M et autres militaires volent partout dans le monde)
        in_zone = any(43.4 <= p[1] <= 45.6 and -1.6 <= p[2] <= 0.2 for p in points)
        if points and in_zone:
            ac = {"hex": hex_, "registration": reg, "name": name, "type": typ, "points": points}
            if psrc:
                ac["photo"] = {"src": psrc, "link": plink, "credit": pcredit}
            out["aircraft"].append(ac)
    out["fires"] = db.execute(
        "SELECT ts, lat, lon, frp FROM fires WHERE ts >= ? AND ts < ? ORDER BY ts", (start, end)
    ).fetchall()
    out["wind"] = db.execute(
        "SELECT ts, speed_kmh, dir_deg FROM wind WHERE ts >= ? AND ts < ? ORDER BY ts", (start, end)
    ).fetchall()
    out["air"] = db.execute(
        "SELECT ts, lat, lon, aqi FROM air WHERE ts >= ? AND ts < ? ORDER BY ts", (start, end)
    ).fetchall()
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    path = EXPORT_DIR / f"{day.isoformat()}.json"
    path.write_text(json.dumps(out, separators=(",", ":")), encoding="utf-8")
    days = sorted(p.stem for p in EXPORT_DIR.glob("????-??-??.json"))
    (EXPORT_DIR / "index.json").write_text(json.dumps({"days": days}), encoding="utf-8")
    n = sum(len(a["points"]) for a in out["aircraft"])
    print(f"Écrit {path} — {len(out['aircraft'])} appareil(s), {n} points, {len(out['fires'])} feux.")


# ---------------------------------------------------------------- status

def cmd_status(args):
    db = get_db()
    print("Jours ingérés :")
    for day, tag, at, n in db.execute("SELECT * FROM ingested_days ORDER BY day"):
        print(f"  {day}  {n:>7} points  ({tag})")
    print("Points par appareil :")
    rows = db.execute(
        "SELECT a.name, a.registration, a.hex, COUNT(p.ts) FROM aircraft a"
        " LEFT JOIN positions p ON p.hex = a.hex GROUP BY a.hex ORDER BY a.name"
    )
    for name, reg, hex_, n in rows:
        print(f"  {name:<12} {reg}  {hex_}  {n:>7} points")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("fleet", help="résout les immatriculations en codes hex").set_defaults(func=cmd_fleet)

    p = sub.add_parser("ingest", help="ingère un jour de données adsb.lol")
    p.add_argument("date", nargs="?", help="YYYY-MM-DD (défaut : hier)")
    p.add_argument("--source", default="prod-0", help="variante de release (défaut : prod-0)")
    p.add_argument("--force", action="store_true", help="ré-ingérer même si déjà fait")
    p.set_defaults(func=cmd_ingest)

    sub.add_parser("today", help="récupère les traces live (~24 h) de la flotte pour le jour courant").set_defaults(func=cmd_today)

    p = sub.add_parser("discover", help="détecte les moyens aériens engagés via l'API live et les ajoute à la flotte")
    p.add_argument("--lat", type=float, default=44.6)
    p.add_argument("--lon", type=float, default=-1.0)
    p.add_argument("--radius", type=int, default=100, help="rayon en milles nautiques")
    p.set_defaults(func=cmd_discover)

    p = sub.add_parser("fires", help="récupère les points chauds NASA FIRMS (Gironde+Landes)")
    p.add_argument("date", nargs="?", help="YYYY-MM-DD, début de plage (défaut : hier)")
    p.add_argument("--days", type=int, default=1, help="nombre de jours à partir de la date")
    p.set_defaults(func=cmd_fires)

    p = sub.add_parser("export", help="exporte un jour en JSON pour le frontend")
    p.add_argument("date", help="YYYY-MM-DD")
    p.set_defaults(func=cmd_export)

    p = sub.add_parser("air", help="récupère la qualité de l'air (Open-Meteo/CAMS, grille horaire)")
    p.add_argument("date", nargs="?", help="YYYY-MM-DD, début de plage (défaut : hier)")
    p.add_argument("--days", type=int, default=1, help="nombre de jours")
    p.set_defaults(func=cmd_air)

    p = sub.add_parser("wind", help="récupère le vent horaire (Open-Meteo, pour la fumée)")
    p.add_argument("date", nargs="?", help="YYYY-MM-DD, début de plage (défaut : hier)")
    p.add_argument("--days", type=int, default=1, help="nombre de jours")
    p.set_defaults(func=cmd_wind)

    p = sub.add_parser("photos", help="récupère les photos des appareils (planespotters.net)")
    p.add_argument("--force", action="store_true", help="rafraîchir aussi les photos déjà en cache")
    p.set_defaults(func=cmd_photos)

    sub.add_parser("status", help="résumé de la base").set_defaults(func=cmd_status)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
