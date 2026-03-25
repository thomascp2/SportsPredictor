import React, { useCallback, useRef } from 'react';
import { Pressable, Text, StyleSheet, ViewStyle, Animated } from 'react-native';
import * as Haptics from 'expo-haptics';

interface PickButtonProps {
  type: 'OVER' | 'UNDER';
  selected: boolean;
  disabled: boolean;
  result?: 'HIT' | 'MISS' | null;
  onPress: () => void;
  style?: ViewStyle;
}

const COLORS = {
  OVER: {
    active: '#4CAF50',
    text: '#4CAF50',
    bg: 'rgba(76, 175, 80, 0.15)',
    selectedBg: '#4CAF50',
  },
  UNDER: {
    active: '#F44336',
    text: '#F44336',
    bg: 'rgba(244, 67, 54, 0.15)',
    selectedBg: '#F44336',
  },
  neutral: {
    bg: '#2a2a3e',
    text: '#888',
    border: '#333',
  },
  hit: '#4CAF50',
  miss: '#F44336',
};

export function PickButton({ type, selected, disabled, result, onPress, style }: PickButtonProps) {
  const scale = useRef(new Animated.Value(1)).current;

  const handlePressIn = useCallback(() => {
    Animated.spring(scale, { toValue: 0.92, damping: 12, stiffness: 180, useNativeDriver: true }).start();
  }, [scale]);

  const handlePressOut = useCallback(() => {
    Animated.spring(scale, { toValue: 1, damping: 12, stiffness: 180, useNativeDriver: true }).start();
  }, [scale]);

  const handlePress = useCallback(() => {
    if (disabled) return;
    Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);
    Animated.sequence([
      Animated.spring(scale, { toValue: 1.05, damping: 8, stiffness: 200, useNativeDriver: true }),
      Animated.spring(scale, { toValue: 1, damping: 12, stiffness: 180, useNativeDriver: true }),
    ]).start();
    onPress();
  }, [disabled, onPress, scale]);

  const colors = COLORS[type];
  const bgColor = selected ? colors.selectedBg : COLORS.neutral.bg;
  const borderColor = selected ? colors.active : COLORS.neutral.border;

  const resultOverlay = result === 'HIT' ? styles.hitGlow : result === 'MISS' ? styles.missGlow : null;

  return (
    <Animated.View style={[{ transform: [{ scale }] }, style]}>
      <Pressable
        onPressIn={handlePressIn}
        onPressOut={handlePressOut}
        onPress={handlePress}
        disabled={disabled}
        style={[
          styles.button,
          { backgroundColor: bgColor, borderColor },
          disabled && styles.disabled,
          resultOverlay,
        ]}
      >
        <Text style={[
          styles.label,
          selected && styles.selectedLabel,
          disabled && styles.disabledLabel,
        ]}>
          {type}
        </Text>
        {result && (
          <Text style={[styles.resultIcon, result === 'HIT' ? styles.hitIcon : styles.missIcon]}>
            {result === 'HIT' ? 'V' : 'X'}
          </Text>
        )}
      </Pressable>
    </Animated.View>
  );
}

const styles = StyleSheet.create({
  button: {
    flex: 1,
    height: 48,
    borderRadius: 12,
    borderWidth: 1.5,
    justifyContent: 'center',
    alignItems: 'center',
    flexDirection: 'row',
    gap: 6,
  },
  label: {
    fontSize: 16,
    fontWeight: '700',
    color: '#ccc',
    letterSpacing: 1,
  },
  selectedLabel: {
    color: '#fff',
  },
  disabled: {
    opacity: 0.5,
  },
  disabledLabel: {
    color: '#666',
  },
  resultIcon: {
    fontSize: 14,
    fontWeight: '900',
  },
  hitIcon: {
    color: '#4CAF50',
  },
  missIcon: {
    color: '#F44336',
  },
  hitGlow: {
    shadowColor: '#4CAF50',
    shadowOffset: { width: 0, height: 0 },
    shadowOpacity: 0.4,
    shadowRadius: 8,
    elevation: 4,
  },
  missGlow: {
    shadowColor: '#F44336',
    shadowOffset: { width: 0, height: 0 },
    shadowOpacity: 0.3,
    shadowRadius: 6,
    elevation: 3,
  },
});
