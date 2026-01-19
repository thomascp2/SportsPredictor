import React, { useState } from 'react';
import {
  View,
  Text,
  StyleSheet,
  FlatList,
  RefreshControl,
  ActivityIndicator,
  TouchableOpacity,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useNavigation } from '@react-navigation/native';
import { useSmartPicks } from '../hooks/useSmartPicks';
import { useParlayStore } from '../store/parlayStore';
import { PickCard } from '../components/picks/PickCard';
import { SportToggle } from '../components/common/SportToggle';
import { SmartPick } from '../services/api';

export function SmartPicksScreen() {
  const navigation = useNavigation<any>();
  const [sport, setSport] = useState<'NBA' | 'NHL'>('NBA');
  const { picks, summary, loading, error, refetch } = useSmartPicks(sport.toLowerCase());

  const parlayPicks = useParlayStore((state) => state.picks);
  const addPick = useParlayStore((state) => state.addPick);
  const removePick = useParlayStore((state) => state.removePick);

  const isPickInParlay = (pick: SmartPick) => {
    const pickId = `${pick.player_name}-${pick.prop_type}-${pick.pp_line}`.replace(/\s+/g, '-').toLowerCase();
    return parlayPicks.some((p) => p.id === pickId);
  };

  const handleAddToParlay = (pick: SmartPick) => {
    if (isPickInParlay(pick)) {
      const pickId = `${pick.player_name}-${pick.prop_type}-${pick.pp_line}`.replace(/\s+/g, '-').toLowerCase();
      removePick(pickId);
    } else {
      addPick(pick);
    }
  };

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
              {picks.length} picks | Avg: {(summary.avg_probability * 100).toFixed(0)}% prob
            </Text>
          </View>
        )}
      </View>

      <SportToggle selected={sport} onSelect={setSport} />

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
      ) : picks.length === 0 ? (
        <View style={styles.emptyContainer}>
          <Text style={styles.emptyText}>No picks available</Text>
          <Text style={styles.emptySubtext}>Check back closer to game time</Text>
        </View>
      ) : (
        <FlatList
          data={picks}
          keyExtractor={(item, index) =>
            `${item.player_name}-${item.prop_type}-${index}`
          }
          renderItem={({ item }) => (
            <PickCard
              pick={item}
              onAddToParlay={handleAddToParlay}
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
