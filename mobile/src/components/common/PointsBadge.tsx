import React, { useEffect } from 'react';
import { View, Text, StyleSheet } from 'react-native';
import Animated, {
  useSharedValue,
  useAnimatedStyle,
  withSpring,
  withSequence,
} from 'react-native-reanimated';

interface PointsBadgeProps {
  points: number;
  compact?: boolean;
}

export function PointsBadge({ points, compact = false }: PointsBadgeProps) {
  const scale = useSharedValue(1);

  useEffect(() => {
    // Bounce animation when points change
    scale.value = withSequence(
      withSpring(1.2, { damping: 8, stiffness: 200 }),
      withSpring(1, { damping: 12, stiffness: 180 })
    );
  }, [points, scale]);

  const animatedStyle = useAnimatedStyle(() => ({
    transform: [{ scale: scale.value }],
  }));

  if (compact) {
    return (
      <Animated.View style={[styles.compactContainer, animatedStyle]}>
        <Text style={styles.compactPoints}>{points.toLocaleString()}</Text>
        <Text style={styles.compactLabel}>pts</Text>
      </Animated.View>
    );
  }

  return (
    <Animated.View style={[styles.container, animatedStyle]}>
      <Text style={styles.icon}>*</Text>
      <Text style={styles.points}>{points.toLocaleString()}</Text>
    </Animated.View>
  );
}

const styles = StyleSheet.create({
  container: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: 'rgba(255, 215, 0, 0.15)',
    paddingHorizontal: 10,
    paddingVertical: 4,
    borderRadius: 16,
    gap: 4,
  },
  icon: {
    color: '#FFD700',
    fontSize: 14,
    fontWeight: '700',
  },
  points: {
    color: '#FFD700',
    fontSize: 15,
    fontWeight: '700',
  },
  compactContainer: {
    flexDirection: 'row',
    alignItems: 'baseline',
    gap: 2,
  },
  compactPoints: {
    color: '#FFD700',
    fontSize: 18,
    fontWeight: '800',
  },
  compactLabel: {
    color: '#FFD700',
    fontSize: 11,
    fontWeight: '600',
    opacity: 0.7,
  },
});
