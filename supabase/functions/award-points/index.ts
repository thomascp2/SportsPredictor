// Supabase Edge Function: award-points
// Calculates points earned from graded picks, including streak bonuses.
// Called by grade-user-picks after grading a batch, or directly for daily login.

import { createClient } from "https://esm.sh/@supabase/supabase-js@2";

const supabaseUrl = Deno.env.get("SUPABASE_URL")!;
const serviceRoleKey = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!;

// Point values
const POINTS = {
  CORRECT_PICK: 10,
  STREAK_3: 5,
  STREAK_5: 15,
  STREAK_10: 50,
  DAILY_LOGIN: 5,
  FIRST_PICK: 5,
} as const;

interface AwardRequest {
  user_id: string;
  hits: number;
  total: number;
  game_date: string;
  reason?: string; // 'grading' | 'daily_login' | 'first_pick'
}

Deno.serve(async (req: Request) => {
  try {
    const body = (await req.json()) as AwardRequest;
    const { user_id, game_date, reason } = body;

    if (!user_id) {
      return new Response(JSON.stringify({ error: "user_id required" }), {
        status: 400,
        headers: { "Content-Type": "application/json" },
      });
    }

    const supabase = createClient(supabaseUrl, serviceRoleKey);

    // Get current profile
    const { data: profile, error: profileError } = await supabase
      .from("profiles")
      .select("points, streak, best_streak, total_picks, total_hits")
      .eq("id", user_id)
      .single();

    if (profileError || !profile) {
      throw new Error(`Profile not found: ${profileError?.message}`);
    }

    let totalPointsAwarded = 0;
    const transactions: Array<{ amount: number; reason: string }> = [];
    let newStreak = profile.streak;

    // Handle daily login bonus
    if (reason === "daily_login") {
      totalPointsAwarded += POINTS.DAILY_LOGIN;
      transactions.push({
        amount: POINTS.DAILY_LOGIN,
        reason: "daily_login",
      });
    }

    // Handle first pick of the day bonus
    if (reason === "first_pick") {
      totalPointsAwarded += POINTS.FIRST_PICK;
      transactions.push({
        amount: POINTS.FIRST_PICK,
        reason: "first_pick_of_day",
      });
    }

    // Handle grading results
    if (body.hits !== undefined && body.total !== undefined) {
      const { hits, total } = body;

      // Points for correct picks
      if (hits > 0) {
        const pickPoints = hits * POINTS.CORRECT_PICK;
        totalPointsAwarded += pickPoints;
        transactions.push({
          amount: pickPoints,
          reason: `correct_picks_x${hits}`,
        });
      }

      // Calculate new streak
      // Get recent picks to compute consecutive hits
      const { data: recentPicks } = await supabase
        .from("user_picks")
        .select("outcome, graded_at")
        .eq("user_id", user_id)
        .not("outcome", "is", null)
        .order("graded_at", { ascending: false })
        .limit(50);

      if (recentPicks) {
        // Count consecutive hits from most recent
        newStreak = 0;
        for (const pick of recentPicks) {
          if (pick.outcome === "HIT") {
            newStreak++;
          } else {
            break;
          }
        }
      }

      // Streak bonuses (award once when threshold crossed)
      const oldStreak = profile.streak;
      if (newStreak >= 3 && oldStreak < 3) {
        totalPointsAwarded += POINTS.STREAK_3;
        transactions.push({
          amount: POINTS.STREAK_3,
          reason: "streak_bonus_3",
        });
      }
      if (newStreak >= 5 && oldStreak < 5) {
        totalPointsAwarded += POINTS.STREAK_5;
        transactions.push({
          amount: POINTS.STREAK_5,
          reason: "streak_bonus_5",
        });
      }
      if (newStreak >= 10 && oldStreak < 10) {
        totalPointsAwarded += POINTS.STREAK_10;
        transactions.push({
          amount: POINTS.STREAK_10,
          reason: "streak_bonus_10",
        });
      }

      // Update profile stats
      const newTotalPicks = profile.total_picks + total;
      const newTotalHits = profile.total_hits + hits;

      // Determine tier based on total picks and accuracy
      const accuracy =
        newTotalPicks > 0 ? newTotalHits / newTotalPicks : 0;
      let tier = "rookie";
      if (newTotalPicks >= 500 && accuracy >= 0.6) tier = "legend";
      else if (newTotalPicks >= 200 && accuracy >= 0.55) tier = "elite";
      else if (newTotalPicks >= 50 && accuracy >= 0.5) tier = "pro";

      const newPoints = profile.points + totalPointsAwarded;

      await supabase
        .from("profiles")
        .update({
          points: newPoints,
          streak: newStreak,
          best_streak: Math.max(profile.best_streak, newStreak),
          total_picks: newTotalPicks,
          total_hits: newTotalHits,
          tier,
        })
        .eq("id", user_id);

      // Record point transactions
      let runningBalance = profile.points;
      for (const tx of transactions) {
        runningBalance += tx.amount;
        await supabase.from("point_transactions").insert({
          user_id,
          amount: tx.amount,
          reason: tx.reason,
          balance_after: runningBalance,
        });
      }

      return new Response(
        JSON.stringify({
          success: true,
          user_id,
          points_awarded: totalPointsAwarded,
          new_balance: newPoints,
          streak: newStreak,
          best_streak: Math.max(profile.best_streak, newStreak),
          tier,
          transactions,
        }),
        { headers: { "Content-Type": "application/json" } }
      );
    }

    // Simple point award (login/first pick only, no grading)
    const newPoints = profile.points + totalPointsAwarded;

    if (totalPointsAwarded > 0) {
      await supabase
        .from("profiles")
        .update({ points: newPoints })
        .eq("id", user_id);

      for (const tx of transactions) {
        await supabase.from("point_transactions").insert({
          user_id,
          amount: tx.amount,
          reason: tx.reason,
          balance_after: newPoints,
        });
      }
    }

    return new Response(
      JSON.stringify({
        success: true,
        user_id,
        points_awarded: totalPointsAwarded,
        new_balance: newPoints,
        transactions,
      }),
      { headers: { "Content-Type": "application/json" } }
    );
  } catch (error) {
    return new Response(
      JSON.stringify({ error: (error as Error).message }),
      { status: 500, headers: { "Content-Type": "application/json" } }
    );
  }
});
