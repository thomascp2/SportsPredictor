# SportsPredictor Mobile App

A React Native (Expo) mobile app for visualizing sports prediction data.

## Features

- **Live Scoreboard**: NBA/NHL game scores with auto-refresh
- **Smart Picks**: Today's predictions with tiers, edge, and probability
- **Parlay Builder**: Visual parlay builder with real-time EV calculations
- **Performance**: System accuracy metrics and trends
- **Player Search**: Find player prediction history

## Setup

### Prerequisites

1. Node.js 18+ installed
2. Expo Go app on your phone (iOS/Android)
3. Backend API running on port 8000

### Installation

```bash
# Navigate to mobile folder
cd mobile

# Install dependencies
npm install

# Start Expo development server
npx expo start
```

### Running the App

1. **Start the backend API** (in separate terminal):
   ```bash
   cd api
   uvicorn main:app --reload --port 8000
   ```

2. **Start Expo**:
   ```bash
   cd mobile
   npx expo start
   ```

3. **Scan QR code** with Expo Go app on your phone

### Configuration

Edit `src/utils/constants.ts` to change the API URL:

```typescript
// For local development (emulator)
export const API_BASE_URL = 'http://localhost:8000/api';

// For physical device (use your computer's IP)
export const API_BASE_URL = 'http://192.168.1.x:8000/api';
```

## Project Structure

```
mobile/
├── App.tsx                 # Root component with navigation
├── app.json               # Expo configuration
├── package.json           # Dependencies
├── tsconfig.json          # TypeScript config
└── src/
    ├── components/        # Reusable UI components
    │   ├── common/       # Card, SportToggle
    │   ├── picks/        # PickCard, TierBadge, EdgeIndicator
    │   ├── parlay/       # ParlaySlip, EVCalculator
    │   └── scores/       # GameCard, LiveIndicator
    ├── hooks/            # Data fetching hooks
    │   ├── useLiveScores.ts
    │   ├── useSmartPicks.ts
    │   └── usePerformance.ts
    ├── screens/          # Main app screens
    │   ├── ScoreboardScreen.tsx
    │   ├── SmartPicksScreen.tsx
    │   ├── ParlayBuilderScreen.tsx
    │   ├── PerformanceScreen.tsx
    │   └── PlayerSearchScreen.tsx
    ├── services/         # API client
    │   └── api.ts
    ├── store/            # Zustand state management
    │   └── parlayStore.ts
    └── utils/            # Utilities
        ├── calculations.ts  # EV math
        └── constants.ts     # Config values
```

## Parlay EV Math

The app calculates Expected Value using:

```
totalLegValue = sum of leg values (goblin=0.5, standard=1.0, demon=1.5)
combinedProbability = P1 * P2 * ... * Pn
payoutMultiplier = interpolate from PAYOUTS table
expectedValue = (combinedProbability * payout) - 1
```

**Payout Table:**
- 2 legs: 3x
- 3 legs: 5x
- 4 legs: 10x
- 5 legs: 20x
- 6 legs: 25x

**Example:** 3 standard picks at 70% each = 3 legs, 5x payout, 34.3% combined prob, EV = +71.5%

## Tech Stack

- **Expo SDK 52**
- **React Native 0.76**
- **React Navigation 6**
- **Zustand** (state management)
- **Axios** (HTTP client)
- **TypeScript**
