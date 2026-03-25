import React, { useState } from 'react';
import {
  View,
  Text,
  StyleSheet,
  TouchableOpacity,
  ScrollView,
  ActivityIndicator,
  Alert,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import {
  runPredictions,
  refreshLines,
  getSystemStatus,
  clearCache,
} from '../services/api';

interface ActionButtonProps {
  title: string;
  subtitle: string;
  onPress: () => void;
  loading: boolean;
  color?: string;
}

function ActionButton({ title, subtitle, onPress, loading, color = '#4CAF50' }: ActionButtonProps) {
  return (
    <TouchableOpacity
      style={[styles.actionButton, { borderColor: color }]}
      onPress={onPress}
      disabled={loading}
    >
      {loading ? (
        <ActivityIndicator size="small" color={color} />
      ) : (
        <>
          <Text style={[styles.actionTitle, { color }]}>{title}</Text>
          <Text style={styles.actionSubtitle}>{subtitle}</Text>
        </>
      )}
    </TouchableOpacity>
  );
}

export function AdminScreen() {
  const [loading, setLoading] = useState<string | null>(null);
  const [status, setStatus] = useState<any>(null);
  const [lastResult, setLastResult] = useState<string | null>(null);

  const handleRunPredictions = async (sport: string) => {
    setLoading(`predictions-${sport}`);
    setLastResult(null);
    try {
      const result = await runPredictions(sport);
      setLastResult(
        result.success
          ? `${sport.toUpperCase()} predictions generated successfully!`
          : `Failed: ${result.message}`
      );
      if (result.success) {
        Alert.alert('Success', `${sport.toUpperCase()} predictions generated!`);
      } else {
        Alert.alert('Error', result.message || 'Failed to generate predictions');
      }
    } catch (err: any) {
      setLastResult(`Error: ${err.message}`);
      Alert.alert('Error', err.message || 'Failed to run predictions');
    } finally {
      setLoading(null);
    }
  };

  const handleRefreshLines = async () => {
    setLoading('lines');
    setLastResult(null);
    try {
      const result = await refreshLines('all');
      setLastResult(
        result.success
          ? `Fetched ${result.details?.total_lines || 0} lines from PrizePicks`
          : `Failed: ${result.message}`
      );
      if (result.success) {
        Alert.alert('Success', `Fetched ${result.details?.total_lines || 0} lines!`);
      }
    } catch (err: any) {
      setLastResult(`Error: ${err.message}`);
      Alert.alert('Error', err.message || 'Failed to refresh lines');
    } finally {
      setLoading(null);
    }
  };

  const handleClearCache = async () => {
    setLoading('cache');
    try {
      const result = await clearCache();
      Alert.alert('Success', result.message || 'Cache cleared');
    } catch (err: any) {
      Alert.alert('Error', err.message || 'Failed to clear cache');
    } finally {
      setLoading(null);
    }
  };

  const handleCheckStatus = async () => {
    setLoading('status');
    try {
      const result = await getSystemStatus();
      setStatus(result);
    } catch (err: any) {
      Alert.alert('Error', err.message || 'Failed to get status');
    } finally {
      setLoading(null);
    }
  };

  return (
    <SafeAreaView style={styles.container} edges={['top']}>
      <ScrollView contentContainerStyle={styles.content}>
        <Text style={styles.title}>Admin</Text>
        <Text style={styles.subtitle}>Run predictions and manage the system</Text>

        {/* Generate Predictions */}
        <View style={styles.section}>
          <Text style={styles.sectionTitle}>Generate Predictions</Text>
          <Text style={styles.sectionDesc}>
            Run the prediction pipeline for today's games. This fetches schedules,
            generates predictions, and saves them to the database.
          </Text>
          <View style={styles.buttonRow}>
            <ActionButton
              title="NBA"
              subtitle="Generate NBA picks"
              onPress={() => handleRunPredictions('nba')}
              loading={loading === 'predictions-nba'}
              color="#1976D2"
            />
            <ActionButton
              title="NHL"
              subtitle="Generate NHL picks"
              onPress={() => handleRunPredictions('nhl')}
              loading={loading === 'predictions-nhl'}
              color="#4CAF50"
            />
          </View>
        </View>

        {/* Refresh Lines */}
        <View style={styles.section}>
          <Text style={styles.sectionTitle}>Refresh PrizePicks Lines</Text>
          <Text style={styles.sectionDesc}>
            Fetch the latest lines from PrizePicks. Do this before generating
            predictions to ensure you have current data.
          </Text>
          <ActionButton
            title="Refresh Lines"
            subtitle="Fetch NBA + NHL lines from PrizePicks"
            onPress={handleRefreshLines}
            loading={loading === 'lines'}
            color="#FF9800"
          />
        </View>

        {/* System Status */}
        <View style={styles.section}>
          <Text style={styles.sectionTitle}>System Status</Text>
          <View style={styles.buttonRow}>
            <ActionButton
              title="Check Status"
              subtitle="View database stats"
              onPress={handleCheckStatus}
              loading={loading === 'status'}
              color="#9C27B0"
            />
            <ActionButton
              title="Clear Cache"
              subtitle="Force fresh data"
              onPress={handleClearCache}
              loading={loading === 'cache'}
              color="#607D8B"
            />
          </View>
        </View>

        {/* Status Display */}
        {status && (
          <View style={styles.statusBox}>
            <Text style={styles.statusTitle}>System Status</Text>
            <Text style={styles.statusText}>API: {status.api || 'online'}</Text>
            {status.predictions && (
              <>
                <Text style={styles.statusLabel}>NBA:</Text>
                <Text style={styles.statusText}>
                  {status.predictions.nba?.total || 0} predictions,{' '}
                  {status.predictions.nba?.graded || 0} graded
                </Text>
                <Text style={styles.statusLabel}>NHL:</Text>
                <Text style={styles.statusText}>
                  {status.predictions.nhl?.total || 0} predictions,{' '}
                  {status.predictions.nhl?.graded || 0} graded
                </Text>
              </>
            )}
          </View>
        )}

        {/* Last Result */}
        {lastResult && (
          <View style={styles.resultBox}>
            <Text style={styles.resultText}>{lastResult}</Text>
          </View>
        )}

        {/* Workflow Guide */}
        <View style={styles.section}>
          <Text style={styles.sectionTitle}>Daily Workflow</Text>
          <View style={styles.workflowStep}>
            <Text style={styles.stepNumber}>1</Text>
            <Text style={styles.stepText}>Refresh Lines (fetches current PrizePicks data)</Text>
          </View>
          <View style={styles.workflowStep}>
            <Text style={styles.stepNumber}>2</Text>
            <Text style={styles.stepText}>Generate NBA/NHL predictions</Text>
          </View>
          <View style={styles.workflowStep}>
            <Text style={styles.stepNumber}>3</Text>
            <Text style={styles.stepText}>Go to Picks tab to view smart picks</Text>
          </View>
        </View>
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#121212',
  },
  content: {
    padding: 16,
    paddingBottom: 40,
  },
  title: {
    color: '#fff',
    fontSize: 28,
    fontWeight: 'bold',
  },
  subtitle: {
    color: '#888',
    fontSize: 14,
    marginBottom: 24,
  },
  section: {
    marginBottom: 24,
  },
  sectionTitle: {
    color: '#fff',
    fontSize: 18,
    fontWeight: 'bold',
    marginBottom: 8,
  },
  sectionDesc: {
    color: '#888',
    fontSize: 13,
    marginBottom: 12,
    lineHeight: 18,
  },
  buttonRow: {
    flexDirection: 'row',
    gap: 12,
  },
  actionButton: {
    flex: 1,
    backgroundColor: '#1E1E1E',
    borderWidth: 2,
    borderRadius: 12,
    padding: 16,
    alignItems: 'center',
    justifyContent: 'center',
    minHeight: 80,
  },
  actionTitle: {
    fontSize: 18,
    fontWeight: 'bold',
    marginBottom: 4,
  },
  actionSubtitle: {
    color: '#888',
    fontSize: 11,
    textAlign: 'center',
  },
  statusBox: {
    backgroundColor: '#1E1E1E',
    borderRadius: 12,
    padding: 16,
    marginBottom: 16,
  },
  statusTitle: {
    color: '#fff',
    fontSize: 16,
    fontWeight: 'bold',
    marginBottom: 12,
  },
  statusLabel: {
    color: '#4CAF50',
    fontSize: 12,
    fontWeight: 'bold',
    marginTop: 8,
  },
  statusText: {
    color: '#888',
    fontSize: 13,
  },
  resultBox: {
    backgroundColor: '#1E1E1E',
    borderRadius: 12,
    padding: 16,
    marginBottom: 16,
    borderLeftWidth: 4,
    borderLeftColor: '#4CAF50',
  },
  resultText: {
    color: '#fff',
    fontSize: 14,
  },
  workflowStep: {
    flexDirection: 'row',
    alignItems: 'center',
    marginBottom: 12,
  },
  stepNumber: {
    width: 28,
    height: 28,
    borderRadius: 14,
    backgroundColor: '#4CAF50',
    color: '#fff',
    fontSize: 14,
    fontWeight: 'bold',
    textAlign: 'center',
    lineHeight: 28,
    marginRight: 12,
  },
  stepText: {
    color: '#888',
    fontSize: 13,
    flex: 1,
  },
});
