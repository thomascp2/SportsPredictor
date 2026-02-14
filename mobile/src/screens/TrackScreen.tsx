import React, { useEffect, useState, useCallback } from 'react';
import {
  View,
  Text,
  StyleSheet,
  FlatList,
  Pressable,
  RefreshControl,
  Alert,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useNavigation } from '@react-navigation/native';
import { useBetStore } from '../store/betStore';
import { BetCard } from '../components/tracking/BetCard';
import { PLSummary } from '../components/tracking/PLSummary';
import type { UserBet } from '../types/supabase';

const FILTERS: Array<{ key: 'all' | 'pending' | 'won' | 'lost'; label: string }> = [
  { key: 'all', label: 'All' },
  { key: 'pending', label: 'Open' },
  { key: 'won', label: 'Won' },
  { key: 'lost', label: 'Lost' },
];

export function TrackScreen() {
  const navigation = useNavigation<any>();
  const { bets, stats, loading, filter, setFilter, fetchBets, updateBetStatus, deleteBet } = useBetStore();

  useEffect(() => {
    fetchBets();
  }, [fetchBets]);

  const filteredBets = filter === 'all'
    ? bets
    : bets.filter(b => b.status === filter);

  const handleSettle = useCallback(async (betId: string, status: 'won' | 'lost') => {
    const bet = bets.find(b => b.id === betId);
    const payout = status === 'won' ? bet?.potential_payout : 0;
    try {
      await updateBetStatus(betId, status, payout || undefined);
    } catch (e) {
      Alert.alert('Error', (e as Error).message);
    }
  }, [bets, updateBetStatus]);

  const handleDelete = useCallback((betId: string) => {
    Alert.alert('Delete Bet', 'Are you sure?', [
      { text: 'Cancel', style: 'cancel' },
      { text: 'Delete', style: 'destructive', onPress: () => deleteBet(betId) },
    ]);
  }, [deleteBet]);

  const renderBet = useCallback(({ item }: { item: UserBet }) => (
    <BetCard
      bet={item}
      onSettle={handleSettle}
      onDelete={handleDelete}
    />
  ), [handleSettle, handleDelete]);

  return (
    <SafeAreaView style={styles.container} edges={['top']}>
      <View style={styles.header}>
        <Text style={styles.title}>Bet Tracker</Text>
        <Pressable
          style={styles.addButton}
          onPress={() => navigation.navigate('AddBet')}
        >
          <Text style={styles.addButtonText}>+ New Bet</Text>
        </Pressable>
      </View>

      {/* P/L Summary */}
      <PLSummary
        netPL={stats.netPL}
        totalStaked={stats.totalStaked}
        wonBets={stats.wonBets}
        lostBets={stats.lostBets}
        pendingBets={stats.pendingBets}
      />

      {/* Filters */}
      <View style={styles.filters}>
        {FILTERS.map(f => (
          <Pressable
            key={f.key}
            style={[styles.filterChip, filter === f.key && styles.activeFilterChip]}
            onPress={() => setFilter(f.key)}
          >
            <Text style={[styles.filterText, filter === f.key && styles.activeFilterText]}>
              {f.label}
            </Text>
          </Pressable>
        ))}
      </View>

      {/* Bet list */}
      <FlatList
        data={filteredBets}
        keyExtractor={(item) => item.id}
        renderItem={renderBet}
        contentContainerStyle={styles.listContent}
        showsVerticalScrollIndicator={false}
        refreshControl={
          <RefreshControl
            refreshing={loading}
            onRefresh={fetchBets}
            tintColor="#4CAF50"
            colors={['#4CAF50']}
          />
        }
        ListEmptyComponent={
          <View style={styles.empty}>
            <Text style={styles.emptyText}>No bets yet</Text>
            <Text style={styles.emptySubtext}>Tap "+ New Bet" to log your first bet</Text>
          </View>
        }
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
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingHorizontal: 16,
    paddingVertical: 12,
  },
  title: {
    color: '#fff',
    fontSize: 26,
    fontWeight: '800',
  },
  addButton: {
    backgroundColor: '#4CAF50',
    paddingHorizontal: 16,
    paddingVertical: 8,
    borderRadius: 20,
  },
  addButtonText: {
    color: '#fff',
    fontSize: 13,
    fontWeight: '700',
  },
  filters: {
    flexDirection: 'row',
    paddingHorizontal: 16,
    paddingVertical: 8,
    gap: 8,
  },
  filterChip: {
    paddingHorizontal: 14,
    paddingVertical: 6,
    borderRadius: 16,
    backgroundColor: '#1e1e2e',
    borderWidth: 1,
    borderColor: '#333',
  },
  activeFilterChip: {
    backgroundColor: 'rgba(76, 175, 80, 0.15)',
    borderColor: '#4CAF50',
  },
  filterText: {
    color: '#888',
    fontSize: 13,
    fontWeight: '600',
  },
  activeFilterText: {
    color: '#4CAF50',
  },
  listContent: {
    paddingBottom: 20,
  },
  empty: {
    alignItems: 'center',
    paddingTop: 60,
  },
  emptyText: {
    color: '#888',
    fontSize: 18,
    fontWeight: '600',
  },
  emptySubtext: {
    color: '#666',
    fontSize: 14,
    marginTop: 8,
  },
});
