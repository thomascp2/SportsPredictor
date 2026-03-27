// API Configuration
// For local development (emulator): 'http://localhost:8000/api'
// For physical device: use your PC's IP address
export const API_BASE_URL = 'http://192.168.1.70:8000/api';

// Supabase Configuration
// Replace with your Supabase project credentials
export const SUPABASE_URL = process.env.EXPO_PUBLIC_SUPABASE_URL || 'YOUR_SUPABASE_URL';
export const SUPABASE_ANON_KEY = process.env.EXPO_PUBLIC_SUPABASE_ANON_KEY || 'YOUR_SUPABASE_ANON_KEY';

// Points System
export const POINTS = {
  CORRECT_PICK: 10,
  STREAK_3_BONUS: 5,
  STREAK_5_BONUS: 15,
  STREAK_10_BONUS: 50,
  DAILY_LOGIN: 5,
  FIRST_PICK: 5,
  // Costs
  UNLOCK_SINGLE_AI: 25,
  UNLOCK_GAME_AI: 100,
  UNLOCK_DAY_AI: 200,
} as const;

// Tier thresholds and display
export const TIER_INFO: Record<string, { label: string; color: string; minPicks: number; minAccuracy: number }> = {
  rookie: { label: 'Rookie', color: '#888', minPicks: 0, minAccuracy: 0 },
  pro: { label: 'Pro', color: '#4CAF50', minPicks: 50, minAccuracy: 0.5 },
  elite: { label: 'Elite', color: '#FFD700', minPicks: 200, minAccuracy: 0.55 },
  legend: { label: 'Legend', color: '#FF6B35', minPicks: 500, minAccuracy: 0.6 },
};

// Sportsbooks for bet tracking
export const SPORTSBOOKS = [
  'PrizePicks', 'Underdog', 'DraftKings', 'FanDuel', 'BetMGM',
  'Caesars', 'PointsBet', 'Bet365', 'Other',
] as const;

// Parlay Payout Multipliers by total leg value
export const PAYOUTS: Record<number, number> = {
  2: 3.0,
  3: 5.0,
  4: 10.0,
  5: 20.0,
  6: 25.0,
};

// How much each odds type counts toward total legs
export const LEG_VALUES: Record<string, number> = {
  goblin: 0.5,
  standard: 1.0,
  demon: 1.5,
};

// Break-even win rates per pick type
export const BREAK_EVEN_RATES: Record<string, number> = {
  goblin: 0.76,
  standard: 0.56,
  demon: 0.45,
};

// Tier colors for display
export const TIER_COLORS: Record<string, string> = {
  'T1-ELITE': '#FFD700',     // Gold
  'T2-STRONG': '#00FF00',    // Green
  'T3-GOOD': '#00BFFF',      // Light Blue
  'T4-LEAN': '#FFA500',      // Orange
  'T5-FADE': '#FF4444',      // Red
};

// EV color thresholds
export const EV_COLORS = {
  positive: '#00FF00',   // Green for +EV
  neutral: '#FFD700',    // Gold for neutral
  negative: '#FF4444',   // Red for -EV
};

// Sports
export const SPORTS = ['NBA', 'NHL'] as const;
export type Sport = typeof SPORTS[number];

// Star Players - Well-known players for filtering
export const STAR_PLAYERS: Record<string, string[]> = {
  NBA: [
    // Top Superstars
    'LeBron James', 'Kevin Durant', 'Stephen Curry', 'Giannis Antetokounmpo',
    'Nikola Jokic', 'Luka Doncic', 'Joel Embiid', 'Jayson Tatum',
    'Shai Gilgeous-Alexander', 'Anthony Edwards', 'Devin Booker', 'Donovan Mitchell',
    // All-Stars
    'Damian Lillard', 'Kyrie Irving', 'Trae Young', 'Ja Morant',
    'Anthony Davis', 'Jimmy Butler', 'Paul George', 'Kawhi Leonard',
    'Bam Adebayo', 'De\'Aaron Fox', 'Tyrese Haliburton', 'Tyrese Maxey',
    'Jaylen Brown', 'Zion Williamson', 'Karl-Anthony Towns', 'Domantas Sabonis',
    'LaMelo Ball', 'Cade Cunningham', 'Paolo Banchero', 'Victor Wembanyama',
    // Quality Starters
    'Jalen Brunson', 'Fred VanVleet', 'Scottie Barnes', 'Franz Wagner',
    'Alperen Sengun', 'Evan Mobley', 'Lauri Markkanen', 'Mikal Bridges',
  ],
  NHL: [
    // Top Superstars
    'Connor McDavid', 'Nathan MacKinnon', 'Cale Makar', 'Auston Matthews',
    'Leon Draisaitl', 'Nikita Kucherov', 'David Pastrnak', 'Mikko Rantanen',
    // Elite Forwards
    'Sidney Crosby', 'Alex Ovechkin', 'Jack Hughes', 'Matthew Tkachuk',
    'Jason Robertson', 'Kirill Kaprizov', 'Mitch Marner', 'Jack Eichel',
    'Elias Pettersson', 'Tim Stutzle', 'Brady Tkachuk', 'Trevor Zegras',
    'Tage Thompson', 'Kyle Connor', 'Sebastian Aho', 'Roope Hintz',
    // Elite Defensemen
    'Quinn Hughes', 'Adam Fox', 'Erik Karlsson', 'Roman Josi',
    'Victor Hedman', 'Rasmus Dahlin', 'Miro Heiskanen', 'Moritz Seider',
    // Star Goalies
    'Connor Hellebuyck', 'Igor Shesterkin', 'Andrei Vasilevskiy', 'Juuse Saros',
  ],
};

// Check if a player is a star player
export const isStarPlayer = (playerName: string, sport: string): boolean => {
  const sportKey = sport.toUpperCase() as keyof typeof STAR_PLAYERS;
  const stars = STAR_PLAYERS[sportKey] || [];
  return stars.some(star =>
    playerName.toLowerCase().includes(star.toLowerCase()) ||
    star.toLowerCase().includes(playerName.toLowerCase())
  );
};

// Common prop types by sport
export const PROP_TYPES: Record<string, string[]> = {
  NBA: ['points', 'rebounds', 'assists', 'threes', 'pra', 'stocks', 'minutes', 'blocks', 'steals', 'turnovers'],
  NHL: ['points', 'shots', 'goals', 'assists', 'saves', 'blocks'],
};
