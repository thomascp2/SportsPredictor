# Post-Migration Pre-Work — 2026-04-18

Migration completed evening of 2026-04-17. VPS is live and running autonomously.
This doc covers what to monitor and what to finish next session.

---

## First Thing — Verify Overnight Ran

Check Discord for notifications that should have fired overnight:
- NBA grading (~5 AM CST)
- NHL grading (~3 AM CST)
- NBA predictions (~6 AM CST)
- NHL predictions (~4 AM CST)
- MLB predictions (~10 AM CST)
- Top picks Discord post (~2 PM CST)

If any are missing, SSH in and check logs:
```bash
ssh root@YOUR_VPS_IP
sudo journalctl -fu sportspredictor -n 200
tail -f /opt/SportsPredictor/logs/pipeline_nba_$(date +%Y%m%d).log
```

---

## Second — Verify Timezone is Set

The vps_setup.sh set this but double check:
```bash
timedatectl
```
Should show `America/Chicago`. If not:
```bash
sudo timedatectl set-timezone America/Chicago
sudo systemctl restart sportspredictor
```

---

## Remaining Tasks (Next Session)

### 1. Dashboard on VPS (15 min)
Add a streamlit systemd service so the dashboard runs on the VPS permanently.
- Create `deploy/systemd/streamlit.service`
- Put it behind a Cloudflare tunnel (download Linux cloudflared binary)
- Update `deploy/MIGRATION.md`

### 2. Mobile App API URL (5 min)
Update mobile to point at VPS FastAPI instead of localhost:
- File: `mobile/src/services/api.ts` or `mobile/src/utils/constants.ts`
- Change PEGASUS base URL to `http://YOUR_VPS_IP:8600` (or Cloudflare tunnel URL)

### 3. PEGASUS run_daily.py First Run
Confirm the pegasus-daily.timer fired at 2 PM CST and wrote picks to Turso.
Check:
```bash
sudo journalctl -u pegasus-daily -n 50
ls /opt/SportsPredictor/PEGASUS/data/picks/
```

### 4. Easy Deploy Alias (2 min)
Add to VPS `~/.bashrc` so deploys are one command:
```bash
echo "alias deploy='cd /opt/SportsPredictor && git pull && systemctl restart sportspredictor discord-bot pegasus-api && echo Deployed OK'" >> ~/.bashrc
source ~/.bashrc
```
Then from local machine: `ssh root@YOUR_VPS_IP deploy`

### 5. mlb_feature_store DuckDB (if needed)
PEGASUS MLB XGBoost blend reads from `mlb_feature_store/data/mlb.duckdb`.
Check if it exists on VPS:
```bash
ls /opt/SportsPredictor/mlb_feature_store/data/
```
If missing, transfer from local:
```bash
# Local Git Bash
scp -o PubkeyAuthentication=no -o PasswordAuthentication=yes mlb_feature_store/data/mlb.duckdb root@YOUR_VPS_IP:/opt/SportsPredictor/mlb_feature_store/data/
```

---

## Deploy Code Changes Going Forward

```bash
# Local machine (after git push):
ssh root@YOUR_VPS_IP "cd /opt/SportsPredictor && git pull && systemctl restart sportspredictor discord-bot pegasus-api"
```

---

## VPS Quick Reference

| What | Command |
|---|---|
| Watch orchestrator live | `sudo journalctl -fu sportspredictor` |
| Watch PEGASUS API | `sudo journalctl -fu pegasus-api` |
| Watch Discord bot | `sudo journalctl -fu discord-bot` |
| Restart everything | `sudo systemctl restart sportspredictor discord-bot pegasus-api` |
| PEGASUS API health | `curl http://localhost:8600/health` |
| Run PEGASUS manually | `source venv/bin/activate && python PEGASUS/run_daily.py` |
| Check all services | `sudo systemctl status sportspredictor discord-bot pegasus-api` |
