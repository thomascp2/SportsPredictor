import React, { useState, useCallback } from 'react';
import {
  View,
  Text,
  StyleSheet,
  FlatList,
  RefreshControl,
  ActivityIndicator,
  Alert,
  Pressable,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useFreePicks } from '../hooks/useFreePicks';
import { useWatchlistStore } from '../store/watchlistStore';
import { PropCard } from '../components/picks/PropCard';
import { PlayerCardModal } from '../components/picks/PlayerCardModal';
import { PointsBadge } from '../components/common/PointsBadge';
import { StreakBadge } from '../components/common/StreakBadge';
import { WatchlistStrip } from '../components/watchlist/WatchlistStrip';
import { SportToggle } from '../components/common/SportToggle';
import type { DailyProp } from '../types/supabase';

export function PlayScreen() {
  const {
    props,
    userPicks,
    sport,
    loading,
    error,
    todayStats,
    isAuthenticated,
    profile,
    setSport,
    makePick,
    refresh,
  } = useFreePicks();

  const { items: watchlistItems } = useWatchlistStore();
  const [watchlistFilter, setWatchlistFilter] = useState<string | null>(null);
  const [selectedProp, setSelectedProp] = useState<DailyProp | null>(null);

  const filteredProps = watchlistFilter
    ? props.filter(p => p.player_name === watchlistFilter)
    : props;

  const handlePick = useCallback(async (propId: string, prediction: 'OVER' | 'UNDER') => {
    if (!isAuthenticated) {
      Alert.alert('Sign In Required', 'Please sign in to make picks.');
      return;
    }
    try {
      await makePick(propId, prediction);
    } catch (e) {
      Alert.alert('Error', (e as Error).message);
    }
  }, [isAuthenticated, makePick]);

  const renderProp = useCallback(({ item }: { item: DailyProp }) => (
    <Pressable onPress={() => setSelectedProp(item)}>
      <PropCard
        prop={item}
        userPick={userPicks[item.id]}
        onPick={handlePick}
        showAI={profile?.premium || __DEV__}
      />
    </Pressable>
  ), [userPicks, handlePick, profile?.premium]);

  return (
    <SafeAreaView style={styles.container} edges={['top']}>
      {/* Header */}
      <View style={styles.header}>
        <View style={styles.headerTop}>
          <Text style={styles.title}>FreePicks</Text>
          <View style={styles.badges}>
            {profile && <StreakBadge streak={profile.streak} />}
            {profile && <PointsBadge points={profile.points} />}
          </View>
        </View>
        {todayStats.total > 0 && (
          <Text style={styles.statsText}>
            {todayStats.hits} hits / {todayStats.total} picks today
            {todayStats.pending > 0 ? ` (${todayStats.pending} pending)` : ''}
          </Text>
        )}
      </View>

      <SportToggle selected={sport} onSelect={(s) => setSport(s as 'NBA' | 'NHL')} />

      {/* Watchlist strip */}
      <WatchlistStrip
        items={watchlistItems.filter(w => w.sport.toUpperCase() === sport)}
        selectedPlayer={watchlistFilter}
        onSelectPlayer={setWatchlistFilter}
      />

      {/* Props list */}
      {loading && props.length === 0 ? (
        <View style={styles.center}>
          <ActivityIndicator size="large" color="#4CAF50" />
          <Text style={styles.loadingText}>Loading props...</Text>
        </View>
      ) : error ? (
        <View style={styles.center}>
          <Text style={styles.errorText}>{error}</Text>
          <Text style={styles.subtleText}>Pull to refresh</Text>
        </View>
      ) : filteredProps.length === 0 ? (
        <View style={styles.center}>
          <Text style={styles.emptyTitle}>No props available</Text>
          <Text style={styles.subtleText}>
            {watchlistFilter
              ? 'No props for this player today'
              : `Check back later for ${sport} props`
            }
          </Text>
        </View>
      ) : (
        <FlatList
          data={filteredProps}
          keyExtractor={(item) => item.id}
          renderItem={renderProp}
          contentContainerStyle={styles.listContent}
          showsVerticalScrollIndicator={false}
          refreshControl={
            <RefreshControl
              refreshing={loading}
              onRefresh={refresh}
              tintColor="#4CAF50"
              colors={['#4CAF50']}
            />
          }
        />
      )}

      <PlayerCardModal
        visible={!!selectedProp}
        playerName={selectedProp?.player_name ?? ''}
        sport={sport}
        propType={selectedProp?.prop_type}
        ppLine={selectedProp?.line}
        onClose={() => setSelectedProp(null)}
      />
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#121212',
  },
  header: {
    paddingHorizontal: 16,
    paddingVertical: 10,
  },
  headerTop: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  title: {
    color: '#4CAF50',
    fontSize: 26,
    fontWeight: '900',
    letterSpacing: -0.5,
  },
  badges: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
  },
  statsText: {
    color: '#888',
    fontSize: 12,
    marginTop: 4,
  },
  listContent: {
    paddingBottom: 20,
  },
  center: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    paddingHorizontal: 32,
  },
  loadingText: {
    color: '#888',
    fontSize: 14,
    marginTop: 12,
  },
  errorText: {
    color: '#F44336',
    fontSize: 16,
    textAlign: 'center',
  },
  emptyTitle: {
    color: '#888',
    fontSize: 18,
    fontWeight: '600',
  },
  subtleText: {
    color: '#666',
    fontSize: 14,
    marginTop: 8,
    textAlign: 'center',
  },
});
