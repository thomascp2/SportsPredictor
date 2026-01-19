import React from 'react';
import { View, Text, TouchableOpacity, StyleSheet } from 'react-native';

interface SportToggleProps {
  selected: 'NBA' | 'NHL';
  onSelect: (sport: 'NBA' | 'NHL') => void;
}

export function SportToggle({ selected, onSelect }: SportToggleProps) {
  return (
    <View style={styles.container}>
      <TouchableOpacity
        style={[styles.button, selected === 'NBA' && styles.selected]}
        onPress={() => onSelect('NBA')}
      >
        <Text style={[styles.text, selected === 'NBA' && styles.selectedText]}>
          NBA
        </Text>
      </TouchableOpacity>
      <TouchableOpacity
        style={[styles.button, selected === 'NHL' && styles.selected]}
        onPress={() => onSelect('NHL')}
      >
        <Text style={[styles.text, selected === 'NHL' && styles.selectedText]}>
          NHL
        </Text>
      </TouchableOpacity>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flexDirection: 'row',
    backgroundColor: '#2a2a3e',
    borderRadius: 8,
    padding: 4,
    marginHorizontal: 16,
    marginVertical: 8,
  },
  button: {
    flex: 1,
    paddingVertical: 10,
    alignItems: 'center',
    borderRadius: 6,
  },
  selected: {
    backgroundColor: '#4a4a6e',
  },
  text: {
    color: '#888',
    fontSize: 16,
    fontWeight: '600',
  },
  selectedText: {
    color: '#fff',
  },
});
