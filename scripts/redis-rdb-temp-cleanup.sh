#!/bin/bash
# Remove stale Redis temp-*.rdb files left by failed/aborted BGSAVE runs.

set -euo pipefail

REDIS_URL=${REDIS_URL:-redis://localhost:6379}
# Only delete temp files older than this many minutes.
MIN_AGE_MINUTES=${MIN_AGE_MINUTES:-120}
DRY_RUN=${DRY_RUN:-false}

REDIS_DIR=$(redis-cli -u "$REDIS_URL" CONFIG GET dir | awk 'NR==2{print}')
if [ -z "$REDIS_DIR" ] || [ ! -d "$REDIS_DIR" ]; then
  echo "Redis dir not found: $REDIS_DIR"
  exit 1
fi

BGSAVE_IN_PROGRESS=$(redis-cli -u "$REDIS_URL" INFO persistence | awk -F: '/^rdb_bgsave_in_progress:/{gsub("\r","",$2); print $2}')
if [ "$BGSAVE_IN_PROGRESS" = "1" ]; then
  echo "BGSAVE in progress; aborting cleanup."
  exit 0
fi

echo "Redis dir: $REDIS_DIR"
echo "Deleting temp-*.rdb older than ${MIN_AGE_MINUTES} minutes"
echo "Dry run: $DRY_RUN"

deleted=0
freed_bytes=0

while IFS= read -r file; do
  [ -z "$file" ] && continue
  size=$(stat -f%z "$file" 2>/dev/null || echo 0)
  if [ "$DRY_RUN" = "true" ]; then
    echo "[DRY RUN] Would remove: $file ($(awk -v s="$size" 'BEGIN{printf "%.2f MiB", s/1024/1024}'))"
  else
    rm -f "$file"
    echo "Removed: $file"
  fi
  deleted=$((deleted + 1))
  freed_bytes=$((freed_bytes + size))
done < <(find "$REDIS_DIR" -maxdepth 1 -type f -name 'temp-*.rdb' -mmin "+$MIN_AGE_MINUTES" -print 2>/dev/null)

echo "Files matched: $deleted"
echo "Space impacted: $(awk -v s="$freed_bytes" 'BEGIN{printf "%.2f GiB", s/1024/1024/1024}')"
