// Supabase Edge Function: grade-user-picks
// Called after props are graded (sync pipeline updates daily_props.result)
// Sets user_picks.outcome = HIT/MISS and triggers point awards

import { createClient } from "https://esm.sh/@supabase/supabase-js@2";

const supabaseUrl = Deno.env.get("SUPABASE_URL")!;
const serviceRoleKey = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!;

interface GradeRequest {
  game_date: string; // YYYY-MM-DD
  sport?: string;
}

Deno.serve(async (req: Request) => {
  try {
    const { game_date, sport } = (await req.json()) as GradeRequest;

    if (!game_date) {
      return new Response(JSON.stringify({ error: "game_date required" }), {
        status: 400,
        headers: { "Content-Type": "application/json" },
      });
    }

    const supabase = createClient(supabaseUrl, serviceRoleKey);

    // Find all graded props for this date
    let propsQuery = supabase
      .from("daily_props")
      .select("id, result, ai_prediction")
      .eq("game_date", game_date)
      .eq("status", "graded")
      .not("result", "is", null);

    if (sport) {
      propsQuery = propsQuery.eq("sport", sport);
    }

    const { data: gradedProps, error: propsError } = await propsQuery;

    if (propsError) {
      throw new Error(`Failed to fetch graded props: ${propsError.message}`);
    }

    if (!gradedProps || gradedProps.length === 0) {
      return new Response(
        JSON.stringify({ message: "No graded props found", graded: 0 }),
        { headers: { "Content-Type": "application/json" } }
      );
    }

    let totalGraded = 0;
    let totalHits = 0;
    const userPoints: Record<string, { hits: number; total: number }> = {};

    // Grade each user pick
    for (const prop of gradedProps) {
      const { data: picks, error: picksError } = await supabase
        .from("user_picks")
        .select("id, user_id, prediction")
        .eq("prop_id", prop.id)
        .is("outcome", null);

      if (picksError || !picks) continue;

      for (const pick of picks) {
        // Determine outcome: user's prediction matches the prop result
        const isHit =
          (pick.prediction === prop.ai_prediction && prop.result === "HIT") ||
          (pick.prediction !== prop.ai_prediction && prop.result === "MISS");

        // Actually, result on daily_props is based on the AI prediction.
        // For user picks, we need to check if the user's prediction matches actual outcome.
        // If actual_value > line and user picked OVER -> HIT
        // If actual_value <= line and user picked UNDER -> HIT
        // Since we grade based on the prop result field which is relative to ai_prediction,
        // we need the actual comparison. But the prop has result field set during sync.
        // Let's use a simpler approach: the prop's result tells us the actual outcome direction.

        // The daily_props.result is set by the sync pipeline as HIT/MISS relative to ai_prediction.
        // To determine if user pick is correct, we need to know the actual direction.
        // If ai_prediction=OVER and result=HIT -> actual was OVER
        // If ai_prediction=OVER and result=MISS -> actual was UNDER
        // If ai_prediction=UNDER and result=HIT -> actual was UNDER
        // If ai_prediction=UNDER and result=MISS -> actual was OVER

        let actualDirection: string;
        if (prop.ai_prediction === "OVER") {
          actualDirection = prop.result === "HIT" ? "OVER" : "UNDER";
        } else {
          actualDirection = prop.result === "HIT" ? "UNDER" : "OVER";
        }

        const outcome = pick.prediction === actualDirection ? "HIT" : "MISS";

        await supabase
          .from("user_picks")
          .update({
            outcome,
            graded_at: new Date().toISOString(),
          })
          .eq("id", pick.id);

        totalGraded++;
        if (outcome === "HIT") totalHits++;

        // Track per-user stats
        if (!userPoints[pick.user_id]) {
          userPoints[pick.user_id] = { hits: 0, total: 0 };
        }
        userPoints[pick.user_id].total++;
        if (outcome === "HIT") userPoints[pick.user_id].hits++;
      }
    }

    // Trigger point awards for each user
    const awardResults = [];
    for (const [userId, stats] of Object.entries(userPoints)) {
      try {
        const { data } = await supabase.functions.invoke("award-points", {
          body: {
            user_id: userId,
            hits: stats.hits,
            total: stats.total,
            game_date,
          },
        });
        awardResults.push({ userId, ...data });
      } catch (e) {
        awardResults.push({ userId, error: (e as Error).message });
      }
    }

    return new Response(
      JSON.stringify({
        success: true,
        game_date,
        total_graded: totalGraded,
        total_hits: totalHits,
        accuracy:
          totalGraded > 0
            ? Math.round((totalHits / totalGraded) * 1000) / 10
            : 0,
        users_awarded: awardResults.length,
        awards: awardResults,
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
