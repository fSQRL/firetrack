#!/bin/sh
# Jour courant : traces live + feux + vent + export. Lancé toutes les 30 min par cron.
cd "$(dirname "$0")/.." || exit 1
echo "=== $(date -u +%FT%TZ) live ==="
python3 backend/cli.py today
python3 backend/cli.py fires "$(date +%F)"
python3 backend/cli.py wind "$(date +%F)"
python3 backend/cli.py air "$(date +%F)"
python3 backend/cli.py export "$(date +%F)"
