#!/usr/bin/env bash
# Deploy a published image set (tagged with a git SHA) on the testnet VM. Run on the VM.
# Usage: infra/scripts/deploy-testnet.sh <git-sha>
# Needs infra/env/.env with APP_DOMAIN, GHCR_OWNER, SUPABASE_DATABASE_URL and the other values from
# infra/env/.env.example. Docker must already be logged in to ghcr.io if the images are private.
set -euo pipefail

tag=${1:?usage: deploy-testnet.sh <git-sha>}
root=$(cd "$(dirname "$0")/../.." && pwd)
cd "$root"

if [[ ! "$tag" =~ ^[0-9a-f]{40}$ ]]; then
  echo "IMAGE_TAG must be a full 40-char git SHA, got: $tag" >&2
  exit 2
fi
export IMAGE_TAG=$tag

compose=(docker compose --env-file infra/env/.env
  -f infra/compose.yaml -f infra/compose.supabase.yaml
  -f infra/compose.sepolia.yaml -f infra/compose.testnet.yaml --profile testnet)

"${compose[@]}" config --quiet
"${compose[@]}" pull
# MinIO and its bucket init are built from infra/minio, not published to GHCR.
"${compose[@]}" build minio minio-init
"${compose[@]}" run --rm migrate
"${compose[@]}" up -d --no-build --remove-orphans
"${compose[@]}" ps
