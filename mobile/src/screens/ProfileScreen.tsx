import React, { useEffect } from 'react';
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  Pressable,
  RefreshControl,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useNavigation } from '@react-navigation/native';
import { useAuthStore } from '../store/authStore';
import { useWatchlistStore } from '../store/watchlistStore';
import { usePlayerLiveStats } from '../hooks/usePlayerLiveStats';
import { PointsBadge } from '../components/common/PointsBadge';
import { StreakBadge } from '../components/common/StreakBadge';
import { PlayerBoxCard } from '../components/watchlist/PlayerBoxCard';
import { TIER_INFO } from '../utils/constants';

export function ProfileScreen() {
  const navigation = useNavigation<any>();
  const { profile, refreshProfile, signOut, loading } = useAuthStore();
  const { items: watchlistItems, fetchWatchlist } = useWatchlistStore();
  const { playerData, refresh: refreshLiveStats } = usePlayerLiveStats(watchlistItems, 'NBA');

  useEffect(() => {
    fetchWatchlist();
  }, [fetchWatchlist]);

  const tierInfo = profile?.tier ? TIER_INFO[profile.tier] : TIER_INFO.rookie;
  const accuracy = profile && profile.total_picks > 0
    ? (profile.total_hits / profile.total_picks * 100).toFixed(1)
    : '0.0';

  const handleRefresh = async () => {
    await Promise.all([refreshProfile(), fetchWatchlist(), refreshLiveStats()]);
  };

  return (
    <SafeAreaView style={styles.container} edges={['top']}>
      <ScrollView
        showsVerticalScrollIndicator={false}
        refreshControl={
          <RefreshControl
            refreshing={loading}
            onRefresh={handleRefresh}
            tintColor="#4CAF50"
          />
        }
      >
        {/* Profile header */}
        <View style={styles.profileHeader}>
          <View style={styles.avatarContainer}>
            <Text style={styles.avatarText}>
              {profile?.display_name?.[0]?.toUpperCase() || '?'}
            </Text>
          </View>
          <Text style={styles.displayName}>{profile?.display_name || 'Player'}</Text>
          <Text style={styles.username}>@{profile?.username || 'unknown'}</Text>
          <View style={[styles.tierBadge, { backgroundColor: `${tierInfo.color}20`, borderColor: tierInfo.color }]}>
            <Text style={[styles.tierText, { color: tierInfo.color }]}>{tierInfo.label}</Text>
          </View>
        </View>

        {/* Points & streak */}
        <View style={styles.pointsRow}>
          <PointsBadge points={profile?.points || 0} />
          <StreakBadge streak={profile?.streak || 0} />
        </View>

        {/* Stats grid */}
        <View style={styles.statsCard}>
          <View style={styles.statsGrid}>
            <View style={styles.statCell}>
              <Text style={styles.statValue}>{profile?.total_picks?.toLocaleString() || 0}</Text>
              <Text style={styles.statLabel}>Total Picks</Text>
            </View>
            <View style={styles.statCell}>
              <Text style={styles.statValue}>{profile?.total_hits?.toLocaleString() || 0}</Text>
              <Text style={styles.statLabel}>Hits</Text>
            </View>
            <View style={styles.statCell}>
              <Text style={styles.statValue}>{accuracy}%</Text>
              <Text style={styles.statLabel}>Accuracy</Text>
            </View>
            <View style={styles.statCell}>
              <Text style={styles.statValue}>{profile?.best_streak || 0}</Text>
              <Text style={styles.statLabel}>Best Streak</Text>
            </View>
          </View>
        </View>

        {/* Watchlist section */}
        <View style={styles.sectionHeader}>
          <Text style={styles.sectionTitle}>My Watchlist</Text>
          <Pressable onPress={() => navigation.navigate('Watchlist')}>
            <Text style={styles.sectionLink}>
              {watchlistItems.length}/10 - Edit
            </Text>
          </Pressable>
        </View>

        {playerData.length > 0 ? (
          playerData.map((player) => (
            <PlayerBoxCard
              key={player.playerName}
              playerName={player.playerName}
              team={player.team}
              sport={player.sport}
              game={player.game}
              props={player.props}
            />
          ))
        ) : (
          <Pressable
            style={styles.emptyWatchlist}
            onPress={() => navigation.navigate('Watchlist')}
          >
            <Text style={styles.emptyText}>Add players to your watchlist</Text>
            <Text style={styles.emptySubtext}>Track live stats for up to 10 players</Text>
          </Pressable>
        )}

        {/* Settings / Sign out */}
        <View style={styles.settingsSection}>
          <Pressable style={styles.settingsButton} onPress={signOut}>
            <Text style={styles.signOutText}>Sign Out</Text>
          </Pressable>
        </View>
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#121212',
  },
  profileHeader: {
    alignItems: 'center',
    paddingVertical: 24,
  },
  avatarContainer: {
    width: 72,
    height: 72,
    borderRadius: 36,
    backgroundColor: '#1e1e2e',
    justifyContent: 'center',
    alignItems: 'center',
    marginBottom: 12,
  },
  avatarText: {
    color: '#4CAF50',
    fontSize: 28,
    fontWeight: '800',
  },
  displayName: {
    color: '#fff',
    fontSize: 22,
    fontWeight: '700',
  },
  username: {
    color: '#888',
    fontSize: 14,
    marginTop: 2,
  },
  tierBadge: {
    marginTop: 8,
    paddingHorizontal: 12,
    paddingVertical: 4,
    borderRadius: 12,
    borderWidth: 1,
  },
  tierText: {
    fontSize: 12,
    fontWeight: '700',
    textTransform: 'uppercase',
    letterSpacing: 0.5,
  },
  pointsRow: {
    flexDirection: 'row',
    justifyContent: 'center',
    gap: 12,
    marginBottom: 16,
  },
  statsCard: {
    backgroundColor: '#1e1e2e',
    borderRadius: 12,
    marginHorizontal: 16,
    padding: 16,
    marginBottom: 20,
  },
  statsGrid: {
    flexDirection: 'row',
    justifyContent: 'space-around',
  },
  statCell: {
    alignItems: 'center',
  },
  statValue: {
    color: '#fff',
    fontSize: 20,
    fontWeight: '700',
  },
  statLabel: {
    color: '#888',
    fontSize: 11,
    marginTop: 4,
    textTransform: 'uppercase',
  },
  sectionHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingHorizontal: 16,
    paddingVertical: 12,
  },
  sectionTitle: {
    color: '#fff',
    fontSize: 18,
    fontWeight: '700',
  },
  sectionLink: {
    color: '#4CAF50',
    fontSize: 13,
    fontWeight: '600',
  },
  emptyWatchlist: {
    backgroundColor: '#1e1e2e',
    borderRadius: 12,
    marginHorizontal: 16,
    padding: 24,
    alignItems: 'center',
    borderWidth: 1,
    borderColor: '#333',
    borderStyle: 'dashed',
  },
  emptyText: {
    color: '#888',
    fontSize: 15,
    fontWeight: '600',
  },
  emptySubtext: {
    color: '#666',
    fontSize: 12,
    marginTop: 4,
  },
  settingsSection: {
    paddingHorizontal: 16,
    paddingVertical: 24,
  },
  settingsButton: {
    backgroundColor: '#1e1e2e',
    borderRadius: 12,
    padding: 14,
    alignItems: 'center',
  },
  signOutText: {
    color: '#F44336',
    fontSize: 15,
    fontWeight: '600',
  },
});
