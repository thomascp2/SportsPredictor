import React from 'react';
import { View, Text, StyleSheet } from 'react-native';
import { TIER_COLORS } from '../../utils/constants';

interface TierBadgeProps {
  tier: string;
  size?: 'small' | 'medium' | 'large';
}

export function TierBadge({ tier, size = 'medium' }: TierBadgeProps) {
  const color = TIER_COLORS[tier] || '#888';

  const sizeStyles = {
    small: { paddingHorizontal: 6, paddingVertical: 2, fontSize: 10 },
    medium: { paddingHorizontal: 8, paddingVertical: 4, fontSize: 12 },
    large: { paddingHorizontal: 12, paddingVertical: 6, fontSize: 14 },
  };

  const { paddingHorizontal, paddingVertical, fontSize } = sizeStyles[size];

  // Extract short tier name (T1, T2, etc.)
  const shortTier = tier.split('-')[0];

  return (
    <View
      style={[
        styles.badge,
        { backgroundColor: color + '20', borderColor: color, paddingHorizontal, paddingVertical },
      ]}
    >
      <Text style={[styles.text, { color, fontSize }]}>{shortTier}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  badge: {
    borderRadius: 4,
    borderWidth: 1,
    alignSelf: 'flex-start',
  },
  text: {
    fontWeight: 'bold',
  },
});
