"use client";

import { create } from "zustand";
import { persist, createJSONStorage } from "zustand/middleware";

type AuthState = {
  accessToken: string | null;
  refreshToken: string | null;
  tokenType: string;
  status: "unknown" | "authenticated" | "unauthenticated";
  hydrated: boolean;
  setTokens: (input: { accessToken: string; refreshToken: string; tokenType?: string }) => void;
  clearAuth: () => void;
  setStatus: (status: AuthState["status"]) => void;
};

export const useAuthStore = create<AuthState>()(
  persist(
    (set) => ({
      accessToken: null,
      refreshToken: null,
      tokenType: "bearer",
      status: "unknown",
      hydrated: false,
      setTokens: ({ accessToken, refreshToken, tokenType = "bearer" }) =>
        set({ accessToken, refreshToken, tokenType, status: "authenticated" }),
      clearAuth: () =>
        set({ accessToken: null, refreshToken: null, tokenType: "bearer", status: "unauthenticated" }),
      setStatus: (status) => set({ status }),
    }),
    {
      name: "chat-auth",
      storage: createJSONStorage(() => localStorage),
      partialize: (state) => ({ refreshToken: state.refreshToken, tokenType: state.tokenType }),
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

export function setTokenPair(tokens: { access_token: string; refresh_token: string; token_type?: string }) {
  useAuthStore.getState().setTokens({
    accessToken: tokens.access_token,
    refreshToken: tokens.refresh_token,
    tokenType: tokens.token_type ?? "bearer",
  });
}

