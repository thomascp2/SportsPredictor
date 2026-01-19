// API Configuration
// For local development (emulator): 'http://localhost:8000/api'
// For physical device: use your PC's IP address
export const API_BASE_URL = 'http://192.168.1.70:8000/api';

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
