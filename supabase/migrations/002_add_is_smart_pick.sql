-- Migration 002: Add is_smart_pick flag to daily_props
-- Distinguishes ML-selected smart picks (suppression applied, edge >= 0)
-- from raw prediction rows synced for grading coverage.
-- Apply via Supabase Dashboard > SQL Editor

ALTER TABLE daily_props
  ADD COLUMN IF NOT EXISTS is_smart_pick BOOLEAN NOT NULL DEFAULT FALSE;

-- Backfill: treat any row with ai_tier not T5-FADE and ai_edge >= 0 as a smart pick
-- (best approximation for historical rows before the flag existed)
UPDATE daily_props
SET is_smart_pick = TRUE
WHERE ai_edge >= 0
  AND ai_tier != 'T5-FADE'
  AND ai_tier IS NOT NULL;
