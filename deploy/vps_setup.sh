#!/usr/bin/env bash
# deploy/vps_setup.sh
# Run this ON THE VPS after cloning the repo and creating .env
# Usage: bash deploy/vps_setup.sh
#
# What it does:
#   1. Sets timezone to Chicago (CST/CDT)
#   2. Creates Python venv + installs all deps
#   3. Creates required directories (logs, data)
#   4. Installs and enables all systemd services
#   5. Runs a quick smoke test

set -e

REPO="/opt/SportsPredictor"
VENV="${REPO}/venv"

echo "====================================================="
echo " SportsPredictor VPS Setup"
echo "====================================================="

# ── 1. Timezone ──────────────────────────────────────────
echo ""
echo "[1/5] Setting timezone to America/Chicago (CST/CDT)..."
sudo timedatectl set-timezone America/Chicago
echo "      $(timedatectl | grep 'Time zone')"

# ── 2. Python venv + deps ────────────────────────────────
echo ""
echo "[2/5] Creating Python venv and installing dependencies..."
cd "${REPO}"

if [ ! -d "${VENV}" ]; then
  python3 -m venv venv
fi

source "${VENV}/bin/activate"

pip install --quiet --upgrade pip
pip install --quiet -r requirements.txt
pip install --quiet duckdb libsql-client fastapi uvicorn python-dotenv "discord.py>=2.0"

echo "      Python $(python --version) | $(pip show fastapi | grep Version)"

# ── 3. Required runtime directories ─────────────────────
echo ""
echo "[3/5] Creating runtime directories..."
mkdir -p "${REPO}/logs"
mkdir -p "${REPO}/nba/backups"
mkdir -p "${REPO}/nhl/backups"
mkdir -p "${REPO}/mlb/backups"
mkdir -p "${REPO}/PEGASUS/data/picks"
mkdir -p "${REPO}/PEGASUS/data/calibration_tables"
mkdir -p "${REPO}/PEGASUS/data/reports"
mkdir -p "${REPO}/ml_training/model_registry"
echo "      Done."

# ── 4. Verify .env exists ────────────────────────────────
echo ""
echo "[4/5] Checking .env..."
if [ ! -f "${REPO}/.env" ]; then
  echo "      ERROR: /opt/SportsPredictor/.env not found!"
  echo "      Copy deploy/env.template to .env and fill in all values."
  exit 1
fi
echo "      .env found ($(wc -l < "${REPO}/.env") lines)"

# ── 5. Install systemd services ──────────────────────────
echo ""
echo "[5/5] Installing systemd services..."
sudo cp "${REPO}/deploy/systemd/sportspredictor.service"  /etc/systemd/system/
sudo cp "${REPO}/deploy/systemd/discord-bot.service"      /etc/systemd/system/
sudo cp "${REPO}/deploy/systemd/pegasus-api.service"      /etc/systemd/system/
sudo cp "${REPO}/deploy/systemd/pegasus-daily.service"    /etc/systemd/system/
sudo cp "${REPO}/deploy/systemd/pegasus-daily.timer"      /etc/systemd/system/
# cloudflared.service requires manual config — install separately when ready

sudo systemctl daemon-reload

sudo systemctl enable sportspredictor
sudo systemctl enable discord-bot
sudo systemctl enable pegasus-api
sudo systemctl enable pegasus-daily.timer

sudo systemctl start pegasus-api
sudo systemctl start discord-bot

echo ""
echo "====================================================="
echo " Setup complete. Start the orchestrator manually once"
echo " databases have been transferred (Step 4 in MIGRATION.md)"
echo ""
echo " Start orchestrator:   sudo systemctl start sportspredictor"
echo " Start PEGASUS timer:  sudo systemctl start pegasus-daily.timer"
echo ""
echo " Watch logs:"
echo "   sudo journalctl -fu sportspredictor"
echo "   sudo journalctl -fu pegasus-api"
echo "   sudo journalctl -fu discord-bot"
echo ""
echo " Check PEGASUS API:"
echo "   curl http://localhost:8600/health"
echo "====================================================="
