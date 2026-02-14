import { create } from 'zustand';
import { supabase } from '../services/supabase';
import type { Profile } from '../types/supabase';
import type { Session, AuthChangeEvent } from '@supabase/supabase-js';

interface AuthState {
  session: Session | null;
  profile: Profile | null;
  loading: boolean;
  initialized: boolean;

  initialize: () => Promise<void>;
  signInWithGoogle: () => Promise<void>;
  signInWithApple: () => Promise<void>;
  signInWithDiscord: () => Promise<void>;
  signOut: () => Promise<void>;
  refreshProfile: () => Promise<void>;
  updateProfile: (updates: Partial<Profile>) => Promise<void>;
}

export const useAuthStore = create<AuthState>((set, get) => ({
  session: null,
  profile: null,
  loading: false,
  initialized: false,

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
      const { error } = await supabase.auth.signInWithOAuth({
        provider: 'google',
      });
      if (error) throw error;
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
      const { error } = await supabase.auth.signInWithOAuth({
        provider: 'apple',
      });
      if (error) throw error;
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
      const { error } = await supabase.auth.signInWithOAuth({
        provider: 'discord',
      });
      if (error) throw error;
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
