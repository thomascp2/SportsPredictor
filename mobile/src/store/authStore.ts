import { create } from 'zustand';
import * as WebBrowser from 'expo-web-browser';
import { makeRedirectUri } from 'expo-auth-session';
import * as QueryParams from 'expo-auth-session/build/QueryParams';
import { supabase } from '../services/supabase';
import type { Profile } from '../types/supabase';
import type { Session, AuthChangeEvent } from '@supabase/supabase-js';

// Required for web browser auth session to work properly on Android
WebBrowser.maybeCompleteAuthSession();

// Generate the redirect URI for OAuth callbacks
// Expo Go: exp://192.168.x.x:8081  |  Standalone: freepicks://
const redirectTo = makeRedirectUri();

/** Extract tokens from the callback URL and create a Supabase session */
async function createSessionFromUrl(url: string): Promise<Session | null> {
  const { params, errorCode } = QueryParams.getQueryParams(url);

  if (errorCode) {
    console.error('OAuth callback error:', errorCode);
    throw new Error(errorCode);
  }

  const { access_token, refresh_token } = params;
  if (!access_token) return null;

  const { data, error } = await supabase.auth.setSession({
    access_token,
    refresh_token,
  });

  if (error) throw error;
  return data.session;
}

/** Open Supabase OAuth in a web browser and handle the redirect */
async function performOAuth(provider: 'google' | 'apple' | 'discord'): Promise<Session | null> {
  // Get the OAuth URL from Supabase (don't auto-redirect the browser)
  const { data, error } = await supabase.auth.signInWithOAuth({
    provider,
    options: {
      redirectTo,
      skipBrowserRedirect: true,
    },
  });

  if (error) throw error;
  if (!data?.url) throw new Error('No OAuth URL returned');

  // Open the auth URL in a web browser overlay
  const result = await WebBrowser.openAuthSessionAsync(
    data.url,
    redirectTo,
  );

  if (result.type === 'success') {
    return createSessionFromUrl(result.url);
  }

  // User cancelled or dismissed the browser
  return null;
}

interface AuthState {
  session: Session | null;
  profile: Profile | null;
  loading: boolean;
  initialized: boolean;

  initialize: () => Promise<void>;
  devSignIn: () => void;
  signInWithGoogle: () => Promise<void>;
  signInWithApple: () => Promise<void>;
  signInWithDiscord: () => Promise<void>;
  signOut: () => Promise<void>;
  refreshProfile: () => Promise<void>;
  updateProfile: (updates: Partial<Profile> & Record<string, unknown>) => Promise<void>;
}

export const useAuthStore = create<AuthState>((set, get) => ({
  session: null,
  profile: null,
  loading: false,
  initialized: false,

  devSignIn: () => {
    const mockSession = { user: { id: 'dev-user', email: 'dev@freepicks.local' } } as unknown as Session;
    const mockProfile: Profile = {
      id: 'dev-user',
      username: 'devmode',
      display_name: 'Dev Mode',
      avatar_url: null,
      points: 999,
      streak: 3,
      best_streak: 7,
      tier: 'pro',
      total_picks: 42,
      total_hits: 30,
      premium: false,
      premium_until: null,
      push_token: null,
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    };
    set({ session: mockSession, profile: mockProfile, initialized: true });
  },

  initialize: async () => {
    try {
      const { data: { session } } = await supabase.auth.getSession();
      set({ session, initialized: true });

      if (session?.user) {
        await get().refreshProfile();
      }

      // Listen for auth changes
      supabase.auth.onAuthStateChange(async (_event: AuthChangeEvent, session: Session | null) => {
        set({ session });
        if (session?.user) {
          await get().refreshProfile();
        } else {
          set({ profile: null });
        }
      });
    } catch (error) {
      console.error('Auth init error:', error);
      set({ initialized: true });
    }
  },

  signInWithGoogle: async () => {
    set({ loading: true });
    try {
      await performOAuth('google');
    } catch (error) {
      console.error('Google sign-in error:', error);
      throw error;
    } finally {
      set({ loading: false });
    }
  },

  signInWithApple: async () => {
    set({ loading: true });
    try {
      await performOAuth('apple');
    } catch (error) {
      console.error('Apple sign-in error:', error);
      throw error;
    } finally {
      set({ loading: false });
    }
  },

  signInWithDiscord: async () => {
    set({ loading: true });
    try {
      await performOAuth('discord');
    } catch (error) {
      console.error('Discord sign-in error:', error);
      throw error;
    } finally {
      set({ loading: false });
    }
  },

  signOut: async () => {
    set({ loading: true });
    try {
      await supabase.auth.signOut();
      set({ session: null, profile: null });
    } catch (error) {
      console.error('Sign-out error:', error);
    } finally {
      set({ loading: false });
    }
  },

  refreshProfile: async () => {
    const { session } = get();
    if (!session?.user) return;

    try {
      const { data, error } = await supabase
        .from('profiles')
        .select('*')
        .eq('id', session.user.id)
        .single();

      if (error) throw error;
      set({ profile: data as Profile });
    } catch (error) {
      console.error('Profile fetch error:', error);
    }
  },

  updateProfile: async (updates: Partial<Profile> & Record<string, unknown>) => {
    const { session } = get();
    if (!session?.user) return;

    try {
      const { error } = await supabase
        .from('profiles')
        .update(updates)
        .eq('id', session.user.id);

      if (error) throw error;
      await get().refreshProfile();
    } catch (error) {
      console.error('Profile update error:', error);
      throw error;
    }
  },
}));
