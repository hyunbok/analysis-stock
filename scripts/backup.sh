#!/bin/bash
set -euo pipefail

BACKUP_DIR="./backups"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
COMPOSE_FILE="docker-compose.prod.yml"

mkdir -p "${BACKUP_DIR}/postgres" "${BACKUP_DIR}/mongodb"

echo "=== Starting backup: ${TIMESTAMP} ==="

# PostgreSQL backup
echo "--- PostgreSQL backup ---"
docker compose -f $COMPOSE_FILE exec -T postgres \
    pg_dump -U cointrader -Fc cointrader \
    > "${BACKUP_DIR}/postgres/cointrader_${TIMESTAMP}.dump"
echo "PostgreSQL backup saved: ${BACKUP_DIR}/postgres/cointrader_${TIMESTAMP}.dump"

# MongoDB backup
echo "--- MongoDB backup ---"
docker compose -f $COMPOSE_FILE exec -T mongodb \
    mongodump --archive --gzip \
    --username cointrader --password "${MONGO_PASSWORD:-password}" --authenticationDatabase admin \
    --db cointrader \
    > "${BACKUP_DIR}/mongodb/cointrader_${TIMESTAMP}.archive.gz"
echo "MongoDB backup saved: ${BACKUP_DIR}/mongodb/cointrader_${TIMESTAMP}.archive.gz"

# Cleanup old backups (keep last 7 days)
echo "--- Cleaning up old backups ---"
find "${BACKUP_DIR}" -type f -mtime +7 -delete

echo "=== Backup complete: ${TIMESTAMP} ==="
