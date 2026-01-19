import React from 'react';
import { View, Text, StyleSheet, TouchableOpacity, ScrollView } from 'react-native';
import { ParlayPick } from '../../utils/calculations';
import { LEG_VALUES } from '../../utils/constants';

interface ParlaySlipProps {
  picks: ParlayPick[];
  onRemovePick: (pickId: string) => void;
  onClearAll: () => void;
  onChangeOddsType?: (pickId: string, oddsType: 'goblin' | 'standard' | 'demon') => void;
}

export function ParlaySlip({ picks, onRemovePick, onClearAll, onChangeOddsType }: ParlaySlipProps) {
  if (picks.length === 0) {
    return (
      <View style={styles.emptyContainer}>
        <Text style={styles.emptyText}>No picks added</Text>
        <Text style={styles.emptySubtext}>
          Add picks from the Smart Picks screen to build your parlay
        </Text>
      </View>
    );
  }

  return (
    <View style={styles.container}>
      <View style={styles.header}>
        <Text style={styles.title}>Your Parlay ({picks.length} picks)</Text>
        <TouchableOpacity onPress={onClearAll}>
          <Text style={styles.clearButton}>Clear All</Text>
        </TouchableOpacity>
      </View>

      <ScrollView style={styles.picksList} showsVerticalScrollIndicator={false}>
        {picks.map((pick) => (
          <View key={pick.id} style={styles.pickItem}>
            <View style={styles.pickInfo}>
              <Text style={styles.playerName}>{pick.playerName}</Text>
              <Text style={styles.propDetails}>
                {pick.propType} {pick.prediction} {pick.line}
              </Text>
              <Text style={styles.probability}>
                {(pick.probability * 100).toFixed(0)}% prob
              </Text>
            </View>

            <View style={styles.pickActions}>
              {/* Odds type selector */}
              {onChangeOddsType && (
                <View style={styles.oddsTypeSelector}>
                  {(['goblin', 'standard', 'demon'] as const).map((type) => (
                    <TouchableOpacity
                      key={type}
                      style={[
                        styles.oddsTypeButton,
                        pick.oddsType === type && styles.oddsTypeSelected,
                        pick.oddsType === type && styles[type as keyof typeof styles],
                      ]}
                      onPress={() => onChangeOddsType(pick.id, type)}
                    >
                      <Text
                        style={[
                          styles.oddsTypeButtonText,
                          pick.oddsType === type && styles.oddsTypeSelectedText,
                        ]}
                      >
                        {type.charAt(0).toUpperCase()}
                      </Text>
                    </TouchableOpacity>
                  ))}
                </View>
              )}

              <View style={styles.legValue}>
                <Text style={styles.legValueText}>
                  {LEG_VALUES[pick.oddsType]}L
                </Text>
              </View>

              <TouchableOpacity
                style={styles.removeButton}
                onPress={() => onRemovePick(pick.id)}
              >
                <Text style={styles.removeButtonText}>X</Text>
              </TouchableOpacity>
            </View>
          </View>
        ))}
      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#1e1e2e',
    borderRadius: 12,
    padding: 16,
  },
  emptyContainer: {
    backgroundColor: '#1e1e2e',
    borderRadius: 12,
    padding: 32,
    alignItems: 'center',
  },
  emptyText: {
    color: '#888',
    fontSize: 16,
    fontWeight: '600',
  },
  emptySubtext: {
    color: '#666',
    fontSize: 12,
    marginTop: 8,
    textAlign: 'center',
  },
  header: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 16,
    paddingBottom: 12,
    borderBottomWidth: 1,
    borderBottomColor: '#333',
  },
  title: {
    color: '#fff',
    fontSize: 16,
    fontWeight: 'bold',
  },
  clearButton: {
    color: '#F44336',
    fontSize: 14,
    fontWeight: '600',
  },
  picksList: {
    flex: 1,
  },
  pickItem: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingVertical: 12,
    borderBottomWidth: 1,
    borderBottomColor: '#2a2a3e',
  },
  pickInfo: {
    flex: 1,
  },
  playerName: {
    color: '#fff',
    fontSize: 14,
    fontWeight: '600',
  },
  propDetails: {
    color: '#888',
    fontSize: 12,
    marginTop: 2,
  },
  probability: {
    color: '#4CAF50',
    fontSize: 12,
    marginTop: 2,
  },
  pickActions: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
  },
  oddsTypeSelector: {
    flexDirection: 'row',
    backgroundColor: '#2a2a3e',
    borderRadius: 4,
    padding: 2,
  },
  oddsTypeButton: {
    width: 24,
    height: 24,
    justifyContent: 'center',
    alignItems: 'center',
    borderRadius: 2,
  },
  oddsTypeSelected: {
    backgroundColor: '#4a4a6e',
  },
  goblin: {
    backgroundColor: '#2E7D32',
  },
  standard: {
    backgroundColor: '#1976D2',
  },
  demon: {
    backgroundColor: '#D32F2F',
  },
  oddsTypeButtonText: {
    color: '#666',
    fontSize: 10,
    fontWeight: 'bold',
  },
  oddsTypeSelectedText: {
    color: '#fff',
  },
  legValue: {
    backgroundColor: '#2a2a3e',
    paddingHorizontal: 8,
    paddingVertical: 4,
    borderRadius: 4,
  },
  legValueText: {
    color: '#FFD700',
    fontSize: 12,
    fontWeight: 'bold',
  },
  removeButton: {
    width: 24,
    height: 24,
    justifyContent: 'center',
    alignItems: 'center',
    backgroundColor: '#F4433620',
    borderRadius: 4,
  },
  removeButtonText: {
    color: '#F44336',
    fontSize: 12,
    fontWeight: 'bold',
  },
});
