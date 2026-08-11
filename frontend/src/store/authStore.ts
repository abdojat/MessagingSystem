import { create } from 'zustand';
import { MeResponse } from '../types/api';

interface AuthState {
  user: MeResponse | null;
  accessToken: string | null;
  isAuthenticated: boolean;
  isInitializing: boolean;
  setAuth: (user: MeResponse, accessToken: string) => void;
  setAccessToken: (accessToken: string | null) => void;
  clearAuth: () => void;
  setInitializing: (val: boolean) => void;
  updateUser: (user: Partial<MeResponse>) => void;
}

export const useAuthStore = create<AuthState>((set) => ({
  user: null,
  accessToken: null,
  isAuthenticated: false,
  isInitializing: true,
  // Access JWTs intentionally live only in this in-memory store. The browser
  // refresh credential is an HttpOnly server cookie and is never passed here.
  setAuth: (user, accessToken) => set({ user, accessToken, isAuthenticated: true, isInitializing: false }),
  setAccessToken: (accessToken) => set({ accessToken }),
  clearAuth: () => {
    set({ user: null, accessToken: null, isAuthenticated: false, isInitializing: false });
  },
  setInitializing: (val) => set({ isInitializing: val }),
  updateUser: (updatedUser) => set((state) => ({ user: state.user ? { ...state.user, ...updatedUser } : null })),
}));
