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

type StorageLike = {
  getItem: (name: string) => string | null;
  setItem: (name: string, value: string) => void;
  removeItem: (name: string) => void;
};

function getPreferredStorage(): Storage {
  const rememberMe = useAuthStore.getState?.().rememberMe;
  if (typeof rememberMe === "boolean") {
    return rememberMe ? localStorage : sessionStorage;
  }
  try {
    const raw = localStorage.getItem("chat-auth");
    if (!raw) return localStorage;
    const parsed = JSON.parse(raw) as { state?: { rememberMe?: boolean } };
    if (parsed?.state?.rememberMe === false) return sessionStorage;
    return localStorage;
  } catch {
    return localStorage;
  }
}

function migrateAuthStorage(rememberMe: boolean) {
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
  getItem: (name) => {
    return localStorage.getItem(name) ?? sessionStorage.getItem(name);
  },
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

export const useAuthStore = create<AuthState>()(
  persist(
    (set) => ({
      accessToken: null,
      refreshToken: null,
      tokenType: "bearer",
      rememberMe: true,
      status: "unknown",
      hydrated: false,
      setRememberMe: (rememberMe) => {
        set({ rememberMe });
        migrateAuthStorage(rememberMe);
      },
      setTokens: ({ accessToken, refreshToken, tokenType = "bearer" }) =>
        set({ accessToken, refreshToken, tokenType, status: "authenticated" }),
      clearAuth: () =>
        set({ accessToken: null, refreshToken: null, tokenType: "bearer", status: "unauthenticated" }),
      setStatus: (status) => set({ status }),
    }),
    {
      name: "chat-auth",
      storage: createJSONStorage(() => dualStorage),
      partialize: (state) => ({ refreshToken: state.refreshToken, tokenType: state.tokenType, rememberMe: state.rememberMe }),
      onRehydrateStorage: () => (state) => {
        if (!state) return;
        state.accessToken = null;
        state.status = "unknown";
        state.hydrated = true;
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
  if (options?.rememberMe !== undefined) {
    useAuthStore.getState().setRememberMe(options.rememberMe);
  }
  useAuthStore.getState().setTokens({
    accessToken: tokens.access_token,
    refreshToken: tokens.refresh_token,
    tokenType: tokens.token_type ?? "bearer",
  });
}
