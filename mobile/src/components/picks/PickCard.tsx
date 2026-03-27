import React from 'react';
import {
  View,
  Text,
  StyleSheet,
  TouchableOpacity,
  ViewStyle,
} from 'react-native';
import { SmartPick } from '../../services/api';
import { TierBadge } from './TierBadge';
import { EdgeIndicator } from './EdgeIndicator';
import { StatPercentileBar } from './StatPercentileBar';
import { Card } from '../common/Card';

// Prop type display labels
const PROP_LABELS: Record<string, string> = {
  points: 'PTS',
  rebounds: 'REB',
  assists: 'AST',
  threes: '3PM',
  pra: 'PRA',
  stocks: 'STK',
  minutes: 'MIN',
  blocks: 'BLK',
  steals: 'STL',
  pts_rebs: 'P+R',
  pts_asts: 'P+A',
  rebs_asts: 'R+A',
  shots: 'SOG',
  goals: 'G',
  saves: 'SAV',
};

const oddsTypeBadgeStyles: Record<string, ViewStyle> = {
  goblin: { backgroundColor: '#2E7D3215', borderColor: '#2E7D32', borderWidth: 1 },
  standard: { backgroundColor: '#1976D215', borderColor: '#1976D2', borderWidth: 1 },
  demon: { backgroundColor: '#D32F2F15', borderColor: '#D32F2F', borderWidth: 1 },
};

const oddsTypeTextColor: Record<string, string> = {
  goblin: '#66BB6A',
  standard: '#42A5F5',
  demon: '#EF5350',
};

interface PickCardProps {
  pick: SmartPick;
  onAddToParlay?: (pick: SmartPick) => void;
  onPlayerPress?: (pick: SmartPick) => void;
  isInParlay?: boolean;
}

export function PickCard({ pick, onAddToParlay, onPlayerPress, isInParlay }: PickCardProps) {
  const predictionColor = pick.prediction === 'OVER' ? '#4CAF50' : '#EF5350';
  const propLabel = PROP_LABELS[pick.prop_type] || pick.prop_type.toUpperCase();
  const oddsType = pick.pp_odds_type || 'standard';
  const textColor = oddsTypeTextColor[oddsType] || '#888';

  // For percentile bar: use season_avg vs pp_line context
  const hasPercentile = pick.percentile_score != null;

  return (
    <Card style={[isInParlay ? styles.inParlay : styles.card]}>
      {/* ── Header row: player name + tier badge ── */}
      <View style={styles.header}>
        <TouchableOpacity
          style={styles.playerArea}
          onPress={() => onPlayerPress?.(pick)}
          disabled={!onPlayerPress}
          activeOpacity={0.7}
        >
          <Text style={styles.playerName} numberOfLines={1}>{pick.player_name}</Text>
          <Text style={styles.matchup} numberOfLines={1}>
            {pick.matchup || `${pick.team} vs ${pick.opponent}`}
          </Text>
        </TouchableOpacity>

        <View style={styles.headerRight}>
          <TierBadge tier={pick.tier} />
          {pick.game_time ? (
            <View style={styles.timeBadge}>
              <Text style={styles.timeText}>{pick.game_time}</Text>
            </View>
          ) : null}
        </View>
      </View>

      {/* ── Prop line row ── */}
      <View style={styles.propRow}>
        {/* Left: prop type + prediction + line */}
        <View style={styles.propLeft}>
          <Text style={styles.propLabel}>{propLabel}</Text>
          <View style={styles.lineRow}>
            <Text style={[styles.direction, { color: predictionColor }]}>
              {pick.prediction}
            </Text>
            <Text style={styles.line}>{pick.pp_line}</Text>
          </View>
        </View>

        {/* Right: probability + edge */}
        <View style={styles.propRight}>
          {/* Circular-ish prob display */}
          <View style={[styles.probBubble, {
            borderColor: pick.pp_probability >= 0.7 ? '#4CAF50' :
              pick.pp_probability >= 0.6 ? '#FFD700' : '#FF9800',
          }]}>
            <Text style={[styles.probValue, {
              color: pick.pp_probability >= 0.7 ? '#4CAF50' :
                pick.pp_probability >= 0.6 ? '#FFD700' : '#FF9800',
            }]}>
              {(pick.pp_probability * 100).toFixed(0)}%
            </Text>
            <Text style={styles.probLabel}>PROB</Text>
          </View>
          <EdgeIndicator edge={pick.edge} />
        </View>
      </View>

      {/* ── League percentile bar ── */}
      {hasPercentile && (
        <View style={styles.percentileSection}>
          <StatPercentileBar
            percentile={pick.percentile_score!}
            seasonAvg={pick.season_avg || undefined}
            ppLine={pick.pp_line}
            propLabel={propLabel}
            height={7}
            showScore={true}
          />
        </View>
      )}

      {/* ── Footer: odds type + add-to-parlay button ── */}
      <View style={styles.footer}>
        <View style={[styles.oddsTypeBadge, oddsTypeBadgeStyles[oddsType] || oddsTypeBadgeStyles.standard]}>
          <Text style={[styles.oddsTypeText, { color: textColor }]}>
            {oddsType.toUpperCase()}
          </Text>
        </View>

        {/* EV signal if high */}
        {pick.ev_4leg != null && pick.ev_4leg > 0.3 && (
          <View style={styles.evBadge}>
            <Text style={styles.evBadgeText}>
              +{(pick.ev_4leg * 100).toFixed(0)}% EV@4L
            </Text>
          </View>
        )}

        {onAddToParlay && (
          <TouchableOpacity
            style={[styles.addButton, isInParlay && styles.removeButton]}
            onPress={() => onAddToParlay(pick)}
            activeOpacity={0.8}
          >
            <Text style={styles.addButtonText}>
              {isInParlay ? '− Remove' : '+ Add'}
            </Text>
          </TouchableOpacity>
        )}
      </View>
    </Card>
  );
}

const styles = StyleSheet.create({
  card: {
    marginHorizontal: 12,
    marginVertical: 5,
  },
  inParlay: {
    marginHorizontal: 12,
    marginVertical: 5,
    borderColor: '#4CAF50',
    borderWidth: 1.5,
  },
  header: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'flex-start',
    marginBottom: 10,
  },
  playerArea: {
    flex: 1,
    paddingRight: 8,
  },
  playerName: {
    color: '#fff',
    fontSize: 17,
    fontWeight: '700',
    letterSpacing: 0.2,
  },
  matchup: {
    color: '#666',
    fontSize: 11,
    marginTop: 2,
  },
  headerRight: {
    alignItems: 'flex-end',
    gap: 4,
  },
  timeBadge: {
    backgroundColor: '#1976D220',
    paddingHorizontal: 6,
    paddingVertical: 2,
    borderRadius: 4,
  },
  timeText: {
    color: '#42A5F5',
    fontSize: 9,
    fontWeight: '600',
  },
  propRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 10,
  },
  propLeft: {
    flex: 1,
  },
  propLabel: {
    color: '#999',
    fontSize: 11,
    fontWeight: '600',
    letterSpacing: 1,
    textTransform: 'uppercase',
    marginBottom: 2,
  },
  lineRow: {
    flexDirection: 'row',
    alignItems: 'baseline',
    gap: 6,
  },
  direction: {
    fontSize: 14,
    fontWeight: '700',
  },
  line: {
    color: '#fff',
    fontSize: 26,
    fontWeight: '800',
    letterSpacing: -0.5,
  },
  propRight: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
  },
  probBubble: {
    alignItems: 'center',
    width: 52,
    height: 52,
    borderRadius: 26,
    borderWidth: 2,
    justifyContent: 'center',
    backgroundColor: '#1a1a2a',
  },
  probValue: {
    fontSize: 14,
    fontWeight: '800',
    lineHeight: 16,
  },
  probLabel: {
    color: '#555',
    fontSize: 8,
    fontWeight: '600',
    letterSpacing: 0.5,
  },
  percentileSection: {
    marginBottom: 10,
  },
  footer: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    flexWrap: 'wrap',
  },
  oddsTypeBadge: {
    paddingHorizontal: 7,
    paddingVertical: 3,
    borderRadius: 4,
  },
  oddsTypeText: {
    fontSize: 9,
    fontWeight: '700',
    letterSpacing: 0.5,
  },
  evBadge: {
    backgroundColor: '#4CAF5015',
    borderColor: '#4CAF50',
    borderWidth: 1,
    paddingHorizontal: 7,
    paddingVertical: 3,
    borderRadius: 4,
  },
  evBadgeText: {
    color: '#4CAF50',
    fontSize: 9,
    fontWeight: '700',
  },
  addButton: {
    marginLeft: 'auto',
    backgroundColor: '#4CAF50',
    paddingHorizontal: 14,
    paddingVertical: 7,
    borderRadius: 6,
  },
  removeButton: {
    backgroundColor: '#EF5350',
  },
  addButtonText: {
    color: '#fff',
    fontSize: 12,
    fontWeight: '700',
  },
});
