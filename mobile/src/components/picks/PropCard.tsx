import React from 'react';
import { View, Text, StyleSheet } from 'react-native';
import { PickButton } from './PickButton';
import { AIPredictionChip } from '../common/AIPredictionChip';
import type { DailyProp, UserPick } from '../../types/supabase';

interface PropCardProps {
  prop: DailyProp;
  userPick?: UserPick;
  onPick: (propId: string, prediction: 'OVER' | 'UNDER') => void;
  showAI?: boolean;
  onUnlockAI?: (propId: string) => void;
}

export function PropCard({ prop, userPick, onPick, showAI = false, onUnlockAI }: PropCardProps) {
  const isLocked = prop.status !== 'open';
  const isGraded = prop.status === 'graded';
  const totalVotes = prop.over_count + prop.under_count;
  const overPct = totalVotes > 0 ? Math.round((prop.over_count / totalVotes) * 100) : 50;

  const formatPropType = (type: string) => {
    return type.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase());
  };

  return (
    <View style={[styles.card, isGraded && styles.gradedCard]}>
      {/* Header: player + matchup */}
      <View style={styles.header}>
        <View style={styles.playerInfo}>
          <Text style={styles.playerName}>{prop.player_name}</Text>
          <Text style={styles.matchup}>
            {prop.team} vs {prop.opponent}
          </Text>
        </View>
        {prop.game_time && (
          <Text style={styles.gameTime}>
            {new Date(prop.game_time).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })}
          </Text>
        )}
      </View>

      {/* Prop details */}
      <View style={styles.propRow}>
        <Text style={styles.propType}>{formatPropType(prop.prop_type)}</Text>
        <Text style={styles.line}>{prop.line}</Text>
        {prop.odds_type !== 'standard' && (
          <View style={[styles.oddsTag, prop.odds_type === 'goblin' ? styles.goblinTag : styles.demonTag]}>
            <Text style={styles.oddsTagText}>
              {prop.odds_type === 'goblin' ? 'GOB' : 'DMN'}
            </Text>
          </View>
        )}
      </View>

      {/* Actual value if graded */}
      {isGraded && prop.actual_value !== null && (
        <View style={styles.actualRow}>
          <Text style={styles.actualLabel}>Actual:</Text>
          <Text style={[
            styles.actualValue,
            prop.actual_value > prop.line ? styles.overActual : styles.underActual,
          ]}>
            {prop.actual_value}
          </Text>
        </View>
      )}

      {/* AI Prediction Chip */}
      {prop.ai_prediction && (
        <AIPredictionChip
          prediction={prop.ai_prediction}
          probability={prop.ai_probability}
          tier={prop.ai_tier}
          unlocked={showAI}
          onUnlock={onUnlockAI ? () => onUnlockAI(prop.id) : undefined}
        />
      )}

      {/* Pick Buttons — goblin/demon only allow OVER on PP */}
      <View style={styles.buttons}>
        <PickButton
          type="OVER"
          selected={userPick?.prediction === 'OVER'}
          disabled={isLocked || (!!userPick && userPick.prediction !== 'OVER')}
          result={userPick?.prediction === 'OVER' ? userPick.outcome : null}
          onPress={() => onPick(prop.id, 'OVER')}
        />
        {prop.odds_type === 'standard' && (
          <>
            <View style={styles.buttonGap} />
            <PickButton
              type="UNDER"
              selected={userPick?.prediction === 'UNDER'}
              disabled={isLocked || (!!userPick && userPick.prediction !== 'UNDER')}
              result={userPick?.prediction === 'UNDER' ? userPick.outcome : null}
              onPress={() => onPick(prop.id, 'UNDER')}
            />
          </>
        )}
      </View>

      {/* Community consensus bar */}
      {totalVotes > 0 && (
        <View style={styles.consensusContainer}>
          <View style={styles.consensusBar}>
            <View style={[styles.overBar, { flex: overPct }]} />
            <View style={[styles.underBar, { flex: 100 - overPct }]} />
          </View>
          <View style={styles.consensusLabels}>
            <Text style={styles.consensusText}>{overPct}% Over</Text>
            <Text style={styles.consensusText}>{100 - overPct}% Under</Text>
          </View>
        </View>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    backgroundColor: '#1e1e2e',
    borderRadius: 12,
    padding: 16,
    marginHorizontal: 16,
    marginVertical: 6,
  },
  gradedCard: {
    opacity: 0.8,
  },
  header: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'flex-start',
    marginBottom: 8,
  },
  playerInfo: {
    flex: 1,
  },
  playerName: {
    color: '#fff',
    fontSize: 18,
    fontWeight: '700',
  },
  matchup: {
    color: '#888',
    fontSize: 13,
    marginTop: 2,
  },
  gameTime: {
    color: '#888',
    fontSize: 12,
  },
  propRow: {
    flexDirection: 'row',
    alignItems: 'center',
    marginBottom: 12,
    gap: 8,
  },
  propType: {
    color: '#aaa',
    fontSize: 14,
  },
  line: {
    color: '#fff',
    fontSize: 28,
    fontWeight: '800',
  },
  oddsTag: {
    paddingHorizontal: 6,
    paddingVertical: 2,
    borderRadius: 4,
  },
  goblinTag: {
    backgroundColor: 'rgba(76, 175, 80, 0.2)',
  },
  demonTag: {
    backgroundColor: 'rgba(244, 67, 54, 0.2)',
  },
  oddsTagText: {
    color: '#aaa',
    fontSize: 10,
    fontWeight: '700',
  },
  actualRow: {
    flexDirection: 'row',
    alignItems: 'center',
    marginBottom: 8,
    gap: 6,
  },
  actualLabel: {
    color: '#888',
    fontSize: 13,
  },
  actualValue: {
    fontSize: 16,
    fontWeight: '700',
  },
  overActual: {
    color: '#4CAF50',
  },
  underActual: {
    color: '#F44336',
  },
  buttons: {
    flexDirection: 'row',
    gap: 0,
  },
  buttonGap: {
    width: 10,
  },
  consensusContainer: {
    marginTop: 10,
  },
  consensusBar: {
    flexDirection: 'row',
    height: 4,
    borderRadius: 2,
    overflow: 'hidden',
  },
  overBar: {
    backgroundColor: 'rgba(76, 175, 80, 0.6)',
  },
  underBar: {
    backgroundColor: 'rgba(244, 67, 54, 0.6)',
  },
  consensusLabels: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    marginTop: 4,
  },
  consensusText: {
    color: '#666',
    fontSize: 11,
  },
});
