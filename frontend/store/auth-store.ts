"use client";

import { create } from "zustand";
import { persist, createJSONStorage } from "zustand/middleware";

type AuthState = {
  accessToken: string | null;
  refreshToken: string | null;
  tokenType: string;
  rememberMe: boolean;
  status: "unknown" | "authenticated" | "unauthenticated";
  hydrated: boolean;
  setRememberMe: (rememberMe: boolean) => void;
  setTokens: (input: { accessToken: string; refreshToken: string; tokenType?: string }) => void;
  clearAuth: () => void;
  setStatus: (status: AuthState["status"]) => void;
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

function createInitialState(set: (partial: Partial<AuthState>) => void): AuthState {
  return {
    accessToken: null,
    refreshToken: null,
    tokenType: "bearer",
    rememberMe: true,
    status: "unknown",
    hydrated: false,
    setRememberMe: (rememberMe) => {
      rememberMePreference = rememberMe;
      set({ rememberMe });
      migrateAuthStorage(rememberMe);
    },
    setTokens: ({ accessToken, refreshToken, tokenType = "bearer" }) =>
      set({ accessToken, refreshToken, tokenType, status: "authenticated" }),
    clearAuth: () =>
      set({ accessToken: null, refreshToken: null, tokenType: "bearer", status: "unauthenticated" }),
    setStatus: (status) => set({ status }),
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
          status: "unknown",
          hydrated: false,
        };
      },
      onRehydrateStorage: () => {
        return (_state, error) => {
          if (error) {
            rememberMePreference = true;
          }
          useAuthStore.setState({ hydrated: true });
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

export function setTokenPair(tokens: { access_token: string; refresh_token: string; token_type?: string }, options?: { rememberMe?: boolean }) {
  const state = useAuthStore.getState();

  if (options?.rememberMe !== undefined) {
    state.setRememberMe(options.rememberMe);
  }

  state.setTokens({
    accessToken: tokens.access_token,
    refreshToken: tokens.refresh_token,
    tokenType: tokens.token_type ?? "bearer",
  });
}
