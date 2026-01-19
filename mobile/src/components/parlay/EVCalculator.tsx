import React from 'react';
import { View, Text, StyleSheet } from 'react-native';
import { ParlayResult } from '../../utils/calculations';
import { EV_COLORS } from '../../utils/constants';

interface EVCalculatorProps {
  result: ParlayResult;
}

export function EVCalculator({ result }: EVCalculatorProps) {
  const evColor =
    result.evPercentage >= 30
      ? EV_COLORS.positive
      : result.evPercentage >= 0
      ? EV_COLORS.neutral
      : EV_COLORS.negative;

  return (
    <View style={styles.container}>
      <View style={styles.header}>
        <Text style={styles.title}>Expected Value</Text>
        <Text style={[styles.recommendation, { color: evColor }]}>
          {result.recommendation}
        </Text>
      </View>

      <View style={styles.mainStat}>
        <Text style={[styles.evValue, { color: evColor }]}>
          {result.evPercentage >= 0 ? '+' : ''}{result.evPercentage.toFixed(1)}%
        </Text>
        <Text style={styles.evLabel}>EV</Text>
      </View>

      <View style={styles.statsRow}>
        <View style={styles.stat}>
          <Text style={styles.statValue}>{result.totalLegValue}</Text>
          <Text style={styles.statLabel}>Legs</Text>
        </View>

        <View style={styles.stat}>
          <Text style={styles.statValue}>{result.payoutMultiplier}x</Text>
          <Text style={styles.statLabel}>Payout</Text>
        </View>

        <View style={styles.stat}>
          <Text style={styles.statValue}>{result.combinedProbabilityPct}</Text>
          <Text style={styles.statLabel}>Win Prob</Text>
        </View>
      </View>

      <View style={styles.breakEvenRow}>
        <Text style={styles.breakEvenLabel}>Break-even: </Text>
        <Text style={styles.breakEvenValue}>
          {(result.breakEvenProbability * 100).toFixed(1)}%
        </Text>
        <Text style={[styles.edgeValue, { color: evColor }]}>
          ({result.edgePct} edge)
        </Text>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    backgroundColor: '#1e1e2e',
    borderRadius: 12,
    padding: 16,
    marginVertical: 8,
  },
  header: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 16,
  },
  title: {
    color: '#fff',
    fontSize: 16,
    fontWeight: 'bold',
  },
  recommendation: {
    fontSize: 12,
    fontWeight: 'bold',
  },
  mainStat: {
    alignItems: 'center',
    marginBottom: 20,
  },
  evValue: {
    fontSize: 48,
    fontWeight: 'bold',
  },
  evLabel: {
    color: '#888',
    fontSize: 14,
    marginTop: 4,
  },
  statsRow: {
    flexDirection: 'row',
    justifyContent: 'space-around',
    marginBottom: 16,
    paddingTop: 16,
    borderTopWidth: 1,
    borderTopColor: '#333',
  },
  stat: {
    alignItems: 'center',
  },
  statValue: {
    color: '#fff',
    fontSize: 20,
    fontWeight: 'bold',
  },
  statLabel: {
    color: '#888',
    fontSize: 12,
    marginTop: 4,
  },
  breakEvenRow: {
    flexDirection: 'row',
    justifyContent: 'center',
    alignItems: 'center',
  },
  breakEvenLabel: {
    color: '#888',
    fontSize: 12,
  },
  breakEvenValue: {
    color: '#fff',
    fontSize: 12,
    fontWeight: '600',
  },
  edgeValue: {
    fontSize: 12,
    fontWeight: '600',
    marginLeft: 4,
  },
});
