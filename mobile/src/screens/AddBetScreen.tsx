import React, { useState } from 'react';
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  TextInput,
  Pressable,
  Alert,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useNavigation } from '@react-navigation/native';
import { useBetStore } from '../store/betStore';
import { SPORTSBOOKS, SPORTS } from '../utils/constants';
import type { BetLeg } from '../types/supabase';

type BetType = 'single' | 'parlay' | 'flex';

export function AddBetScreen() {
  const navigation = useNavigation();
  const { addBet } = useBetStore();

  const [sport, setSport] = useState<string>(SPORTS[0]);
  const [sportsbook, setSportsbook] = useState<string>(SPORTSBOOKS[0]);
  const [betType, setBetType] = useState<BetType>('parlay');
  const [stake, setStake] = useState('');
  const [payout, setPayout] = useState('');
  const [notes, setNotes] = useState('');
  const [legs, setLegs] = useState<BetLeg[]>([{ player: '', prop_type: '', line: 0, prediction: 'OVER' }]);
  const [submitting, setSubmitting] = useState(false);

  const addLeg = () => {
    setLegs([...legs, { player: '', prop_type: '', line: 0, prediction: 'OVER' }]);
  };

  const removeLeg = (index: number) => {
    if (legs.length <= 1) return;
    setLegs(legs.filter((_, i) => i !== index));
  };

  const updateLeg = (index: number, field: keyof BetLeg, value: string | number) => {
    const updated = [...legs];
    (updated[index] as any)[field] = value;
    setLegs(updated);
  };

  const handleSubmit = async () => {
    // Validate
    const validLegs = legs.filter(l => l.player.trim() !== '');
    if (validLegs.length === 0) {
      Alert.alert('Error', 'Add at least one leg with a player name.');
      return;
    }

    setSubmitting(true);
    try {
      await addBet({
        sport,
        sportsbook,
        bet_type: betType,
        stake: parseFloat(stake) || 0,
        potential_payout: parseFloat(payout) || 0,
        legs: validLegs,
        notes: notes || undefined,
      });
      navigation.goBack();
    } catch (e) {
      Alert.alert('Error', (e as Error).message);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <SafeAreaView style={styles.container} edges={['top']}>
      <View style={styles.header}>
        <Pressable onPress={() => navigation.goBack()}>
          <Text style={styles.cancelText}>Cancel</Text>
        </Pressable>
        <Text style={styles.title}>Log a Bet</Text>
        <Pressable onPress={handleSubmit} disabled={submitting}>
          <Text style={[styles.saveText, submitting && styles.disabledText]}>Save</Text>
        </Pressable>
      </View>

      <ScrollView style={styles.form} showsVerticalScrollIndicator={false}>
        {/* Sport */}
        <Text style={styles.label}>Sport</Text>
        <View style={styles.chipRow}>
          {SPORTS.map(s => (
            <Pressable
              key={s}
              style={[styles.chip, sport === s && styles.activeChip]}
              onPress={() => setSport(s)}
            >
              <Text style={[styles.chipText, sport === s && styles.activeChipText]}>{s}</Text>
            </Pressable>
          ))}
        </View>

        {/* Sportsbook */}
        <Text style={styles.label}>Sportsbook</Text>
        <ScrollView horizontal showsHorizontalScrollIndicator={false}>
          <View style={styles.chipRow}>
            {SPORTSBOOKS.map(sb => (
              <Pressable
                key={sb}
                style={[styles.chip, sportsbook === sb && styles.activeChip]}
                onPress={() => setSportsbook(sb)}
              >
                <Text style={[styles.chipText, sportsbook === sb && styles.activeChipText]}>{sb}</Text>
              </Pressable>
            ))}
          </View>
        </ScrollView>

        {/* Bet type */}
        <Text style={styles.label}>Type</Text>
        <View style={styles.chipRow}>
          {(['single', 'parlay', 'flex'] as BetType[]).map(t => (
            <Pressable
              key={t}
              style={[styles.chip, betType === t && styles.activeChip]}
              onPress={() => setBetType(t)}
            >
              <Text style={[styles.chipText, betType === t && styles.activeChipText]}>
                {t.charAt(0).toUpperCase() + t.slice(1)}
              </Text>
            </Pressable>
          ))}
        </View>

        {/* Stake & Payout */}
        <View style={styles.moneyRow}>
          <View style={styles.moneyField}>
            <Text style={styles.label}>Stake ($)</Text>
            <TextInput
              style={styles.input}
              value={stake}
              onChangeText={setStake}
              keyboardType="numeric"
              placeholder="0.00"
              placeholderTextColor="#555"
            />
          </View>
          <View style={styles.moneyField}>
            <Text style={styles.label}>Potential Payout ($)</Text>
            <TextInput
              style={styles.input}
              value={payout}
              onChangeText={setPayout}
              keyboardType="numeric"
              placeholder="0.00"
              placeholderTextColor="#555"
            />
          </View>
        </View>

        {/* Legs */}
        <View style={styles.legsHeader}>
          <Text style={styles.label}>Legs</Text>
          <Pressable onPress={addLeg}>
            <Text style={styles.addLegText}>+ Add Leg</Text>
          </Pressable>
        </View>

        {legs.map((leg, index) => (
          <View key={index} style={styles.legCard}>
            <View style={styles.legTopRow}>
              <Text style={styles.legNumber}>#{index + 1}</Text>
              {legs.length > 1 && (
                <Pressable onPress={() => removeLeg(index)}>
                  <Text style={styles.removeLeg}>Remove</Text>
                </Pressable>
              )}
            </View>
            <TextInput
              style={styles.input}
              value={leg.player}
              onChangeText={v => updateLeg(index, 'player', v)}
              placeholder="Player name"
              placeholderTextColor="#555"
            />
            <View style={styles.legDetailRow}>
              <TextInput
                style={[styles.input, styles.smallInput]}
                value={leg.prop_type}
                onChangeText={v => updateLeg(index, 'prop_type', v)}
                placeholder="Prop (pts)"
                placeholderTextColor="#555"
              />
              <TextInput
                style={[styles.input, styles.smallInput]}
                value={leg.line ? String(leg.line) : ''}
                onChangeText={v => updateLeg(index, 'line', parseFloat(v) || 0)}
                keyboardType="numeric"
                placeholder="Line"
                placeholderTextColor="#555"
              />
              <Pressable
                style={[styles.directionBtn, leg.prediction === 'OVER' ? styles.overBtn : styles.underBtn]}
                onPress={() => updateLeg(index, 'prediction', leg.prediction === 'OVER' ? 'UNDER' : 'OVER')}
              >
                <Text style={styles.directionText}>{leg.prediction}</Text>
              </Pressable>
            </View>
          </View>
        ))}

        {/* Notes */}
        <Text style={styles.label}>Notes (optional)</Text>
        <TextInput
          style={[styles.input, styles.notesInput]}
          value={notes}
          onChangeText={setNotes}
          placeholder="Any notes about this bet..."
          placeholderTextColor="#555"
          multiline
        />

        <View style={styles.bottomSpacer} />
      </ScrollView>
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
    borderBottomWidth: 1,
    borderBottomColor: '#1e1e2e',
  },
  cancelText: {
    color: '#888',
    fontSize: 15,
  },
  title: {
    color: '#fff',
    fontSize: 17,
    fontWeight: '700',
  },
  saveText: {
    color: '#4CAF50',
    fontSize: 15,
    fontWeight: '700',
  },
  disabledText: {
    opacity: 0.5,
  },
  form: {
    paddingHorizontal: 16,
    paddingTop: 16,
  },
  label: {
    color: '#888',
    fontSize: 12,
    fontWeight: '600',
    textTransform: 'uppercase',
    letterSpacing: 0.5,
    marginBottom: 8,
    marginTop: 16,
  },
  chipRow: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 8,
  },
  chip: {
    paddingHorizontal: 14,
    paddingVertical: 8,
    borderRadius: 8,
    backgroundColor: '#1e1e2e',
    borderWidth: 1,
    borderColor: '#333',
  },
  activeChip: {
    backgroundColor: 'rgba(76, 175, 80, 0.15)',
    borderColor: '#4CAF50',
  },
  chipText: {
    color: '#888',
    fontSize: 13,
    fontWeight: '600',
  },
  activeChipText: {
    color: '#4CAF50',
  },
  moneyRow: {
    flexDirection: 'row',
    gap: 12,
  },
  moneyField: {
    flex: 1,
  },
  input: {
    backgroundColor: '#1e1e2e',
    borderRadius: 8,
    borderWidth: 1,
    borderColor: '#333',
    paddingHorizontal: 12,
    paddingVertical: 10,
    color: '#fff',
    fontSize: 15,
  },
  legsHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginTop: 16,
    marginBottom: 8,
  },
  addLegText: {
    color: '#4CAF50',
    fontSize: 13,
    fontWeight: '600',
  },
  legCard: {
    backgroundColor: '#1a1a2e',
    borderRadius: 10,
    padding: 12,
    marginBottom: 8,
    gap: 8,
  },
  legTopRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  legNumber: {
    color: '#888',
    fontSize: 12,
    fontWeight: '700',
  },
  removeLeg: {
    color: '#F44336',
    fontSize: 12,
  },
  legDetailRow: {
    flexDirection: 'row',
    gap: 8,
  },
  smallInput: {
    flex: 1,
  },
  directionBtn: {
    paddingHorizontal: 14,
    justifyContent: 'center',
    borderRadius: 8,
  },
  overBtn: {
    backgroundColor: 'rgba(76, 175, 80, 0.2)',
  },
  underBtn: {
    backgroundColor: 'rgba(244, 67, 54, 0.2)',
  },
  directionText: {
    color: '#fff',
    fontSize: 12,
    fontWeight: '700',
  },
  notesInput: {
    height: 80,
    textAlignVertical: 'top',
  },
  bottomSpacer: {
    height: 40,
  },
});
