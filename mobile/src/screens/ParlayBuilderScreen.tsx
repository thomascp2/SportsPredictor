import React, { useState } from 'react';
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  TextInput,
  TouchableOpacity,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useParlayStore } from '../store/parlayStore';
import { ParlaySlip } from '../components/parlay/ParlaySlip';
import { EVCalculator } from '../components/parlay/EVCalculator';
import { PAYOUTS } from '../utils/constants';

const QUICK_STAKES = [5, 10, 20, 50, 100];

export function ParlayBuilderScreen() {
  const picks = useParlayStore((state) => state.picks);
  const result = useParlayStore((state) => state.result);
  const stakeAmount = useParlayStore((state) => state.stakeAmount);
  const removePick = useParlayStore((state) => state.removePick);
  const clearPicks = useParlayStore((state) => state.clearPicks);
  const updatePickOddsType = useParlayStore((state) => state.updatePickOddsType);
  const setStakeAmount = useParlayStore((state) => state.setStakeAmount);

  const [stakeInput, setStakeInput] = useState(String(stakeAmount));

  const handleStakeChange = (text: string) => {
    setStakeInput(text);
    const val = parseFloat(text);
    if (!isNaN(val) && val > 0) {
      setStakeAmount(val);
    }
  };

  const handleQuickStake = (amount: number) => {
    setStakeInput(String(amount));
    setStakeAmount(amount);
  };

  // Compute payout amounts
  const payoutMultiplier = result?.payoutMultiplier ?? 0;
  const grossPayout = stakeAmount * payoutMultiplier;
  const netProfit = grossPayout - stakeAmount;
  const evColor =
    !result
      ? '#888'
      : result.evPercentage >= 30
      ? '#00E676'
      : result.evPercentage >= 0
      ? '#FFD700'
      : '#EF5350';

  return (
    <SafeAreaView style={styles.container} edges={['top']}>
      <View style={styles.header}>
        <Text style={styles.title}>Parlay Builder</Text>
        <Text style={styles.subtitle}>
          {picks.length} pick{picks.length !== 1 ? 's' : ''} selected
        </Text>
      </View>

      <ScrollView
        style={styles.content}
        contentContainerStyle={styles.contentContainer}
        showsVerticalScrollIndicator={false}
        keyboardShouldPersistTaps="handled"
      >
        {/* ── Stake input ── */}
        <View style={styles.stakeCard}>
          <Text style={styles.stakeTitle}>Wager Amount</Text>
          <View style={styles.stakeRow}>
            <Text style={styles.dollarSign}>$</Text>
            <TextInput
              style={styles.stakeInput}
              value={stakeInput}
              onChangeText={handleStakeChange}
              keyboardType="decimal-pad"
              selectTextOnFocus
              placeholderTextColor="#555"
            />
          </View>
          {/* Quick-pick amounts */}
          <View style={styles.quickStakes}>
            {QUICK_STAKES.map((amt) => (
              <TouchableOpacity
                key={amt}
                style={[
                  styles.quickStakeBtn,
                  stakeAmount === amt && styles.quickStakeBtnActive,
                ]}
                onPress={() => handleQuickStake(amt)}
              >
                <Text
                  style={[
                    styles.quickStakeText,
                    stakeAmount === amt && styles.quickStakeTextActive,
                  ]}
                >
                  ${amt}
                </Text>
              </TouchableOpacity>
            ))}
          </View>
        </View>

        {/* ── Payout summary ── */}
        {result && picks.length >= 2 && (
          <View style={styles.payoutCard}>
            <View style={styles.payoutRow}>
              <View style={styles.payoutItem}>
                <Text style={styles.payoutLabel}>Stake</Text>
                <Text style={styles.payoutAmount}>${stakeAmount.toFixed(2)}</Text>
              </View>
              <View style={styles.payoutDivider} />
              <View style={styles.payoutItem}>
                <Text style={styles.payoutLabel}>Multiplier</Text>
                <Text style={[styles.payoutAmount, { color: evColor }]}>
                  {payoutMultiplier}×
                </Text>
              </View>
              <View style={styles.payoutDivider} />
              <View style={styles.payoutItem}>
                <Text style={styles.payoutLabel}>To Win</Text>
                <Text style={[styles.payoutWin, { color: netProfit > 0 ? '#00E676' : '#EF5350' }]}>
                  +${netProfit.toFixed(2)}
                </Text>
              </View>
              <View style={styles.payoutDivider} />
              <View style={styles.payoutItem}>
                <Text style={styles.payoutLabel}>Total Out</Text>
                <Text style={[styles.payoutAmount, { color: '#fff' }]}>
                  ${grossPayout.toFixed(2)}
                </Text>
              </View>
            </View>
            <View style={[styles.evBar, { backgroundColor: evColor + '25' }]}>
              <Text style={[styles.evBarText, { color: evColor }]}>
                {result.recommendation}
                {'  '}
                <Text style={styles.evBarSubtext}>
                  {result.evPercentage >= 0 ? '+' : ''}{result.evPercentage.toFixed(1)}% EV
                  {'  ·  '}
                  {result.combinedProbabilityPct} hit prob
                </Text>
              </Text>
            </View>
          </View>
        )}

        {/* ── Parlay slip ── */}
        <ParlaySlip
          picks={picks}
          onRemovePick={removePick}
          onClearAll={clearPicks}
          onChangeOddsType={updatePickOddsType}
        />

        {/* ── EV Calculator ── */}
        {result && picks.length >= 2 && (
          <View style={styles.evSection}>
            <EVCalculator result={result} />
          </View>
        )}

        {/* ── Payout reference ── */}
        <View style={styles.referenceCard}>
          <Text style={styles.referenceTitle}>Payout Reference</Text>
          <View style={styles.payoutTable}>
            {Object.entries(PAYOUTS).map(([legs, payout]) => {
              const gross = stakeAmount * payout;
              const net = gross - stakeAmount;
              return (
                <View key={legs} style={styles.payoutTableRow}>
                  <Text style={styles.payoutTableLegs}>{legs} legs</Text>
                  <Text style={styles.payoutTableMultiplier}>{payout}×</Text>
                  <Text style={styles.payoutTableNet}>+${net.toFixed(2)}</Text>
                  <Text style={styles.payoutTableGross}>${gross.toFixed(2)}</Text>
                </View>
              );
            })}
          </View>

          <View style={styles.legValueInfo}>
            <Text style={styles.legValueTitle}>Leg Values:</Text>
            <View style={styles.legValueRow}>
              {(['goblin', 'standard', 'demon'] as const).map((type) => (
                <View
                  key={type}
                  style={[
                    styles.legValueBadge,
                    type === 'goblin' ? styles.goblinBadge
                      : type === 'demon' ? styles.demonBadge
                      : styles.standardBadge,
                  ]}
                >
                  <Text style={styles.legValueText}>
                    {type.charAt(0).toUpperCase() + type.slice(1)} ={' '}
                    {type === 'goblin' ? '0.5L' : type === 'standard' ? '1.0L' : '1.5L'}
                  </Text>
                </View>
              ))}
            </View>
          </View>
        </View>
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#0d0d1a',
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
    color: '#555',
    fontSize: 12,
    marginTop: 2,
  },
  content: {
    flex: 1,
  },
  contentContainer: {
    padding: 16,
    paddingBottom: 40,
    gap: 14,
  },
  // Stake card
  stakeCard: {
    backgroundColor: '#161625',
    borderRadius: 14,
    padding: 16,
    borderWidth: 1,
    borderColor: '#2a2a3e',
  },
  stakeTitle: {
    color: '#888',
    fontSize: 11,
    fontWeight: '600',
    letterSpacing: 1,
    textTransform: 'uppercase',
    marginBottom: 10,
  },
  stakeRow: {
    flexDirection: 'row',
    alignItems: 'center',
    marginBottom: 12,
  },
  dollarSign: {
    color: '#4CAF50',
    fontSize: 28,
    fontWeight: '700',
    marginRight: 6,
  },
  stakeInput: {
    color: '#fff',
    fontSize: 32,
    fontWeight: '800',
    flex: 1,
    borderBottomWidth: 2,
    borderBottomColor: '#4CAF50',
    paddingBottom: 2,
    letterSpacing: -0.5,
  },
  quickStakes: {
    flexDirection: 'row',
    gap: 8,
    flexWrap: 'wrap',
  },
  quickStakeBtn: {
    backgroundColor: '#252535',
    paddingHorizontal: 14,
    paddingVertical: 7,
    borderRadius: 20,
    borderWidth: 1,
    borderColor: '#333',
  },
  quickStakeBtnActive: {
    backgroundColor: '#4CAF5020',
    borderColor: '#4CAF50',
  },
  quickStakeText: {
    color: '#666',
    fontSize: 13,
    fontWeight: '600',
  },
  quickStakeTextActive: {
    color: '#4CAF50',
  },
  // Payout card
  payoutCard: {
    backgroundColor: '#161625',
    borderRadius: 14,
    overflow: 'hidden',
    borderWidth: 1,
    borderColor: '#2a2a3e',
  },
  payoutRow: {
    flexDirection: 'row',
    padding: 14,
  },
  payoutItem: {
    flex: 1,
    alignItems: 'center',
  },
  payoutDivider: {
    width: 1,
    backgroundColor: '#2a2a3e',
    marginVertical: 4,
  },
  payoutLabel: {
    color: '#555',
    fontSize: 10,
    fontWeight: '600',
    letterSpacing: 0.5,
    textTransform: 'uppercase',
    marginBottom: 4,
  },
  payoutAmount: {
    color: '#fff',
    fontSize: 17,
    fontWeight: '700',
  },
  payoutWin: {
    fontSize: 17,
    fontWeight: '800',
  },
  evBar: {
    paddingVertical: 9,
    paddingHorizontal: 14,
    alignItems: 'center',
  },
  evBarText: {
    fontSize: 13,
    fontWeight: '700',
  },
  evBarSubtext: {
    fontWeight: '400',
    color: '#888',
    fontSize: 12,
  },
  evSection: {},
  // Reference table
  referenceCard: {
    backgroundColor: '#161625',
    borderRadius: 14,
    padding: 16,
    borderWidth: 1,
    borderColor: '#2a2a3e',
  },
  referenceTitle: {
    color: '#fff',
    fontSize: 14,
    fontWeight: '700',
    marginBottom: 12,
  },
  payoutTable: {
    gap: 6,
  },
  payoutTableRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingVertical: 6,
    borderBottomWidth: 1,
    borderBottomColor: '#1e1e2e',
  },
  payoutTableLegs: {
    color: '#666',
    fontSize: 13,
    flex: 1,
  },
  payoutTableMultiplier: {
    color: '#888',
    fontSize: 13,
    fontWeight: '600',
    flex: 1,
    textAlign: 'center',
  },
  payoutTableNet: {
    color: '#4CAF50',
    fontSize: 13,
    fontWeight: '700',
    flex: 1,
    textAlign: 'center',
  },
  payoutTableGross: {
    color: '#fff',
    fontSize: 13,
    fontWeight: '600',
    flex: 1,
    textAlign: 'right',
  },
  legValueInfo: {
    marginTop: 16,
    paddingTop: 14,
    borderTopWidth: 1,
    borderTopColor: '#252535',
  },
  legValueTitle: {
    color: '#666',
    fontSize: 11,
    marginBottom: 8,
  },
  legValueRow: {
    flexDirection: 'row',
    gap: 8,
    flexWrap: 'wrap',
  },
  legValueBadge: {
    paddingHorizontal: 10,
    paddingVertical: 5,
    borderRadius: 6,
    borderWidth: 1,
  },
  goblinBadge: {
    backgroundColor: '#2E7D3215',
    borderColor: '#2E7D32',
  },
  standardBadge: {
    backgroundColor: '#1976D215',
    borderColor: '#1976D2',
  },
  demonBadge: {
    backgroundColor: '#D32F2F15',
    borderColor: '#D32F2F',
  },
  legValueText: {
    color: '#ccc',
    fontSize: 12,
    fontWeight: '600',
  },
});
