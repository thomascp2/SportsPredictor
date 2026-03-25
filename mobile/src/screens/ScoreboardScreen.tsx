import React, { useState, useCallback } from 'react';
import {
  View,
  Text,
  StyleSheet,
  FlatList,
  RefreshControl,
  ActivityIndicator,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useNavigation } from '@react-navigation/native';
import { useLiveScores } from '../hooks/useLiveScores';
import { GameCard } from '../components/scores/GameCard';
import { SportToggle } from '../components/common/SportToggle';
import { LiveGame } from '../services/api';

// Helper to extract team name from string or object
const getTeamName = (team: any): string => {
  if (typeof team === 'string') return team;
  if (team?.name) return team.name;
  if (team?.abbreviation) return team.abbreviation;
  return 'Unknown';
};

export function ScoreboardScreen() {
  const navigation = useNavigation<any>();
  const [sport, setSport] = useState<'NBA' | 'NHL'>('NBA');
  const { games, lastUpdated, loading, error, refetch } = useLiveScores(
    sport.toLowerCase(),
    30000 // Refresh every 30 seconds
  );

  const handleGamePress = useCallback((game: LiveGame) => {
    const homeTeam = getTeamName(game.home_team);
    const awayTeam = getTeamName(game.away_team);
    navigation.navigate('Picks', {
      gameFilter: {
        homeTeam,
        awayTeam,
        sport: sport,
      },
    });
  }, [navigation, sport]);

  const formatLastUpdated = () => {
    if (!lastUpdated) return '';
    try {
      const date = new Date(lastUpdated);
      return `Updated ${date.toLocaleTimeString()}`;
    } catch {
      return '';
    }
  };

  return (
    <SafeAreaView style={styles.container} edges={['top']}>
      <View style={styles.header}>
        <Text style={styles.title}>Live Scores</Text>
        <Text style={styles.subtitle}>{formatLastUpdated()}</Text>
      </View>

      <SportToggle selected={sport} onSelect={setSport} />

      {loading && games.length === 0 ? (
        <View style={styles.loadingContainer}>
          <ActivityIndicator size="large" color="#4CAF50" />
          <Text style={styles.loadingText}>Loading scores...</Text>
        </View>
      ) : error ? (
        <View style={styles.errorContainer}>
          <Text style={styles.errorText}>{error}</Text>
          <Text style={styles.errorSubtext}>Pull to refresh</Text>
        </View>
      ) : games.length === 0 ? (
        <View style={styles.emptyContainer}>
          <Text style={styles.emptyText}>No games today</Text>
          <Text style={styles.emptySubtext}>Check back later for {sport} games</Text>
        </View>
      ) : (
        <FlatList
          data={games}
          keyExtractor={(item) => item.game_id}
          renderItem={({ item }) => <GameCard game={item} onPress={handleGamePress} />}
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
});
