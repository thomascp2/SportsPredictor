import React, { useState, useCallback, useMemo, useEffect } from 'react';
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
import { useNavigation, useRoute } from '@react-navigation/native';
import { useSmartPicks } from '../hooks/useSmartPicks';
import { useParlayStore } from '../store/parlayStore';
import { PickCard } from '../components/picks/PickCard';
import { PickCarousel } from '../components/picks/PickCarousel';
import { PlayerCardModal } from '../components/picks/PlayerCardModal';
import { SportToggle } from '../components/common/SportToggle';
import { SmartPick, SortOption } from '../services/api';
import { isStarPlayer, PROP_TYPES } from '../utils/constants';

interface GameFilter {
  homeTeam: string;
  awayTeam: string;
  sport: string;
}

const SORT_OPTIONS: { label: string; value: SortOption }[] = [
  { label: 'Edge', value: 'edge' },
  { label: 'Prob', value: 'probability' },
  { label: 'A-Z', value: 'player' },
  { label: 'Time', value: 'game_time' },
  { label: 'Team', value: 'team' },
  { label: 'Tier', value: 'tier' },
];

const TIER_OPTIONS = ['ALL', 'T1-ELITE', 'T2-STRONG', 'T3-GOOD', 'T4-LEAN'];
const PREDICTION_OPTIONS = ['ALL', 'OVER', 'UNDER'];
const GAME_STATUS_OPTIONS = ['UPCOMING', 'ALL GAMES'];
const PLAYER_FILTER_OPTIONS = ['ALL', 'STARS'];

export function SmartPicksScreen() {
  const navigation = useNavigation<any>();
  const route = useRoute<any>();
  const [sport, setSport] = useState<'NBA' | 'NHL'>('NBA');
  const [sortBy, setSortBy] = useState<SortOption>('edge');
  const [tierFilter, setTierFilter] = useState('ALL');
  const [predictionFilter, setPredictionFilter] = useState('ALL');
  const [propTypeFilter, setPropTypeFilter] = useState('ALL');
  const [playerFilter, setPlayerFilter] = useState('ALL');
  const [showFilters, setShowFilters] = useState(false);
  const [hideStarted, setHideStarted] = useState(true);
  const [selectedPlayer, setSelectedPlayer] = useState<SmartPick | null>(null);
  const [gameFilter, setGameFilter] = useState<GameFilter | null>(null);
  const [viewMode, setViewMode] = useState<'list' | 'carousel'>('list');
  const [oddsTypeFilter, setOddsTypeFilter] = useState('ALL');
  const [minEdgeFilter, setMinEdgeFilter] = useState(0);

  // Handle incoming game filter from navigation
  useEffect(() => {
    if (route.params?.gameFilter) {
      const filter = route.params.gameFilter as GameFilter;
      setGameFilter(filter);
      setSport(filter.sport as 'NBA' | 'NHL');
      // Clear the param to prevent re-setting on re-render
      navigation.setParams({ gameFilter: undefined });
    }
  }, [route.params?.gameFilter, navigation]);

  const { picks, summary, loading, error, minutesSinceRefresh, refetch } = useSmartPicks(
    sport.toLowerCase(),
    { sortBy, hideStarted }
  );

  const parlayPicks = useParlayStore((state) => state.picks);
  const addPick = useParlayStore((state) => state.addPick);
  const removePick = useParlayStore((state) => state.removePick);
  const clearPicks = useParlayStore((state) => state.clearPicks);

  // Get available prop types from current picks
  const availablePropTypes = useMemo(() => {
    const types = new Set<string>();
    picks.forEach((p) => types.add(p.prop_type));
    return ['ALL', ...Array.from(types).sort()];
  }, [picks]);

  // Helper to check if a pick matches the game filter
  const pickMatchesGame = useCallback((pick: SmartPick, filter: GameFilter): boolean => {
    const pickTeam = pick.team?.toLowerCase() || '';
    const pickOpponent = pick.opponent?.toLowerCase() || '';
    const pickMatchup = pick.matchup?.toLowerCase() || '';
    const homeTeam = filter.homeTeam.toLowerCase();
    const awayTeam = filter.awayTeam.toLowerCase();

    // Check if pick's team or opponent contains the home/away team names
    return (
      pickTeam.includes(homeTeam) ||
      pickTeam.includes(awayTeam) ||
      pickOpponent.includes(homeTeam) ||
      pickOpponent.includes(awayTeam) ||
      pickMatchup.includes(homeTeam) ||
      pickMatchup.includes(awayTeam)
    );
  }, []);

  // Apply local filters
  const filteredPicks = useMemo(() => {
    let result = [...picks];

    // Apply game filter first if set
    if (gameFilter) {
      result = result.filter((p) => pickMatchesGame(p, gameFilter));
    }

    if (tierFilter !== 'ALL') {
      result = result.filter((p) => p.tier === tierFilter);
    }

    if (predictionFilter !== 'ALL') {
      result = result.filter((p) => p.prediction === predictionFilter);
    }

    if (propTypeFilter !== 'ALL') {
      result = result.filter((p) => p.prop_type === propTypeFilter);
    }

    if (playerFilter === 'STARS') {
      result = result.filter((p) => isStarPlayer(p.player_name, sport));
    }

    if (oddsTypeFilter !== 'ALL') {
      result = result.filter((p) => (p.pp_odds_type || 'standard').toLowerCase() === oddsTypeFilter.toLowerCase());
    }

    if (minEdgeFilter > 0) {
      result = result.filter((p) => p.edge >= minEdgeFilter);
    }

    return result;
  }, [picks, tierFilter, predictionFilter, propTypeFilter, playerFilter, sport, gameFilter, pickMatchesGame, oddsTypeFilter, minEdgeFilter]);

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

  // Get all picks for the selected player (for the modal)
  const selectedPlayerTodayPicks = useMemo(() => {
    if (!selectedPlayer) return [];
    return picks.filter(
      (p) => p.player_name === selectedPlayer.player_name
    );
  }, [picks, selectedPlayer]);

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
        <View style={styles.titleRow}>
          <Text style={styles.title}>Smart Picks</Text>
          {minutesSinceRefresh !== null && (
            <TouchableOpacity onPress={refetch} style={styles.refreshBadge}>
              <Text style={styles.refreshBadgeText}>
                {minutesSinceRefresh === 0
                  ? 'Just updated'
                  : `${minutesSinceRefresh}m ago`}
                {'  '}
                <Text style={styles.refreshIcon}>↻</Text>
              </Text>
            </TouchableOpacity>
          )}
        </View>
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

      {/* Game Filter Banner */}
      {gameFilter && (
        <View style={styles.gameFilterBanner}>
          <Text style={styles.gameFilterText}>
            {gameFilter.awayTeam} @ {gameFilter.homeTeam}
          </Text>
          <TouchableOpacity
            style={styles.clearGameFilter}
            onPress={() => setGameFilter(null)}
          >
            <Text style={styles.clearGameFilterText}>X Clear</Text>
          </TouchableOpacity>
        </View>
      )}

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
        {/* View mode toggle */}
        <TouchableOpacity
          style={[styles.viewModeBtn, viewMode === 'carousel' && styles.viewModeBtnActive]}
          onPress={() => setViewMode(viewMode === 'list' ? 'carousel' : 'list')}
        >
          <Text style={[styles.viewModeBtnText, viewMode === 'carousel' && styles.viewModeBtnTextActive]}>
            {viewMode === 'list' ? 'Cards' : 'List'}
          </Text>
        </TouchableOpacity>
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
            <Text style={styles.filterLabel}>Games:</Text>
            <ScrollView horizontal showsHorizontalScrollIndicator={false}>
              {GAME_STATUS_OPTIONS.map((option) => (
                <TouchableOpacity
                  key={option}
                  style={[
                    styles.filterChip,
                    (option === 'UPCOMING' ? hideStarted : !hideStarted) && styles.filterChipActive,
                  ]}
                  onPress={() => setHideStarted(option === 'UPCOMING')}
                >
                  <Text
                    style={[
                      styles.filterChipText,
                      (option === 'UPCOMING' ? hideStarted : !hideStarted) && styles.filterChipTextActive,
                    ]}
                  >
                    {option}
                  </Text>
                </TouchableOpacity>
              ))}
            </ScrollView>
          </View>
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
          <View style={styles.filterRow}>
            <Text style={styles.filterLabel}>Prop:</Text>
            <ScrollView horizontal showsHorizontalScrollIndicator={false}>
              {availablePropTypes.map((prop) => (
                <TouchableOpacity
                  key={prop}
                  style={[
                    styles.filterChip,
                    propTypeFilter === prop && styles.filterChipActive,
                  ]}
                  onPress={() => setPropTypeFilter(prop)}
                >
                  <Text
                    style={[
                      styles.filterChipText,
                      propTypeFilter === prop && styles.filterChipTextActive,
                    ]}
                  >
                    {prop === 'ALL' ? 'ALL' : prop.toUpperCase()}
                  </Text>
                </TouchableOpacity>
              ))}
            </ScrollView>
          </View>
          <View style={styles.filterRow}>
            <Text style={styles.filterLabel}>Player:</Text>
            <ScrollView horizontal showsHorizontalScrollIndicator={false}>
              {PLAYER_FILTER_OPTIONS.map((opt) => (
                <TouchableOpacity
                  key={opt}
                  style={[
                    styles.filterChip,
                    playerFilter === opt && styles.filterChipActive,
                    opt === 'STARS' && playerFilter === opt && styles.starsChipActive,
                  ]}
                  onPress={() => setPlayerFilter(opt)}
                >
                  <Text
                    style={[
                      styles.filterChipText,
                      playerFilter === opt && styles.filterChipTextActive,
                    ]}
                  >
                    {opt === 'STARS' ? 'STARS ONLY' : opt}
                  </Text>
                </TouchableOpacity>
              ))}
            </ScrollView>
          </View>
          {/* Odds type filter */}
          <View style={styles.filterRow}>
            <Text style={styles.filterLabel}>Odds:</Text>
            <ScrollView horizontal showsHorizontalScrollIndicator={false}>
              {['ALL', 'goblin', 'standard', 'demon'].map((opt) => (
                <TouchableOpacity
                  key={opt}
                  style={[
                    styles.filterChip,
                    oddsTypeFilter === opt && styles.filterChipActive,
                    opt === 'goblin' && oddsTypeFilter === opt && styles.goblinChipActive,
                    opt === 'demon' && oddsTypeFilter === opt && styles.demonChipActive,
                  ]}
                  onPress={() => setOddsTypeFilter(opt)}
                >
                  <Text
                    style={[
                      styles.filterChipText,
                      oddsTypeFilter === opt && styles.filterChipTextActive,
                    ]}
                  >
                    {opt.toUpperCase()}
                  </Text>
                </TouchableOpacity>
              ))}
            </ScrollView>
          </View>
          {/* Min edge filter */}
          <View style={styles.filterRow}>
            <Text style={styles.filterLabel}>Edge:</Text>
            <ScrollView horizontal showsHorizontalScrollIndicator={false}>
              {[0, 5, 10, 14, 19].map((threshold) => (
                <TouchableOpacity
                  key={threshold}
                  style={[
                    styles.filterChip,
                    minEdgeFilter === threshold && styles.filterChipActive,
                  ]}
                  onPress={() => setMinEdgeFilter(threshold)}
                >
                  <Text
                    style={[
                      styles.filterChipText,
                      minEdgeFilter === threshold && styles.filterChipTextActive,
                    ]}
                  >
                    {threshold === 0 ? 'ANY' : `${threshold}%+`}
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
      ) : viewMode === 'carousel' ? (
        <PickCarousel
          picks={filteredPicks}
          onAddToParlay={handleAddToParlay}
          onPlayerPress={handlePlayerPress}
          isPickInParlay={isPickInParlay}
        />
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

      {/* Floating parlay buttons */}
      {parlayPicks.length > 0 && (
        <View style={styles.parlayButtonContainer}>
          <TouchableOpacity style={styles.clearButton} onPress={clearPicks}>
            <Text style={styles.clearButtonText}>Clear</Text>
          </TouchableOpacity>
          <TouchableOpacity style={styles.parlayButton} onPress={goToParlay}>
            <Text style={styles.parlayButtonText}>
              View Parlay ({parlayPicks.length})
            </Text>
          </TouchableOpacity>
        </View>
      )}

      {/* Player Card Modal */}
      <PlayerCardModal
        visible={selectedPlayer !== null}
        playerName={selectedPlayer?.player_name || ''}
        sport={sport.toLowerCase()}
        propType={selectedPlayer?.prop_type}
        todayPicks={selectedPlayerTodayPicks}
        onClose={() => setSelectedPlayer(null)}
        onAddToParlay={handleAddToParlay}
        isPickInParlay={isPickInParlay}
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
  titleRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
  },
  title: {
    color: '#fff',
    fontSize: 28,
    fontWeight: 'bold',
  },
  refreshBadge: {
    backgroundColor: '#1a1a2a',
    borderColor: '#333',
    borderWidth: 1,
    paddingHorizontal: 10,
    paddingVertical: 4,
    borderRadius: 12,
  },
  refreshBadgeText: {
    color: '#666',
    fontSize: 11,
  },
  refreshIcon: {
    color: '#4CAF50',
    fontSize: 13,
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
  viewModeBtn: {
    paddingHorizontal: 10,
    paddingVertical: 6,
    borderRadius: 16,
    backgroundColor: '#252535',
    borderWidth: 1,
    borderColor: '#333',
    marginLeft: 8,
  },
  viewModeBtnActive: {
    backgroundColor: '#4CAF5020',
    borderColor: '#4CAF50',
  },
  viewModeBtnText: {
    color: '#666',
    fontSize: 12,
    fontWeight: 'bold',
  },
  viewModeBtnTextActive: {
    color: '#4CAF50',
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
  gameFilterBanner: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    backgroundColor: '#1976D2',
    paddingHorizontal: 16,
    paddingVertical: 10,
  },
  gameFilterText: {
    color: '#fff',
    fontSize: 14,
    fontWeight: 'bold',
  },
  clearGameFilter: {
    backgroundColor: '#ffffff30',
    paddingHorizontal: 12,
    paddingVertical: 4,
    borderRadius: 12,
  },
  clearGameFilterText: {
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
  starsChipActive: {
    backgroundColor: '#FFD700',
  },
  goblinChipActive: {
    backgroundColor: '#2E7D32',
  },
  demonChipActive: {
    backgroundColor: '#B71C1C',
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
  parlayButtonContainer: {
    position: 'absolute',
    bottom: 20,
    left: 20,
    right: 20,
    flexDirection: 'row',
    gap: 10,
  },
  clearButton: {
    backgroundColor: '#F44336',
    paddingVertical: 16,
    paddingHorizontal: 20,
    borderRadius: 12,
    alignItems: 'center',
    justifyContent: 'center',
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 4 },
    shadowOpacity: 0.3,
    shadowRadius: 8,
    elevation: 8,
  },
  clearButtonText: {
    color: '#fff',
    fontSize: 14,
    fontWeight: 'bold',
  },
  parlayButton: {
    flex: 1,
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
