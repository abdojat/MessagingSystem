"use client";

import { createContext, useContext, useEffect, useMemo } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiError } from "@/lib/api-client";
import { queryKeys } from "@/lib/query-keys";
import { useAuthStore } from "@/store/auth-store";
import type { MeResponse } from "@/types/api";

type AuthContextValue = {
  status: "loading" | "authenticated" | "unauthenticated";
  isReady: boolean;
  isAuthenticated: boolean;
  isLoading: boolean;
  user: MeResponse | null;
};

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const queryClient = useQueryClient();
  const hydrated = useAuthStore((state) => state.hydrated);
  const initialized = useAuthStore((state) => state.initialized);
  const status = useAuthStore((state) => state.status);
  const refreshToken = useAuthStore((state) => state.refreshToken);
  const establishSession = useAuthStore((state) => state.establishSession);
  const markUnauthenticated = useAuthStore((state) => state.markUnauthenticated);
  const clearSession = useAuthStore((state) => state.clearSession);

  const meQuery = useQuery({
    queryKey: queryKeys.me,
    queryFn: api.me,
    enabled: hydrated && initialized && status === "authenticated",
    retry: (count, error) => (error instanceof ApiError ? error.status !== 401 && count < 2 : count < 2),
  });

  useEffect(() => {
    if (hydrated) {
      return;
    }

    void useAuthStore.persist.rehydrate();

    const hydrationTimeout = window.setTimeout(() => {
      if (useAuthStore.persist.hasHydrated()) {
        return;
      }

      queryClient.removeQueries({ queryKey: queryKeys.me });
      queryClient.removeQueries({ queryKey: queryKeys.sessions });
      clearSession();
      useAuthStore.setState({ hydrated: true, initialized: true, status: "unauthenticated" });
    }, 3_000);

    return () => {
      window.clearTimeout(hydrationTimeout);
    };
  }, [hydrated, clearSession, queryClient]);

  useEffect(() => {
    if (!hydrated || initialized) {
      return;
    }

    let cancelled = false;
    const bootstrapTimeout = window.setTimeout(() => {
      if (!cancelled) {
        queryClient.removeQueries({ queryKey: queryKeys.me });
        clearSession();
      }
    }, 10_000);

    const bootstrap = async () => {
      if (!refreshToken) {
        markUnauthenticated();
        return;
      }

      try {
        const tokenPair = await api.refresh(refreshToken);
        if (!cancelled) {
          establishSession(tokenPair);
        }
      } catch {
        if (!cancelled) {
          queryClient.removeQueries({ queryKey: queryKeys.me });
          clearSession();
        }
      } finally {
        window.clearTimeout(bootstrapTimeout);
      }
    };

    void bootstrap();

    return () => {
      cancelled = true;
      window.clearTimeout(bootstrapTimeout);
    };
  }, [hydrated, initialized, refreshToken, establishSession, markUnauthenticated, clearSession, queryClient]);

  useEffect(() => {
    if (!(meQuery.error instanceof ApiError) || meQuery.error.status !== 401) {
      return;
    }

    queryClient.removeQueries({ queryKey: queryKeys.me });
    queryClient.removeQueries({ queryKey: queryKeys.sessions });
    clearSession();
  }, [meQuery.error, clearSession, queryClient]);

  useEffect(() => {
    if (status !== "unauthenticated") {
      return;
    }

    queryClient.removeQueries({ queryKey: queryKeys.me });
    queryClient.removeQueries({ queryKey: queryKeys.sessions });
  }, [status, queryClient]);

  const value = useMemo<AuthContextValue>(() => {
    const isReady = hydrated && initialized;
    const isAuthenticated = status === "authenticated";
    const isResolvingAuthenticatedUser = isAuthenticated && !meQuery.data && meQuery.fetchStatus === "fetching";

    return {
      status,
      isReady,
      isAuthenticated,
      isLoading: !isReady || isResolvingAuthenticatedUser,
      user: meQuery.data ?? null,
    };
  }, [hydrated, initialized, status, meQuery.data, meQuery.fetchStatus]);

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuthSession() {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error("useAuthSession must be used within an AuthProvider");
  }
  return context;
}
