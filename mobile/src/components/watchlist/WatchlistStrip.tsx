import React from 'react';
import { View, Text, StyleSheet, ScrollView, Pressable } from 'react-native';
import type { WatchlistItem } from '../../types/supabase';

interface WatchlistStripProps {
  items: WatchlistItem[];
  selectedPlayer: string | null;
  onSelectPlayer: (playerName: string | null) => void;
}

export function WatchlistStrip({ items, selectedPlayer, onSelectPlayer }: WatchlistStripProps) {
  if (items.length === 0) return null;

  return (
    <ScrollView
      horizontal
      showsHorizontalScrollIndicator={false}
      contentContainerStyle={styles.container}
    >
      {/* "All" chip */}
      <Pressable
        style={[styles.chip, !selectedPlayer && styles.selectedChip]}
        onPress={() => onSelectPlayer(null)}
      >
        <Text style={[styles.chipText, !selectedPlayer && styles.selectedChipText]}>All</Text>
      </Pressable>

      {items.map((item) => {
        const isSelected = selectedPlayer === item.player_name;
        // Get initials
        const initials = item.player_name
          .split(' ')
          .map(n => n[0])
          .join('')
          .slice(0, 2)
          .toUpperCase();

        return (
          <Pressable
            key={item.id}
            style={[styles.chip, isSelected && styles.selectedChip]}
            onPress={() => onSelectPlayer(isSelected ? null : item.player_name)}
          >
            <View style={[styles.avatar, isSelected && styles.selectedAvatar]}>
              <Text style={styles.avatarText}>{initials}</Text>
            </View>
            <Text
              style={[styles.chipText, isSelected && styles.selectedChipText]}
              numberOfLines={1}
            >
              {item.player_name.split(' ').pop()}
            </Text>
          </Pressable>
        );
      })}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: {
    paddingHorizontal: 16,
    paddingVertical: 8,
    gap: 8,
  },
  chip: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: 10,
    paddingVertical: 6,
    borderRadius: 20,
    backgroundColor: '#1e1e2e',
    borderWidth: 1,
    borderColor: '#333',
    gap: 6,
  },
  selectedChip: {
    backgroundColor: 'rgba(76, 175, 80, 0.15)',
    borderColor: '#4CAF50',
  },
  chipText: {
    color: '#888',
    fontSize: 12,
    fontWeight: '600',
  },
  selectedChipText: {
    color: '#4CAF50',
  },
  avatar: {
    width: 22,
    height: 22,
    borderRadius: 11,
    backgroundColor: '#333',
    justifyContent: 'center',
    alignItems: 'center',
  },
  selectedAvatar: {
    backgroundColor: 'rgba(76, 175, 80, 0.3)',
  },
  avatarText: {
    color: '#aaa',
    fontSize: 9,
    fontWeight: '700',
  },
});
