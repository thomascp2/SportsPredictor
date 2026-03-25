import React from 'react';
import { View, Text, StyleSheet } from 'react-native';
import { EV_COLORS } from '../../utils/constants';

interface EdgeIndicatorProps {
  edge: number;
  showLabel?: boolean;
}

export function EdgeIndicator({ edge, showLabel = true }: EdgeIndicatorProps) {
  const color = edge >= 10 ? EV_COLORS.positive : edge >= 0 ? EV_COLORS.neutral : EV_COLORS.negative;

  return (
    <View style={styles.container}>
      {showLabel && <Text style={styles.label}>Edge</Text>}
      <Text style={[styles.value, { color }]}>
        {edge >= 0 ? '+' : ''}{edge.toFixed(1)}%
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    alignItems: 'center',
  },
  label: {
    color: '#888',
    fontSize: 10,
    marginBottom: 2,
  },
  value: {
    fontSize: 16,
    fontWeight: 'bold',
  },
});
