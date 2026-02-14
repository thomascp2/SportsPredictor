import React from 'react';
import { View, Text, StyleSheet, Pressable } from 'react-native';
import type { UserBet } from '../../types/supabase';

interface BetCardProps {
  bet: UserBet;
  onSettle?: (betId: string, status: 'won' | 'lost') => void;
  onDelete?: (betId: string) => void;
}

const STATUS_COLORS: Record<string, string> = {
  pending: '#FFD700',
  won: '#4CAF50',
  lost: '#F44336',
  push: '#888',
};

export function BetCard({ bet, onSettle, onDelete }: BetCardProps) {
  const statusColor = STATUS_COLORS[bet.status] || '#888';

  return (
    <View style={styles.card}>
      {/* Header */}
      <View style={styles.header}>
        <View style={styles.headerLeft}>
          <Text style={styles.betType}>{bet.bet_type.toUpperCase()}</Text>
          <Text style={styles.sport}>{bet.sport}</Text>
          {bet.sportsbook && <Text style={styles.sportsbook}>{bet.sportsbook}</Text>}
        </View>
        <View style={[styles.statusBadge, { backgroundColor: `${statusColor}20`, borderColor: statusColor }]}>
          <Text style={[styles.statusText, { color: statusColor }]}>
            {bet.status.toUpperCase()}
          </Text>
        </View>
      </View>

      {/* Legs */}
      <View style={styles.legs}>
        {bet.legs.map((leg, i) => (
          <View key={i} style={styles.leg}>
            <Text style={styles.legPlayer}>{leg.player}</Text>
            <Text style={styles.legDetail}>
              {leg.prediction} {leg.line} {leg.prop_type}
            </Text>
            {leg.outcome && (
              <Text style={[
                styles.legOutcome,
                leg.outcome === 'HIT' ? styles.hitText : styles.missText,
              ]}>
                {leg.outcome}
              </Text>
            )}
          </View>
        ))}
      </View>

      {/* Footer: stake/payout */}
      <View style={styles.footer}>
        <View style={styles.moneyRow}>
          {bet.stake !== null && (
            <Text style={styles.stake}>${bet.stake.toFixed(2)}</Text>
          )}
          <Text style={styles.arrow}>-&gt;</Text>
          <Text style={[
            styles.payout,
            bet.status === 'won' && styles.wonPayout,
            bet.status === 'lost' && styles.lostPayout,
          ]}>
            ${(bet.status === 'won'
              ? (bet.actual_payout || bet.potential_payout || 0)
              : (bet.potential_payout || 0)
            ).toFixed(2)}
          </Text>
        </View>

        {/* Settle buttons for pending bets */}
        {bet.status === 'pending' && onSettle && (
          <View style={styles.settleButtons}>
            <Pressable
              style={[styles.settleBtn, styles.wonBtn]}
              onPress={() => onSettle(bet.id, 'won')}
            >
              <Text style={styles.settleBtnText}>Won</Text>
            </Pressable>
            <Pressable
              style={[styles.settleBtn, styles.lostBtn]}
              onPress={() => onSettle(bet.id, 'lost')}
            >
              <Text style={styles.settleBtnText}>Lost</Text>
            </Pressable>
          </View>
        )}
      </View>

      {bet.notes && <Text style={styles.notes}>{bet.notes}</Text>}
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    backgroundColor: '#1e1e2e',
    borderRadius: 12,
    padding: 14,
    marginHorizontal: 16,
    marginVertical: 4,
  },
  header: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 10,
  },
  headerLeft: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
  },
  betType: {
    color: '#fff',
    fontSize: 13,
    fontWeight: '700',
  },
  sport: {
    color: '#888',
    fontSize: 12,
  },
  sportsbook: {
    color: '#666',
    fontSize: 11,
  },
  statusBadge: {
    paddingHorizontal: 8,
    paddingVertical: 3,
    borderRadius: 6,
    borderWidth: 1,
  },
  statusText: {
    fontSize: 10,
    fontWeight: '800',
    letterSpacing: 0.5,
  },
  legs: {
    gap: 6,
    marginBottom: 10,
  },
  leg: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
  },
  legPlayer: {
    color: '#fff',
    fontSize: 14,
    fontWeight: '600',
    flex: 1,
  },
  legDetail: {
    color: '#aaa',
    fontSize: 12,
  },
  legOutcome: {
    fontSize: 11,
    fontWeight: '700',
    width: 32,
    textAlign: 'right',
  },
  hitText: {
    color: '#4CAF50',
  },
  missText: {
    color: '#F44336',
  },
  footer: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    borderTopWidth: 1,
    borderTopColor: '#2a2a3e',
    paddingTop: 10,
  },
  moneyRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
  },
  stake: {
    color: '#aaa',
    fontSize: 14,
    fontWeight: '600',
  },
  arrow: {
    color: '#666',
    fontSize: 12,
  },
  payout: {
    color: '#fff',
    fontSize: 16,
    fontWeight: '700',
  },
  wonPayout: {
    color: '#4CAF50',
  },
  lostPayout: {
    color: '#F44336',
  },
  settleButtons: {
    flexDirection: 'row',
    gap: 6,
  },
  settleBtn: {
    paddingHorizontal: 14,
    paddingVertical: 6,
    borderRadius: 6,
  },
  wonBtn: {
    backgroundColor: 'rgba(76, 175, 80, 0.2)',
  },
  lostBtn: {
    backgroundColor: 'rgba(244, 67, 54, 0.2)',
  },
  settleBtnText: {
    color: '#fff',
    fontSize: 12,
    fontWeight: '600',
  },
  notes: {
    color: '#666',
    fontSize: 11,
    marginTop: 6,
    fontStyle: 'italic',
  },
});
