import React from 'react';
import { View, Text, StyleSheet, Pressable } from 'react-native';
import type { DailyProp, DailyGame } from '../../types/supabase';

interface PlayerBoxCardProps {
  playerName: string;
  team: string;
  sport: string;
  game?: DailyGame;
  props: DailyProp[];
  onPropPress?: (propId: string) => void;
  onRemove?: () => void;
}

// Stat abbreviations for display
const STAT_ABBREVS: Record<string, string> = {
  points: 'PTS',
  rebounds: 'REB',
  assists: 'AST',
  threes: '3PM',
  stocks: 'STL+BLK',
  pra: 'PRA',
  minutes: 'MIN',
  steals: 'STL',
  blocks: 'BLK',
  turnovers: 'TO',
  shots: 'SOG',
  goals: 'G',
};

export function PlayerBoxCard({
  playerName,
  team,
  game,
  props,
  onPropPress,
  onRemove,
}: PlayerBoxCardProps) {
  const isLive = game?.status === 'live';
  const isFinal = game?.status === 'final';

  const getStatusText = () => {
    if (!game) return 'No game';
    if (isLive) return `${game.period} ${game.clock}`;
    if (isFinal) return 'FINAL';
    if (game.start_time) {
      return new Date(game.start_time).toLocaleTimeString([], {
        hour: 'numeric',
        minute: '2-digit',
      });
    }
    return game.status;
  };

  return (
    <View style={styles.card}>
      {/* Header row */}
      <View style={styles.header}>
        <View style={styles.playerRow}>
          <View style={[styles.teamDot, { backgroundColor: '#4CAF50' }]} />
          <Text style={styles.playerName} numberOfLines={1}>
            {playerName}
          </Text>
          <Text style={styles.team}>{team}</Text>
        </View>
        <View style={styles.statusRow}>
          <Text style={[styles.status, isLive && styles.liveStatus]}>
            {getStatusText()}
          </Text>
          {isLive && <View style={styles.liveDot} />}
        </View>
      </View>

      {/* Props as stat line */}
      {props.length > 0 ? (
        <View style={styles.statsGrid}>
          {props.slice(0, 6).map((prop) => {
            const abbrev = STAT_ABBREVS[prop.prop_type] || prop.prop_type.toUpperCase().slice(0, 3);
            const isOver = prop.actual_value !== null && prop.actual_value > prop.line;
            const isUnder = prop.actual_value !== null && prop.actual_value <= prop.line;

            return (
              <Pressable
                key={prop.id}
                style={styles.statCell}
                onPress={() => onPropPress?.(prop.id)}
              >
                <Text style={styles.statLabel}>{abbrev}</Text>
                {prop.actual_value !== null ? (
                  <Text style={[
                    styles.statValue,
                    isOver && styles.overValue,
                    isUnder && styles.underValue,
                  ]}>
                    {prop.actual_value}
                  </Text>
                ) : (
                  <Text style={styles.statValue}>-</Text>
                )}
                <Text style={styles.lineText}>o{prop.line}</Text>
              </Pressable>
            );
          })}
        </View>
      ) : (
        <Text style={styles.noProps}>No props available today</Text>
      )}

      {/* AI recommendation (if any T1/T2 pick) */}
      {props.some(p => p.ai_tier === 'T1-ELITE' || p.ai_tier === 'T2-STRONG') && (
        <View style={styles.aiRow}>
          <Text style={styles.aiLabel}>AI</Text>
          <Text style={styles.aiText}>
            Top pick available
          </Text>
        </View>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    backgroundColor: '#1e1e2e',
    borderRadius: 12,
    padding: 12,
    marginHorizontal: 16,
    marginVertical: 4,
  },
  header: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 10,
  },
  playerRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    flex: 1,
  },
  teamDot: {
    width: 8,
    height: 8,
    borderRadius: 4,
  },
  playerName: {
    color: '#fff',
    fontSize: 16,
    fontWeight: '700',
    flex: 1,
  },
  team: {
    color: '#888',
    fontSize: 12,
  },
  statusRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
  },
  status: {
    color: '#888',
    fontSize: 12,
  },
  liveStatus: {
    color: '#4CAF50',
    fontWeight: '600',
  },
  liveDot: {
    width: 6,
    height: 6,
    borderRadius: 3,
    backgroundColor: '#4CAF50',
  },
  statsGrid: {
    flexDirection: 'row',
    justifyContent: 'space-between',
  },
  statCell: {
    alignItems: 'center',
    minWidth: 42,
    flex: 1,
  },
  statLabel: {
    color: '#666',
    fontSize: 10,
    fontWeight: '600',
    marginBottom: 2,
  },
  statValue: {
    color: '#fff',
    fontSize: 18,
    fontWeight: '700',
  },
  overValue: {
    color: '#4CAF50',
  },
  underValue: {
    color: '#F44336',
  },
  lineText: {
    color: '#555',
    fontSize: 10,
    marginTop: 1,
  },
  noProps: {
    color: '#555',
    fontSize: 12,
    textAlign: 'center',
    paddingVertical: 8,
  },
  aiRow: {
    flexDirection: 'row',
    alignItems: 'center',
    marginTop: 8,
    paddingTop: 8,
    borderTopWidth: 1,
    borderTopColor: '#2a2a3e',
    gap: 6,
  },
  aiLabel: {
    color: '#FFD700',
    fontSize: 10,
    fontWeight: '800',
  },
  aiText: {
    color: '#888',
    fontSize: 11,
  },
});
