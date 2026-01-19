import React, { useState, useCallback } from 'react';
import {
  View,
  Text,
  StyleSheet,
  TextInput,
  FlatList,
  TouchableOpacity,
  ActivityIndicator,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { searchPlayers, PlayerSearchResult } from '../services/api';
import { Card } from '../components/common/Card';

export function PlayerSearchScreen() {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<PlayerSearchResult[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [hasSearched, setHasSearched] = useState(false);

  const handleSearch = useCallback(async () => {
    if (query.length < 2) {
      setError('Enter at least 2 characters');
      return;
    }

    try {
      setLoading(true);
      setError(null);
      setHasSearched(true);
      const data = await searchPlayers(query);
      setResults(data.players);
    } catch (err: any) {
      setError(err.message || 'Search failed');
      setResults([]);
    } finally {
      setLoading(false);
    }
  }, [query]);

  const renderPlayer = ({ item }: { item: PlayerSearchResult }) => (
    <Card>
      <View style={styles.playerHeader}>
        <Text style={styles.playerName}>{item.player_name}</Text>
        <View style={[styles.sportBadge, item.sport === 'NBA' ? styles.nbaBadge : styles.nhlBadge]}>
          <Text style={styles.sportText}>{item.sport}</Text>
        </View>
      </View>

      <View style={styles.playerStats}>
        <View style={styles.statItem}>
          <Text style={styles.statLabel}>Predictions</Text>
          <Text style={styles.statValue}>{item.total_predictions}</Text>
        </View>

        <View style={styles.statItem}>
          <Text style={styles.statLabel}>Accuracy</Text>
          <Text
            style={[
              styles.statValue,
              item.accuracy >= 60
                ? styles.goodAccuracy
                : item.accuracy >= 50
                ? styles.okAccuracy
                : styles.badAccuracy,
            ]}
          >
            {item.accuracy.toFixed(1)}%
          </Text>
        </View>

        <View style={styles.statItem}>
          <Text style={styles.statLabel}>Last Game</Text>
          <Text style={styles.statValue}>{item.last_game_date || 'N/A'}</Text>
        </View>
      </View>
    </Card>
  );

  return (
    <SafeAreaView style={styles.container} edges={['top']}>
      <View style={styles.header}>
        <Text style={styles.title}>Player Search</Text>
        <Text style={styles.subtitle}>Find player prediction history</Text>
      </View>

      {/* Search Input */}
      <View style={styles.searchContainer}>
        <TextInput
          style={styles.searchInput}
          placeholder="Search players..."
          placeholderTextColor="#666"
          value={query}
          onChangeText={setQuery}
          onSubmitEditing={handleSearch}
          returnKeyType="search"
          autoCapitalize="words"
          autoCorrect={false}
        />
        <TouchableOpacity
          style={[styles.searchButton, query.length < 2 && styles.searchButtonDisabled]}
          onPress={handleSearch}
          disabled={query.length < 2}
        >
          <Text style={styles.searchButtonText}>Search</Text>
        </TouchableOpacity>
      </View>

      {/* Results */}
      {loading ? (
        <View style={styles.loadingContainer}>
          <ActivityIndicator size="large" color="#4CAF50" />
          <Text style={styles.loadingText}>Searching...</Text>
        </View>
      ) : error ? (
        <View style={styles.messageContainer}>
          <Text style={styles.errorText}>{error}</Text>
        </View>
      ) : !hasSearched ? (
        <View style={styles.messageContainer}>
          <Text style={styles.hintText}>Enter a player name to search</Text>
          <Text style={styles.hintSubtext}>
            View prediction history and accuracy for any player
          </Text>
        </View>
      ) : results.length === 0 ? (
        <View style={styles.messageContainer}>
          <Text style={styles.emptyText}>No players found</Text>
          <Text style={styles.emptySubtext}>Try a different search term</Text>
        </View>
      ) : (
        <FlatList
          data={results}
          keyExtractor={(item) => `${item.player_name}-${item.sport}`}
          renderItem={renderPlayer}
          contentContainerStyle={styles.listContent}
          showsVerticalScrollIndicator={false}
        />
      )}
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
  subtitle: {
    color: '#888',
    fontSize: 12,
    marginTop: 4,
  },
  searchContainer: {
    flexDirection: 'row',
    paddingHorizontal: 16,
    paddingVertical: 8,
    gap: 8,
  },
  searchInput: {
    flex: 1,
    backgroundColor: '#1e1e2e',
    borderRadius: 8,
    paddingHorizontal: 16,
    paddingVertical: 12,
    color: '#fff',
    fontSize: 16,
  },
  searchButton: {
    backgroundColor: '#4CAF50',
    paddingHorizontal: 20,
    borderRadius: 8,
    justifyContent: 'center',
  },
  searchButtonDisabled: {
    backgroundColor: '#333',
  },
  searchButtonText: {
    color: '#fff',
    fontSize: 14,
    fontWeight: 'bold',
  },
  listContent: {
    paddingBottom: 20,
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
  messageContainer: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    paddingHorizontal: 32,
  },
  hintText: {
    color: '#888',
    fontSize: 16,
  },
  hintSubtext: {
    color: '#666',
    fontSize: 12,
    marginTop: 8,
    textAlign: 'center',
  },
  errorText: {
    color: '#F44336',
    fontSize: 14,
  },
  emptyText: {
    color: '#888',
    fontSize: 16,
  },
  emptySubtext: {
    color: '#666',
    fontSize: 12,
    marginTop: 8,
  },
  playerHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 12,
  },
  playerName: {
    color: '#fff',
    fontSize: 18,
    fontWeight: 'bold',
    flex: 1,
  },
  sportBadge: {
    paddingHorizontal: 8,
    paddingVertical: 4,
    borderRadius: 4,
  },
  nbaBadge: {
    backgroundColor: '#C9082A20',
    borderColor: '#C9082A',
    borderWidth: 1,
  },
  nhlBadge: {
    backgroundColor: '#00000040',
    borderColor: '#888',
    borderWidth: 1,
  },
  sportText: {
    color: '#fff',
    fontSize: 10,
    fontWeight: 'bold',
  },
  playerStats: {
    flexDirection: 'row',
    justifyContent: 'space-between',
  },
  statItem: {
    alignItems: 'center',
  },
  statLabel: {
    color: '#666',
    fontSize: 10,
    marginBottom: 4,
  },
  statValue: {
    color: '#fff',
    fontSize: 14,
    fontWeight: '600',
  },
  goodAccuracy: {
    color: '#4CAF50',
  },
  okAccuracy: {
    color: '#FFD700',
  },
  badAccuracy: {
    color: '#F44336',
  },
});
