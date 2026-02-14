import React from 'react';
import { View, Text, StyleSheet } from 'react-native';

interface StreakBadgeProps {
  streak: number;
  compact?: boolean;
}

export function StreakBadge({ streak, compact = false }: StreakBadgeProps) {
  if (streak <= 0) return null;

  const getColor = () => {
    if (streak >= 10) return '#FF6B35';
    if (streak >= 5) return '#FFD700';
    if (streak >= 3) return '#4CAF50';
    return '#888';
  };

  if (compact) {
    return (
      <View style={[styles.compactContainer, { borderColor: getColor() }]}>
        <Text style={[styles.compactStreak, { color: getColor() }]}>{streak}</Text>
      </View>
    );
  }

  return (
    <View style={[styles.container, { backgroundColor: `${getColor()}20` }]}>
      <Text style={styles.fireIcon}>^</Text>
      <Text style={[styles.streak, { color: getColor() }]}>{streak}</Text>
      <Text style={styles.label}>streak</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: 10,
    paddingVertical: 4,
    borderRadius: 16,
    gap: 3,
  },
  fireIcon: {
    color: '#FF6B35',
    fontSize: 13,
    fontWeight: '700',
  },
  streak: {
    fontSize: 15,
    fontWeight: '800',
  },
  label: {
    color: '#888',
    fontSize: 11,
  },
  compactContainer: {
    width: 28,
    height: 28,
    borderRadius: 14,
    borderWidth: 2,
    justifyContent: 'center',
    alignItems: 'center',
  },
  compactStreak: {
    fontSize: 13,
    fontWeight: '800',
  },
});
