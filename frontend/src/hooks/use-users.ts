import { useQuery } from "@tanstack/react-query";
import { apiClient } from "@/services/api/client";
import type { UserPublicProfile } from "@/types/api";

// Provides user profile behavior; React components use it to access or update application state.
export function useUserProfile(userId: string, enabled = true) {
  return useQuery({
    queryKey: ["/users", userId],
    queryFn: () => apiClient<UserPublicProfile>(`/users/${userId}`),
    enabled: Boolean(userId) && enabled,
    staleTime: 5 * 60 * 1000,
    retry: false,
  });
}

