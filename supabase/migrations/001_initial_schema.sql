-- FreePicks: Initial Schema Migration
-- Tables: profiles, daily_props, user_picks, user_bets, point_transactions,
--         daily_games, model_performance, watchlist

-- ============================================================
-- 1. PROFILES
-- ============================================================
CREATE TABLE public.profiles (
  id UUID REFERENCES auth.users(id) ON DELETE CASCADE PRIMARY KEY,
  username TEXT UNIQUE,
  display_name TEXT,
  avatar_url TEXT,
  points INTEGER DEFAULT 0,
  streak INTEGER DEFAULT 0,
  best_streak INTEGER DEFAULT 0,
  tier TEXT DEFAULT 'rookie', -- rookie, pro, elite, legend
  total_picks INTEGER DEFAULT 0,
  total_hits INTEGER DEFAULT 0,
  premium BOOLEAN DEFAULT false,
  premium_until TIMESTAMPTZ,
  push_token TEXT,
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
);

ALTER TABLE public.profiles ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Profiles are viewable by everyone"
  ON public.profiles FOR SELECT USING (true);

CREATE POLICY "Users can update own profile"
  ON public.profiles FOR UPDATE USING (auth.uid() = id);

CREATE POLICY "Users can insert own profile"
  ON public.profiles FOR INSERT WITH CHECK (auth.uid() = id);

-- Auto-create profile on signup
CREATE OR REPLACE FUNCTION public.handle_new_user()
RETURNS TRIGGER AS $$
BEGIN
  INSERT INTO public.profiles (id, username, display_name, avatar_url)
  VALUES (
    NEW.id,
    COALESCE(NEW.raw_user_meta_data->>'preferred_username', 'user_' || LEFT(NEW.id::text, 8)),
    COALESCE(NEW.raw_user_meta_data->>'full_name', NEW.raw_user_meta_data->>'name', 'Player'),
    COALESCE(NEW.raw_user_meta_data->>'avatar_url', NEW.raw_user_meta_data->>'picture')
  );
  RETURN NEW;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

CREATE TRIGGER on_auth_user_created
  AFTER INSERT ON auth.users
  FOR EACH ROW EXECUTE FUNCTION public.handle_new_user();


-- ============================================================
-- 2. DAILY_PROPS
-- ============================================================
CREATE TABLE public.daily_props (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  game_date DATE NOT NULL,
  sport TEXT NOT NULL,
  player_name TEXT NOT NULL,
  team TEXT NOT NULL,
  opponent TEXT NOT NULL,
  prop_type TEXT NOT NULL,
  line REAL NOT NULL,
  odds_type TEXT DEFAULT 'standard',
  game_time TIMESTAMPTZ,
  matchup TEXT,
  -- AI prediction data (hidden from free users)
  ai_prediction TEXT,      -- OVER or UNDER
  ai_probability REAL,
  ai_edge REAL,
  ai_tier TEXT,            -- T1-ELITE through T5-FADE
  ai_ev_2leg REAL,
  ai_ev_3leg REAL,
  ai_ev_4leg REAL,
  -- Grading
  actual_value REAL,
  result TEXT,             -- HIT, MISS, or PUSH
  graded_at TIMESTAMPTZ,
  -- Community consensus
  over_count INTEGER DEFAULT 0,
  under_count INTEGER DEFAULT 0,
  -- Status
  status TEXT DEFAULT 'open', -- open, locked, graded
  created_at TIMESTAMPTZ DEFAULT now(),
  UNIQUE(game_date, player_name, prop_type, line)
);

CREATE INDEX idx_daily_props_date ON public.daily_props(game_date);
CREATE INDEX idx_daily_props_sport_date ON public.daily_props(sport, game_date);
CREATE INDEX idx_daily_props_status ON public.daily_props(status);
CREATE INDEX idx_daily_props_player ON public.daily_props(player_name);

ALTER TABLE public.daily_props ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Props are viewable by everyone"
  ON public.daily_props FOR SELECT USING (true);

-- Only service_role can insert/update (from sync pipeline)
CREATE POLICY "Service role can manage props"
  ON public.daily_props FOR ALL USING (auth.role() = 'service_role');


-- ============================================================
-- 3. USER_PICKS (FreePicks game)
-- ============================================================
CREATE TABLE public.user_picks (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  user_id UUID REFERENCES public.profiles(id) ON DELETE CASCADE NOT NULL,
  prop_id UUID REFERENCES public.daily_props(id) ON DELETE CASCADE NOT NULL,
  prediction TEXT NOT NULL, -- OVER or UNDER
  outcome TEXT,             -- HIT, MISS, or NULL (pending)
  points_earned INTEGER DEFAULT 0,
  picked_at TIMESTAMPTZ DEFAULT now(),
  graded_at TIMESTAMPTZ,
  UNIQUE(user_id, prop_id)
);

CREATE INDEX idx_user_picks_user ON public.user_picks(user_id);
CREATE INDEX idx_user_picks_prop ON public.user_picks(prop_id);
CREATE INDEX idx_user_picks_user_date ON public.user_picks(user_id, picked_at);

ALTER TABLE public.user_picks ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users can view own picks"
  ON public.user_picks FOR SELECT USING (auth.uid() = user_id);

CREATE POLICY "Users can insert own picks"
  ON public.user_picks FOR INSERT WITH CHECK (auth.uid() = user_id);

CREATE POLICY "Service role can manage picks"
  ON public.user_picks FOR ALL USING (auth.role() = 'service_role');


-- ============================================================
-- 4. USER_BETS (bet tracking)
-- ============================================================
CREATE TABLE public.user_bets (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  user_id UUID REFERENCES public.profiles(id) ON DELETE CASCADE NOT NULL,
  sport TEXT NOT NULL,
  sportsbook TEXT,
  bet_type TEXT NOT NULL,       -- single, parlay, flex
  stake REAL,
  potential_payout REAL,
  actual_payout REAL,
  status TEXT DEFAULT 'pending', -- pending, won, lost, push
  legs JSONB NOT NULL,           -- [{player, prop_type, line, prediction, outcome}]
  notes TEXT,
  placed_at TIMESTAMPTZ DEFAULT now(),
  settled_at TIMESTAMPTZ
);

CREATE INDEX idx_user_bets_user ON public.user_bets(user_id);
CREATE INDEX idx_user_bets_status ON public.user_bets(user_id, status);

ALTER TABLE public.user_bets ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users can view own bets"
  ON public.user_bets FOR SELECT USING (auth.uid() = user_id);

CREATE POLICY "Users can insert own bets"
  ON public.user_bets FOR INSERT WITH CHECK (auth.uid() = user_id);

CREATE POLICY "Users can update own bets"
  ON public.user_bets FOR UPDATE USING (auth.uid() = user_id);

CREATE POLICY "Users can delete own bets"
  ON public.user_bets FOR DELETE USING (auth.uid() = user_id);


-- ============================================================
-- 5. POINT_TRANSACTIONS
-- ============================================================
CREATE TABLE public.point_transactions (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  user_id UUID REFERENCES public.profiles(id) ON DELETE CASCADE NOT NULL,
  amount INTEGER NOT NULL,       -- positive = earn, negative = spend
  reason TEXT NOT NULL,          -- correct_pick, streak_bonus, daily_login, unlock_ai, etc.
  reference_id UUID,             -- optional: pick_id, prop_id, etc.
  balance_after INTEGER NOT NULL,
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_point_tx_user ON public.point_transactions(user_id);
CREATE INDEX idx_point_tx_user_date ON public.point_transactions(user_id, created_at);

ALTER TABLE public.point_transactions ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users can view own transactions"
  ON public.point_transactions FOR SELECT USING (auth.uid() = user_id);

CREATE POLICY "Service role can manage transactions"
  ON public.point_transactions FOR ALL USING (auth.role() = 'service_role');


-- ============================================================
-- 6. DAILY_GAMES
-- ============================================================
CREATE TABLE public.daily_games (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  game_date DATE NOT NULL,
  sport TEXT NOT NULL,
  game_id TEXT NOT NULL,         -- external game ID (ESPN/NHL)
  home_team TEXT NOT NULL,
  away_team TEXT NOT NULL,
  home_score INTEGER DEFAULT 0,
  away_score INTEGER DEFAULT 0,
  status TEXT DEFAULT 'scheduled', -- scheduled, live, final
  period TEXT,
  clock TEXT,
  start_time TIMESTAMPTZ,
  broadcast TEXT,
  updated_at TIMESTAMPTZ DEFAULT now(),
  UNIQUE(game_date, sport, game_id)
);

CREATE INDEX idx_daily_games_date ON public.daily_games(game_date);
CREATE INDEX idx_daily_games_sport_date ON public.daily_games(sport, game_date);

ALTER TABLE public.daily_games ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Games are viewable by everyone"
  ON public.daily_games FOR SELECT USING (true);

CREATE POLICY "Service role can manage games"
  ON public.daily_games FOR ALL USING (auth.role() = 'service_role');


-- ============================================================
-- 7. MODEL_PERFORMANCE
-- ============================================================
CREATE TABLE public.model_performance (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  game_date DATE NOT NULL,
  sport TEXT NOT NULL,
  total_predictions INTEGER DEFAULT 0,
  total_graded INTEGER DEFAULT 0,
  hits INTEGER DEFAULT 0,
  accuracy REAL,
  over_accuracy REAL,
  under_accuracy REAL,
  by_prop JSONB,                 -- {points: {total, hits, accuracy}, ...}
  by_tier JSONB,                 -- {T1-ELITE: {total, hits, accuracy}, ...}
  created_at TIMESTAMPTZ DEFAULT now(),
  UNIQUE(game_date, sport)
);

CREATE INDEX idx_model_perf_sport_date ON public.model_performance(sport, game_date);

ALTER TABLE public.model_performance ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Performance is viewable by everyone"
  ON public.model_performance FOR SELECT USING (true);

CREATE POLICY "Service role can manage performance"
  ON public.model_performance FOR ALL USING (auth.role() = 'service_role');


-- ============================================================
-- 8. WATCHLIST
-- ============================================================
CREATE TABLE public.watchlist (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  user_id UUID REFERENCES public.profiles(id) ON DELETE CASCADE NOT NULL,
  player_name TEXT NOT NULL,
  sport TEXT NOT NULL,
  position INTEGER DEFAULT 0,   -- sort order (0-9)
  added_at TIMESTAMPTZ DEFAULT now(),
  UNIQUE(user_id, player_name, sport)
);

CREATE INDEX idx_watchlist_user ON public.watchlist(user_id);

ALTER TABLE public.watchlist ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users can view own watchlist"
  ON public.watchlist FOR SELECT USING (auth.uid() = user_id);

CREATE POLICY "Users can insert own watchlist"
  ON public.watchlist FOR INSERT WITH CHECK (auth.uid() = user_id);

CREATE POLICY "Users can update own watchlist"
  ON public.watchlist FOR UPDATE USING (auth.uid() = user_id);

CREATE POLICY "Users can delete own watchlist"
  ON public.watchlist FOR DELETE USING (auth.uid() = user_id);


-- ============================================================
-- HELPER FUNCTIONS
-- ============================================================

-- Update updated_at timestamp
CREATE OR REPLACE FUNCTION public.update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
  NEW.updated_at = now();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER profiles_updated_at
  BEFORE UPDATE ON public.profiles
  FOR EACH ROW EXECUTE FUNCTION public.update_updated_at();

CREATE TRIGGER daily_games_updated_at
  BEFORE UPDATE ON public.daily_games
  FOR EACH ROW EXECUTE FUNCTION public.update_updated_at();

-- Increment community vote counts (called from client)
CREATE OR REPLACE FUNCTION public.increment_vote(prop_id UUID, vote TEXT)
RETURNS void AS $$
BEGIN
  IF vote = 'OVER' THEN
    UPDATE public.daily_props SET over_count = over_count + 1 WHERE id = prop_id;
  ELSIF vote = 'UNDER' THEN
    UPDATE public.daily_props SET under_count = under_count + 1 WHERE id = prop_id;
  END IF;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;
