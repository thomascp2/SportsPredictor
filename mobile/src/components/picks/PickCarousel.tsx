/**
 * PickCarousel
 * ============
 * A smooth, physics-based horizontal card carousel for browsing player props.
 *
 * Features:
 * - Snap-to-card with spring physics via Reanimated
 * - Adjacent cards shrink + fade for depth perception
 * - Peek of next/previous cards (~8% of screen width on each side)
 * - Animated "add to parlay" indicator when card is active
 * - Dot navigation + counter
 */

import React, { useCallback, useRef, useState } from 'react';
import {
  View,
  Text,
  StyleSheet,
  Dimensions,
  FlatList,
  TouchableOpacity,
  NativeSyntheticEvent,
  NativeScrollEvent,
  Animated,
  ViewStyle,
} from 'react-native';
import { SmartPick } from '../../services/api';
import { StatPercentileBar } from './StatPercentileBar';
import { TierBadge } from './TierBadge';
import { EdgeIndicator } from './EdgeIndicator';

const { width: SCREEN_WIDTH } = Dimensions.get('window');

// Card sizing
const PEEK = 24;          // how much of adjacent cards peek in from each side
const GAP = 10;           // gap between cards
const CARD_WIDTH = SCREEN_WIDTH - PEEK * 2 - GAP * 2;
const ITEM_WIDTH = CARD_WIDTH + GAP;   // total slot width (card + one gap)

const PROP_LABELS: Record<string, string> = {
  points: 'PTS', rebounds: 'REB', assists: 'AST', threes: '3PM',
  pra: 'PRA', stocks: 'STK', minutes: 'MIN', blocks: 'BLK',
  steals: 'STL', pts_rebs: 'P+R', pts_asts: 'P+A', rebs_asts: 'R+A',
  shots: 'SOG', goals: 'G', saves: 'SAV',
};

const TIER_GLOW: Record<string, string> = {
  'T1-ELITE': '#FFD700',
  'T2-STRONG': '#4CAF50',
  'T3-GOOD': '#00BCD4',
  'T4-LEAN': '#FF9800',
  'T5-FADE': '#EF5350',
};

interface PickCarouselProps {
  picks: SmartPick[];
  onAddToParlay: (pick: SmartPick) => void;
  onPlayerPress: (pick: SmartPick) => void;
  isPickInParlay: (pick: SmartPick) => boolean;
}

interface CarouselCardProps {
  pick: SmartPick;
  index: number;
  activeIndex: number;
  scrollX: Animated.Value;
  onAddToParlay: (pick: SmartPick) => void;
  onPlayerPress: (pick: SmartPick) => void;
  isInParlay: boolean;
  total: number;
}

function CarouselCard({
  pick,
  index,
  scrollX,
  onAddToParlay,
  onPlayerPress,
  isInParlay,
}: CarouselCardProps) {
  const propLabel = PROP_LABELS[pick.prop_type] || pick.prop_type.toUpperCase();
  const predictionColor = pick.prediction === 'OVER' ? '#4CAF50' : '#EF5350';
  const tierGlow = TIER_GLOW[pick.tier] || '#888';

  // Animated scale + opacity based on scroll position
  const inputRange = [
    (index - 1) * ITEM_WIDTH,
    index * ITEM_WIDTH,
    (index + 1) * ITEM_WIDTH,
  ];

  const scale = scrollX.interpolate({
    inputRange,
    outputRange: [0.91, 1, 0.91],
    extrapolate: 'clamp',
  });

  const opacity = scrollX.interpolate({
    inputRange,
    outputRange: [0.55, 1, 0.55],
    extrapolate: 'clamp',
  });

  const translateY = scrollX.interpolate({
    inputRange,
    outputRange: [10, 0, 10],
    extrapolate: 'clamp',
  });

  return (
    <Animated.View
      style={[
        styles.cardWrapper,
        { width: CARD_WIDTH, opacity, transform: [{ scale }, { translateY }] },
      ]}
    >
      <TouchableOpacity
        style={[
          styles.card,
          isInParlay && styles.cardInParlay,
          { borderColor: isInParlay ? '#4CAF50' : tierGlow + '40' },
        ]}
        onPress={() => onPlayerPress(pick)}
        activeOpacity={0.92}
      >
        {/* Tier glow accent line at top */}
        <View style={[styles.tierAccent, { backgroundColor: tierGlow }]} />

        {/* ── Header ── */}
        <View style={styles.cardHeader}>
          <View style={styles.playerMeta}>
            <Text style={styles.playerName} numberOfLines={1}>{pick.player_name}</Text>
            <Text style={styles.matchupText} numberOfLines={1}>
              {pick.matchup || `${pick.team} vs ${pick.opponent}`}
            </Text>
          </View>
          <TierBadge tier={pick.tier} />
        </View>

        {/* ── Prop + Line ── */}
        <View style={styles.propSection}>
          <View style={styles.propLabelRow}>
            <Text style={styles.propLabel}>{propLabel}</Text>
            {pick.game_time ? (
              <View style={styles.timePill}>
                <Text style={styles.timePillText}>{pick.game_time}</Text>
              </View>
            ) : null}
          </View>
          <View style={styles.lineRow}>
            <Text style={[styles.lineDirection, { color: predictionColor }]}>
              {pick.prediction}
            </Text>
            <Text style={styles.lineValue}>{pick.pp_line}</Text>
          </View>
        </View>

        {/* ── Stats row: prob + edge ── */}
        <View style={styles.statsRow}>
          <View style={styles.statItem}>
            <Text style={[styles.statValue, {
              color: pick.pp_probability >= 0.7 ? '#4CAF50'
                : pick.pp_probability >= 0.6 ? '#FFD700' : '#FF9800',
            }]}>
              {(pick.pp_probability * 100).toFixed(0)}%
            </Text>
            <Text style={styles.statLabel}>PROB</Text>
          </View>

          <View style={styles.statDivider} />

          <View style={styles.statItem}>
            <EdgeIndicator edge={pick.edge} />
            <Text style={styles.statLabel}>EDGE</Text>
          </View>

          {pick.season_avg != null && (
            <>
              <View style={styles.statDivider} />
              <View style={styles.statItem}>
                <Text style={styles.statValue}>{pick.season_avg.toFixed(1)}</Text>
                <Text style={styles.statLabel}>AVG</Text>
              </View>
            </>
          )}

          {pick.ev_4leg != null && Math.abs(pick.ev_4leg) > 0 && (
            <>
              <View style={styles.statDivider} />
              <View style={styles.statItem}>
                <Text style={[styles.statValue, {
                  color: pick.ev_4leg > 0 ? '#4CAF50' : '#EF5350',
                }]}>
                  {pick.ev_4leg > 0 ? '+' : ''}{(pick.ev_4leg * 100).toFixed(0)}%
                </Text>
                <Text style={styles.statLabel}>EV@4L</Text>
              </View>
            </>
          )}
        </View>

        {/* ── League percentile bar ── */}
        {pick.percentile_score != null && (
          <View style={styles.percentileSection}>
            <StatPercentileBar
              percentile={pick.percentile_score}
              seasonAvg={pick.season_avg || undefined}
              ppLine={pick.pp_line}
              propLabel={propLabel}
              height={8}
              showScore={true}
            />
          </View>
        )}

        {/* ── Model signals row ── */}
        <View style={styles.signalRow}>
          {pick.days_rest != null && (
            <View style={[styles.signalPill, {
              backgroundColor: pick.days_rest === 0 ? '#EF535015' : '#4CAF5015',
              borderColor: pick.days_rest === 0 ? '#EF5350' : '#4CAF50',
            }]}>
              <Text style={[styles.signalText, { color: pick.days_rest === 0 ? '#EF5350' : '#4CAF50' }]}>
                {pick.days_rest === 0 ? 'B2B' : `${pick.days_rest}d rest`}
              </Text>
            </View>
          )}

          {pick.line_movement != null && Math.abs(pick.line_movement) >= 0.5 && (
            <View style={[styles.signalPill, {
              backgroundColor: pick.movement_agrees ? '#4CAF5015' : '#FF980015',
              borderColor: pick.movement_agrees ? '#4CAF50' : '#FF9800',
            }]}>
              <Text style={[styles.signalText, { color: pick.movement_agrees ? '#4CAF50' : '#FF9800' }]}>
                Line {pick.line_movement > 0 ? 'UP' : 'DOWN'} {Math.abs(pick.line_movement).toFixed(1)}
              </Text>
            </View>
          )}

          {/* Odds type pill */}
          <View style={[styles.signalPill, styles.oddsTypePill]}>
            <Text style={styles.oddsTypeText}>
              {(pick.pp_odds_type || 'STD').toUpperCase()}
            </Text>
          </View>
        </View>

        {/* ── Add to parlay CTA ── */}
        <TouchableOpacity
          style={[
            styles.ctaButton,
            isInParlay ? styles.ctaRemove : styles.ctaAdd,
          ]}
          onPress={() => onAddToParlay(pick)}
          activeOpacity={0.85}
        >
          <Text style={styles.ctaText}>
            {isInParlay ? '− Remove from Parlay' : '+ Add to Parlay'}
          </Text>
        </TouchableOpacity>
      </TouchableOpacity>
    </Animated.View>
  );
}

export function PickCarousel({
  picks,
  onAddToParlay,
  onPlayerPress,
  isPickInParlay,
}: PickCarouselProps) {
  const [activeIndex, setActiveIndex] = useState(0);
  const scrollX = useRef(new Animated.Value(0)).current;
  const flatListRef = useRef<FlatList>(null);

  const onScroll = Animated.event(
    [{ nativeEvent: { contentOffset: { x: scrollX } } }],
    { useNativeDriver: false }
  );

  const onMomentumScrollEnd = useCallback(
    (e: NativeSyntheticEvent<NativeScrollEvent>) => {
      const newIndex = Math.round(e.nativeEvent.contentOffset.x / ITEM_WIDTH);
      setActiveIndex(Math.max(0, Math.min(newIndex, picks.length - 1)));
    },
    [picks.length]
  );

  const scrollToIndex = useCallback(
    (index: number) => {
      flatListRef.current?.scrollToOffset({
        offset: index * ITEM_WIDTH,
        animated: true,
      });
      setActiveIndex(index);
    },
    []
  );

  if (picks.length === 0) {
    return (
      <View style={styles.emptyContainer}>
        <Text style={styles.emptyText}>No picks available</Text>
        <Text style={styles.emptySubtext}>Check back closer to game time</Text>
      </View>
    );
  }

  return (
    <View style={styles.root}>
      {/* Card count */}
      <View style={styles.counterRow}>
        <Text style={styles.counterText}>
          {activeIndex + 1} / {picks.length}
        </Text>
      </View>

      {/* Horizontal scroll */}
      <Animated.FlatList
        ref={flatListRef}
        data={picks}
        keyExtractor={(item, i) => `${item.player_name}-${item.prop_type}-${i}`}
        horizontal
        showsHorizontalScrollIndicator={false}
        snapToInterval={ITEM_WIDTH}
        decelerationRate="fast"
        contentContainerStyle={styles.listContent}
        onScroll={onScroll}
        scrollEventThrottle={16}
        onMomentumScrollEnd={onMomentumScrollEnd}
        renderItem={({ item, index }) => (
          <CarouselCard
            pick={item}
            index={index}
            activeIndex={activeIndex}
            scrollX={scrollX}
            onAddToParlay={onAddToParlay}
            onPlayerPress={onPlayerPress}
            isInParlay={isPickInParlay(item)}
            total={picks.length}
          />
        )}
      />

      {/* Dot indicator (max 15 dots, then just show numbers) */}
      {picks.length <= 15 ? (
        <View style={styles.dotsRow}>
          {picks.map((_, i) => (
            <TouchableOpacity key={i} onPress={() => scrollToIndex(i)}>
              <View
                style={[
                  styles.dot,
                  i === activeIndex ? styles.dotActive : styles.dotInactive,
                  // Shrink dots that are far from active index
                  Math.abs(i - activeIndex) > 2 ? styles.dotSmall : undefined,
                ]}
              />
            </TouchableOpacity>
          ))}
        </View>
      ) : (
        <View style={styles.dotsRow}>
          {/* Show a mini progress bar instead */}
          <View style={styles.progressTrack}>
            <View
              style={[
                styles.progressFill,
                { width: `${((activeIndex + 1) / picks.length) * 100}%` },
              ]}
            />
          </View>
        </View>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  root: {
    flex: 1,
  },
  counterRow: {
    alignItems: 'center',
    marginBottom: 8,
  },
  counterText: {
    color: '#555',
    fontSize: 12,
    fontWeight: '600',
    letterSpacing: 1,
  },
  listContent: {
    paddingHorizontal: PEEK + GAP / 2,
    paddingBottom: 8,
  },
  cardWrapper: {
    marginHorizontal: GAP / 2,
  },
  card: {
    backgroundColor: '#161625',
    borderRadius: 20,
    padding: 20,
    borderWidth: 1,
    overflow: 'hidden',
    // Shadow
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 8 },
    shadowOpacity: 0.4,
    shadowRadius: 16,
    elevation: 10,
  },
  cardInParlay: {
    borderColor: '#4CAF50',
    borderWidth: 1.5,
  },
  tierAccent: {
    position: 'absolute',
    top: 0,
    left: 0,
    right: 0,
    height: 3,
    opacity: 0.8,
  },
  // Header
  cardHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'flex-start',
    marginBottom: 16,
    marginTop: 6,
  },
  playerMeta: {
    flex: 1,
    paddingRight: 10,
  },
  playerName: {
    color: '#fff',
    fontSize: 20,
    fontWeight: '800',
    letterSpacing: 0.1,
  },
  matchupText: {
    color: '#555',
    fontSize: 12,
    marginTop: 3,
  },
  // Prop
  propSection: {
    marginBottom: 16,
  },
  propLabelRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    marginBottom: 4,
  },
  propLabel: {
    color: '#888',
    fontSize: 12,
    fontWeight: '700',
    letterSpacing: 1.5,
    textTransform: 'uppercase',
  },
  timePill: {
    backgroundColor: '#1976D220',
    paddingHorizontal: 8,
    paddingVertical: 2,
    borderRadius: 10,
    borderWidth: 1,
    borderColor: '#1976D240',
  },
  timePillText: {
    color: '#42A5F5',
    fontSize: 10,
    fontWeight: '600',
  },
  lineRow: {
    flexDirection: 'row',
    alignItems: 'baseline',
    gap: 8,
  },
  lineDirection: {
    fontSize: 18,
    fontWeight: '700',
  },
  lineValue: {
    color: '#fff',
    fontSize: 44,
    fontWeight: '900',
    letterSpacing: -1,
    lineHeight: 48,
  },
  // Stats
  statsRow: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: '#0d0d1a',
    borderRadius: 12,
    paddingVertical: 12,
    paddingHorizontal: 14,
    marginBottom: 14,
  },
  statItem: {
    flex: 1,
    alignItems: 'center',
  },
  statDivider: {
    width: 1,
    height: 30,
    backgroundColor: '#252535',
  },
  statValue: {
    color: '#fff',
    fontSize: 16,
    fontWeight: '700',
    marginBottom: 2,
  },
  statLabel: {
    color: '#555',
    fontSize: 9,
    fontWeight: '600',
    letterSpacing: 0.8,
  },
  // Percentile
  percentileSection: {
    marginBottom: 14,
  },
  // Signals
  signalRow: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 6,
    marginBottom: 16,
  },
  signalPill: {
    paddingHorizontal: 8,
    paddingVertical: 4,
    borderRadius: 6,
    borderWidth: 1,
  },
  signalText: {
    fontSize: 10,
    fontWeight: '700',
  },
  oddsTypePill: {
    backgroundColor: '#252535',
    borderColor: '#333',
  },
  oddsTypeText: {
    color: '#888',
    fontSize: 10,
    fontWeight: '700',
  },
  // CTA
  ctaButton: {
    borderRadius: 12,
    paddingVertical: 14,
    alignItems: 'center',
  },
  ctaAdd: {
    backgroundColor: '#4CAF50',
  },
  ctaRemove: {
    backgroundColor: '#EF535020',
    borderWidth: 1,
    borderColor: '#EF5350',
  },
  ctaText: {
    color: '#fff',
    fontSize: 15,
    fontWeight: '700',
    letterSpacing: 0.3,
  },
  // Dots
  dotsRow: {
    flexDirection: 'row',
    justifyContent: 'center',
    alignItems: 'center',
    paddingTop: 12,
    paddingBottom: 4,
    gap: 5,
  },
  dot: {
    borderRadius: 6,
  },
  dotActive: {
    width: 18,
    height: 6,
    backgroundColor: '#4CAF50',
    borderRadius: 3,
  },
  dotInactive: {
    width: 6,
    height: 6,
    backgroundColor: '#333',
  },
  dotSmall: {
    width: 4,
    height: 4,
  },
  progressTrack: {
    flex: 1,
    maxWidth: 200,
    height: 4,
    backgroundColor: '#252535',
    borderRadius: 2,
    overflow: 'hidden',
  },
  progressFill: {
    height: '100%',
    backgroundColor: '#4CAF50',
    borderRadius: 2,
  },
  // Empty
  emptyContainer: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    paddingVertical: 60,
  },
  emptyText: {
    color: '#666',
    fontSize: 18,
    fontWeight: '600',
  },
  emptySubtext: {
    color: '#444',
    fontSize: 13,
    marginTop: 8,
  },
});
