#!/bin/bash
set -euo pipefail

IMAGE_TAG=${1:-latest}
COMPOSE_FILE="docker-compose.prod.yml"

echo "=== Deploying image: ${IMAGE_TAG} ==="

# 1. Pull new image
IMAGE_TAG=$IMAGE_TAG docker compose -f $COMPOSE_FILE pull server-1 server-2 celery-worker

# 2. Rolling update: server-1 first
echo "--- Updating server-1 ---"
IMAGE_TAG=$IMAGE_TAG docker compose -f $COMPOSE_FILE up -d --no-deps server-1
sleep 10

# Health check server-1
for i in $(seq 1 12); do
    if docker compose -f $COMPOSE_FILE exec server-1 python -c "import httpx; httpx.get('http://localhost:8000/api/v1/health').raise_for_status()" 2>/dev/null; then
        echo "server-1 healthy"
        break
    fi
    if [ $i -eq 12 ]; then
        echo "server-1 failed health check"
        exit 1
    fi
    sleep 5
done

# 3. Update server-2
echo "--- Updating server-2 ---"
IMAGE_TAG=$IMAGE_TAG docker compose -f $COMPOSE_FILE up -d --no-deps server-2
sleep 10

# Health check server-2
for i in $(seq 1 12); do
    if docker compose -f $COMPOSE_FILE exec server-2 python -c "import httpx; httpx.get('http://localhost:8000/api/v1/health').raise_for_status()" 2>/dev/null; then
        echo "server-2 healthy"
        break
    fi
    if [ $i -eq 12 ]; then
        echo "server-2 failed health check"
        exit 1
    fi
    sleep 5
done

# 4. Update celery worker/beat
echo "--- Updating celery ---"
IMAGE_TAG=$IMAGE_TAG docker compose -f $COMPOSE_FILE up -d --no-deps celery-worker celery-beat

# 5. Reload nginx (upstream refresh)
docker compose -f $COMPOSE_FILE exec nginx nginx -s reload

echo "=== Deploy complete: ${IMAGE_TAG} ==="
