#!/bin/bash
set -euo pipefail

PREVIOUS_TAG=${1:?"Usage: rollback.sh <previous_image_tag>"}
echo "=== Rolling back to: ${PREVIOUS_TAG} ==="

bash "$(dirname "$0")/deploy.sh" "$PREVIOUS_TAG"
