import React, { useState, useCallback, useMemo } from 'react';
import {
  View,
  Text,
  StyleSheet,
  FlatList,
  RefreshControl,
  ActivityIndicator,
  TouchableOpacity,
  ScrollView,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useNavigation } from '@react-navigation/native';
import { useSmartPicks } from '../hooks/useSmartPicks';
import { useParlayStore } from '../store/parlayStore';
import { PickCard } from '../components/picks/PickCard';
import { PlayerCardModal } from '../components/picks/PlayerCardModal';
import { SportToggle } from '../components/common/SportToggle';
import { SmartPick, SortOption } from '../services/api';

const SORT_OPTIONS: { label: string; value: SortOption }[] = [
  { label: 'Edge', value: 'edge' },
  { label: 'Prob', value: 'probability' },
  { label: 'Time', value: 'game_time' },
  { label: 'Team', value: 'team' },
  { label: 'Tier', value: 'tier' },
];

const TIER_OPTIONS = ['ALL', 'T1-ELITE', 'T2-STRONG', 'T3-GOOD', 'T4-LEAN'];
const PREDICTION_OPTIONS = ['ALL', 'OVER', 'UNDER'];

export function SmartPicksScreen() {
  const navigation = useNavigation<any>();
  const [sport, setSport] = useState<'NBA' | 'NHL'>('NBA');
  const [sortBy, setSortBy] = useState<SortOption>('edge');
  const [tierFilter, setTierFilter] = useState('ALL');
  const [predictionFilter, setPredictionFilter] = useState('ALL');
  const [showFilters, setShowFilters] = useState(false);
  const [selectedPlayer, setSelectedPlayer] = useState<SmartPick | null>(null);

  const { picks, summary, loading, error, refetch } = useSmartPicks(
    sport.toLowerCase(),
    { sortBy }
  );

  const parlayPicks = useParlayStore((state) => state.picks);
  const addPick = useParlayStore((state) => state.addPick);
  const removePick = useParlayStore((state) => state.removePick);

  // Apply local filters
  const filteredPicks = useMemo(() => {
    let result = [...picks];

    if (tierFilter !== 'ALL') {
      result = result.filter((p) => p.tier === tierFilter);
    }

    if (predictionFilter !== 'ALL') {
      result = result.filter((p) => p.prediction === predictionFilter);
    }

    return result;
  }, [picks, tierFilter, predictionFilter]);

  // Group by game
  const gameGroups = useMemo(() => {
    const groups: Record<string, SmartPick[]> = {};
    filteredPicks.forEach((pick) => {
      const key = pick.matchup || `${pick.team} vs ${pick.opponent}`;
      if (!groups[key]) {
        groups[key] = [];
      }
      groups[key].push(pick);
    });
    return Object.entries(groups).map(([matchup, picks]) => ({
      matchup,
      game_time: picks[0]?.game_time || '',
      picks,
    }));
  }, [filteredPicks]);

  const isPickInParlay = useCallback(
    (pick: SmartPick) => {
      const pickId = `${pick.player_name}-${pick.prop_type}-${pick.pp_line}`
        .replace(/\s+/g, '-')
        .toLowerCase();
      return parlayPicks.some((p) => p.id === pickId);
    },
    [parlayPicks]
  );

  const handleAddToParlay = useCallback(
    (pick: SmartPick) => {
      if (isPickInParlay(pick)) {
        const pickId = `${pick.player_name}-${pick.prop_type}-${pick.pp_line}`
          .replace(/\s+/g, '-')
          .toLowerCase();
        removePick(pickId);
      } else {
        addPick(pick);
      }
    },
    [isPickInParlay, addPick, removePick]
  );

  const handlePlayerPress = useCallback((pick: SmartPick) => {
    setSelectedPlayer(pick);
  }, []);

  const goToParlay = () => {
    navigation.navigate('Parlay');
  };

  return (
    <SafeAreaView style={styles.container} edges={['top']}>
      <View style={styles.header}>
        <Text style={styles.title}>Smart Picks</Text>
        {summary && (
          <View style={styles.summaryRow}>
            <Text style={styles.summaryText}>
              {filteredPicks.length} picks | {gameGroups.length} games | Avg:{' '}
              {(summary.avg_probability * 100).toFixed(0)}% prob
            </Text>
          </View>
        )}
      </View>

      <SportToggle selected={sport} onSelect={setSport} />

      {/* Sort Bar */}
      <View style={styles.sortBar}>
        <Text style={styles.sortLabel}>Sort:</Text>
        <ScrollView horizontal showsHorizontalScrollIndicator={false}>
          {SORT_OPTIONS.map((option) => (
            <TouchableOpacity
              key={option.value}
              style={[
                styles.sortButton,
                sortBy === option.value && styles.sortButtonActive,
              ]}
              onPress={() => setSortBy(option.value)}
            >
              <Text
                style={[
                  styles.sortButtonText,
                  sortBy === option.value && styles.sortButtonTextActive,
                ]}
              >
                {option.label}
              </Text>
            </TouchableOpacity>
          ))}
        </ScrollView>
        <TouchableOpacity
          style={styles.filterToggle}
          onPress={() => setShowFilters(!showFilters)}
        >
          <Text style={styles.filterToggleText}>
            {showFilters ? 'Hide' : 'Filters'}
          </Text>
        </TouchableOpacity>
      </View>

      {/* Filter Bar */}
      {showFilters && (
        <View style={styles.filterBar}>
          <View style={styles.filterRow}>
            <Text style={styles.filterLabel}>Tier:</Text>
            <ScrollView horizontal showsHorizontalScrollIndicator={false}>
              {TIER_OPTIONS.map((tier) => (
                <TouchableOpacity
                  key={tier}
                  style={[
                    styles.filterChip,
                    tierFilter === tier && styles.filterChipActive,
                  ]}
                  onPress={() => setTierFilter(tier)}
                >
                  <Text
                    style={[
                      styles.filterChipText,
                      tierFilter === tier && styles.filterChipTextActive,
                    ]}
                  >
                    {tier}
                  </Text>
                </TouchableOpacity>
              ))}
            </ScrollView>
          </View>
          <View style={styles.filterRow}>
            <Text style={styles.filterLabel}>Pick:</Text>
            <ScrollView horizontal showsHorizontalScrollIndicator={false}>
              {PREDICTION_OPTIONS.map((pred) => (
                <TouchableOpacity
                  key={pred}
                  style={[
                    styles.filterChip,
                    predictionFilter === pred && styles.filterChipActive,
                    pred === 'OVER' && predictionFilter === pred && styles.overChipActive,
                    pred === 'UNDER' && predictionFilter === pred && styles.underChipActive,
                  ]}
                  onPress={() => setPredictionFilter(pred)}
                >
                  <Text
                    style={[
                      styles.filterChipText,
                      predictionFilter === pred && styles.filterChipTextActive,
                    ]}
                  >
                    {pred}
                  </Text>
                </TouchableOpacity>
              ))}
            </ScrollView>
          </View>
        </View>
      )}

      {loading && picks.length === 0 ? (
        <View style={styles.loadingContainer}>
          <ActivityIndicator size="large" color="#4CAF50" />
          <Text style={styles.loadingText}>Loading picks...</Text>
        </View>
      ) : error ? (
        <View style={styles.errorContainer}>
          <Text style={styles.errorText}>{error}</Text>
          <Text style={styles.errorSubtext}>Pull to refresh</Text>
        </View>
      ) : filteredPicks.length === 0 ? (
        <View style={styles.emptyContainer}>
          <Text style={styles.emptyText}>No picks available</Text>
          <Text style={styles.emptySubtext}>
            {picks.length > 0
              ? 'Try adjusting your filters'
              : 'Check back closer to game time'}
          </Text>
        </View>
      ) : (
        <FlatList
          data={filteredPicks}
          keyExtractor={(item, index) =>
            `${item.player_name}-${item.prop_type}-${index}`
          }
          renderItem={({ item }) => (
            <PickCard
              pick={item}
              onAddToParlay={handleAddToParlay}
              onPlayerPress={handlePlayerPress}
              isInParlay={isPickInParlay(item)}
            />
          )}
          contentContainerStyle={styles.listContent}
          showsVerticalScrollIndicator={false}
          refreshControl={
            <RefreshControl
              refreshing={loading}
              onRefresh={refetch}
              tintColor="#4CAF50"
              colors={['#4CAF50']}
            />
          }
        />
      )}

      {/* Floating parlay button */}
      {parlayPicks.length > 0 && (
        <TouchableOpacity style={styles.parlayButton} onPress={goToParlay}>
          <Text style={styles.parlayButtonText}>
            View Parlay ({parlayPicks.length})
          </Text>
        </TouchableOpacity>
      )}

      {/* Player Card Modal */}
      <PlayerCardModal
        visible={selectedPlayer !== null}
        playerName={selectedPlayer?.player_name || ''}
        sport={sport.toLowerCase()}
        onClose={() => setSelectedPlayer(null)}
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
    paddingVertical: 12,
  },
  title: {
    color: '#fff',
    fontSize: 28,
    fontWeight: 'bold',
  },
  summaryRow: {
    marginTop: 4,
  },
  summaryText: {
    color: '#888',
    fontSize: 12,
  },
  sortBar: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: 16,
    paddingVertical: 8,
    borderBottomWidth: 1,
    borderBottomColor: '#333',
  },
  sortLabel: {
    color: '#888',
    fontSize: 12,
    marginRight: 8,
  },
  sortButton: {
    paddingHorizontal: 12,
    paddingVertical: 6,
    borderRadius: 16,
    backgroundColor: '#333',
    marginRight: 8,
  },
  sortButtonActive: {
    backgroundColor: '#4CAF50',
  },
  sortButtonText: {
    color: '#888',
    fontSize: 12,
  },
  sortButtonTextActive: {
    color: '#fff',
    fontWeight: 'bold',
  },
  filterToggle: {
    paddingHorizontal: 12,
    paddingVertical: 6,
    borderRadius: 16,
    backgroundColor: '#1976D2',
    marginLeft: 8,
  },
  filterToggleText: {
    color: '#fff',
    fontSize: 12,
    fontWeight: 'bold',
  },
  filterBar: {
    paddingHorizontal: 16,
    paddingVertical: 8,
    borderBottomWidth: 1,
    borderBottomColor: '#333',
    backgroundColor: '#1a1a1a',
  },
  filterRow: {
    flexDirection: 'row',
    alignItems: 'center',
    marginBottom: 8,
  },
  filterLabel: {
    color: '#888',
    fontSize: 12,
    marginRight: 8,
    width: 40,
  },
  filterChip: {
    paddingHorizontal: 10,
    paddingVertical: 4,
    borderRadius: 12,
    backgroundColor: '#333',
    marginRight: 6,
  },
  filterChipActive: {
    backgroundColor: '#4CAF50',
  },
  overChipActive: {
    backgroundColor: '#4CAF50',
  },
  underChipActive: {
    backgroundColor: '#F44336',
  },
  filterChipText: {
    color: '#888',
    fontSize: 11,
  },
  filterChipTextActive: {
    color: '#fff',
    fontWeight: 'bold',
  },
  listContent: {
    paddingBottom: 80,
  },
  loadingContainer: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
  },
  loadingText: {
    color: '#888',
    fontSize: 14,
    marginTop: 12,
  },
  errorContainer: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    paddingHorizontal: 32,
  },
  errorText: {
    color: '#F44336',
    fontSize: 16,
    textAlign: 'center',
  },
  errorSubtext: {
    color: '#888',
    fontSize: 14,
    marginTop: 8,
  },
  emptyContainer: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
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
  parlayButton: {
    position: 'absolute',
    bottom: 20,
    left: 20,
    right: 20,
    backgroundColor: '#4CAF50',
    paddingVertical: 16,
    borderRadius: 12,
    alignItems: 'center',
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 4 },
    shadowOpacity: 0.3,
    shadowRadius: 8,
    elevation: 8,
  },
  parlayButtonText: {
    color: '#fff',
    fontSize: 16,
    fontWeight: 'bold',
  },
});
