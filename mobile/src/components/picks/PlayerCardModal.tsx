import React, { useEffect, useState } from 'react';
import {
  View,
  Text,
  StyleSheet,
  Modal,
  TouchableOpacity,
  ScrollView,
  ActivityIndicator,
} from 'react-native';
import { fetchPlayerHistory, PlayerHistory } from '../../services/api';

interface PlayerCardModalProps {
  visible: boolean;
  playerName: string;
  sport: string;
  onClose: () => void;
}

export function PlayerCardModal({
  visible,
  playerName,
  sport,
  onClose,
}: PlayerCardModalProps) {
  const [loading, setLoading] = useState(true);
  const [history, setHistory] = useState<PlayerHistory | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (visible && playerName) {
      loadPlayerHistory();
    }
  }, [visible, playerName]);

  const loadPlayerHistory = async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await fetchPlayerHistory(playerName, sport);
      setHistory(data);
    } catch (err) {
      setError('Failed to load player history');
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  return (
    <Modal
      visible={visible}
      animationType="slide"
      transparent={true}
      onRequestClose={onClose}
    >
      <View style={styles.overlay}>
        <View style={styles.modal}>
          <View style={styles.header}>
            <Text style={styles.title}>{playerName}</Text>
            <TouchableOpacity onPress={onClose} style={styles.closeButton}>
              <Text style={styles.closeText}>X</Text>
            </TouchableOpacity>
          </View>

          {loading ? (
            <View style={styles.loadingContainer}>
              <ActivityIndicator size="large" color="#4CAF50" />
              <Text style={styles.loadingText}>Loading history...</Text>
            </View>
          ) : error ? (
            <View style={styles.errorContainer}>
              <Text style={styles.errorText}>{error}</Text>
            </View>
          ) : history ? (
            <ScrollView style={styles.content}>
              <View style={styles.statsRow}>
                <View style={styles.statBox}>
                  <Text style={styles.statValue}>
                    {history.overall?.accuracy?.toFixed(1) || 0}%
                  </Text>
                  <Text style={styles.statLabel}>Accuracy</Text>
                </View>
                <View style={styles.statBox}>
                  <Text style={styles.statValue}>
                    {history.overall?.total_predictions || 0}
                  </Text>
                  <Text style={styles.statLabel}>Predictions</Text>
                </View>
                <View style={styles.statBox}>
                  <Text style={styles.statValue}>
                    {history.overall?.hits || 0}
                  </Text>
                  <Text style={styles.statLabel}>Hits</Text>
                </View>
              </View>

              <Text style={styles.sectionTitle}>Recent Predictions</Text>
              {history.predictions?.length > 0 ? (
                history.predictions.slice(0, 10).map((pred, index) => (
                  <View key={index} style={styles.predictionRow}>
                    <View style={styles.predictionInfo}>
                      <Text style={styles.predictionDate}>{pred.date}</Text>
                      <Text style={styles.predictionProp}>
                        {pred.prop_type} {pred.prediction} {pred.line}
                      </Text>
                    </View>
                    <View
                      style={[
                        styles.outcomeBadge,
                        pred.outcome === 'HIT'
                          ? styles.hitBadge
                          : pred.outcome === 'MISS'
                          ? styles.missBadge
                          : styles.pendingBadge,
                      ]}
                    >
                      <Text style={styles.outcomeText}>
                        {pred.outcome || 'PENDING'}
                      </Text>
                    </View>
                  </View>
                ))
              ) : (
                <Text style={styles.noDataText}>
                  {history.message || 'No recent predictions'}
                </Text>
              )}
            </ScrollView>
          ) : (
            <Text style={styles.noDataText}>No data available</Text>
          )}
        </View>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  overlay: {
    flex: 1,
    backgroundColor: 'rgba(0, 0, 0, 0.8)',
    justifyContent: 'center',
    alignItems: 'center',
    padding: 20,
  },
  modal: {
    backgroundColor: '#1E1E1E',
    borderRadius: 16,
    width: '100%',
    maxHeight: '80%',
    overflow: 'hidden',
  },
  header: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    padding: 16,
    borderBottomWidth: 1,
    borderBottomColor: '#333',
  },
  title: {
    color: '#fff',
    fontSize: 20,
    fontWeight: 'bold',
  },
  closeButton: {
    width: 32,
    height: 32,
    borderRadius: 16,
    backgroundColor: '#333',
    justifyContent: 'center',
    alignItems: 'center',
  },
  closeText: {
    color: '#fff',
    fontSize: 16,
    fontWeight: 'bold',
  },
  content: {
    padding: 16,
  },
  loadingContainer: {
    padding: 40,
    alignItems: 'center',
  },
  loadingText: {
    color: '#888',
    marginTop: 12,
  },
  errorContainer: {
    padding: 40,
    alignItems: 'center',
  },
  errorText: {
    color: '#F44336',
  },
  statsRow: {
    flexDirection: 'row',
    justifyContent: 'space-around',
    marginBottom: 24,
  },
  statBox: {
    alignItems: 'center',
  },
  statValue: {
    color: '#4CAF50',
    fontSize: 24,
    fontWeight: 'bold',
  },
  statLabel: {
    color: '#888',
    fontSize: 12,
    marginTop: 4,
  },
  sectionTitle: {
    color: '#fff',
    fontSize: 16,
    fontWeight: 'bold',
    marginBottom: 12,
  },
  predictionRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingVertical: 10,
    borderBottomWidth: 1,
    borderBottomColor: '#333',
  },
  predictionInfo: {
    flex: 1,
  },
  predictionDate: {
    color: '#888',
    fontSize: 12,
  },
  predictionProp: {
    color: '#fff',
    fontSize: 14,
    marginTop: 2,
  },
  outcomeBadge: {
    paddingHorizontal: 10,
    paddingVertical: 4,
    borderRadius: 4,
  },
  hitBadge: {
    backgroundColor: '#4CAF5030',
  },
  missBadge: {
    backgroundColor: '#F4433630',
  },
  pendingBadge: {
    backgroundColor: '#FFA50030',
  },
  outcomeText: {
    color: '#fff',
    fontSize: 12,
    fontWeight: 'bold',
  },
  noDataText: {
    color: '#888',
    textAlign: 'center',
    padding: 20,
  },
});
