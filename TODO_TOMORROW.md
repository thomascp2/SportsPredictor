# Tomorrow's To-Do List (Feb 9, 2026)

## Morning (Before Work) - 15 min

### 1. Create NBA Discord Webhook
- [ ] Open Discord → Right-click `#nba` channel → Edit Channel
- [ ] Integrations → Webhooks → New Webhook
- [ ] Name it "NBA Smart Picks"
- [ ] Copy the webhook URL
- [ ] Edit `orchestrator.py` line ~210, replace:
  ```
  "https://discord.com/api/webhooks/YOUR_NBA_CHANNEL_WEBHOOK_HERE"
  ```
  with your copied URL

### 2. Test Smart Picks Post
```bash
cd C:\Users\thoma\SportsPredictor\shared
python smart_pick_selector.py --sport nba --date 2026-02-09 --post-discord
```

---

## On Commute - Read These Files
- `CLOUD_DEPLOYMENT.md` - Full cloud setup guide
- `discord_bot.py` - How the Discord bot works

---

## Evening (30-45 min) - Cloud Setup

### 3. Create Discord Bot
- [ ] Go to https://discord.com/developers/applications
- [ ] New Application → Name: "SportsBot"
- [ ] Bot → Add Bot → Copy Token (save it!)
- [ ] Enable "Message Content Intent"
- [ ] OAuth2 → URL Generator:
  - Scopes: `bot`
  - Permissions: `Send Messages`, `Read Message History`
- [ ] Copy URL → Open in browser → Add to your server

### 4. Create DigitalOcean Droplet ($6/month)
- [ ] Sign up at https://digitalocean.com
- [ ] Create Droplet:
  - Ubuntu 22.04
  - Basic $6/month plan
  - New York region
  - Password auth (easier for now)
- [ ] Save the IP address and password

### 5. Set Up Server (SSH from computer)
```bash
# Connect to server
ssh root@YOUR_DROPLET_IP

# Run these commands:
apt update && apt upgrade -y
apt install python3 python3-pip python3-venv git -y

# Create user
adduser sportsbot
usermod -aG sudo sportsbot
su - sportsbot

# Clone repo
git clone https://github.com/YOUR_USERNAME/SportsPredictor.git
cd SportsPredictor

# Setup Python
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
pip install discord.py schedule requests fuzzywuzzy python-Levenshtein

# Create .env file
cat > .env << 'EOF'
DISCORD_BOT_TOKEN=paste_your_bot_token
NBA_DISCORD_WEBHOOK=paste_your_nba_webhook
EOF

# Test it works
python discord_bot.py
```

### 6. Make It Run Forever
```bash
# As root, create service files (copy from CLOUD_DEPLOYMENT.md)
# Then:
sudo systemctl enable sportsbot discord-bot
sudo systemctl start sportsbot discord-bot
```

---

## Success Checklist
- [ ] NBA picks auto-post to #nba channel
- [ ] Can type `!status` in Discord and get response
- [ ] Can type `!picks nba` from iPad
- [ ] System runs 24/7 without your computer

---

## Quick Reference

**Discord Bot Commands:**
```
!status       - System health
!picks nba    - Today's picks
!predict nba  - Run predictions
!grade nba    - Grade yesterday
!health       - Check APIs
```

**Server Management:**
```bash
ssh root@YOUR_IP                    # Connect
sudo systemctl status sportsbot    # Check status
sudo journalctl -u sportsbot -f    # View logs
```

**iPad Apps to Install:**
- Discord (control bot)
- Termius (SSH to server)
