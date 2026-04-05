#!/usr/bin/env bash
set -euo pipefail

# Safe Docker/Colima cleanup:
# - prunes unused images
# - prunes build cache
# - prunes stopped containers
# - reports unused volumes but does NOT delete them unless explicitly requested

IMAGE_UNTIL="${IMAGE_UNTIL:-168h}"
BUILD_CACHE_UNTIL="${BUILD_CACHE_UNTIL:-168h}"
PRUNE_UNUSED_VOLUMES="${PRUNE_UNUSED_VOLUMES:-0}"

echo "== Docker context =="
docker context show

echo
echo "== Before =="
docker system df -v || true

echo
echo "== Prune stopped containers =="
docker container prune -f || true

echo
echo "== Prune unused images older than ${IMAGE_UNTIL} =="
docker image prune -a -f --filter "until=${IMAGE_UNTIL}" || true

echo
echo "== Prune build cache older than ${BUILD_CACHE_UNTIL} =="
docker builder prune -a -f --filter "until=${BUILD_CACHE_UNTIL}" || true

echo
echo "== Unused volumes (report only by default) =="
docker volume ls -qf dangling=true | while read -r volume; do
  [ -n "${volume}" ] || continue
  size="$(docker system df -v 2>/dev/null | rg "^${volume}[[:space:]]" -o || true)"
  echo "${volume}${size:+  ${size}}"
done

if [[ "${PRUNE_UNUSED_VOLUMES}" == "1" ]]; then
  echo
  echo "== Prune unused volumes =="
  docker volume prune -f || true
else
  echo
  echo "Skipping volume prune. Set PRUNE_UNUSED_VOLUMES=1 to remove dangling volumes."
fi

echo
echo "== After =="
docker system df -v || true
