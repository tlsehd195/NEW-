#!/usr/bin/env bash
# One-time setup for running the Paper Trading scheduler on a fresh
# Oracle Cloud Always Free VM (ADR-0081). Run this ON THE VM itself,
# after SSH access is confirmed (docs/operations/ORACLE-CLOUD-DEPLOYMENT.md
# Part A). Idempotent-ish: safe to re-run, but a second run will ask
# again for anything it can't detect is already done.
set -euo pipefail

REPO_DIR="${REPO_DIR:-$HOME/aiinvest}"
DATA_DIR="$REPO_DIR/data"

echo "== 1. Installing system packages =="
sudo apt-get update -y
sudo apt-get install -y git python3 python3-venv python3-pip

if [ -d "$REPO_DIR/.git" ]; then
    echo "== 2. Repository already cloned at $REPO_DIR, skipping clone =="
else
    echo "== 2. Cloning repository =="
    read -rp "Repository URL (e.g. https://github.com/tlsehd195/NEW-.git): " REPO_URL
    read -rp "Is this repository private? [y/N]: " IS_PRIVATE
    if [[ "$IS_PRIVATE" =~ ^[Yy]$ ]]; then
        read -rsp "GitHub Personal Access Token (input hidden, not stored): " GH_TOKEN
        echo
        AUTH_URL="$(echo "$REPO_URL" | sed -E "s#https://#https://${GH_TOKEN}@#")"
        git clone "$AUTH_URL" "$REPO_DIR"
        unset GH_TOKEN AUTH_URL
    else
        git clone "$REPO_URL" "$REPO_DIR"
    fi
fi

echo "== 3. Creating Python virtual environment =="
cd "$REPO_DIR"
if [ ! -d "venv" ]; then
    python3 -m venv venv
fi
# shellcheck disable=SC1091
source venv/bin/activate
pip install --upgrade pip
pip install -e .
pip install duckdb pyarrow

echo "== 4. Creating data directories =="
mkdir -p "$DATA_DIR/real_market_data" "$DATA_DIR/paper_trading_store"

echo
echo "================================================================"
echo "Setup complete."
echo
echo "Before the first scheduled run, populate the market data catalog"
echo "manually once, e.g.:"
echo "  cd $REPO_DIR && source venv/bin/activate"
echo "  python3 scripts/ingest_real_market_data.py --symbols <...> \\"
echo "      --start <YYYY-MM-DD> --end <YYYY-MM-DD> \\"
echo "      --db-path $DATA_DIR/real_market_data \\"
echo "      --manifest-out $DATA_DIR/real_market_data/manifest.json"
echo
echo "Then register this crontab line (crontab -e), matching ADR-0075:"
echo
echo "30 21 * * 1-5 cd $REPO_DIR && flock -n /tmp/paper_trading_cycle.lock \\"
echo "    $REPO_DIR/venv/bin/python3 scripts/run_paper_trading_cycle.py \\"
echo "    --universe RESEARCH_UNIVERSE --db-path $DATA_DIR/real_market_data \\"
echo "    --paper-store $DATA_DIR/paper_trading_store --resume \\"
echo "    --start 2024-01-02 --end \"\$(date +\%F)\" \\"
echo "    --out $DATA_DIR/paper_trading_cycle_report.json \\"
echo "    >> $DATA_DIR/paper_trading_cycle.log 2>&1"
echo "================================================================"
