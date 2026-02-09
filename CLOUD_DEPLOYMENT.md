# Cloud Deployment Guide

## Quick Cost Comparison

| Option | Monthly Cost | Setup Time | Best For |
|--------|-------------|------------|----------|
| DigitalOcean Droplet | $6-12 | 30 min | Reliability + SSH access |
| Railway | $5-20 | 15 min | Easy GitHub deploy |
| PythonAnywhere | $5-12 | 20 min | Python-specific, built-in scheduler |
| AWS EC2 Free Tier | $0-5 | 1 hour | Free first year |

## Recommended: DigitalOcean ($6/month)

### Step 1: Create Droplet
1. Sign up at https://digitalocean.com
2. Create Droplet:
   - Image: Ubuntu 22.04
   - Plan: Basic $6/month (1GB RAM, 25GB SSD)
   - Region: New York (or closest to you)
   - Authentication: SSH key (recommended) or password

### Step 2: Initial Setup
```bash
# SSH into your droplet
ssh root@your_droplet_ip

# Update system
apt update && apt upgrade -y

# Install Python and dependencies
apt install python3 python3-pip python3-venv git -y

# Create app user
adduser sportsbot
usermod -aG sudo sportsbot
su - sportsbot

# Clone your repo (or upload files)
git clone https://github.com/yourusername/SportsPredictor.git
cd SportsPredictor

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
pip install discord.py schedule requests fuzzywuzzy python-Levenshtein
```

### Step 3: Set Environment Variables
```bash
# Create .env file
cat > .env << 'EOF'
DISCORD_BOT_TOKEN=your_bot_token_here
NBA_DISCORD_WEBHOOK=your_nba_webhook_here
NHL_DISCORD_WEBHOOK=your_nhl_webhook_here
ANTHROPIC_API_KEY=your_key_here
EOF

# Load in bashrc
echo 'export $(cat ~/SportsPredictor/.env | xargs)' >> ~/.bashrc
source ~/.bashrc
```

### Step 4: Set Up Systemd Services

**Orchestrator Service** (runs predictions/grading on schedule):
```bash
sudo tee /etc/systemd/system/sportsbot.service << 'EOF'
[Unit]
Description=Sports Predictor Orchestrator
After=network.target

[Service]
Type=simple
User=sportsbot
WorkingDirectory=/home/sportsbot/SportsPredictor
Environment=PATH=/home/sportsbot/SportsPredictor/venv/bin
EnvironmentFile=/home/sportsbot/SportsPredictor/.env
ExecStart=/home/sportsbot/SportsPredictor/venv/bin/python orchestrator.py --sport all --mode continuous
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl enable sportsbot
sudo systemctl start sportsbot
```

**Discord Bot Service** (control from anywhere):
```bash
sudo tee /etc/systemd/system/discord-bot.service << 'EOF'
[Unit]
Description=Sports Predictor Discord Bot
After=network.target

[Service]
Type=simple
User=sportsbot
WorkingDirectory=/home/sportsbot/SportsPredictor
Environment=PATH=/home/sportsbot/SportsPredictor/venv/bin
EnvironmentFile=/home/sportsbot/SportsPredictor/.env
ExecStart=/home/sportsbot/SportsPredictor/venv/bin/python discord_bot.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl enable discord-bot
sudo systemctl start discord-bot
```

### Step 5: Verify It's Running
```bash
# Check orchestrator status
sudo systemctl status sportsbot

# Check discord bot status
sudo systemctl status discord-bot

# View logs
sudo journalctl -u sportsbot -f
sudo journalctl -u discord-bot -f
```

---

## Discord Bot Commands (from iPad/phone/anywhere)

Once the bot is running, you can control everything from Discord:

| Command | Description |
|---------|-------------|
| `!status` | Show system status, prediction counts |
| `!picks nba` | Get today's NBA smart picks |
| `!picks nba 2026-02-10` | Get picks for specific date |
| `!predict nba` | Run NBA prediction pipeline |
| `!grade nba` | Run NBA grading pipeline |
| `!health` | Check if APIs are working |
| `!refresh nba` | Refresh PrizePicks lines |

---

## Creating a Discord Bot

1. Go to https://discord.com/developers/applications
2. Click "New Application" → Name it "SportsBot"
3. Go to "Bot" → Click "Add Bot"
4. Under Token, click "Reset Token" → Copy it
5. Enable these Intents:
   - Message Content Intent
   - Server Members Intent (optional)
6. Go to OAuth2 → URL Generator:
   - Scopes: `bot`
   - Bot Permissions: `Send Messages`, `Read Message History`
7. Copy the generated URL → Open in browser → Add to your server

---

## iPad Access Options

### Option A: Discord Bot (Recommended)
- Control everything via Discord app on iPad
- Works anywhere with internet
- No special apps needed

### Option B: SSH App
- Download "Termius" or "Blink Shell" on iPad
- SSH directly into your cloud server
- Full terminal access

### Option C: Web Dashboard (Future)
- Could add Streamlit dashboard exposed via web
- Access from any browser

---

## Backup & Recovery

### Automatic Database Backup
Add to crontab on server:
```bash
crontab -e

# Add this line (daily backup at 3 AM):
0 3 * * * cp /home/sportsbot/SportsPredictor/nba/database/nba_predictions.db /home/sportsbot/backups/nba_$(date +\%Y\%m\%d).db
```

### Sync to Cloud Storage (Optional)
```bash
# Install rclone
curl https://rclone.org/install.sh | sudo bash

# Configure with Google Drive/Dropbox
rclone config

# Add to crontab for daily sync
0 4 * * * rclone sync /home/sportsbot/backups remote:SportsPredictor/backups
```

---

## Monitoring & Alerts

The Discord bot will post to your channels:
- Daily picks automatically at 10 AM
- Grading results automatically
- Error alerts if something fails

For additional monitoring:
- DigitalOcean has built-in alerting (CPU, memory, disk)
- UptimeRobot (free) can ping your bot to ensure it's online

---

## Total Monthly Cost

| Item | Cost |
|------|------|
| DigitalOcean Droplet (Basic) | $6 |
| Domain name (optional) | $1 |
| **Total** | **$6-7/month** |

No power outages. No internet issues. Accessible from anywhere.
