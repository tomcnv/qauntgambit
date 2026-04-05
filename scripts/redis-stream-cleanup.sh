#!/bin/bash
# Redis Stream Cleanup Script
# Trims streams to prevent unbounded memory growth

set -e

# Configuration
MAX_STREAM_LENGTH=${MAX_STREAM_LENGTH:-10000}  # General events retention
MAX_HOT_STREAM_LENGTH=${MAX_HOT_STREAM_LENGTH:-5000}  # orderbook/trades retention
DRY_RUN=${DRY_RUN:-false}
EXACT_TRIM=${EXACT_TRIM:-false}
REDIS_URL=${REDIS_URL:-redis://localhost:6379}
STREAM_PATTERNS=${STREAM_PATTERNS:-"events:* orderbook:* trades:*"}

echo "═══════════════════════════════════════════════════════════════"
echo "  Redis Stream Cleanup - $(date)"
echo "  General stream max length: $MAX_STREAM_LENGTH"
echo "  Hot stream max length: $MAX_HOT_STREAM_LENGTH (orderbook/trades)"
echo "  Dry run: $DRY_RUN"
echo "  Exact trim: $EXACT_TRIM"
echo "═══════════════════════════════════════════════════════════════"
echo ""

# Get current memory usage
MEMORY_BEFORE=$(redis-cli -u "$REDIS_URL" INFO memory | awk -F: '/^used_memory_human:/{gsub("\r","",$2); print $2}')
echo "Memory before cleanup: $MEMORY_BEFORE"
echo ""

TOTAL_TRIMMED=0
STREAMS_TRIMMED=0

seen_streams=""
for pattern in $STREAM_PATTERNS; do
    while IFS= read -r stream; do
        [ -z "$stream" ] && continue
        # De-dupe overlaps (e.g. custom patterns including events:* and events:trades:*)
        if printf '%s\n' "$seen_streams" | awk -v s="$stream" '$0==s{found=1} END{exit !found}'; then
            continue
        fi
        seen_streams="${seen_streams}"$'\n'"$stream"

        key_type=$(redis-cli -u "$REDIS_URL" TYPE "$stream" 2>/dev/null | tr -d '\r')
        [ "$key_type" != "stream" ] && continue

        CURRENT_LEN=$(redis-cli -u "$REDIS_URL" XLEN "$stream" 2>/dev/null | tr -d '\r')
        [ -z "$CURRENT_LEN" ] && continue

        target_len=$MAX_STREAM_LENGTH
        case "$stream" in
            orderbook:*|trades:*|events:orderbook_feed:*|events:trades:*)
                target_len=$MAX_HOT_STREAM_LENGTH
                ;;
        esac

        if [ "$CURRENT_LEN" -gt "$target_len" ]; then
            TO_TRIM=$((CURRENT_LEN - target_len))

            if [ "$DRY_RUN" = "true" ]; then
                echo "[DRY RUN] Would trim $stream: $CURRENT_LEN → $target_len (removing ~$TO_TRIM)"
            else
                if [ "$EXACT_TRIM" = "true" ]; then
                    redis-cli -u "$REDIS_URL" XTRIM "$stream" MAXLEN "=" "$target_len" > /dev/null
                else
                    # Approximate trim is much faster at high write rates.
                    redis-cli -u "$REDIS_URL" XTRIM "$stream" MAXLEN "~" "$target_len" > /dev/null
                fi
                NEW_LEN=$(redis-cli -u "$REDIS_URL" XLEN "$stream" 2>/dev/null | tr -d '\r')
                echo "Trimmed $stream: $CURRENT_LEN → $NEW_LEN (target=$target_len)"
            fi

            TOTAL_TRIMMED=$((TOTAL_TRIMMED + TO_TRIM))
            STREAMS_TRIMMED=$((STREAMS_TRIMMED + 1))
        fi
    done < <(redis-cli -u "$REDIS_URL" --scan --pattern "$pattern")
done

echo ""
echo "═══════════════════════════════════════════════════════════════"
echo "  Summary"
echo "═══════════════════════════════════════════════════════════════"
echo "Streams trimmed: $STREAMS_TRIMMED"
echo "Total messages removed: ~$TOTAL_TRIMMED"

if [ "$DRY_RUN" != "true" ]; then
    # Force memory reclamation
    redis-cli -u "$REDIS_URL" MEMORY PURGE > /dev/null 2>&1 || true
    
    sleep 2
    MEMORY_AFTER=$(redis-cli -u "$REDIS_URL" INFO memory | awk -F: '/^used_memory_human:/{gsub("\r","",$2); print $2}')
    echo "Memory after cleanup: $MEMORY_AFTER"
fi

echo ""
echo "Done!"
