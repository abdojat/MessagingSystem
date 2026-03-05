"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api-client";
import { queryKeys } from "@/lib/query-keys";
import { useAuthStore } from "@/store/auth-store";

export function useCurrentUser() {
  const status = useAuthStore((s) => s.status);
  return useQuery({
    queryKey: queryKeys.me,
    queryFn: api.me,
    enabled: status === "authenticated",
  });
}

