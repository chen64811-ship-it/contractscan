#!/usr/bin/env bash
#set -euo pipefail

# Start services
docker-compose up -d

# Wait for contractscan health
for i in {1..60}; do
  STATUS=$(docker inspect --format='{{json .State.Health.Status}}' contractscan 2>/dev/null || echo "null")
  if [[ "$STATUS" == '"healthy"' ]]; then
    echo "contractscan is healthy"
    break
  fi
  echo "Waiting for contractscan to become healthy... ($i)"
  sleep 2
done

# Show health endpoint
curl -sS http://localhost:8000/api/health || true

echo "Demo complete. Open http://localhost:8000 in your browser."
