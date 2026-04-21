#!/usr/bin/env bash
# deploy/transfer.sh
# Run from repo root on your LOCAL Windows desktop (Git Bash)
# Usage: bash deploy/transfer.sh YOUR_VPS_IP
#
# Transfers all data files that are gitignored (databases, models, PEGASUS data).
# Does NOT transfer: mlb/backups/ (2.5 GB), logs/, venvs.

set -e

VPS_IP="${1:?Usage: bash deploy/transfer.sh YOUR_VPS_IP}"
VPS_USER="root"  # change if your DO droplet uses a different user
REMOTE="${VPS_USER}@${VPS_IP}"
REPO="/opt/SportsPredictor"

echo "====================================================="
echo " SportsPredictor Data Transfer"
echo " Destination: ${REMOTE}:${REPO}"
echo "====================================================="

# Create remote database directories
ssh "${REMOTE}" "mkdir -p ${REPO}/nba/database ${REPO}/nhl/database ${REPO}/mlb/database ${REPO}/ml_training/model_registry ${REPO}/PEGASUS/data"

echo ""
echo "[1/6] NBA database (247 MB)..."
rsync -avz --progress \
  nba/database/nba_predictions.db \
  nba/database/elo_ratings_nba.json \
  "${REMOTE}:${REPO}/nba/database/"

echo ""
echo "[2/6] NHL database (89 MB)..."
rsync -avz --progress \
  nhl/database/nhl_predictions_v2.db \
  nhl/database/hits_blocks.db \
  nhl/database/elo_ratings_nhl.json \
  "${REMOTE}:${REPO}/nhl/database/"

echo ""
echo "[3/6] MLB database (97 MB)..."
rsync -avz --progress \
  mlb/database/mlb_predictions.db \
  "${REMOTE}:${REPO}/mlb/database/"

echo ""
echo "[4/6] ML model registry (97 MB)..."
rsync -avz --progress \
  ml_training/model_registry/ \
  "${REMOTE}:${REPO}/ml_training/model_registry/"

echo ""
echo "[5/6] PEGASUS data (calibration tables, picks JSON)..."
rsync -avz --progress \
  PEGASUS/data/ \
  "${REMOTE}:${REPO}/PEGASUS/data/"

echo ""
echo "[6/6] Checking for MLB DuckDB (mlb_feature_store)..."
if [ -f "mlb_feature_store/data/mlb.duckdb" ]; then
  ssh "${REMOTE}" "mkdir -p ${REPO}/mlb_feature_store/data"
  rsync -avz --progress \
    mlb_feature_store/data/mlb.duckdb \
    "${REMOTE}:${REPO}/mlb_feature_store/data/"
  echo "     Transferred mlb.duckdb"
else
  echo "     mlb_feature_store/data/mlb.duckdb not found locally — skipping"
  echo "     PEGASUS MLB XGBoost blend will be unavailable until this is seeded"
fi

echo ""
echo "====================================================="
echo " Transfer complete."
echo " Next: SSH into VPS and run deploy/systemd setup"
echo "====================================================="
