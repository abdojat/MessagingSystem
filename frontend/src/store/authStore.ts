import { create } from 'zustand';
import { MeResponse } from '../types/api';
import { clearSessionCookies, persistSessionCookies } from '@/services/auth/session-cookie';

interface AuthState {
  user: MeResponse | null;
  accessToken: string | null;
  isAuthenticated: boolean;
  isInitializing: boolean;
  setAuth: (user: MeResponse, accessToken: string, refreshToken: string) => void;
  clearAuth: () => void;
  setInitializing: (val: boolean) => void;
  updateUser: (user: Partial<MeResponse>) => void;
}

export const useAuthStore = create<AuthState>((set) => ({
  user: null,
  accessToken: null,
  isAuthenticated: false,
  isInitializing: true,
  setAuth: (user, accessToken, refreshToken) => {
    localStorage.setItem('chat_refresh_token', refreshToken);
    persistSessionCookies(accessToken, user.is_superadmin ? "superadmin" : "member");
    set({ user, accessToken, isAuthenticated: true, isInitializing: false });
  },
  clearAuth: () => {
    localStorage.removeItem('chat_refresh_token');
    clearSessionCookies();
    set({ user: null, accessToken: null, isAuthenticated: false, isInitializing: false });
  },
  setInitializing: (val) => set({ isInitializing: val }),
  updateUser: (updatedUser) => set((state) => ({ user: state.user ? { ...state.user, ...updatedUser } : null })),
}));
