import React from 'react';
import { View, Text, StyleSheet } from 'react-native';

interface PLSummaryProps {
  netPL: number;
  totalStaked: number;
  wonBets: number;
  lostBets: number;
  pendingBets: number;
}

export function PLSummary({ netPL, totalStaked, wonBets, lostBets, pendingBets }: PLSummaryProps) {
  const roi = totalStaked > 0 ? (netPL / totalStaked) * 100 : 0;
  const winRate = (wonBets + lostBets) > 0
    ? (wonBets / (wonBets + lostBets)) * 100
    : 0;

  return (
    <View style={styles.container}>
      {/* Main P/L */}
      <View style={styles.plSection}>
        <Text style={styles.plLabel}>Net P/L</Text>
        <Text style={[
          styles.plValue,
          netPL > 0 ? styles.positive : netPL < 0 ? styles.negative : styles.neutral,
        ]}>
          {netPL >= 0 ? '+' : ''}{netPL.toFixed(2)}
        </Text>
        <Text style={[
          styles.roi,
          roi > 0 ? styles.positive : roi < 0 ? styles.negative : styles.neutral,
        ]}>
          {roi >= 0 ? '+' : ''}{roi.toFixed(1)}% ROI
        </Text>
      </View>

      {/* Stats row */}
      <View style={styles.statsRow}>
        <View style={styles.stat}>
          <Text style={styles.statValue}>${totalStaked.toFixed(0)}</Text>
          <Text style={styles.statLabel}>Staked</Text>
        </View>
        <View style={styles.divider} />
        <View style={styles.stat}>
          <Text style={[styles.statValue, styles.positive]}>{wonBets}</Text>
          <Text style={styles.statLabel}>Won</Text>
        </View>
        <View style={styles.divider} />
        <View style={styles.stat}>
          <Text style={[styles.statValue, styles.negative]}>{lostBets}</Text>
          <Text style={styles.statLabel}>Lost</Text>
        </View>
        <View style={styles.divider} />
        <View style={styles.stat}>
          <Text style={styles.statValue}>{pendingBets}</Text>
          <Text style={styles.statLabel}>Open</Text>
        </View>
        <View style={styles.divider} />
        <View style={styles.stat}>
          <Text style={styles.statValue}>{winRate.toFixed(0)}%</Text>
          <Text style={styles.statLabel}>Win Rate</Text>
        </View>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    backgroundColor: '#1e1e2e',
    borderRadius: 12,
    padding: 16,
    marginHorizontal: 16,
    marginVertical: 8,
  },
  plSection: {
    alignItems: 'center',
    marginBottom: 14,
  },
  plLabel: {
    color: '#888',
    fontSize: 12,
    fontWeight: '600',
    textTransform: 'uppercase',
    letterSpacing: 1,
  },
  plValue: {
    fontSize: 36,
    fontWeight: '800',
    marginVertical: 2,
  },
  roi: {
    fontSize: 14,
    fontWeight: '600',
  },
  positive: {
    color: '#4CAF50',
  },
  negative: {
    color: '#F44336',
  },
  neutral: {
    color: '#888',
  },
  statsRow: {
    flexDirection: 'row',
    justifyContent: 'space-around',
    alignItems: 'center',
    borderTopWidth: 1,
    borderTopColor: '#2a2a3e',
    paddingTop: 12,
  },
  stat: {
    alignItems: 'center',
    flex: 1,
  },
  statValue: {
    color: '#fff',
    fontSize: 16,
    fontWeight: '700',
  },
  statLabel: {
    color: '#666',
    fontSize: 10,
    marginTop: 2,
    textTransform: 'uppercase',
  },
  divider: {
    width: 1,
    height: 24,
    backgroundColor: '#2a2a3e',
  },
});
