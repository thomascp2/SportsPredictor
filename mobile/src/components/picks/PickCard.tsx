import React from 'react';
import { View, Text, StyleSheet, TouchableOpacity } from 'react-native';
import { SmartPick } from '../../services/api';
import { TierBadge } from './TierBadge';
import { EdgeIndicator } from './EdgeIndicator';
import { Card } from '../common/Card';

interface PickCardProps {
  pick: SmartPick;
  onAddToParlay?: (pick: SmartPick) => void;
  isInParlay?: boolean;
}

export function PickCard({ pick, onAddToParlay, isInParlay }: PickCardProps) {
  const predictionColor = pick.prediction === 'OVER' ? '#4CAF50' : '#F44336';

  return (
    <Card style={isInParlay ? styles.inParlay : undefined}>
      <View style={styles.header}>
        <View style={styles.playerInfo}>
          <Text style={styles.playerName}>{pick.player_name}</Text>
          <View style={styles.matchupRow}>
            <Text style={styles.matchup}>
              {pick.team} vs {pick.opponent}
            </Text>
            <View style={styles.todayBadge}>
              <Text style={styles.todayText}>TODAY</Text>
            </View>
          </View>
        </View>
        <TierBadge tier={pick.tier} />
      </View>

      <View style={styles.propRow}>
        <View style={styles.propInfo}>
          <Text style={styles.propType}>{pick.prop_type}</Text>
          <View style={styles.lineContainer}>
            <Text style={[styles.prediction, { color: predictionColor }]}>
              {pick.prediction}
            </Text>
            <Text style={styles.line}>{pick.pp_line}</Text>
          </View>
        </View>

        <View style={styles.statsContainer}>
          <View style={styles.stat}>
            <Text style={styles.statLabel}>Prob</Text>
            <Text style={styles.statValue}>
              {(pick.pp_probability * 100).toFixed(0)}%
            </Text>
          </View>
          <EdgeIndicator edge={pick.edge} />
        </View>
      </View>

      {/* Probability bar */}
      <View style={styles.probBarContainer}>
        <View
          style={[
            styles.probBar,
            {
              width: `${Math.min(pick.pp_probability * 100, 100)}%`,
              backgroundColor:
                pick.pp_probability >= 0.7
                  ? '#4CAF50'
                  : pick.pp_probability >= 0.6
                  ? '#FFD700'
                  : '#FFA500',
            },
          ]}
        />
      </View>

      {/* Odds type badge */}
      <View style={styles.footer}>
        <View style={[styles.oddsTypeBadge, styles[pick.pp_odds_type as keyof typeof styles] || styles.standard]}>
          <Text style={styles.oddsTypeText}>{pick.pp_odds_type?.toUpperCase() || 'STANDARD'}</Text>
        </View>

        {onAddToParlay && (
          <TouchableOpacity
            style={[styles.addButton, isInParlay && styles.removeButton]}
            onPress={() => onAddToParlay(pick)}
          >
            <Text style={styles.addButtonText}>
              {isInParlay ? '- Remove' : '+ Parlay'}
            </Text>
          </TouchableOpacity>
        )}
      </View>
    </Card>
  );
}

const styles = StyleSheet.create({
  header: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'flex-start',
    marginBottom: 12,
  },
  playerInfo: {
    flex: 1,
  },
  playerName: {
    color: '#fff',
    fontSize: 18,
    fontWeight: 'bold',
  },
  matchupRow: {
    flexDirection: 'row',
    alignItems: 'center',
    marginTop: 2,
    gap: 8,
  },
  matchup: {
    color: '#888',
    fontSize: 12,
  },
  todayBadge: {
    backgroundColor: '#4CAF5030',
    paddingHorizontal: 6,
    paddingVertical: 2,
    borderRadius: 4,
  },
  todayText: {
    color: '#4CAF50',
    fontSize: 9,
    fontWeight: 'bold',
  },
  propRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 12,
  },
  propInfo: {
    flex: 1,
  },
  propType: {
    color: '#aaa',
    fontSize: 14,
    textTransform: 'uppercase',
  },
  lineContainer: {
    flexDirection: 'row',
    alignItems: 'baseline',
    marginTop: 4,
  },
  prediction: {
    fontSize: 16,
    fontWeight: 'bold',
    marginRight: 8,
  },
  line: {
    color: '#fff',
    fontSize: 24,
    fontWeight: 'bold',
  },
  statsContainer: {
    flexDirection: 'row',
    gap: 16,
  },
  stat: {
    alignItems: 'center',
  },
  statLabel: {
    color: '#888',
    fontSize: 10,
    marginBottom: 2,
  },
  statValue: {
    color: '#fff',
    fontSize: 16,
    fontWeight: 'bold',
  },
  probBarContainer: {
    height: 4,
    backgroundColor: '#333',
    borderRadius: 2,
    marginBottom: 12,
    overflow: 'hidden',
  },
  probBar: {
    height: '100%',
    borderRadius: 2,
  },
  footer: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  oddsTypeBadge: {
    paddingHorizontal: 8,
    paddingVertical: 4,
    borderRadius: 4,
  },
  goblin: {
    backgroundColor: '#2E7D3220',
    borderColor: '#2E7D32',
    borderWidth: 1,
  },
  standard: {
    backgroundColor: '#1976D220',
    borderColor: '#1976D2',
    borderWidth: 1,
  },
  demon: {
    backgroundColor: '#D32F2F20',
    borderColor: '#D32F2F',
    borderWidth: 1,
  },
  oddsTypeText: {
    color: '#fff',
    fontSize: 10,
    fontWeight: 'bold',
  },
  addButton: {
    backgroundColor: '#4CAF50',
    paddingHorizontal: 12,
    paddingVertical: 6,
    borderRadius: 4,
  },
  removeButton: {
    backgroundColor: '#F44336',
  },
  addButtonText: {
    color: '#fff',
    fontSize: 12,
    fontWeight: 'bold',
  },
  inParlay: {
    borderColor: '#4CAF50',
    borderWidth: 2,
  },
});
