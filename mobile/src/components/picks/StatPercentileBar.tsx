import React, { useEffect, useRef } from 'react';
import { View, Text, StyleSheet, Animated } from 'react-native';

interface StatPercentileBarProps {
  /** Percentile rank 0-100 among tracked players for this prop type */
  percentile: number;
  /** Season average stat value to display */
  seasonAvg?: number;
  /** PP line for context */
  ppLine?: number;
  /** Prop label e.g. "PTS" */
  propLabel?: string;
  height?: number;
  showScore?: boolean;
}

function getBarColor(pct: number): string {
  if (pct >= 90) return '#00E676'; // Elite - bright green
  if (pct >= 75) return '#4CAF50'; // Great - green
  if (pct >= 55) return '#FFD700'; // Above avg - gold
  if (pct >= 35) return '#FF9800'; // Below avg - orange
  return '#F44336';                 // Low - red
}

function getBarLabel(pct: number): string {
  if (pct >= 90) return 'ELITE';
  if (pct >= 75) return 'GREAT';
  if (pct >= 55) return 'ABOVE AVG';
  if (pct >= 35) return 'AVG';
  return 'BELOW';
}

export function StatPercentileBar({
  percentile,
  seasonAvg,
  ppLine,
  propLabel,
  height = 6,
  showScore = true,
}: StatPercentileBarProps) {
  const animatedWidth = useRef(new Animated.Value(0)).current;

  useEffect(() => {
    animatedWidth.setValue(0);
    Animated.timing(animatedWidth, {
      toValue: percentile,
      duration: 700,
      delay: 100,
      useNativeDriver: false,
    }).start();
  }, [percentile]);

  const color = getBarColor(percentile);
  const score = Math.round(percentile);

  return (
    <View style={styles.wrapper}>
      {/* Avg vs Line label */}
      {seasonAvg != null && ppLine != null && (
        <View style={styles.contextRow}>
          <Text style={styles.contextLabel}>
            {propLabel ? `${propLabel} avg ` : 'Avg '}
            <Text style={styles.contextValue}>{seasonAvg.toFixed(1)}</Text>
            <Text style={styles.contextMid}> vs line </Text>
            <Text style={[
              styles.contextValue,
              { color: seasonAvg > ppLine ? '#4CAF50' : '#F44336' },
            ]}>
              {ppLine}
            </Text>
          </Text>
          <Text style={[styles.labelBadge, { color, borderColor: color + '50', backgroundColor: color + '18' }]}>
            {getBarLabel(percentile)}
          </Text>
        </View>
      )}

      {/* Bar + score */}
      <View style={styles.barRow}>
        <View style={[styles.track, { height }]}>
          {/* Subtle tick marks at 25/50/75 */}
          <View style={[styles.tick, { left: '25%' }]} />
          <View style={[styles.tick, { left: '50%' }]} />
          <View style={[styles.tick, { left: '75%' }]} />
          <Animated.View
            style={[
              styles.fill,
              {
                height,
                backgroundColor: color,
                width: animatedWidth.interpolate({
                  inputRange: [0, 100],
                  outputRange: ['0%', '100%'],
                }),
                // Glow effect via shadow
                shadowColor: color,
                shadowOffset: { width: 0, height: 0 },
                shadowOpacity: 0.6,
                shadowRadius: 4,
                elevation: 2,
              },
            ]}
          />
        </View>
        {showScore && (
          <Text style={[styles.score, { color }]}>
            {score}
            <Text style={styles.outOf}>/100</Text>
          </Text>
        )}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  wrapper: {
    gap: 4,
  },
  contextRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 2,
  },
  contextLabel: {
    color: '#888',
    fontSize: 11,
  },
  contextValue: {
    color: '#ccc',
    fontWeight: '600',
  },
  contextMid: {
    color: '#666',
  },
  labelBadge: {
    fontSize: 9,
    fontWeight: 'bold',
    paddingHorizontal: 5,
    paddingVertical: 2,
    borderRadius: 4,
    borderWidth: 1,
    overflow: 'hidden',
  },
  barRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
  },
  track: {
    flex: 1,
    backgroundColor: '#1a1a2a',
    borderRadius: 4,
    overflow: 'visible',
    position: 'relative',
  },
  fill: {
    borderRadius: 4,
    position: 'absolute',
    left: 0,
    top: 0,
  },
  tick: {
    position: 'absolute',
    top: 0,
    width: 1,
    height: '100%',
    backgroundColor: '#333',
    zIndex: 1,
  },
  score: {
    fontSize: 13,
    fontWeight: 'bold',
    minWidth: 48,
    textAlign: 'right',
  },
  outOf: {
    fontSize: 10,
    fontWeight: 'normal',
    color: '#555',
  },
});
