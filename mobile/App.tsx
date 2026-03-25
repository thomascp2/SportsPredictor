import React, { useEffect } from 'react';
import { StatusBar } from 'expo-status-bar';
import { NavigationContainer, DefaultTheme } from '@react-navigation/native';
import { createBottomTabNavigator } from '@react-navigation/bottom-tabs';
import { createNativeStackNavigator } from '@react-navigation/native-stack';
import { SafeAreaProvider } from 'react-native-safe-area-context';
import { Text, View, ActivityIndicator } from 'react-native';

import { useAuthStore } from './src/store/authStore';
import { registerQuickActions } from './src/utils/quickActions';

// Auth screen
import { AuthScreen } from './src/screens/AuthScreen';

// Main tab screens
import { PlayScreen } from './src/screens/PlayScreen';
import { ScoreboardScreen } from './src/screens/ScoreboardScreen';
import { TrackScreen } from './src/screens/TrackScreen';
import { ProfileScreen } from './src/screens/ProfileScreen';

// Modal/stack screens
import { AddBetScreen } from './src/screens/AddBetScreen';
import { WatchlistScreen } from './src/screens/WatchlistScreen';

// Legacy screens (accessible from Profile or hidden debug)
import { SmartPicksScreen } from './src/screens/SmartPicksScreen';
import { ParlayBuilderScreen } from './src/screens/ParlayBuilderScreen';
import { PerformanceScreen } from './src/screens/PerformanceScreen';
import { AdminScreen } from './src/screens/AdminScreen';

const Tab = createBottomTabNavigator();
const Stack = createNativeStackNavigator();

// Custom dark theme
const DarkTheme = {
  ...DefaultTheme,
  colors: {
    ...DefaultTheme.colors,
    primary: '#4CAF50',
    background: '#121212',
    card: '#1e1e2e',
    text: '#ffffff',
    border: '#333',
    notification: '#4CAF50',
  },
};

// Tab icon component
function TabIcon({ name, focused }: { name: string; focused: boolean }) {
  const icons: Record<string, string> = {
    Play: 'P',
    Scores: 'S',
    Track: 'T',
    Profile: 'U',
  };

  return (
    <View
      style={{
        width: 28,
        height: 28,
        borderRadius: 14,
        backgroundColor: focused ? '#4CAF50' : '#333',
        justifyContent: 'center',
        alignItems: 'center',
      }}
    >
      <Text
        style={{
          color: focused ? '#fff' : '#888',
          fontSize: 14,
          fontWeight: 'bold',
        }}
      >
        {icons[name] || name[0]}
      </Text>
    </View>
  );
}

// Main 4-tab navigator
function MainTabs() {
  return (
    <Tab.Navigator
      screenOptions={({ route }) => ({
        headerShown: false,
        tabBarIcon: ({ focused }) => (
          <TabIcon name={route.name} focused={focused} />
        ),
        tabBarActiveTintColor: '#4CAF50',
        tabBarInactiveTintColor: '#888',
        tabBarStyle: {
          backgroundColor: '#1e1e2e',
          borderTopColor: '#333',
          paddingTop: 8,
          paddingBottom: 8,
          height: 60,
        },
        tabBarLabelStyle: {
          fontSize: 10,
          fontWeight: '600',
        },
      })}
    >
      <Tab.Screen
        name="Play"
        component={PlayScreen}
        options={{ tabBarLabel: 'Play' }}
      />
      <Tab.Screen
        name="Scores"
        component={ScoreboardScreen}
        options={{ tabBarLabel: 'Scores' }}
      />
      <Tab.Screen
        name="Track"
        component={TrackScreen}
        options={{ tabBarLabel: 'Track' }}
      />
      <Tab.Screen
        name="Profile"
        component={ProfileScreen}
        options={{ tabBarLabel: 'Profile' }}
      />
    </Tab.Navigator>
  );
}

// Root navigator with auth gate
function RootNavigator() {
  const { session, initialized } = useAuthStore();

  if (!initialized) {
    return (
      <View style={{ flex: 1, backgroundColor: '#121212', justifyContent: 'center', alignItems: 'center' }}>
        <ActivityIndicator size="large" color="#4CAF50" />
      </View>
    );
  }

  return (
    <Stack.Navigator screenOptions={{ headerShown: false }}>
      {!session ? (
        <Stack.Screen name="Auth" component={AuthScreen} />
      ) : (
        <>
          <Stack.Screen name="Main" component={MainTabs} />
          <Stack.Screen
            name="AddBet"
            component={AddBetScreen}
            options={{ presentation: 'modal' }}
          />
          <Stack.Screen
            name="Watchlist"
            component={WatchlistScreen}
            options={{ presentation: 'modal' }}
          />
          {/* Legacy screens accessible as stack pushes */}
          <Stack.Screen name="SmartPicks" component={SmartPicksScreen} />
          <Stack.Screen name="ParlayBuilder" component={ParlayBuilderScreen} />
          <Stack.Screen name="Performance" component={PerformanceScreen} />
          <Stack.Screen name="Admin" component={AdminScreen} />
        </>
      )}
    </Stack.Navigator>
  );
}

export default function App() {
  const { initialize } = useAuthStore();

  useEffect(() => {
    initialize();
    registerQuickActions();
  }, [initialize]);

  return (
    <SafeAreaProvider>
      <NavigationContainer theme={DarkTheme}>
        <RootNavigator />
        <StatusBar style="light" />
      </NavigationContainer>
    </SafeAreaProvider>
  );
}
