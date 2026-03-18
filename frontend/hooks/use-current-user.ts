"use client";

import { useAuthSession } from "@/components/auth/auth-provider";

export function useCurrentUser() {
  const { user, isAuthenticated, isLoading } = useAuthSession();
  return {
    data: user,
    isLoading,
    isAuthenticated,
  };
}
