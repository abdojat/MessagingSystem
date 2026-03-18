"use client";

import { create } from "zustand";
import { createJSONStorage, persist } from "zustand/middleware";
import type { TokenPair } from "@/types/api";

type AuthState = {
  accessToken: string | null;
  refreshToken: string | null;
  tokenType: string;
  rememberMe: boolean;
  status: "loading" | "authenticated" | "unauthenticated";
  hydrated: boolean;
  initialized: boolean;
  setRememberMe: (rememberMe: boolean) => void;
  establishSession: (tokens: TokenPair, options?: { rememberMe?: boolean }) => void;
  markUnauthenticated: () => void;
  clearSession: () => void;
};

type PersistedAuthState = Partial<Pick<AuthState, "refreshToken" | "tokenType" | "rememberMe">>;

type StorageLike = {
  getItem: (name: string) => string | null;
  setItem: (name: string, value: string) => void;
  removeItem: (name: string) => void;
};

let rememberMePreference = true;

function isString(value: unknown): value is string {
  return typeof value === "string" && value.length > 0;
}

function readStoredAuthState() {
  try {
    const raw = localStorage.getItem("chat-auth") ?? sessionStorage.getItem("chat-auth");
    if (!raw) return null;
    return JSON.parse(raw) as { state?: PersistedAuthState };
  } catch {
    return null;
  }
}

function getPreferredStorage(): Storage {
  const parsed = readStoredAuthState();
  if (parsed?.state?.rememberMe === false) return sessionStorage;
  return rememberMePreference ? localStorage : sessionStorage;
}

function migrateAuthStorage(rememberMe: boolean) {
  rememberMePreference = rememberMe;
  const name = "chat-auth";
  const preferred = rememberMe ? localStorage : sessionStorage;
  const other = rememberMe ? sessionStorage : localStorage;
  const existing = localStorage.getItem(name) ?? sessionStorage.getItem(name);

  if (existing !== null) {
    preferred.setItem(name, existing);
  }

  other.removeItem(name);
}

const dualStorage: StorageLike = {
  getItem: (name) => localStorage.getItem(name) ?? sessionStorage.getItem(name),
  setItem: (name, value) => {
    const preferred = getPreferredStorage();
    preferred.setItem(name, value);
    if (preferred === localStorage) {
      sessionStorage.removeItem(name);
    } else {
      localStorage.removeItem(name);
    }
  },
  removeItem: (name) => {
    localStorage.removeItem(name);
    sessionStorage.removeItem(name);
  },
};

const noopStorage: StorageLike = {
  getItem: () => null,
  setItem: () => undefined,
  removeItem: () => undefined,
};

function createInitialState(set: (partial: Partial<AuthState> | ((state: AuthState) => Partial<AuthState>)) => void): AuthState {
  return {
    accessToken: null,
    refreshToken: null,
    tokenType: "bearer",
    rememberMe: true,
    status: "loading",
    hydrated: false,
    initialized: false,
    setRememberMe: (rememberMe) => {
      rememberMePreference = rememberMe;
      set({ rememberMe });
      migrateAuthStorage(rememberMe);
    },
    establishSession: (tokens, options) => {
      if (options?.rememberMe !== undefined) {
        rememberMePreference = options.rememberMe;
        migrateAuthStorage(options.rememberMe);
      }
      set((state) => ({
        accessToken: tokens.access_token,
        refreshToken: tokens.refresh_token,
        tokenType: tokens.token_type ?? "bearer",
        rememberMe: options?.rememberMe ?? state.rememberMe,
        status: "authenticated",
        initialized: true,
      }));
    },
    markUnauthenticated: () =>
      set({
        accessToken: null,
        status: "unauthenticated",
        initialized: true,
      }),
    clearSession: () =>
      set({
        accessToken: null,
        refreshToken: null,
        tokenType: "bearer",
        status: "unauthenticated",
        initialized: true,
      }),
  };
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set) => createInitialState(set),
    {
      name: "chat-auth",
      storage: createJSONStorage(() => (typeof window === "undefined" ? noopStorage : dualStorage)),
      partialize: (state) => ({
        refreshToken: state.refreshToken,
        tokenType: state.tokenType,
        rememberMe: state.rememberMe,
      }),
      merge: (persistedState, currentState) => {
        const persisted = (persistedState ?? {}) as PersistedAuthState;
        const rememberMe = typeof persisted.rememberMe === "boolean" ? persisted.rememberMe : currentState.rememberMe;

        rememberMePreference = rememberMe;

        return {
          ...currentState,
          accessToken: null,
          refreshToken: isString(persisted.refreshToken) ? persisted.refreshToken : null,
          tokenType: isString(persisted.tokenType) ? persisted.tokenType : currentState.tokenType,
          rememberMe,
          status: "loading",
          hydrated: false,
          initialized: false,
        };
      },
      onRehydrateStorage: () => {
        return (_state, error) => {
          if (error) {
            rememberMePreference = true;
            useAuthStore.setState({
              accessToken: null,
              refreshToken: null,
              tokenType: "bearer",
              rememberMe: true,
              status: "unauthenticated",
              hydrated: true,
              initialized: true,
            });
            return;
          }

          const state = useAuthStore.getState();
          useAuthStore.setState({
            hydrated: true,
            initialized: state.initialized || !state.refreshToken,
            status: state.refreshToken ? state.status : "unauthenticated",
          });
        };
      },
    },
  ),
);

export function getAccessToken() {
  return useAuthStore.getState().accessToken;
}

export function getRefreshToken() {
  return useAuthStore.getState().refreshToken;
}

export function setAuthenticatedSession(tokens: TokenPair, options?: { rememberMe?: boolean }) {
  useAuthStore.getState().establishSession(tokens, options);
}

export function clearAuthenticatedSession() {
  useAuthStore.getState().clearSession();
}
