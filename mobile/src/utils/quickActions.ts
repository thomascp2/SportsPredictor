import * as QuickActions from 'expo-quick-actions';

/**
 * Register app icon quick actions (iOS 3D Touch / Android shortcuts).
 */
export function registerQuickActions() {
  QuickActions.setItems([
    {
      id: 'today_picks',
      title: "Today's Picks",
      subtitle: 'Make your OVER/UNDER picks',
      icon: 'symbol:sportscourt',
    },
    {
      id: 'watchlist',
      title: 'My Watchlist',
      subtitle: 'Check your player box scores',
      icon: 'symbol:star',
    },
    {
      id: 'log_bet',
      title: 'Log a Bet',
      subtitle: 'Track a new bet',
      icon: 'symbol:plus.circle',
    },
  ]);
}

/**
 * Handle a quick action selection.
 * Returns the tab/screen to navigate to.
 */
export function handleQuickAction(actionId: string): { tab: string; screen?: string } | null {
  switch (actionId) {
    case 'today_picks':
      return { tab: 'Play' };
    case 'watchlist':
      return { tab: 'Profile', screen: 'Watchlist' };
    case 'log_bet':
      return { tab: 'Track', screen: 'AddBet' };
    default:
      return null;
  }
}
