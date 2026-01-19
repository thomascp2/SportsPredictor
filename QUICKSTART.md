# SportsPredictor - Quick Start Guide

## Prerequisites
- Python 3.11+ installed
- Node.js 18+ installed (at `C:\Program Files\nodejs\`)
- Expo Go app installed on your phone (iOS/Android)
- Phone and PC on the same WiFi network

---

## Quick Start (3 Steps)

### Step 1: Start the API Server

Open **PowerShell** and run:
```powershell
cd C:\Users\thoma\SportsPredictor
python -m uvicorn api.main:app --reload --port 8000 --host 0.0.0.0
```

You should see:
```
INFO:     Uvicorn running on http://0.0.0.0:8000
INFO:     Application startup complete.
```

**Keep this terminal open!**

### Step 2: Start the Mobile App

Open a **new PowerShell** and run:
```powershell
cd C:\Users\thoma\SportsPredictor\mobile
$env:Path += ";C:\Program Files\nodejs"
npx expo start
```

You should see a QR code appear.

**Keep this terminal open!**

### Step 3: Connect Your Phone

1. Open the **Expo Go** app on your phone
2. Scan the QR code from Step 2
3. The app should load!

---

## Troubleshooting

### "Port 8000 is in use" or "WinError 10013"
Kill the old process and restart:
```powershell
taskkill /F /IM python.exe
cd C:\Users\thoma\SportsPredictor
python -m uvicorn api.main:app --reload --port 8000 --host 0.0.0.0
```

### "Network Error" in the app
1. Find your PC's IP:
   ```powershell
   ipconfig | findstr /i "IPv4"
   ```
2. Edit `mobile/src/utils/constants.ts`:
   ```typescript
   export const API_BASE_URL = 'http://YOUR_IP_HERE:8000/api';
   ```
3. Reload the app (press `r` in Expo terminal)

### "npx is not recognized"
Add Node.js to your PATH:
```powershell
$env:Path += ";C:\Program Files\nodejs"
```

### App shows old data / changes not reflecting
Restart the API server completely:
```powershell
taskkill /F /IM python.exe
cd C:\Users\thoma\SportsPredictor
python -m uvicorn api.main:app --reload --port 8000 --host 0.0.0.0
```

### Expo errors / red screen
Clear Expo cache:
```powershell
cd C:\Users\thoma\SportsPredictor\mobile
npx expo start --clear
```

---

## Architecture Overview

```
┌─────────────────────┐     ┌─────────────────────┐     ┌─────────────────────┐
│   Your Phone        │────▶│   API Server        │────▶│   SQLite Databases  │
│   (Expo Go App)     │     │   (Port 8000)       │     │   + External APIs   │
└─────────────────────┘     └─────────────────────┘     └─────────────────────┘
```

**API Server** (`api/`)
- FastAPI backend on port 8000
- Endpoints: `/api/picks`, `/api/scores`, `/api/parlays`, `/api/performance`, `/api/players`
- Connects to NBA and NHL prediction databases
- Fetches live scores from ESPN and NHL APIs

**Mobile App** (`mobile/`)
- Expo/React Native app
- Connects to API via your local network
- 5 screens: Scores, Picks, Parlay, Stats, Search

---

## Key Files

| File | Purpose |
|------|---------|
| `api/main.py` | API entry point |
| `api/routers/picks.py` | Smart picks endpoint |
| `api/routers/scores.py` | Live scores endpoint |
| `api/routers/parlays.py` | Parlay calculator |
| `api/routers/performance.py` | Stats endpoint |
| `mobile/App.tsx` | Mobile app entry |
| `mobile/src/utils/constants.ts` | API URL config |
| `mobile/src/store/parlayStore.ts` | Parlay state |

---

## Useful Commands

```powershell
# Test API is running
curl http://localhost:8000/

# Test NBA scores
curl http://localhost:8000/api/scores/live?sport=nba

# Test NHL picks
curl http://localhost:8000/api/picks/today?sport=nhl

# Kill all Python processes
taskkill /F /IM python.exe

# Kill all Node processes
taskkill /F /IM node.exe

# Find your IP address
ipconfig | findstr /i "IPv4"
```

---

## Daily Workflow

1. **Morning**: Start API server and Expo
2. **Check picks**: Review today's smart picks on the Picks tab
3. **Build parlays**: Add high-confidence picks to your parlay
4. **Monitor games**: Watch live scores on the Scores tab
5. **Track performance**: Check accuracy trends on Stats tab

---

## Current Configuration

- **API URL**: `http://192.168.1.70:8000/api`
- **API Port**: 8000
- **Expo Port**: 8081 (or 8082 if 8081 in use)
- **NBA Database**: `nba/database/nba_predictions.db`
- **NHL Database**: `nhl/database/nhl_predictions_v2.db`
