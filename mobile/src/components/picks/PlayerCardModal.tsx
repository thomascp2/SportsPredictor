import React, { useEffect, useState, useMemo } from 'react';
import {
  View,
  Text,
  StyleSheet,
  Modal,
  TouchableOpacity,
  ScrollView,
  ActivityIndicator,
  Dimensions,
} from 'react-native';
import { LineChart } from 'react-native-chart-kit';
import { fetchPlayerHistory, PlayerHistory, SmartPick, ModelSignals } from '../../services/api';
import { TIER_COLORS } from '../../utils/constants';

const screenWidth = Dimensions.get('window').width;

interface PlayerCardModalProps {
  visible: boolean;
  playerName: string;
  sport: string;
  propType?: string;
  todayPicks?: SmartPick[];
  onClose: () => void;
  onAddToParlay?: (pick: SmartPick) => void;
  isPickInParlay?: (pick: SmartPick) => boolean;
}

export function PlayerCardModal({
  visible,
  playerName,
  sport,
  propType,
  todayPicks = [],
  onClose,
  onAddToParlay,
  isPickInParlay,
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

  // Filter predictions by prop type if specified
  const filteredPredictions = useMemo(() => {
    if (!history?.predictions) return [];
    if (!propType) return history.predictions;
    return history.predictions.filter(
      (p) => p.prop_type?.toLowerCase() === propType.toLowerCase()
    );
  }, [history, propType]);

  // Get stats for the specific prop type
  const propStats = useMemo(() => {
    if (!history?.by_prop_type || !propType) return null;
    const key = Object.keys(history.by_prop_type).find(
      (k) => k.toLowerCase() === propType.toLowerCase()
    );
    return key ? history.by_prop_type[key] : null;
  }, [history, propType]);

  // Filter today's picks for this player (excluding current prop type to avoid duplicate)
  const otherTodayPicks = useMemo(() => {
    return todayPicks.filter(
      (p) => p.prop_type?.toLowerCase() !== propType?.toLowerCase()
    );
  }, [todayPicks, propType]);

  // Get the current pick for this prop type (to show PP line on chart)
  const currentPick = useMemo(() => {
    return todayPicks.find(
      (p) => p.prop_type?.toLowerCase() === propType?.toLowerCase()
    );
  }, [todayPicks, propType]);

  // Prepare chart data from filtered predictions
  const chartData = useMemo(() => {
    // Get predictions with actual values, reverse to show oldest first
    const withActual = filteredPredictions
      .filter((p) => p.actual_value !== undefined && p.actual_value !== null)
      .slice(0, 8)
      .reverse();

    if (withActual.length < 2) return null;

    const labels = withActual.map((p) => {
      // Format date as MM/DD
      const parts = p.date?.split('-');
      if (parts && parts.length >= 3) {
        return `${parts[1]}/${parts[2]}`;
      }
      return '';
    });

    const values = withActual.map((p) => p.actual_value || 0);
    const ppLine = currentPick?.pp_line;

    return {
      labels,
      datasets: [
        {
          data: values,
          color: (opacity = 1) => `rgba(76, 175, 80, ${opacity})`,
          strokeWidth: 2,
        },
        // Reference line for PP line (if available)
        ...(ppLine
          ? [
              {
                data: Array(values.length).fill(ppLine),
                color: (opacity = 1) => `rgba(255, 193, 7, ${opacity})`,
                strokeWidth: 1,
                withDots: false,
              },
            ]
          : []),
      ],
      ppLine,
    };
  }, [filteredPredictions, currentPick]);

  const formatPropType = (type: string) => {
    return type.charAt(0).toUpperCase() + type.slice(1).toLowerCase();
  };

  const getTierColor = (tier: string) => {
    return TIER_COLORS[tier] || '#888';
  };

  // Merge model signals from two sources: history (per prop_type) and currentPick (ML averages)
  const modelSignals: ModelSignals | null = useMemo(() => {
    const fromHistory = propType && history?.model_signals
      ? history.model_signals[propType] ?? history.model_signals[propType.toLowerCase()] ?? null
      : null;

    const fromPick: Partial<ModelSignals> = currentPick
      ? {
          season_avg: currentPick.season_avg,
          l10_avg: currentPick.recent_avg,
        }
      : {};

    if (!fromHistory && !currentPick) return null;
    return { ...fromPick, ...fromHistory };
  }, [history, currentPick, propType]);

  const formatRate = (rate?: number) => {
    if (rate == null) return '-';
    // Stored as 0-1 fraction
    return `${(rate * 100).toFixed(0)}%`;
  };

  const formatAvg = (avg?: number) => {
    if (avg == null || avg === 0) return '-';
    return avg % 1 === 0 ? avg.toFixed(0) : avg.toFixed(1);
  };

  const formatStreak = (streak?: number) => {
    if (streak == null || streak === 0) return '-';
    return streak > 0 ? `+${streak} OVER` : `${streak} UNDER`;
  };

  const getStreakColor = (streak?: number) => {
    if (!streak) return '#888';
    return streak > 0 ? '#4CAF50' : '#F44336';
  };

  const formatTrend = (slope?: number) => {
    if (slope == null) return '-';
    if (slope > 0.5) return 'Rising';
    if (slope < -0.5) return 'Falling';
    return 'Flat';
  };

  const getTrendColor = (slope?: number) => {
    if (slope == null) return '#888';
    if (slope > 0.5) return '#4CAF50';
    if (slope < -0.5) return '#F44336';
    return '#FFC107';
  };

  const formatMatchup = (rating?: number, ppLine?: number) => {
    if (rating == null || ppLine == null) return '-';
    // rating = avg stat the opponent allows; compare to the PP line as rough proxy
    const diff = rating - ppLine;
    if (diff > 2) return 'Weak DEF';
    if (diff < -2) return 'Strong DEF';
    return 'Avg DEF';
  };

  const getMatchupColor = (rating?: number, ppLine?: number) => {
    if (rating == null || ppLine == null) return '#888';
    const diff = rating - ppLine;
    if (diff > 2) return '#4CAF50';   // Weak defense = good for OVER
    if (diff < -2) return '#F44336';  // Strong defense = bad for OVER
    return '#FFC107';
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
            <View style={styles.headerLeft}>
              <Text style={styles.title}>{playerName}</Text>
              {propType && (
                <View style={styles.propBadge}>
                  <Text style={styles.propBadgeText}>
                    {formatPropType(propType)}
                  </Text>
                </View>
              )}
            </View>
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
          ) : (
            <ScrollView style={styles.content}>
              {/* Stats for specific prop type */}
              {propStats ? (
                <View style={styles.statsRow}>
                  <View style={styles.statBox}>
                    <Text style={styles.statValue}>
                      {propStats.accuracy?.toFixed(1) || 0}%
                    </Text>
                    <Text style={styles.statLabel}>
                      {formatPropType(propType || '')} Accuracy
                    </Text>
                  </View>
                  <View style={styles.statBox}>
                    <Text style={styles.statValue}>{propStats.total || 0}</Text>
                    <Text style={styles.statLabel}>Predictions</Text>
                  </View>
                  <View style={styles.statBox}>
                    <Text style={styles.statValue}>{propStats.hits || 0}</Text>
                    <Text style={styles.statLabel}>Hits</Text>
                  </View>
                </View>
              ) : history?.overall ? (
                <View style={styles.statsRow}>
                  <View style={styles.statBox}>
                    <Text style={styles.statValue}>
                      {history.overall.accuracy?.toFixed(1) || 0}%
                    </Text>
                    <Text style={styles.statLabel}>Overall Accuracy</Text>
                  </View>
                  <View style={styles.statBox}>
                    <Text style={styles.statValue}>
                      {history.overall.total_predictions || 0}
                    </Text>
                    <Text style={styles.statLabel}>Predictions</Text>
                  </View>
                  <View style={styles.statBox}>
                    <Text style={styles.statValue}>
                      {history.overall.hits || 0}
                    </Text>
                    <Text style={styles.statLabel}>Hits</Text>
                  </View>
                </View>
              ) : null}

              {/* Performance Chart */}
              {chartData && propType && (
                <View style={styles.chartContainer}>
                  <View style={styles.chartHeader}>
                    <Text style={styles.chartTitle}>
                      Recent {formatPropType(propType)} Performance
                    </Text>
                    {chartData.ppLine && (
                      <View style={styles.chartLegend}>
                        <View style={styles.legendItem}>
                          <View style={[styles.legendDot, { backgroundColor: '#4CAF50' }]} />
                          <Text style={styles.legendText}>Actual</Text>
                        </View>
                        <View style={styles.legendItem}>
                          <View style={[styles.legendDot, { backgroundColor: '#FFC107' }]} />
                          <Text style={styles.legendText}>Line ({chartData.ppLine})</Text>
                        </View>
                      </View>
                    )}
                  </View>
                  <LineChart
                    data={{
                      labels: chartData.labels,
                      datasets: chartData.datasets,
                    }}
                    width={screenWidth - 72}
                    height={160}
                    chartConfig={{
                      backgroundColor: '#252525',
                      backgroundGradientFrom: '#252525',
                      backgroundGradientTo: '#252525',
                      decimalPlaces: 0,
                      color: (opacity = 1) => `rgba(255, 255, 255, ${opacity})`,
                      labelColor: (opacity = 1) => `rgba(136, 136, 136, ${opacity})`,
                      style: {
                        borderRadius: 8,
                      },
                      propsForDots: {
                        r: '4',
                        strokeWidth: '2',
                        stroke: '#4CAF50',
                      },
                      propsForBackgroundLines: {
                        strokeDasharray: '',
                        stroke: '#333',
                      },
                    }}
                    bezier
                    style={styles.chart}
                    withInnerLines={true}
                    withOuterLines={false}
                    withVerticalLines={false}
                    withHorizontalLines={true}
                    fromZero={false}
                    segments={4}
                    formatYLabel={(value) => Math.round(parseFloat(value)).toString()}
                  />
                </View>
              )}

              {/* Model Signals Section */}
              {modelSignals && propType && (
                <View style={styles.signalsContainer}>
                  <Text style={styles.sectionTitle}>Model Signals</Text>

                  {/* Row 1: Hit rates */}
                  <View style={styles.signalRow}>
                    <View style={styles.signalTile}>
                      <Text style={styles.signalValue}>{formatRate(modelSignals.l5_success_rate)}</Text>
                      <Text style={styles.signalLabel}>L5 Hit Rate</Text>
                    </View>
                    <View style={styles.signalTile}>
                      <Text style={styles.signalValue}>{formatRate(modelSignals.l10_success_rate)}</Text>
                      <Text style={styles.signalLabel}>L10 Hit Rate</Text>
                    </View>
                    <View style={styles.signalTile}>
                      <Text style={styles.signalValue}>{formatRate(modelSignals.season_success_rate)}</Text>
                      <Text style={styles.signalLabel}>Season Rate</Text>
                    </View>
                  </View>

                  {/* Row 2: Averages */}
                  <View style={styles.signalRow}>
                    <View style={styles.signalTile}>
                      <Text style={styles.signalValue}>{formatAvg(modelSignals.l5_avg)}</Text>
                      <Text style={styles.signalLabel}>L5 Avg</Text>
                    </View>
                    <View style={styles.signalTile}>
                      <Text style={styles.signalValue}>{formatAvg(modelSignals.l10_avg)}</Text>
                      <Text style={styles.signalLabel}>L10 Avg</Text>
                    </View>
                    <View style={styles.signalTile}>
                      <Text style={styles.signalValue}>{formatAvg(modelSignals.season_avg)}</Text>
                      <Text style={styles.signalLabel}>Season Avg</Text>
                    </View>
                  </View>

                  {/* Row 3: Streak, Trend, Matchup */}
                  <View style={styles.signalRow}>
                    <View style={styles.signalTile}>
                      <Text style={[styles.signalValue, { color: getStreakColor(modelSignals.current_streak) }]}>
                        {formatStreak(modelSignals.current_streak)}
                      </Text>
                      <Text style={styles.signalLabel}>Streak</Text>
                    </View>
                    <View style={styles.signalTile}>
                      <Text style={[styles.signalValue, { color: getTrendColor(modelSignals.trend_slope) }]}>
                        {formatTrend(modelSignals.trend_slope)}
                      </Text>
                      <Text style={styles.signalLabel}>Trend</Text>
                    </View>
                    <View style={styles.signalTile}>
                      <Text style={[styles.signalValue, { color: getMatchupColor(modelSignals.opp_defensive_rating, currentPick?.pp_line) }]}>
                        {formatMatchup(modelSignals.opp_defensive_rating, currentPick?.pp_line)}
                      </Text>
                      <Text style={styles.signalLabel}>Matchup</Text>
                    </View>
                  </View>

                  {/* ML Adjustment badge (only if non-trivial) */}
                  {currentPick?.ml_adjustment != null && Math.abs(currentPick.ml_adjustment) >= 1 && (
                    <View style={[
                      styles.mlAdjBadge,
                      { backgroundColor: currentPick.ml_adjustment > 0 ? '#4CAF5020' : '#F4433620' },
                    ]}>
                      <Text style={[
                        styles.mlAdjText,
                        { color: currentPick.ml_adjustment > 0 ? '#4CAF50' : '#F44336' },
                      ]}>
                        ML model {currentPick.ml_adjustment > 0 ? '+' : ''}{currentPick.ml_adjustment.toFixed(1)}% vs naive baseline
                      </Text>
                    </View>
                  )}

                  {/* Rest / fatigue badge */}
                  {currentPick?.days_rest != null && (
                    <View style={[
                      styles.mlAdjBadge,
                      {
                        backgroundColor: currentPick.days_rest === 0 ? '#F4433620'
                          : currentPick.days_rest >= 3 ? '#4CAF5020' : '#FF980020',
                      },
                    ]}>
                      <Text style={[
                        styles.mlAdjText,
                        {
                          color: currentPick.days_rest === 0 ? '#F44336'
                            : currentPick.days_rest >= 3 ? '#4CAF50' : '#FF9800',
                        },
                      ]}>
                        {currentPick.days_rest === 0
                          ? 'Back-to-back — fatigue risk'
                          : currentPick.days_rest === 1
                          ? '1 day rest'
                          : `${currentPick.days_rest}+ days rest`}
                      </Text>
                    </View>
                  )}

                  {/* Line movement badge (only if movement detected) */}
                  {currentPick?.line_movement != null && Math.abs(currentPick.line_movement) >= 0.5 && (
                    <View style={[
                      styles.mlAdjBadge,
                      {
                        backgroundColor: currentPick.movement_agrees ? '#4CAF5020' : '#FF980020',
                      },
                    ]}>
                      <Text style={[
                        styles.mlAdjText,
                        { color: currentPick.movement_agrees ? '#4CAF50' : '#FF9800' },
                      ]}>
                        Line {currentPick.line_movement > 0 ? 'moved up' : 'moved down'} {Math.abs(currentPick.line_movement).toFixed(1)}
                        {currentPick.movement_agrees ? ' — market agrees' : ' — fading market'}
                      </Text>
                    </View>
                  )}
                </View>
              )}

              {/* Section 1: Recent predictions for this prop type */}
              <Text style={styles.sectionTitle}>
                {propType
                  ? `Recent ${formatPropType(propType)} Predictions`
                  : 'Recent Predictions'}
              </Text>
              {filteredPredictions.length > 0 ? (
                <View style={styles.predictionsTable}>
                  {/* Header */}
                  <View style={styles.predictionHeader}>
                    <Text style={styles.predictionHeaderText}>Date</Text>
                    <Text style={styles.predictionHeaderText}>Line</Text>
                    <Text style={styles.predictionHeaderText}>Actual</Text>
                    <Text style={styles.predictionHeaderText}>Result</Text>
                  </View>
                  {/* Rows */}
                  {filteredPredictions.slice(0, 8).map((pred, index) => (
                    <View key={index} style={styles.predictionTableRow}>
                      <Text style={styles.predictionCell}>
                        {pred.date?.slice(5) || '-'}
                      </Text>
                      <Text style={styles.predictionCell}>
                        {pred.prediction?.charAt(0)}{pred.line}
                      </Text>
                      <Text style={styles.predictionCellValue}>
                        {pred.actual_value ?? '-'}
                      </Text>
                      <View
                        style={[
                          styles.outcomeChip,
                          pred.outcome === 'HIT'
                            ? styles.hitChip
                            : pred.outcome === 'MISS'
                            ? styles.missChip
                            : styles.pendingChip,
                        ]}
                      >
                        <Text style={styles.outcomeChipText}>
                          {pred.outcome || '-'}
                        </Text>
                      </View>
                    </View>
                  ))}
                </View>
              ) : (
                <Text style={styles.noDataText}>
                  {propType
                    ? `No ${formatPropType(propType)} predictions found`
                    : 'No recent predictions'}
                </Text>
              )}

              {/* Section 2: Today's other plays for this player */}
              {otherTodayPicks.length > 0 && (
                <>
                  <View style={[styles.sectionHeader, { marginTop: 24 }]}>
                    <Text style={styles.sectionTitle}>Other Plays Today</Text>
                    <Text style={styles.tapHint}>Tap to add to parlay</Text>
                  </View>
                  {otherTodayPicks.map((pick, index) => (
                    <TouchableOpacity
                      key={index}
                      style={styles.todayPickRow}
                      onPress={() => onAddToParlay?.(pick)}
                      activeOpacity={0.7}
                    >
                      <View style={styles.todayPickInfo}>
                        <View style={styles.todayPickHeader}>
                          <Text style={styles.todayPickProp}>
                            {formatPropType(pick.prop_type)}
                          </Text>
                          <View
                            style={[
                              styles.tierBadge,
                              { backgroundColor: getTierColor(pick.tier) + '30' },
                            ]}
                          >
                            <Text
                              style={[
                                styles.tierText,
                                { color: getTierColor(pick.tier) },
                              ]}
                            >
                              {pick.tier}
                            </Text>
                          </View>
                        </View>
                        <Text style={styles.todayPickLine}>
                          {pick.prediction} {pick.pp_line}
                        </Text>
                      </View>
                      <View style={styles.todayPickRight}>
                        <Text style={styles.todayPickEdge}>
                          {pick.edge >= 0 ? '+' : ''}{pick.edge.toFixed(1)}%
                        </Text>
                        <Text style={styles.todayPickProb}>
                          {Math.round(pick.pp_probability > 1 ? pick.pp_probability : pick.pp_probability * 100)}%
                        </Text>
                        {isPickInParlay?.(pick) && (
                          <View style={styles.inParlayBadge}>
                            <Text style={styles.inParlayText}>IN PARLAY</Text>
                          </View>
                        )}
                      </View>
                    </TouchableOpacity>
                  ))}
                </>
              )}

              {/* Show all today's picks if no prop type specified */}
              {!propType && todayPicks.length > 0 && (
                <>
                  <Text style={[styles.sectionTitle, styles.sectionTitleMargin]}>
                    Today's Plays
                  </Text>
                  {todayPicks.map((pick, index) => (
                    <TouchableOpacity
                      key={index}
                      style={styles.todayPickRow}
                      onPress={() => onAddToParlay?.(pick)}
                      activeOpacity={0.7}
                    >
                      <View style={styles.todayPickInfo}>
                        <View style={styles.todayPickHeader}>
                          <Text style={styles.todayPickProp}>
                            {formatPropType(pick.prop_type)}
                          </Text>
                          <View
                            style={[
                              styles.tierBadge,
                              { backgroundColor: getTierColor(pick.tier) + '30' },
                            ]}
                          >
                            <Text
                              style={[
                                styles.tierText,
                                { color: getTierColor(pick.tier) },
                              ]}
                            >
                              {pick.tier}
                            </Text>
                          </View>
                        </View>
                        <Text style={styles.todayPickLine}>
                          {pick.prediction} {pick.pp_line}
                        </Text>
                      </View>
                      <View style={styles.todayPickRight}>
                        <Text style={styles.todayPickEdge}>
                          {pick.edge >= 0 ? '+' : ''}{pick.edge.toFixed(1)}%
                        </Text>
                        <Text style={styles.todayPickProb}>
                          {Math.round(pick.pp_probability > 1 ? pick.pp_probability : pick.pp_probability * 100)}%
                        </Text>
                        {isPickInParlay?.(pick) && (
                          <View style={styles.inParlayBadge}>
                            <Text style={styles.inParlayText}>IN PARLAY</Text>
                          </View>
                        )}
                      </View>
                    </TouchableOpacity>
                  ))}
                </>
              )}
            </ScrollView>
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
    maxHeight: '85%',
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
  headerLeft: {
    flexDirection: 'row',
    alignItems: 'center',
    flex: 1,
  },
  title: {
    color: '#fff',
    fontSize: 20,
    fontWeight: 'bold',
  },
  propBadge: {
    backgroundColor: '#1976D2',
    paddingHorizontal: 10,
    paddingVertical: 4,
    borderRadius: 12,
    marginLeft: 10,
  },
  propBadgeText: {
    color: '#fff',
    fontSize: 12,
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
    marginBottom: 16,
    backgroundColor: '#252525',
    padding: 16,
    borderRadius: 12,
  },
  chartContainer: {
    marginBottom: 20,
    backgroundColor: '#252525',
    borderRadius: 12,
    padding: 12,
  },
  chartHeader: {
    marginBottom: 8,
  },
  chartTitle: {
    color: '#fff',
    fontSize: 14,
    fontWeight: 'bold',
  },
  chartLegend: {
    flexDirection: 'row',
    marginTop: 6,
    gap: 16,
  },
  legendItem: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  legendDot: {
    width: 8,
    height: 8,
    borderRadius: 4,
    marginRight: 4,
  },
  legendText: {
    color: '#888',
    fontSize: 10,
  },
  chart: {
    borderRadius: 8,
    marginLeft: -8,
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
    fontSize: 11,
    marginTop: 4,
    textAlign: 'center',
  },
  sectionTitle: {
    color: '#fff',
    fontSize: 16,
    fontWeight: 'bold',
    marginBottom: 12,
  },
  sectionTitleMargin: {
    marginTop: 24,
  },
  sectionHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'flex-end',
    marginBottom: 12,
  },
  tapHint: {
    color: '#4CAF50',
    fontSize: 11,
    fontStyle: 'italic',
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
  predictionsTable: {
    backgroundColor: '#252525',
    borderRadius: 8,
    overflow: 'hidden',
  },
  predictionHeader: {
    flexDirection: 'row',
    backgroundColor: '#333',
    paddingVertical: 8,
    paddingHorizontal: 12,
  },
  predictionHeaderText: {
    color: '#888',
    fontSize: 11,
    fontWeight: 'bold',
    flex: 1,
    textAlign: 'center',
  },
  predictionTableRow: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingVertical: 10,
    paddingHorizontal: 12,
    borderBottomWidth: 1,
    borderBottomColor: '#333',
  },
  predictionCell: {
    color: '#aaa',
    fontSize: 12,
    flex: 1,
    textAlign: 'center',
  },
  predictionCellValue: {
    color: '#fff',
    fontSize: 13,
    fontWeight: 'bold',
    flex: 1,
    textAlign: 'center',
  },
  outcomeChip: {
    flex: 1,
    alignItems: 'center',
    paddingVertical: 3,
    paddingHorizontal: 6,
    borderRadius: 4,
    marginLeft: 4,
  },
  hitChip: {
    backgroundColor: '#4CAF5030',
  },
  missChip: {
    backgroundColor: '#F4433630',
  },
  pendingChip: {
    backgroundColor: '#FFA50030',
  },
  outcomeChipText: {
    color: '#fff',
    fontSize: 10,
    fontWeight: 'bold',
  },
  todayPickRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingVertical: 12,
    paddingHorizontal: 12,
    backgroundColor: '#252525',
    borderRadius: 8,
    marginBottom: 8,
  },
  todayPickInfo: {
    flex: 1,
  },
  todayPickHeader: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  todayPickProp: {
    color: '#fff',
    fontSize: 14,
    fontWeight: 'bold',
  },
  tierBadge: {
    paddingHorizontal: 6,
    paddingVertical: 2,
    borderRadius: 4,
    marginLeft: 8,
  },
  tierText: {
    fontSize: 10,
    fontWeight: 'bold',
  },
  todayPickLine: {
    color: '#aaa',
    fontSize: 13,
    marginTop: 4,
  },
  todayPickRight: {
    alignItems: 'flex-end',
  },
  todayPickEdge: {
    color: '#4CAF50',
    fontSize: 16,
    fontWeight: 'bold',
  },
  todayPickProb: {
    color: '#888',
    fontSize: 11,
    marginTop: 2,
  },
  inParlayBadge: {
    backgroundColor: '#4CAF5030',
    paddingHorizontal: 6,
    paddingVertical: 2,
    borderRadius: 4,
    marginTop: 4,
  },
  inParlayText: {
    color: '#4CAF50',
    fontSize: 9,
    fontWeight: 'bold',
  },
  signalsContainer: {
    backgroundColor: '#252525',
    borderRadius: 12,
    padding: 12,
    marginBottom: 20,
  },
  signalRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    marginBottom: 8,
  },
  signalTile: {
    flex: 1,
    alignItems: 'center',
    backgroundColor: '#1E1E1E',
    borderRadius: 8,
    paddingVertical: 8,
    marginHorizontal: 3,
  },
  signalValue: {
    color: '#fff',
    fontSize: 14,
    fontWeight: 'bold',
  },
  signalLabel: {
    color: '#666',
    fontSize: 10,
    marginTop: 3,
    textAlign: 'center',
  },
  mlAdjBadge: {
    borderRadius: 6,
    paddingVertical: 6,
    paddingHorizontal: 10,
    marginTop: 4,
    alignItems: 'center',
  },
  mlAdjText: {
    fontSize: 11,
    fontWeight: 'bold',
  },
});
