import React from 'react';
import { Pressable, Text, StyleSheet, View } from 'react-native';
import { TIER_COLORS } from '../../utils/constants';

interface AIPredictionChipProps {
  prediction: string;
  probability: number | null;
  tier: string | null;
  unlocked: boolean;
  onUnlock?: () => void;
}

export function AIPredictionChip({
  prediction,
  probability,
  tier,
  unlocked,
  onUnlock,
}: AIPredictionChipProps) {
  const tierColor = tier ? TIER_COLORS[tier] || '#888' : '#888';

  if (!unlocked) {
    return (
      <Pressable onPress={onUnlock} style={styles.lockedContainer}>
        <Text style={styles.lockIcon}>?</Text>
        <Text style={styles.lockedText}>AI Pick Available</Text>
        {onUnlock && <Text style={styles.unlockCost}>25 pts</Text>}
      </Pressable>
    );
  }

  return (
    <View style={[styles.container, { borderColor: tierColor }]}>
      <Text style={[styles.label, { color: tierColor }]}>AI</Text>
      <Text style={[
        styles.prediction,
        prediction === 'OVER' ? styles.overText : styles.underText,
      ]}>
        {prediction}
      </Text>
      {probability !== null && (
        <Text style={[styles.probability, { color: tierColor }]}>
          {Math.round(probability * 100)}%
        </Text>
      )}
      {tier && (
        <View style={[styles.tierBadge, { backgroundColor: `${tierColor}20` }]}>
          <Text style={[styles.tierText, { color: tierColor }]}>
            {tier.replace('T1-', '').replace('T2-', '').replace('T3-', '').replace('T4-', '').replace('T5-', '')}
          </Text>
        </View>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: 10,
    paddingVertical: 6,
    borderRadius: 8,
    borderWidth: 1,
    marginBottom: 10,
    gap: 6,
  },
  label: {
    fontSize: 11,
    fontWeight: '800',
    letterSpacing: 0.5,
  },
  prediction: {
    fontSize: 13,
    fontWeight: '700',
  },
  overText: {
    color: '#4CAF50',
  },
  underText: {
    color: '#F44336',
  },
  probability: {
    fontSize: 14,
    fontWeight: '800',
  },
  tierBadge: {
    paddingHorizontal: 6,
    paddingVertical: 2,
    borderRadius: 4,
  },
  tierText: {
    fontSize: 10,
    fontWeight: '700',
  },
  lockedContainer: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: 10,
    paddingVertical: 6,
    borderRadius: 8,
    backgroundColor: 'rgba(255, 255, 255, 0.05)',
    borderWidth: 1,
    borderColor: '#333',
    borderStyle: 'dashed',
    marginBottom: 10,
    gap: 6,
  },
  lockIcon: {
    color: '#666',
    fontSize: 14,
    fontWeight: '700',
  },
  lockedText: {
    color: '#666',
    fontSize: 12,
    flex: 1,
  },
  unlockCost: {
    color: '#FFD700',
    fontSize: 11,
    fontWeight: '700',
  },
});
