import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiClient } from "@/services/api/client";
import type {
  AdminChannelItem,
  AdminEventItem,
  AdminOverviewResponse,
  AdminUserItem,
} from "@/types/api";

export function useAdminOverview(enabled = true) {
  return useQuery({
    queryKey: ["/admin/overview"],
    queryFn: () => apiClient<AdminOverviewResponse>("/admin/overview"),
    enabled,
  });
}

export function useAdminUsers(q = "", offset = 0, enabled = true) {
  return useQuery({
    queryKey: ["/admin/users", { q, offset }],
    queryFn: () =>
      apiClient<{ items: AdminUserItem[]; total: number }>(
        `/admin/users?limit=100&offset=${offset}${q ? `&q=${encodeURIComponent(q)}` : ""}`,
      ),
    enabled,
  });
}

export function useAdminChannels(q = "", offset = 0, enabled = true) {
  return useQuery({
    queryKey: ["/admin/channels", { q, offset }],
    queryFn: () =>
      apiClient<{ items: AdminChannelItem[]; total: number }>(
        `/admin/channels?limit=100&offset=${offset}&include_deleted=true${q ? `&q=${encodeURIComponent(q)}` : ""}`,
      ),
    enabled,
  });
}

export function useAdminEvents(eventType = "", offset = 0, enabled = true) {
  return useQuery({
    queryKey: ["/admin/events", { eventType, offset }],
    queryFn: () =>
      apiClient<{ items: AdminEventItem[]; total: number }>(
        `/admin/events?limit=100&offset=${offset}${eventType ? `&event_type=${encodeURIComponent(eventType)}` : ""}`,
      ),
    enabled,
  });
}

export function useSetAdminUserStatus() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ userId, isActive }: { userId: string; isActive: boolean }) =>
      apiClient(`/admin/users/${userId}/status`, {
        method: "PATCH",
        body: JSON.stringify({ is_active: isActive }),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["/admin/users"] });
      queryClient.invalidateQueries({ queryKey: ["/admin/overview"] });
      queryClient.invalidateQueries({ queryKey: ["/admin/events"] });
    },
  });
}

export function useRevokeAdminUserSessions() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (userId: string) =>
      apiClient(`/admin/users/${userId}/revoke-sessions`, { method: "POST" }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["/admin/users"] });
      queryClient.invalidateQueries({ queryKey: ["/admin/events"] });
    },
  });
}

export function useSetAdminChannelState() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ channelId, restore }: { channelId: string; restore: boolean }) =>
      apiClient(`/admin/channels/${channelId}${restore ? "/restore" : ""}`, {
        method: restore ? "POST" : "DELETE",
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["/admin/channels"] });
      queryClient.invalidateQueries({ queryKey: ["/admin/overview"] });
      queryClient.invalidateQueries({ queryKey: ["/admin/events"] });
    },
  });
}
