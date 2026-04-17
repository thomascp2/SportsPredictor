/**
 * Turso HTTP Client for FreePicks Mobile
 * =======================================
 * Reads prediction history from Turso (libSQL cloud) via HTTP API.
 * No npm package required — uses standard fetch/axios.
 *
 * Credentials: set EXPO_PUBLIC_TURSO_{SPORT}_URL and EXPO_PUBLIC_TURSO_{SPORT}_TOKEN
 * in your .env file (e.g. EXPO_PUBLIC_TURSO_NBA_URL=https://freepicks-nba-...turso.io)
 */

import axios from 'axios';

// ── Credentials (injected via EXPO_PUBLIC_ env vars) ─────────────────────────
// Add these to your .env file (same dir as app.json):
//   EXPO_PUBLIC_TURSO_NBA_URL=https://freepicks-nba-thomascp2.aws-us-east-1.turso.io
//   EXPO_PUBLIC_TURSO_NBA_TOKEN=<read-only-token>
//   EXPO_PUBLIC_TURSO_NHL_URL=https://freepicks-nhl-thomascp2.aws-us-east-1.turso.io
//   EXPO_PUBLIC_TURSO_NHL_TOKEN=<read-only-token>

const TURSO_CONFIG: Record<string, { url: string; token: string }> = {
  NBA: {
    url: process.env.EXPO_PUBLIC_TURSO_NBA_URL ?? '',
    token: process.env.EXPO_PUBLIC_TURSO_NBA_TOKEN ?? '',
  },
  NHL: {
    url: process.env.EXPO_PUBLIC_TURSO_NHL_URL ?? '',
    token: process.env.EXPO_PUBLIC_TURSO_NHL_TOKEN ?? '',
  },
};

// ── Types ─────────────────────────────────────────────────────────────────────

interface TursoArg {
  type: 'text' | 'integer' | 'real' | 'null';
  value?: string;
}

interface TursoStatement {
  sql: string;
  args: TursoArg[];
}

interface TursoCol {
  name: string;
}

interface TursoRow {
  type: string;
  value: string | null;
}

interface TursoResultSet {
  cols: TursoCol[];
  rows: TursoRow[][];
}

// ── Core HTTP executor ────────────────────────────────────────────────────────

/**
 * Execute a SQL query against the sport-specific Turso database.
 * Returns rows as plain objects keyed by column name.
 */
export async function tursoQuery(
  sport: string,
  sql: string,
  args: (string | number | null)[] = []
): Promise<Record<string, any>[]> {
  const sportKey = sport.toUpperCase();
  const cfg = TURSO_CONFIG[sportKey];

  if (!cfg?.url || !cfg?.token) {
    throw new Error(
      `Turso credentials not configured for ${sportKey}. ` +
      `Add EXPO_PUBLIC_TURSO_${sportKey}_URL and _TOKEN to .env`
    );
  }

  const tursoArgs: TursoArg[] = args.map((v) => {
    if (v === null) return { type: 'null' };
    if (typeof v === 'number') {
      return Number.isInteger(v)
        ? { type: 'integer', value: String(v) }
        : { type: 'real', value: String(v) };
    }
    return { type: 'text', value: String(v) };
  });

  const body = {
    requests: [
      { type: 'execute', stmt: { sql, args: tursoArgs } as TursoStatement },
      { type: 'close' },
    ],
  };

  const resp = await axios.post(`${cfg.url}/v2/pipeline`, body, {
    headers: {
      Authorization: `Bearer ${cfg.token}`,
      'Content-Type': 'application/json',
    },
    timeout: 15000,
  });

  const result = resp.data?.results?.[0];
  if (result?.type !== 'ok') {
    const errMsg = result?.error?.message ?? 'Unknown Turso error';
    throw new Error(`Turso query failed: ${errMsg}`);
  }

  const resultSet: TursoResultSet = result.response?.result;
  if (!resultSet) return [];

  const { cols, rows } = resultSet;
  return rows.map((row) => {
    const obj: Record<string, any> = {};
    cols.forEach((col, i) => {
      const cell = row[i];
      if (!cell || cell.type === 'null') {
        obj[col.name] = null;
      } else if (cell.type === 'integer') {
        obj[col.name] = parseInt(cell.value as string, 10);
      } else if (cell.type === 'real') {
        obj[col.name] = parseFloat(cell.value as string);
      } else {
        obj[col.name] = cell.value;
      }
    });
    return obj;
  });
}

// ── Player History (replaces Supabase daily_props query) ──────────────────────

export interface TursoPlayerRow {
  game_date: string;
  prop_type: string;
  line: number;
  prediction: string;   // OVER | UNDER
  actual_value: number | null;
  opponent: string;
}

/**
 * Fetch a player's prediction history from Turso.
 * Joins predictions + prediction_outcomes to get actual_value.
 * Replaces the Supabase daily_props query in fetchPlayerHistory.
 *
 * @param playerName  Exact player name (as stored in Turso)
 * @param sport       'NBA' | 'NHL'
 * @param sinceDate   ISO date string, e.g. '2026-01-01'
 * @param ppLine      Optional: filter to lines within ±8 of this value
 */
export async function fetchPlayerHistoryFromTurso(
  playerName: string,
  sport: string,
  sinceDate: string,
  ppLine?: number | null
): Promise<TursoPlayerRow[]> {
  let sql = `
    SELECT
      p.game_date,
      p.prop_type,
      p.line,
      p.prediction,
      p.opponent,
      po.actual_value
    FROM predictions p
    LEFT JOIN prediction_outcomes po
      ON p.player_name = po.player_name
      AND p.game_date  = po.game_date
      AND p.prop_type  = po.prop_type
    WHERE p.player_name = ?
      AND p.game_date  >= ?
  `;
  const args: (string | number | null)[] = [playerName, sinceDate];

  if (ppLine != null) {
    sql += ' AND p.line >= ? AND p.line <= ?';
    args.push(ppLine - 8, ppLine + 8);
  } else {
    // When no ppLine provided, restrict to smart-pick rows to avoid noise
    sql += ' AND p.is_smart_pick = 1';
  }

  sql += ' ORDER BY p.game_date DESC LIMIT 500';

  const rows = await tursoQuery(sport, sql, args);

  return rows.map((r) => ({
    game_date: r.game_date as string,
    prop_type: r.prop_type as string,
    line: typeof r.line === 'number' ? r.line : parseFloat(r.line),
    prediction: r.prediction as string,
    opponent: r.opponent as string,
    actual_value: r.actual_value != null ? parseFloat(r.actual_value) : null,
  }));
}
