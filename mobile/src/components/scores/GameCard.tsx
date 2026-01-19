import React from 'react';
import { View, Text, StyleSheet } from 'react-native';
import { LiveGame } from '../../services/api';
import { LiveIndicator } from './LiveIndicator';
import { Card } from '../common/Card';

interface GameCardProps {
  game: LiveGame;
}

// Helper to extract team name from string or object
const getTeamName = (team: any): string => {
  if (typeof team === 'string') return team;
  if (team?.name) return team.name;
  if (team?.abbreviation) return team.abbreviation;
  return 'Unknown';
};

// Helper to extract score - can be at top level or inside team object
const getScore = (game: any, teamKey: 'home' | 'away'): number => {
  // First check top-level score fields
  const scoreKey = teamKey === 'home' ? 'home_score' : 'away_score';
  if (typeof game[scoreKey] === 'number') return game[scoreKey];
  if (typeof game[scoreKey] === 'string') return parseInt(game[scoreKey], 10) || 0;

  // Then check inside team object
  const teamObjKey = teamKey === 'home' ? 'home_team' : 'away_team';
  const teamObj = game[teamObjKey];
  if (teamObj && typeof teamObj === 'object' && typeof teamObj.score === 'number') {
    return teamObj.score;
  }
  if (teamObj && typeof teamObj === 'object' && typeof teamObj.score === 'string') {
    return parseInt(teamObj.score, 10) || 0;
  }

  return 0;
};

export function GameCard({ game }: GameCardProps) {
  const isLive = game.status === 'in_progress' || game.status === 'live';
  const isFinal = game.status === 'final' || game.status === 'completed' || game.status === 'off';
  const isScheduled = game.status === 'scheduled' || game.status === 'not_started' || game.status === 'fut';

  const awayTeam = getTeamName(game.away_team);
  const homeTeam = getTeamName(game.home_team);
  const awayScore = getScore(game, 'away');
  const homeScore = getScore(game, 'home');

  const getDisplayTime = () => {
    // Prefer pre-formatted local time from API
    if ((game as any).start_time_local) {
      return (game as any).start_time_local;
    }
    // Fallback to parsing start_time
    try {
      const date = new Date(game.start_time);
      return date.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
    } catch {
      return game.start_time || '';
    }
  };

  return (
    <Card>
      <View style={styles.header}>
        {isLive && <LiveIndicator isLive={true} />}
        {isFinal && <Text style={styles.finalBadge}>FINAL</Text>}
        {isScheduled && (
          <Text style={styles.scheduledTime}>{getDisplayTime()}</Text>
        )}
        {game.broadcast && (
          <Text style={styles.broadcast}>{game.broadcast}</Text>
        )}
      </View>

      <View style={styles.teamsContainer}>
        {/* Away Team */}
        <View style={styles.teamRow}>
          <Text style={styles.teamName}>{awayTeam}</Text>
          <Text style={[styles.score, awayScore > homeScore && styles.winning]}>
            {isScheduled ? '-' : awayScore}
          </Text>
        </View>

        {/* Home Team */}
        <View style={styles.teamRow}>
          <Text style={styles.teamName}>{homeTeam}</Text>
          <Text style={[styles.score, homeScore > awayScore && styles.winning]}>
            {isScheduled ? '-' : homeScore}
          </Text>
        </View>
      </View>

      {isLive && (
        <View style={styles.gameInfo}>
          <Text style={styles.period}>{game.period}</Text>
          {game.clock && <Text style={styles.clock}>{game.clock}</Text>}
        </View>
      )}
    </Card>
  );
}

const styles = StyleSheet.create({
  header: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 12,
  },
  finalBadge: {
    color: '#888',
    fontSize: 12,
    fontWeight: 'bold',
  },
  scheduledTime: {
    color: '#4CAF50',
    fontSize: 14,
    fontWeight: '600',
  },
  broadcast: {
    color: '#666',
    fontSize: 10,
  },
  teamsContainer: {
    gap: 8,
  },
  teamRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  teamName: {
    color: '#fff',
    fontSize: 18,
    fontWeight: '500',
  },
  score: {
    color: '#fff',
    fontSize: 24,
    fontWeight: 'bold',
  },
  winning: {
    color: '#4CAF50',
  },
  gameInfo: {
    flexDirection: 'row',
    justifyContent: 'center',
    alignItems: 'center',
    marginTop: 12,
    paddingTop: 12,
    borderTopWidth: 1,
    borderTopColor: '#333',
    gap: 12,
  },
  period: {
    color: '#FFD700',
    fontSize: 14,
    fontWeight: 'bold',
  },
  clock: {
    color: '#FF4444',
    fontSize: 14,
    fontWeight: 'bold',
  },
});
