 What Was Actually Going On

  The broken state (before today)

  Look at R. Hintz in that first column: the system was predicting UNDER 59.6% confidence — meaning "we think Hintz takes fewer than 1.5 shots." His L10 average is 3.0 shots per game. A player who averages 3 shots a game should almost never go UNDER 1.5. The stat model knew this and had correctly computed ~69% OVER for him. But then the ML model ran on top and dragged it to UNDER.

  Or A. Tuch — L10 = 2.8 shots, being predicted UNDER at 57.7%. Same story: the math says OVER clearly, the ML model was overriding it with
  garbage.

  Why was the ML doing this? When the ML model runs, it needs to look up each player's shot stats (sog_l10, sog_season, etc.) from the features dictionary. But the stat model had been storing those features under new names with an f_ prefix — so the ML was looking for sog_l10 and finding nothing, defaulting it to zero. A player with 0 average shots will obviously not clear 1.5 shots → every single player gets predicted UNDER with high confidence. The ML was using phantom data for every pick.

  This had been happening since March 25 when the models were first activated.

  ---
  After the fix (what tomorrow's run will produce)

  Same players, correct math now:

  ┌─────────────┬────────────────┬──────────────────┬─────────────────┐
  │   Player    │ Broken (today) │ Fixed (tomorrow) │     Reality     │
  ├─────────────┼────────────────┼──────────────────┼─────────────────┤
  │ R. Hintz    │ UNDER 59.6%    │ OVER 68.6%       │ 3.0 avg shots   │
  ├─────────────┼────────────────┼──────────────────┼─────────────────┤
  │ A. Tuch     │ UNDER 57.7%    │ OVER 76.8%       │ 2.8 avg shots   │
  ├─────────────┼────────────────┼──────────────────┼─────────────────┤
  │ W. Johnston │ UNDER 60.4%    │ OVER 70.1%       │ 2.2 avg shots   │
  ├─────────────┼────────────────┼──────────────────┼─────────────────┤
  │ Z. Benson   │ UNDER 59.4%    │ OVER 72.6%       │ 2.2 avg shots   │
  ├─────────────┼────────────────┼──────────────────┼─────────────────┤
  │ M. Rantanen │ UNDER 71.3%    │ UNDER 57.2%      │ 1.3 avg shots ✓ │
  ├─────────────┼────────────────┼──────────────────┼─────────────────┤
  │ T. Seguin   │ UNDER 80.8%    │ UNDER 82.0%      │ 0.8 avg shots ✓ │
  └─────────────┴────────────────┴──────────────────┴─────────────────┘

  The players who are legitimately UNDER (Seguin, McLeod, Rantanen — low shot volume) stay UNDER. The active shooters (Hintz, Tuch, Johnston) flip to correct OVER predictions. The system stopped being a broken clock that always said UNDER and started reading the actual data again.

  ---
  What Changed in Simple Terms

  Before: The system was running a machine learning model on every shots and points prediction. That ML model was supposed to add sophistication on top of the stat model. Instead, it had a bug where it couldn't read any of the player's actual shot statistics — they all defaulted to zero. So every player looked like they'd never taken a shot → every player got predicted UNDER with confidence. The stat model behind it was totally correct, but the ML was overriding it with nonsense.

  After: ML is turned off. The stat model runs cleanly. Players who average 3 shots/game get OVER predictions. Players who average 0.8
  shots/game get UNDER predictions. The system does what it was always supposed to do.

  No data was lost. All predictions will recalculate correctly on the next run. The fix takes effect the next time the pipeline generates predictions.

  ---
  One More Thing Worth Knowing

  The ML models themselves were also trained on three weeks of this same broken behavior before the March 25 training date — so even if the
  naming bug got fixed, the models had learned corrupted patterns. That's the deeper reason they're off for the rest of this season and need a
  full retrain in October with clean data and the corrected methodology.

● Two separate questions: the retrain process, and the early-warning system. Let me address both and build the monitoring piece since that's
  what would have caught this three weeks earlier.

  ---                                                                                                                                            Where We Are
                                                                                                                                                 Everything from this session is done and saved:
  - Production bug fixed (USE_ML = False)
  - _prepare_features name-mismatch guard applied
  - train_models.py methodology fixed (4 changes: baseline, f_prob_over exclusion, degenerate guard, feature dedup)
  - Full post-mortem at PEGASUS/docs/nhl_ml_post_mortem.md
  - Bookmark at PEGASUS/bookmarks/bookmark-04.md

  ---
  What's Left to Answer (your question)

  The retrain process + self-auditing system is a real build — two pieces:

  1. Direction sanity check — runs automatically after every prediction batch, fires a Discord alert if any normally-competitive prop
  (shots_1.5, points_0.5) is >85% in one direction. This would have caught the bug on March 16, not April 15.
  2. Automated weekly shadow audit — wires audit_nhl_models() (already built in PEGASUS/pipeline/nhl_ml_reader.py) into a scheduled cron, posts
   results to Discord. Kills the ML blend automatically if improvement drops below threshold.

  ---
  How to Proceed

  Option A — Start a fresh session now and I'll build both pieces plus document the full October retrain protocol (pre-flight checklist, run
  order, go/no-go gate).

  Option B — Start fresh and just get the direction sanity check wired in first (30 min job, highest value), then retrain protocol in a
  follow-up.

  Which do you want, and should I write a session prompt so the next conversation picks up exactly here?

✻ Baked for 41s

> please create a markdown and place it in the folder marked 2027 with all of this information so we have it for next season. we need to train    on good data and start out correct so we can place our stamp of approval on these picks. we cant just charge people for picks and give them    shit.                                                                                                                                       
  Listed 1 directory (ctrl+o to expand)
  ⎿  Interrupted · What should Claude do instead?

> oh i see your last question. hmmm give me both options a and b in a prompt for the next session .ensure you include in the prompt that were    still working on project pegasus and include that path along with youre most up to date bookmark. lay all of this out. also, please create a    markdown and place it in the folder marked 2027 with all of this information so we have it for next season. we need to train    on good       data and start out correct so we can place our stamp of approval on these picks. we cant just charge people for picks and give them    shit. 
● Write(PEGASUS\2027\NHL_RETRAIN_MASTERPLAN.md)
  ⎿  Wrote 548 lines to PEGASUS\2027\NHL_RETRAIN_MASTERPLAN.md
       1 # NHL ML Retrain Master Plan — 2026-27 Season
       2 **Written: 2026-04-15 | Source: PEGASUS Session 4 Post-Mortem**
       3                                                                                                                                              4 > **Why this document exists**: We ran a full shadow audit of the v20260325_003 NHL ML
       5 > models in April 2026 and found they were actively corrupting live predictions. Every                                                       6 > shot-over pick for active players was being predicted UNDER because of a feature naming
       7 > bug and a broken ML model that should never have shipped. This doc is the complete
       8 > specification for doing it right next season — so we can put our name on these picks.
       9
      10 ---
     … +539 lines (ctrl+o to expand)

● Now the session prompts for next time:

● Write(PEGASUS\bookmarks\session-5-prompt.md)
  ⎿  Wrote 105 lines to PEGASUS\bookmarks\session-5-prompt.md
       1 # Session 5 Prompt — PEGASUS Continuation
       2 **Use this to start the next session. Copy the block you want.**
       3                                                                                                                                              4 ---
       5                                                                                                                                              6 ## Context (read regardless of which option you pick)
       7
       8 I'm continuing work on **PEGASUS** — a parallel read-only prediction system built on top
       9 of the existing SportsPredictor orchestrator. PEGASUS lives entirely in `PEGASUS/` and
      10 never modifies any existing files outside that directory.
     … +95 lines (ctrl+o to expand)

● Done. Here's what you now have:

  ---                                                                                                                                            What Was Created
                                                                                                                                                 PEGASUS/2027/NHL_RETRAIN_MASTERPLAN.md — the full document for next season. Six parts:

  1. What went wrong — the exact technical breakdown of all 5 root causes, with the code that proved each one. Nobody has to reverse-engineer this next October.
  2. The full retrain protocol — 6 numbered steps in order. Step 0 (stat model health check) is mandatory before touching ML. Includes the actual query to run, the expected healthy values, and the gate that blocks you from training on corrupted data.
  3. Hits and blocked shots — included from day one with their training eligibility timeline (hits_0.5 and blocked_shots_0.5 target January/February 2027), the features to add, and which lines to skip as degenerate.
  4. The self-auditing system — the two pieces that didn't exist: the direction sanity check (fires Discord if any prop goes >85% in one direction same night it happens) and the weekly shadow audit (auto-posts PASS/FAIL to Discord every Sunday, auto-kills ML if it fails).
  5. The philosophy — what "our stamp of approval" actually means. The edge is in situational context at scale — back-to-backs, game-script sensitivity, role-specific patterns — things PP's average pricing doesn't fully reflect. Stat models reproduce what PP already knows. ML on clean, contextual features is what creates the separation.
  6. The activation checklist — one-page summary of everything to verify before setting USE_ML = True next October. Nothing ships without
  clearing every box.

  ---
  PEGASUS/bookmarks/session-5-prompt.md — the next session prompt with both options laid out. Option A is the full session (monitoring + Step 5
   MLB). Option B is monitoring only. Copy whichever you want to start the next conversation.

   recap: Working on PEGASUS, a parallel prediction layer for SportsPredictor. This session audited the NHL ML models, found and fixed a          production bug causing all shots/points predictions to be wrong, and documented the full retrain plan for next season. Next action: start a
  new session using the prompt in PEGASUS/bookmarks/session-5-prompt.md to build the automated monitoring system. (disable recaps in /config)  