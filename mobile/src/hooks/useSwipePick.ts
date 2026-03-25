import { useCallback } from 'react';
import * as Haptics from 'expo-haptics';

/**
 * Hook for swipe-to-pick gesture handling.
 * Returns callbacks for GestureHandler's Swipeable component.
 */
export function useSwipePick(
  propId: string,
  isLocked: boolean,
  onPick: (propId: string, prediction: 'OVER' | 'UNDER') => void,
) {
  const handleSwipeRight = useCallback(() => {
    if (isLocked) return;
    Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);
    onPick(propId, 'OVER');
  }, [propId, isLocked, onPick]);

  const handleSwipeLeft = useCallback(() => {
    if (isLocked) return;
    Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);
    onPick(propId, 'UNDER');
  }, [propId, isLocked, onPick]);

  return {
    onSwipeRight: handleSwipeRight,
    onSwipeLeft: handleSwipeLeft,
  };
}
