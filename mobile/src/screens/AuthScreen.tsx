import React from 'react';
import {
  View,
  Text,
  StyleSheet,
  Pressable,
  ActivityIndicator,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useAuthStore } from '../store/authStore';

export function AuthScreen() {
  const { signInWithGoogle, signInWithApple, signInWithDiscord, loading } = useAuthStore();

  return (
    <SafeAreaView style={styles.container}>
      <View style={styles.content}>
        {/* Branding */}
        <View style={styles.branding}>
          <Text style={styles.logo}>FreePicks</Text>
          <Text style={styles.tagline}>AI-Powered Prop Predictions</Text>
          <Text style={styles.subtitle}>
            Pick OVER or UNDER on today's player props.{'\n'}
            Earn points. Beat the AI. Track your bets.
          </Text>
        </View>

        {/* Stats showcase */}
        <View style={styles.statsRow}>
          <View style={styles.statBox}>
            <Text style={styles.statValue}>80%</Text>
            <Text style={styles.statLabel}>NBA Accuracy</Text>
          </View>
          <View style={styles.statBox}>
            <Text style={styles.statValue}>117k+</Text>
            <Text style={styles.statLabel}>Predictions</Text>
          </View>
          <View style={styles.statBox}>
            <Text style={styles.statValue}>Free</Text>
            <Text style={styles.statLabel}>To Play</Text>
          </View>
        </View>

        {/* Auth buttons */}
        <View style={styles.authButtons}>
          {loading ? (
            <ActivityIndicator size="large" color="#4CAF50" />
          ) : (
            <>
              <Pressable
                style={[styles.authButton, styles.googleButton]}
                onPress={signInWithGoogle}
              >
                <Text style={styles.authButtonIcon}>G</Text>
                <Text style={styles.authButtonText}>Continue with Google</Text>
              </Pressable>

              <Pressable
                style={[styles.authButton, styles.appleButton]}
                onPress={signInWithApple}
              >
                <Text style={styles.authButtonIcon}>A</Text>
                <Text style={styles.authButtonText}>Continue with Apple</Text>
              </Pressable>

              <Pressable
                style={[styles.authButton, styles.discordButton]}
                onPress={signInWithDiscord}
              >
                <Text style={styles.authButtonIcon}>D</Text>
                <Text style={styles.authButtonText}>Continue with Discord</Text>
              </Pressable>
            </>
          )}
        </View>

        {/* Footer */}
        <Text style={styles.disclaimer}>
          No real money wagered. Points have no cash value.{'\n'}
          By signing in you agree to our Terms of Service.
        </Text>
      </View>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#121212',
  },
  content: {
    flex: 1,
    justifyContent: 'center',
    paddingHorizontal: 32,
  },
  branding: {
    alignItems: 'center',
    marginBottom: 40,
  },
  logo: {
    color: '#4CAF50',
    fontSize: 42,
    fontWeight: '900',
    letterSpacing: -1,
  },
  tagline: {
    color: '#888',
    fontSize: 14,
    marginTop: 4,
    letterSpacing: 1,
  },
  subtitle: {
    color: '#666',
    fontSize: 14,
    textAlign: 'center',
    marginTop: 16,
    lineHeight: 22,
  },
  statsRow: {
    flexDirection: 'row',
    justifyContent: 'space-around',
    marginBottom: 40,
    paddingVertical: 16,
    backgroundColor: '#1e1e2e',
    borderRadius: 12,
  },
  statBox: {
    alignItems: 'center',
  },
  statValue: {
    color: '#fff',
    fontSize: 22,
    fontWeight: '800',
  },
  statLabel: {
    color: '#888',
    fontSize: 11,
    marginTop: 2,
  },
  authButtons: {
    gap: 12,
    marginBottom: 32,
  },
  authButton: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    paddingVertical: 14,
    borderRadius: 12,
    gap: 10,
  },
  googleButton: {
    backgroundColor: '#fff',
  },
  appleButton: {
    backgroundColor: '#000',
    borderWidth: 1,
    borderColor: '#333',
  },
  discordButton: {
    backgroundColor: '#5865F2',
  },
  authButtonIcon: {
    fontSize: 18,
    fontWeight: '700',
    color: '#333',
  },
  authButtonText: {
    fontSize: 16,
    fontWeight: '600',
    color: '#333',
  },
  disclaimer: {
    color: '#555',
    fontSize: 11,
    textAlign: 'center',
    lineHeight: 18,
  },
});
