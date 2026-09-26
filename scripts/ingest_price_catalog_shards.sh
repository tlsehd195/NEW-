#!/usr/bin/env bash
# Ingests shards FROM..TO of $UNIVERSE_INPUT into $CATALOG_DIR with
# scripts/ingest_real_market_data.py --tiingo-only, sleeping
# $SHARD_SLEEP_SECONDS between shards so each shard gets a fresh Tiingo
# hourly window (ADR-0213, ingest_research_price_catalog.yml).
#
# Usage: ingest_price_catalog_shards.sh FROM TO initial-sleep|no-initial-sleep [sweep]
#   sweep: after shard TO, sleep once more and re-fetch up to
#          $SWEEP_MAX_SYMBOLS symbols of the whole universe that still
#          have no bars (a shard's symbols that failed on a timeout or a
#          spent budget).
# Env:   UNIVERSE_INPUT START_INPUT END_INPUT CATALOG_DIR SHARD_COUNT
#        SHARD_SLEEP_SECONDS SWEEP_MAX_SYMBOLS TIINGO_TIMEOUT_SECONDS
#        MARKET_DATA_API_KEY
#
# Every call passes --skip-symbols-with-bars, so a shard whose symbols
# are already in the catalog (a resumed run) spends no requests.
#
# A failing shard does not stop later shards: the ingest script's own
# exit code reflects per-symbol provider failures, and one bad symbol
# should not cost the other ~200 their hour slot. The coverage report
# run after the last shard is what gates publishing.
set -uo pipefail

from="$1"
to="$2"
sleep_mode="$3"
sweep="${4:-}"

ingest() {
  python3 scripts/ingest_real_market_data.py \
    --universe "$UNIVERSE_INPUT" \
    --start "$START_INPUT" --end "$END_INPUT" \
    --db-path "$CATALOG_DIR" \
    --tiingo-only --tiingo-timeout-seconds "$TIINGO_TIMEOUT_SECONDS" \
    --skip-symbols-with-bars \
    "$@"
}

# The hourly wait is only owed after a call that actually hit Tiingo: a
# shard whose symbols are all already covered (a resumed run) prints
# NOTHING_TO_DO and spends nothing, so the next shard need not wait.
NOTHING_TO_DO="No symbols left to fetch"
log="$(mktemp)"
owe_sleep=0
[ "$sleep_mode" = "initial-sleep" ] && owe_sleep=1

wait_if_owed() {
  if [ "$owe_sleep" -eq 1 ]; then
    echo "Sleeping ${SHARD_SLEEP_SECONDS}s before $1 (Tiingo hourly budget)."
    sleep "$SHARD_SLEEP_SECONDS"
  fi
}

record_spend() {
  if grep -q "$NOTHING_TO_DO" "$log"; then owe_sleep=0; else owe_sleep=1; fi
}

mkdir -p "$CATALOG_DIR"
failed=()
for ((shard = from; shard <= to; shard++)); do
  wait_if_owed "shard $shard"
  echo "::group::Shard $shard of $SHARD_COUNT"
  if ! ingest --manifest-out "$CATALOG_DIR/ingestion_manifest_shard_${shard}.json" \
      --shard-index "$shard" --shard-count "$SHARD_COUNT" 2>&1 | tee "$log"; then
    failed+=("$shard")
  fi
  record_spend
  echo "::endgroup::"
done

if [ "$sweep" = "sweep" ]; then
  wait_if_owed "the retry sweep"
  echo "::group::Retry sweep (symbols still without bars, at most $SWEEP_MAX_SYMBOLS)"
  if ! ingest --manifest-out "$CATALOG_DIR/ingestion_manifest_sweep.json" --max-symbols "$SWEEP_MAX_SYMBOLS" 2>&1 | tee "$log"; then
    failed+=("sweep")
  fi
  echo "::endgroup::"
fi

if [ "${#failed[@]}" -gt 0 ]; then
  echo "::warning::Shards with a non-zero ingest exit: ${failed[*]} (see each shard's log group; coverage report decides publishing)."
fi
exit 0
