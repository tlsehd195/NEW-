#!/usr/bin/env bash
# Ingests batches FROM..TO of the symbols in $SYMBOLS_FILE (one per line,
# $BATCH_SIZE per batch) into $CATALOG_DIR with
# scripts/ingest_real_market_data.py --tiingo-only --symbols, sleeping
# $BATCH_SLEEP_SECONDS between batches so each gets a fresh Tiingo
# hourly window (ADR-0224, extend_research_price_catalog.yml). The same
# shape as ingest_price_catalog_shards.sh, for an explicit symbol list
# instead of a named universe.
#
# Usage: ingest_symbol_batches.sh FROM TO initial-sleep|no-initial-sleep
# Env:   SYMBOLS_FILE BATCH_SIZE START_INPUT END_INPUT CATALOG_DIR
#        BATCH_SLEEP_SECONDS TIINGO_TIMEOUT_SECONDS MARKET_DATA_API_KEY
#
# --skip-symbols-with-bars makes a rerun or resume free for symbols
# already fetched, and a batch with nothing left owes no hourly wait.
# A failing batch does not stop later ones (a symbol past Tiingo's
# monthly unique-symbol cap fails alone); the coverage step decides
# what is published.
set -uo pipefail

from="$1"
to="$2"
sleep_mode="$3"

mapfile -t all_symbols < <(grep -v '^[[:space:]]*$' "$SYMBOLS_FILE")
batch_count=$(( (${#all_symbols[@]} + BATCH_SIZE - 1) / BATCH_SIZE ))
echo "${#all_symbols[@]} symbols, $batch_count batches of $BATCH_SIZE."

NOTHING_TO_DO="No symbols left to fetch"
log="$(mktemp)"
owe_sleep=0
[ "$sleep_mode" = "initial-sleep" ] && owe_sleep=1

mkdir -p "$CATALOG_DIR"
for ((batch = from; batch <= to && batch < batch_count; batch++)); do
  symbols=("${all_symbols[@]:$((batch * BATCH_SIZE)):$BATCH_SIZE}")
  if [ "$owe_sleep" -eq 1 ]; then
    echo "Sleeping ${BATCH_SLEEP_SECONDS}s before batch $batch (Tiingo hourly budget)."
    sleep "$BATCH_SLEEP_SECONDS"
  fi
  echo "::group::Batch $batch: ${symbols[*]}"
  python3 scripts/ingest_real_market_data.py \
    --symbols "${symbols[@]}" \
    --start "$START_INPUT" --end "$END_INPUT" \
    --db-path "$CATALOG_DIR" \
    --tiingo-only --tiingo-timeout-seconds "$TIINGO_TIMEOUT_SECONDS" \
    --skip-symbols-with-bars \
    --manifest-out "$CATALOG_DIR/ingestion_manifest_extend_batch_${batch}.json" 2>&1 | tee "$log" \
    || echo "::warning::Batch $batch exited non-zero (see its log group)."
  if grep -q "$NOTHING_TO_DO" "$log"; then owe_sleep=0; else owe_sleep=1; fi
  echo "::endgroup::"
done
exit 0
