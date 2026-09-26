#!/usr/bin/env bash
# Ingests shards FROM..TO of $UNIVERSE_INPUT into $CATALOG_DIR with
# scripts/ingest_real_market_data.py --tiingo-only, sleeping
# $SHARD_SLEEP_SECONDS between shards so each shard gets a fresh Tiingo
# hourly window (ADR-0213, ingest_research_price_catalog.yml).
#
# Usage: ingest_price_catalog_shards.sh FROM TO initial-sleep|no-initial-sleep
# Env:   UNIVERSE_INPUT START_INPUT END_INPUT CATALOG_DIR SHARD_COUNT
#        SHARD_SLEEP_SECONDS MARKET_DATA_API_KEY
#
# A failing shard does not stop later shards: the ingest script's own
# exit code reflects per-symbol provider failures, and one bad symbol
# should not cost the other ~200 their hour slot. The coverage report
# run after the last shard is what gates publishing.
set -uo pipefail

from="$1"
to="$2"
sleep_mode="$3"

mkdir -p "$CATALOG_DIR"
failed=()
for ((shard = from; shard <= to; shard++)); do
  if [ "$shard" -ne "$from" ] || [ "$sleep_mode" = "initial-sleep" ]; then
    echo "Sleeping ${SHARD_SLEEP_SECONDS}s before shard $shard (Tiingo hourly budget)."
    sleep "$SHARD_SLEEP_SECONDS"
  fi
  echo "::group::Shard $shard of $SHARD_COUNT"
  if ! python3 scripts/ingest_real_market_data.py \
      --universe "$UNIVERSE_INPUT" \
      --start "$START_INPUT" --end "$END_INPUT" \
      --db-path "$CATALOG_DIR" \
      --manifest-out "$CATALOG_DIR/ingestion_manifest_shard_${shard}.json" \
      --tiingo-only \
      --shard-index "$shard" --shard-count "$SHARD_COUNT"; then
    failed+=("$shard")
  fi
  echo "::endgroup::"
done

if [ "${#failed[@]}" -gt 0 ]; then
  echo "::warning::Shards with a non-zero ingest exit: ${failed[*]} (see each shard's log group; coverage report decides publishing)."
fi
exit 0
