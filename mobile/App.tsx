import React from 'react';
import { StatusBar } from 'expo-status-bar';
import { NavigationContainer, DefaultTheme } from '@react-navigation/native';
import { createBottomTabNavigator } from '@react-navigation/bottom-tabs';
import { SafeAreaProvider } from 'react-native-safe-area-context';
import { Text, View } from 'react-native';

import { ScoreboardScreen } from './src/screens/ScoreboardScreen';
import { SmartPicksScreen } from './src/screens/SmartPicksScreen';
import { ParlayBuilderScreen } from './src/screens/ParlayBuilderScreen';
import { PerformanceScreen } from './src/screens/PerformanceScreen';
import { PlayerSearchScreen } from './src/screens/PlayerSearchScreen';
import { AdminScreen } from './src/screens/AdminScreen';

const Tab = createBottomTabNavigator();

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

// Simple tab icon component (using text for now - could be replaced with icons)
function TabIcon({ name, focused }: { name: string; focused: boolean }) {
  const icons: Record<string, string> = {
    Scores: 'S',
    Picks: 'P',
    Parlay: '$',
    Stats: '%',
    Admin: 'A',
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

export default function App() {
  return (
    <SafeAreaProvider>
      <NavigationContainer theme={DarkTheme}>
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
            name="Scores"
            component={ScoreboardScreen}
            options={{ tabBarLabel: 'Scores' }}
          />
          <Tab.Screen
            name="Picks"
            component={SmartPicksScreen}
            options={{ tabBarLabel: 'Picks' }}
          />
          <Tab.Screen
            name="Parlay"
            component={ParlayBuilderScreen}
            options={{ tabBarLabel: 'Parlay' }}
          />
          <Tab.Screen
            name="Stats"
            component={PerformanceScreen}
            options={{ tabBarLabel: 'Stats' }}
          />
          <Tab.Screen
            name="Admin"
            component={AdminScreen}
            options={{ tabBarLabel: 'Admin' }}
          />
        </Tab.Navigator>
        <StatusBar style="light" />
      </NavigationContainer>
    </SafeAreaProvider>
  );
}
