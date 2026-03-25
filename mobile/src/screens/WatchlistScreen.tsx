import React, { useState, useEffect, useCallback } from 'react';
import {
  View,
  Text,
  StyleSheet,
  FlatList,
  Pressable,
  TextInput,
  Alert,
  SectionList,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useNavigation } from '@react-navigation/native';
import { useWatchlistStore } from '../store/watchlistStore';
import { supabase, getTodayDate } from '../services/supabase';
import { STAR_PLAYERS } from '../utils/constants';
import type { DailyProp } from '../types/supabase';

interface GalleryPlayer {
  name: string;
  team: string;
  sport: string;
  propsCount: number;
  aiTier: string | null;
  aiEdge: number | null;
}

export function WatchlistScreen() {
  const navigation = useNavigation();
  const { items, addPlayer, removePlayer, isWatched, canAdd, fetchWatchlist } = useWatchlistStore();
  const [search, setSearch] = useState('');
  const [galleryPlayers, setGalleryPlayers] = useState<GalleryPlayer[]>([]);
  const [sport] = useState<string>('NBA');

  // Fetch gallery data
  useEffect(() => {
    fetchGallery();
    fetchWatchlist();
  }, [sport, fetchWatchlist]);

  const fetchGallery = async () => {
    try {
      const today = getTodayDate();
      const { data: props } = await supabase
        .from('daily_props')
        .select('player_name, team, sport, ai_tier, ai_edge')
        .eq('game_date', today)
        .eq('sport', sport);

      // Build unique player list from today's props
      const playerMap = new Map<string, GalleryPlayer>();
      for (const prop of (props || []) as DailyProp[]) {
        const existing = playerMap.get(prop.player_name);
        if (existing) {
          existing.propsCount++;
          // Keep best tier
          if (prop.ai_tier && (!existing.aiTier || prop.ai_tier < existing.aiTier)) {
            existing.aiTier = prop.ai_tier;
          }
          if (prop.ai_edge !== null && (existing.aiEdge === null || prop.ai_edge > existing.aiEdge)) {
            existing.aiEdge = prop.ai_edge;
          }
        } else {
          playerMap.set(prop.player_name, {
            name: prop.player_name,
            team: prop.team,
            sport: prop.sport,
            propsCount: 1,
            aiTier: prop.ai_tier,
            aiEdge: prop.ai_edge,
          });
        }
      }

      setGalleryPlayers(Array.from(playerMap.values()));
    } catch (error) {
      console.error('Gallery fetch error:', error);
    }
  };

  // Build sections
  const sections = React.useMemo(() => {
    const filterName = search.toLowerCase();

    // Current watchlist
    const watchlistSection = {
      title: `My Watchlist (${items.length}/10)`,
      data: items.map(i => ({
        name: i.player_name,
        team: '',
        sport: i.sport,
        propsCount: 0,
        aiTier: null,
        aiEdge: null,
        watchlistId: i.id,
      })),
    };

    // AI Top Picks
    const aiTopPicks = galleryPlayers
      .filter(p =>
        (p.aiTier === 'T1-ELITE' || p.aiTier === 'T2-STRONG') &&
        !isWatched(p.name, p.sport) &&
        p.name.toLowerCase().includes(filterName)
      )
      .sort((a, b) => (b.aiEdge || 0) - (a.aiEdge || 0))
      .slice(0, 10);

    // Superstars not already shown
    const shownNames = new Set([
      ...items.map(i => i.player_name),
      ...aiTopPicks.map(p => p.name),
    ]);
    const superstars = (STAR_PLAYERS[sport] || [])
      .filter(name =>
        !shownNames.has(name) &&
        !isWatched(name, sport) &&
        name.toLowerCase().includes(filterName)
      )
      .map(name => ({
        name,
        team: '',
        sport,
        propsCount: 0,
        aiTier: null,
        aiEdge: null,
      }));

    const result = [watchlistSection];
    if (aiTopPicks.length > 0) {
      result.push({ title: 'AI Top Picks', data: aiTopPicks as any[] });
    }
    if (superstars.length > 0) {
      result.push({ title: 'Superstars', data: superstars as any[] });
    }

    return result;
  }, [items, galleryPlayers, sport, search, isWatched]);

  const handleToggle = useCallback(async (playerName: string, sportStr: string, watchlistId?: string) => {
    try {
      if (watchlistId) {
        await removePlayer(watchlistId);
      } else if (isWatched(playerName, sportStr)) {
        const item = items.find(i => i.player_name === playerName && i.sport.toUpperCase() === sportStr.toUpperCase());
        if (item) await removePlayer(item.id);
      } else {
        if (!canAdd()) {
          Alert.alert('Watchlist Full', 'Max 10 players. Remove one first.');
          return;
        }
        await addPlayer(playerName, sportStr);
      }
    } catch (e) {
      Alert.alert('Error', (e as Error).message);
    }
  }, [items, addPlayer, removePlayer, isWatched, canAdd]);

  const renderItem = useCallback(({ item }: { item: any }) => {
    const watched = isWatched(item.name, item.sport || sport);

    return (
      <Pressable
        style={styles.playerRow}
        onPress={() => handleToggle(item.name, item.sport || sport, item.watchlistId)}
      >
        <View style={styles.playerInfo}>
          <Text style={styles.playerName}>{item.name}</Text>
          <View style={styles.playerMeta}>
            {item.team ? <Text style={styles.metaText}>{item.team}</Text> : null}
            {item.propsCount > 0 && (
              <Text style={styles.metaText}>{item.propsCount} props</Text>
            )}
            {item.aiTier && (
              <Text style={[styles.tierTag, {
                color: item.aiTier.includes('ELITE') ? '#FFD700' :
                       item.aiTier.includes('STRONG') ? '#00FF00' : '#888'
              }]}>
                {item.aiTier.replace('T1-', '').replace('T2-', '')}
              </Text>
            )}
          </View>
        </View>
        <View style={[styles.watchBtn, watched && styles.watchedBtn]}>
          <Text style={[styles.watchBtnText, watched && styles.watchedBtnText]}>
            {watched ? 'Remove' : '+ Add'}
          </Text>
        </View>
      </Pressable>
    );
  }, [isWatched, sport, handleToggle]);

  return (
    <SafeAreaView style={styles.container} edges={['top']}>
      <View style={styles.header}>
        <Pressable onPress={() => navigation.goBack()}>
          <Text style={styles.backText}>Back</Text>
        </Pressable>
        <Text style={styles.title}>Player Watchlist</Text>
        <View style={{ width: 40 }} />
      </View>

      {/* Search */}
      <View style={styles.searchContainer}>
        <TextInput
          style={styles.searchInput}
          value={search}
          onChangeText={setSearch}
          placeholder="Search players..."
          placeholderTextColor="#555"
        />
      </View>

      <SectionList
        sections={sections}
        keyExtractor={(item, index) => item.name + index}
        renderItem={renderItem}
        renderSectionHeader={({ section }) => (
          <View style={styles.sectionHeader}>
            <Text style={styles.sectionTitle}>{section.title}</Text>
          </View>
        )}
        contentContainerStyle={styles.listContent}
        showsVerticalScrollIndicator={false}
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
  backText: {
    color: '#4CAF50',
    fontSize: 15,
  },
  title: {
    color: '#fff',
    fontSize: 17,
    fontWeight: '700',
  },
  searchContainer: {
    paddingHorizontal: 16,
    paddingBottom: 8,
  },
  searchInput: {
    backgroundColor: '#1e1e2e',
    borderRadius: 10,
    paddingHorizontal: 14,
    paddingVertical: 10,
    color: '#fff',
    fontSize: 15,
    borderWidth: 1,
    borderColor: '#333',
  },
  sectionHeader: {
    paddingHorizontal: 16,
    paddingTop: 16,
    paddingBottom: 6,
  },
  sectionTitle: {
    color: '#888',
    fontSize: 13,
    fontWeight: '700',
    textTransform: 'uppercase',
    letterSpacing: 0.5,
  },
  listContent: {
    paddingBottom: 40,
  },
  playerRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: 16,
    paddingVertical: 12,
    borderBottomWidth: 1,
    borderBottomColor: '#1e1e2e',
  },
  playerInfo: {
    flex: 1,
  },
  playerName: {
    color: '#fff',
    fontSize: 15,
    fontWeight: '600',
  },
  playerMeta: {
    flexDirection: 'row',
    gap: 8,
    marginTop: 2,
  },
  metaText: {
    color: '#666',
    fontSize: 12,
  },
  tierTag: {
    fontSize: 11,
    fontWeight: '700',
  },
  watchBtn: {
    paddingHorizontal: 12,
    paddingVertical: 6,
    borderRadius: 6,
    backgroundColor: 'rgba(76, 175, 80, 0.15)',
    borderWidth: 1,
    borderColor: '#4CAF50',
  },
  watchedBtn: {
    backgroundColor: 'rgba(244, 67, 54, 0.1)',
    borderColor: '#F44336',
  },
  watchBtnText: {
    color: '#4CAF50',
    fontSize: 12,
    fontWeight: '600',
  },
  watchedBtnText: {
    color: '#F44336',
  },
});
