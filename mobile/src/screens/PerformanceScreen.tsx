import React, { useState } from 'react';
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  RefreshControl,
  ActivityIndicator,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { usePerformance } from '../hooks/usePerformance';
import { SportToggle } from '../components/common/SportToggle';
import { Card } from '../components/common/Card';

export function PerformanceScreen() {
  const [sport, setSport] = useState<'NBA' | 'NHL'>('NBA');
  const { data, loading, error, refetch } = usePerformance(sport.toLowerCase());

  const formatAccuracy = (acc: number) => `${acc.toFixed(1)}%`;

  return (
    <SafeAreaView style={styles.container} edges={['top']}>
      <View style={styles.header}>
        <Text style={styles.title}>Performance</Text>
        <Text style={styles.subtitle}>Track system accuracy over time</Text>
      </View>

      <SportToggle selected={sport} onSelect={setSport} />

      {loading && !data ? (
        <View style={styles.loadingContainer}>
          <ActivityIndicator size="large" color="#4CAF50" />
          <Text style={styles.loadingText}>Loading performance data...</Text>
        </View>
      ) : error ? (
        <View style={styles.errorContainer}>
          <Text style={styles.errorText}>{error}</Text>
          <Text style={styles.errorSubtext}>Pull to refresh</Text>
        </View>
      ) : data ? (
        <ScrollView
          style={styles.scrollView}
          contentContainerStyle={styles.scrollContent}
          showsVerticalScrollIndicator={false}
          refreshControl={
            <RefreshControl
              refreshing={loading}
              onRefresh={refetch}
              tintColor="#4CAF50"
              colors={['#4CAF50']}
            />
          }
        >
          {/* Main Accuracy Card */}
          <Card style={styles.mainCard}>
            <Text style={styles.mainAccuracyLabel}>Overall Accuracy</Text>
            <Text style={styles.mainAccuracy}>
              {formatAccuracy(data.overall.accuracy)}
            </Text>
            <Text style={styles.totalPredictions}>
              {data.overall.total_graded.toLocaleString()} predictions graded
            </Text>
          </Card>

          {/* Over/Under Breakdown */}
          <View style={styles.ouRow}>
            <Card style={styles.ouCard}>
              <Text style={styles.ouLabel}>OVER</Text>
              <Text style={[styles.ouAccuracy, styles.overColor]}>
                {formatAccuracy(data.overall.over_accuracy)}
              </Text>
              <Text style={styles.ouTotal}>
                {data.overall.over_total.toLocaleString()} picks
              </Text>
            </Card>

            <Card style={styles.ouCard}>
              <Text style={styles.ouLabel}>UNDER</Text>
              <Text style={[styles.ouAccuracy, styles.underColor]}>
                {formatAccuracy(data.overall.under_accuracy)}
              </Text>
              <Text style={styles.ouTotal}>
                {data.overall.under_total.toLocaleString()} picks
              </Text>
            </Card>
          </View>

          {/* By Prop Type */}
          <Card>
            <Text style={styles.sectionTitle}>By Prop Type</Text>
            {Object.entries(data.by_prop_type)
              .sort((a, b) => b[1].total - a[1].total)
              .slice(0, 10)
              .map(([prop, stats]) => (
                <View key={prop} style={styles.propRow}>
                  <View style={styles.propInfo}>
                    <Text style={styles.propName}>{prop}</Text>
                    <Text style={styles.propCount}>
                      {stats.total.toLocaleString()} predictions
                    </Text>
                  </View>
                  <View style={styles.propStats}>
                    <Text
                      style={[
                        styles.propAccuracy,
                        stats.accuracy >= 60
                          ? styles.goodAccuracy
                          : stats.accuracy >= 50
                          ? styles.okAccuracy
                          : styles.badAccuracy,
                      ]}
                    >
                      {formatAccuracy(stats.accuracy)}
                    </Text>
                  </View>
                </View>
              ))}
          </Card>

          {/* By Tier (if available) */}
          {Object.keys(data.by_tier).length > 0 && (
            <Card>
              <Text style={styles.sectionTitle}>By Confidence Tier</Text>
              {Object.entries(data.by_tier)
                .sort((a, b) => a[0].localeCompare(b[0]))
                .map(([tier, stats]) => (
                  <View key={tier} style={styles.propRow}>
                    <View style={styles.propInfo}>
                      <Text style={styles.propName}>{tier}</Text>
                      <Text style={styles.propCount}>
                        {stats.total.toLocaleString()} predictions
                      </Text>
                    </View>
                    <View style={styles.propStats}>
                      <Text
                        style={[
                          styles.propAccuracy,
                          stats.accuracy >= 60
                            ? styles.goodAccuracy
                            : stats.accuracy >= 50
                            ? styles.okAccuracy
                            : styles.badAccuracy,
                        ]}
                      >
                        {formatAccuracy(stats.accuracy)}
                      </Text>
                    </View>
                  </View>
                ))}
            </Card>
          )}

          {/* Trending */}
          {data.trending.length > 0 && (
            <Card>
              <Text style={styles.sectionTitle}>Recent Days</Text>
              {data.trending.slice(0, 7).map((day) => (
                <View key={day.date} style={styles.trendRow}>
                  <Text style={styles.trendDate}>{day.date}</Text>
                  <Text style={styles.trendCount}>
                    {day.total} picks
                  </Text>
                  <Text
                    style={[
                      styles.trendAccuracy,
                      day.accuracy >= 60
                        ? styles.goodAccuracy
                        : day.accuracy >= 50
                        ? styles.okAccuracy
                        : styles.badAccuracy,
                    ]}
                  >
                    {formatAccuracy(day.accuracy)}
                  </Text>
                </View>
              ))}
            </Card>
          )}
        </ScrollView>
      ) : null}
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
  scrollView: {
    flex: 1,
  },
  scrollContent: {
    paddingBottom: 32,
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
  mainCard: {
    alignItems: 'center',
    paddingVertical: 24,
  },
  mainAccuracyLabel: {
    color: '#888',
    fontSize: 14,
    marginBottom: 8,
  },
  mainAccuracy: {
    color: '#4CAF50',
    fontSize: 56,
    fontWeight: 'bold',
  },
  totalPredictions: {
    color: '#666',
    fontSize: 12,
    marginTop: 8,
  },
  ouRow: {
    flexDirection: 'row',
    paddingHorizontal: 8,
  },
  ouCard: {
    flex: 1,
    alignItems: 'center',
    marginHorizontal: 8,
  },
  ouLabel: {
    color: '#888',
    fontSize: 12,
    fontWeight: 'bold',
    marginBottom: 8,
  },
  ouAccuracy: {
    fontSize: 28,
    fontWeight: 'bold',
  },
  overColor: {
    color: '#4CAF50',
  },
  underColor: {
    color: '#F44336',
  },
  ouTotal: {
    color: '#666',
    fontSize: 10,
    marginTop: 4,
  },
  sectionTitle: {
    color: '#fff',
    fontSize: 16,
    fontWeight: 'bold',
    marginBottom: 16,
  },
  propRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingVertical: 8,
    borderBottomWidth: 1,
    borderBottomColor: '#2a2a3e',
  },
  propInfo: {
    flex: 1,
  },
  propName: {
    color: '#fff',
    fontSize: 14,
  },
  propCount: {
    color: '#666',
    fontSize: 10,
    marginTop: 2,
  },
  propStats: {
    alignItems: 'flex-end',
  },
  propAccuracy: {
    fontSize: 16,
    fontWeight: 'bold',
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
  trendRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingVertical: 8,
    borderBottomWidth: 1,
    borderBottomColor: '#2a2a3e',
  },
  trendDate: {
    color: '#fff',
    fontSize: 14,
    flex: 1,
  },
  trendCount: {
    color: '#666',
    fontSize: 12,
    marginRight: 16,
  },
  trendAccuracy: {
    fontSize: 16,
    fontWeight: 'bold',
    width: 60,
    textAlign: 'right',
  },
});
