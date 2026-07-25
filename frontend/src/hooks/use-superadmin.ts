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
    gcTime: 0,
  });
}

export function useAdminUsers(q = "", isActive: boolean | null = null, offset = 0, limit = 25, enabled = true) {
  const params = new URLSearchParams({ offset: String(offset), limit: String(limit) });
  if (q) params.set("q", q);
  if (isActive !== null) params.set("is_active", String(isActive));
  return useQuery({
    queryKey: ["/admin/users", { q, isActive, offset, limit }],
    queryFn: () =>
      apiClient<{ items: AdminUserItem[]; total: number }>(
        `/admin/users?${params.toString()}`,
      ),
    enabled,
    gcTime: 0,
  });
}

export function useAdminChannels(
  q = "",
  state = "",
  visibility = "",
  offset = 0,
  limit = 25,
  enabled = true,
) {
  const params = new URLSearchParams({ offset: String(offset), limit: String(limit), include_deleted: "true" });
  if (q) params.set("q", q);
  if (state) params.set("state", state);
  if (visibility) params.set("visibility", visibility);
  return useQuery({
    queryKey: ["/admin/channels", { q, state, visibility, offset, limit }],
    queryFn: () =>
      apiClient<{ items: AdminChannelItem[]; total: number }>(
        `/admin/channels?${params.toString()}`,
      ),
    enabled,
    gcTime: 0,
  });
}

export function useAdminEvents(q = "", category = "", offset = 0, limit = 25, enabled = true) {
  const params = new URLSearchParams({ offset: String(offset), limit: String(limit) });
  if (q) params.set("q", q);
  if (category) params.set("category", category);
  return useQuery({
    queryKey: ["/admin/events", { q, category, offset, limit }],
    queryFn: () =>
      apiClient<{ items: AdminEventItem[]; total: number }>(
        `/admin/events?${params.toString()}`,
      ),
    enabled,
    gcTime: 0,
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
