#!/usr/bin/env bash
set -euo pipefail
# Usage: ./backup_mysql.sh [output-file]
# Default output path: backups/contractscan_YYYYmmddHHMMSS.sql.gz

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
OUTDIR="$REPO_ROOT/backups"
mkdir -p "$OUTDIR"
TS=$(date +%Y%m%d%H%M%S)
OUTFILE="${1:-$OUTDIR/contractscan_${TS}.sql.gz}"

echo "Creating MySQL backup to $OUTFILE"
docker exec -i contractscan_mysql sh -c 'exec mysqldump -u"$MYSQL_USER" -p"$MYSQL_PASSWORD" "$MYSQL_DATABASE"' | gzip > "$OUTFILE"

echo "Backup completed: $OUTFILE"
