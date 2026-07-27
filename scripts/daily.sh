#!/bin/sh
# Consolidation de la veille avec l'archive complète adsb.lol. Plusieurs passages par jour :
# l'ingestion est idempotente, seul le premier qui trouve la release travaille vraiment.
cd "$(dirname "$0")/.." || exit 1
echo "=== $(date -u +%FT%TZ) daily ==="
python3 backend/cli.py ingest
python3 backend/cli.py fires
python3 backend/cli.py wind
python3 backend/cli.py air
python3 backend/cli.py export "$(date -d yesterday +%F)"
