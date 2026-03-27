import React from 'react';
import { View, Text, StyleSheet, ScrollView } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useParlayStore } from '../store/parlayStore';
import { ParlaySlip } from '../components/parlay/ParlaySlip';
import { EVCalculator } from '../components/parlay/EVCalculator';
import { PAYOUTS } from '../utils/constants';

export function ParlayBuilderScreen() {
  const picks = useParlayStore((state) => state.picks);
  const result = useParlayStore((state) => state.result);
  const removePick = useParlayStore((state) => state.removePick);
  const clearPicks = useParlayStore((state) => state.clearPicks);
  const updatePickOddsType = useParlayStore((state) => state.updatePickOddsType);

  return (
    <SafeAreaView style={styles.container} edges={['top']}>
      <View style={styles.header}>
        <Text style={styles.title}>Parlay Builder</Text>
        <Text style={styles.subtitle}>Build your parlay and see EV in real-time</Text>
      </View>

      <ScrollView
        style={styles.content}
        contentContainerStyle={styles.contentContainer}
        showsVerticalScrollIndicator={false}
      >
        {/* Parlay Slip */}
        <ParlaySlip
          picks={picks}
          onRemovePick={removePick}
          onClearAll={clearPicks}
          onChangeOddsType={updatePickOddsType}
        />

        {/* EV Calculator */}
        {result && (
          <View style={styles.evSection}>
            <EVCalculator result={result} />
          </View>
        )}

        {/* Payout Reference */}
        <View style={styles.referenceCard}>
          <Text style={styles.referenceTitle}>Payout Reference</Text>
          <View style={styles.payoutTable}>
            {Object.entries(PAYOUTS).map(([legs, payout]) => (
              <View key={legs} style={styles.payoutRow}>
                <Text style={styles.payoutLegs}>{legs} legs</Text>
                <Text style={styles.payoutValue}>{payout}x</Text>
              </View>
            ))}
          </View>

          <View style={styles.legValueInfo}>
            <Text style={styles.legValueTitle}>Leg Values:</Text>
            <View style={styles.legValueRow}>
              <View style={[styles.legValueBadge, styles.goblinBadge]}>
                <Text style={styles.legValueText}>Goblin = 0.5L</Text>
              </View>
              <View style={[styles.legValueBadge, styles.standardBadge]}>
                <Text style={styles.legValueText}>Standard = 1L</Text>
              </View>
              <View style={[styles.legValueBadge, styles.demonBadge]}>
                <Text style={styles.legValueText}>Demon = 1.5L</Text>
              </View>
            </View>
          </View>
        </View>

        {/* Tips */}
        <View style={styles.tipsCard}>
          <Text style={styles.tipsTitle}>Tips</Text>
          <Text style={styles.tipText}>
            * EV above +30% is considered strong value
          </Text>
          <Text style={styles.tipText}>
            * Goblin lines are easier but pay less
          </Text>
          <Text style={styles.tipText}>
            * Mix goblin/standard to optimize leg value
          </Text>
          <Text style={styles.tipText}>
            * Fractional legs interpolate payouts
          </Text>
        </View>
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#121212',
  },
  header: {
    paddingHorizontal: 16,
    paddingVertical: 12,
  },
  title: {
    color: '#fff',
    fontSize: 28,
    fontWeight: 'bold',
  },
  subtitle: {
    color: '#888',
    fontSize: 12,
    marginTop: 4,
  },
  content: {
    flex: 1,
  },
  contentContainer: {
    padding: 16,
    paddingBottom: 32,
  },
  evSection: {
    marginTop: 16,
  },
  referenceCard: {
    backgroundColor: '#1e1e2e',
    borderRadius: 12,
    padding: 16,
    marginTop: 16,
  },
  referenceTitle: {
    color: '#fff',
    fontSize: 16,
    fontWeight: 'bold',
    marginBottom: 12,
  },
  payoutTable: {
    gap: 8,
  },
  payoutRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    paddingVertical: 4,
  },
  payoutLegs: {
    color: '#888',
    fontSize: 14,
  },
  payoutValue: {
    color: '#4CAF50',
    fontSize: 14,
    fontWeight: 'bold',
  },
  legValueInfo: {
    marginTop: 16,
    paddingTop: 16,
    borderTopWidth: 1,
    borderTopColor: '#333',
  },
  legValueTitle: {
    color: '#888',
    fontSize: 12,
    marginBottom: 8,
  },
  legValueRow: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 8,
  },
  legValueBadge: {
    paddingHorizontal: 8,
    paddingVertical: 4,
    borderRadius: 4,
  },
  goblinBadge: {
    backgroundColor: '#2E7D3220',
    borderColor: '#2E7D32',
    borderWidth: 1,
  },
  standardBadge: {
    backgroundColor: '#1976D220',
    borderColor: '#1976D2',
    borderWidth: 1,
  },
  demonBadge: {
    backgroundColor: '#D32F2F20',
    borderColor: '#D32F2F',
    borderWidth: 1,
  },
  legValueText: {
    color: '#fff',
    fontSize: 12,
  },
  tipsCard: {
    backgroundColor: '#1e1e2e',
    borderRadius: 12,
    padding: 16,
    marginTop: 16,
  },
  tipsTitle: {
    color: '#FFD700',
    fontSize: 14,
    fontWeight: 'bold',
    marginBottom: 8,
  },
  tipText: {
    color: '#888',
    fontSize: 12,
    marginBottom: 4,
  },
});
