#!/bin/sh
set -eu

stack_dir="${ROUTE_DIFFICULTY_STACK_DIR:-/opt/stacks/route-difficulty}"
if [ "$stack_dir" != "/opt/stacks/route-difficulty" ]; then
  echo "Unexpected stack directory: $stack_dir" >&2
  exit 1
fi
cd "$stack_dir"

image_tag=$(sed -n 's/^ROUTE_DIFFICULTY_IMAGE_TAG=//p' deploy.env | tail -n 1)
image_tag=${image_tag:-main}
image_ref="ghcr.io/jamaica8612/route-difficulty-web:$image_tag"
previous_image=$(docker inspect --format '{{.Image}}' route-difficulty-web 2>/dev/null || true)

docker compose --env-file deploy.env pull web
candidate_image=$(docker image inspect --format '{{.Id}}' "$image_ref")
if [ -n "$previous_image" ] && [ "$previous_image" = "$candidate_image" ]; then
  echo "Web image is already current."
  exit 0
fi

docker compose --env-file deploy.env up -d --no-deps web
attempt=0
while [ "$attempt" -lt 12 ]; do
  if curl --fail --silent --max-time 5 https://route.jamaifamily.duckdns.org/healthz >/dev/null; then
    echo "Web image updated and health check passed."
    exit 0
  fi
  attempt=$((attempt + 1))
  sleep 5
done

if [ -n "$previous_image" ]; then
  echo "New web image failed health verification; restoring previous image." >&2
  docker tag "$previous_image" "$image_ref"
  docker compose --env-file deploy.env up -d --no-deps --force-recreate web
fi
exit 1
