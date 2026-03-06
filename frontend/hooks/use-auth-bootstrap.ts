"use client";

import { useEffect } from "react";
import { useRouter, usePathname } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { api, ApiError } from "@/lib/api-client";
import { queryKeys } from "@/lib/query-keys";
import { setTokenPair, useAuthStore } from "@/store/auth-store";

const PUBLIC_ROUTES = ["/login", "/register"];

export function useAuthBootstrap() {
  const router = useRouter();
  const pathname = usePathname();
  const status = useAuthStore((s) => s.status);
  const hydrated = useAuthStore((s) => s.hydrated);
  const refreshToken = useAuthStore((s) => s.refreshToken);
  const setStatus = useAuthStore((s) => s.setStatus);
  const clearAuth = useAuthStore((s) => s.clearAuth);

  const meQuery = useQuery({
    queryKey: queryKeys.me,
    queryFn: api.me,
    enabled: status === "authenticated",
    retry: (count, error) => (error instanceof ApiError ? error.status !== 401 && count < 2 : count < 2),
  });

  useEffect(() => {
    let cancelled = false;
    if (!hydrated) return;
    if (status !== "unknown") return;

    const bootstrap = async () => {
      if (!refreshToken) {
        setStatus("unauthenticated");
        return;
      }
      try {
        const pair = await api.refresh(refreshToken);
        if (cancelled) return;
        setTokenPair(pair);
      } catch {
        if (cancelled) return;
        clearAuth();
      }
    };

    void bootstrap();
    return () => {
      cancelled = true;
    };
  }, [hydrated, status, refreshToken, setStatus, clearAuth]);

  useEffect(() => {
    const isPublic = PUBLIC_ROUTES.some((route) => pathname.startsWith(route)) || pathname.startsWith("/invites/");

    if (!hydrated) return;

    if (status === "unauthenticated" && !isPublic) {
      router.replace("/login");
    }

    if (status === "authenticated" && meQuery.isSuccess && (pathname === "/" || pathname === "/login" || pathname === "/register")) {
      router.replace("/app");
    }

    if (meQuery.error instanceof ApiError && meQuery.error.status === 401) {
      clearAuth();
      router.replace("/login");
    }
  }, [hydrated, status, pathname, router, meQuery.isSuccess, meQuery.error, clearAuth]);

  return {
    status,
    me: meQuery.data,
    isLoading: !hydrated || status === "unknown" || (status === "authenticated" && meQuery.isLoading),
  };
}

