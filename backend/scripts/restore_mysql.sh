#!/usr/bin/env bash
set -euo pipefail
# Usage: ./restore_mysql.sh backups/file.sql.gz

if [ $# -lt 1 ]; then
  echo "Usage: $0 <backup-file.sql.gz>"
  exit 1
fi

FILE="$1"
if [ ! -f "$FILE" ]; then
  echo "Backup file not found: $FILE"
  exit 1
fi

echo "Restoring $FILE into MySQL container..."
gunzip -c "$FILE" | docker exec -i contractscan_mysql sh -c 'exec mysql -u"$MYSQL_USER" -p"$MYSQL_PASSWORD" "$MYSQL_DATABASE"'
echo "Restore completed."
