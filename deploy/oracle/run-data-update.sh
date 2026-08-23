#!/bin/sh
set -eu

stack_dir="${ROUTE_DIFFICULTY_STACK_DIR:-/opt/stacks/route-difficulty}"
if [ "$stack_dir" != "/opt/stacks/route-difficulty" ]; then
  echo "Unexpected stack directory: $stack_dir" >&2
  exit 1
fi
cd "$stack_dir"

docker compose --env-file deploy.env pull data-builder
set +e
docker compose --env-file deploy.env --profile builder run --rm data-builder monthly
status=$?
set -e

if [ "$status" -eq 75 ]; then
  echo "Public-data request budget reached; the next daily run will resume."
  exit 75
fi
if [ "$status" -ne 0 ]; then
  echo "Dataset update failed; the current manifest remains active." >&2
  exit "$status"
fi

curl --fail --silent --show-error --max-time 15 \
  https://route.jamaifamily.duckdns.org/data/manifest.json >/dev/null
echo "Dataset release published and verified."
