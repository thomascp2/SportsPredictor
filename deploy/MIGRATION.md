# VPS Migration Guide — SportsPredictor + PEGASUS

**Goal:** Move everything from local Windows machine to DigitalOcean VPS.  
**Status:** In progress  
**Started:** 2026-04-17

---

## Path Audit Result: ALL CLEAR

Ran full audit across all production Python files. **No hardcoded Windows paths in production code.**

- `orchestrator.py`, all sport configs, PEGASUS — all use `Path(__file__).parent` (portable)
- `sys.executable` used for all subprocess calls (portable)
- UTF-8 encoding explicitly set throughout (no Windows cp1252 dependency)
- Only Windows-path references found: `nba/scripts/backfill_threes_regrade.py` (one-time script, comment only) and `gsd_module/tests/` (test files, not production)

**No code changes needed before deploying.**

---

## What Transfers

| What | Size | Method |
|---|---|---|
| Code (all scripts, PEGASUS) | — | `git clone` |
| `nba/database/nba_predictions.db` | ~247 MB | rsync |
| `nhl/database/nhl_predictions_v2.db` | ~89 MB | rsync |
| `nhl/database/hits_blocks.db` | ~40 KB | rsync |
| `mlb/database/mlb_predictions.db` | ~97 MB | rsync |
| `nhl/database/elo_ratings_nhl.json` | ~5 KB | rsync |
| `nba/database/elo_ratings_nba.json` | ~5 KB | rsync |
| `ml_training/model_registry/nba/` | ~53 MB | rsync |
| `ml_training/model_registry/nhl/` | ~39 MB | rsync |
| `ml_training/model_registry/mlb_szln/` | ~5 MB | rsync |
| `PEGASUS/data/` | ~319 KB | rsync |
| `.env` credentials | — | create manually |

**Do NOT transfer:** `mlb/backups/` (2.5 GB), `logs/`, Python venv, `mlb_feature_store/.venv/`

---

## Step 1: Prep on Desktop

Commit all working changes before doing anything else:

```bash
git add -A
git commit -m "Pre-VPS migration — sync all working changes"
git push origin master
```

Collect all env vars from `start_orchestrator.bat` — you'll need them for the `.env` file on VPS.
See `deploy/env.template` for the full list.

---

## Step 2: VPS Initial Setup

SSH into your DO droplet. All commands below run on the VPS.

```bash
# Install Python 3.11+ (Ubuntu/Debian)
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3 python3-pip python3-venv git

# Verify Python version (need 3.10+)
python3 --version

# Clone repo
cd /opt
sudo git clone https://github.com/thomascp2/SportsPredictor.git
sudo chown -R $USER:$USER SportsPredictor
cd SportsPredictor

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install all dependencies
pip install -r requirements.txt
pip install duckdb libsql-client fastapi uvicorn python-dotenv discord.py
```

---

## Step 3: Create .env on VPS

```bash
nano /opt/SportsPredictor/.env
```

Paste all credentials — see `deploy/env.template` for the full template.

Protect the file:
```bash
chmod 600 /opt/SportsPredictor/.env
```

---

## Step 4: Transfer Data Files

Run these from your **local Windows desktop** (Git Bash terminal).  
Replace `YOUR_VPS_IP` with your DigitalOcean droplet IP.

```bash
# See deploy/transfer.sh — copy-paste commands or run the script directly
bash deploy/transfer.sh YOUR_VPS_IP
```

---

## Step 5: Install Systemd Services

On the VPS, copy service files and enable:

```bash
# Copy all service files
sudo cp /opt/SportsPredictor/deploy/systemd/*.service /etc/systemd/system/
sudo cp /opt/SportsPredictor/deploy/systemd/*.timer /etc/systemd/system/

# Reload and enable
sudo systemctl daemon-reload
sudo systemctl enable --now sportspredictor
sudo systemctl enable --now discord-bot
sudo systemctl enable --now pegasus-api
sudo systemctl enable --now pegasus-daily.timer
```

---

## Step 6: Verify Services

```bash
# Check each service is running
sudo systemctl status sportspredictor
sudo systemctl status discord-bot
sudo systemctl status pegasus-api
sudo systemctl status pegasus-daily.timer

# Watch live orchestrator logs
sudo journalctl -fu sportspredictor

# Check PEGASUS API is responding
curl http://localhost:8600/health
```

Also check the pipeline logs once it's been running for a day:
```bash
tail -f /opt/SportsPredictor/logs/pipeline_nba_$(date +%Y%m%d).log
```

---

## Step 7: Expose FastAPI (Cloudflare Tunnel)

The `cloudflared.exe` from Windows won't work on Linux. Use the Linux binary.

```bash
# Download cloudflared for Linux
wget https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64
chmod +x cloudflared-linux-amd64
sudo mv cloudflared-linux-amd64 /usr/local/bin/cloudflared

# Option A: Quick tunnel (URL changes each restart — for testing)
cloudflared tunnel --url http://localhost:8600

# Option B: Named tunnel (fixed URL — recommended for production)
# Follow: https://developers.cloudflare.com/cloudflare-one/connections/connect-apps/install-and-setup/
```

For a persistent named tunnel, add a `cloudflared.service` to systemd (see below).

---

## Step 8: Update Mobile App API URL

Once the FastAPI is stable on the VPS, update the mobile app to point at the VPS:

- File: `mobile/src/utils/constants.ts` or `mobile/src/services/api.ts`
- Change the PEGASUS API base URL from `localhost:8600` to `https://your-vps-domain.com`

---

## Step 9: Cutover Checklist

Before stopping the local machine:

- [ ] VPS orchestrator has run prediction pipeline at least once successfully
- [ ] VPS Discord bot is responding to commands in Discord
- [ ] PEGASUS API `/health` returns 200
- [ ] PEGASUS `run_daily.py` has run at least once and written to Turso
- [ ] Mobile app picks are loading from VPS FastAPI
- [ ] All 4 sports producing logs in `/opt/SportsPredictor/logs/`

Once all boxes checked, stop the desktop processes:
- Close `start_orchestrator.bat`
- Close `start_bot.bat`

---

## Ongoing Maintenance on VPS

```bash
# Pull code updates
cd /opt/SportsPredictor && git pull && sudo systemctl restart sportspredictor

# View live logs
sudo journalctl -fu sportspredictor -n 100
sudo journalctl -fu pegasus-api -n 50

# Restart a service
sudo systemctl restart sportspredictor

# Manually run PEGASUS (one-off)
cd /opt/SportsPredictor
source venv/bin/activate
python PEGASUS/run_daily.py
```

---

## Known Issues / Watch-Outs

1. **SQLite concurrency**: The orchestrator and PEGASUS both read SQLite. SQLite handles concurrent readers fine. PEGASUS is read-only so no write conflicts.
2. **mlb_feature_store DuckDB**: PEGASUS config points to `ROOT/mlb_feature_store/data/mlb.duckdb`. That file was not in the rsync list above — check if it exists on desktop and transfer if needed.
3. **Timezone**: VPS may run UTC. The orchestrator schedule times (e.g., "09:00") are assumed CST. Either set VPS timezone to CST or convert all schedule times to UTC.
4. **Discord bot permissions**: The bot must be invited to your server. If running on VPS only, make sure the bot token in `.env` matches the production bot.
5. **mission_control.py**: References `.bat` files (`scripts\nba_game_predictions.bat`). This appears to be an unused/legacy file — do not run it on VPS.

---

## Timezone Fix (IMPORTANT)

The orchestrator uses local system time for scheduling. Set VPS to CST/CDT:

```bash
sudo timedatectl set-timezone America/Chicago
timedatectl  # verify
```

---

## Session Bookmarks

- **2026-04-17**: Migration started. Path audit complete (all clear). Service files created. Transfer script ready. Next: execute Steps 2–9 on actual VPS.
