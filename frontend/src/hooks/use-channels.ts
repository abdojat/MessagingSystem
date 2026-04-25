import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { apiClient } from '@/services/api/client';
import {
  AdminPermissionsUpdateRequest,
  AdminPermissionsUpdateResponse,
  ChannelMembershipListResponse,
  ChannelPatchRequest,
  ChannelResponse,
} from '../types/api';

type ChannelScope = 'my' | 'discover';

interface UseChannelsOptions {
  scope?: ChannelScope;
  q?: string;
  enabled?: boolean;
}

interface UseChannelMembersOptions {
  role?: 'owner' | 'admin' | 'member' | 'pending';
  q?: string;
  enabled?: boolean;
}

export function useChannels(options: UseChannelsOptions = {}) {
  const scope = options.scope ?? 'my';
  const q = options.q?.trim() ?? '';
  const enabled = options.enabled ?? true;

  return useQuery({
    queryKey: ['/channels', { scope, q }],
    queryFn: () => {
      const params = new URLSearchParams();
      params.set('scope', scope);
      if (q) {
        params.set('q', q);
      }

      return apiClient<{items: ChannelResponse[]}>(`/channels?${params.toString()}`).then(res => res.items);
    },
    enabled,
  });
}

export function useChannel(channelId: string) {
  const queryClient = useQueryClient();

  return useQuery({
    queryKey: ['/channels', channelId],
    queryFn: () => apiClient<ChannelResponse>(`/channels/${channelId}`),
    initialData: () => {
      const channelQueries = queryClient.getQueriesData<ChannelResponse[]>({
        queryKey: ['/channels'],
      });

      for (const [, channels] of channelQueries) {
        const match = channels?.find((channel) => channel.id === channelId);
        if (match) {
          return match;
        }
      }

      return undefined;
    },
    enabled: !!channelId
  });
}

export function useCreateChannel() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (data: any) => apiClient<ChannelResponse>('/channels', { method: 'POST', body: JSON.stringify(data) }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['/channels'] })
  });
}

export function useJoinChannel() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (channelId: string) => apiClient(`/channels/${channelId}/join`, { method: 'POST', body: JSON.stringify({}) }),
    onSuccess: (_, channelId) => {
      queryClient.invalidateQueries({ queryKey: ['/channels'] });
      queryClient.invalidateQueries({ queryKey: ['/channels', channelId] });
    }
  });
}

export function useLeaveChannel() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (channelId: string) => apiClient(`/channels/${channelId}/leave`, { method: 'POST' }),
    onSuccess: (_, channelId) => {
      queryClient.invalidateQueries({ queryKey: ['/channels'] });
      queryClient.invalidateQueries({ queryKey: ['/channels', channelId] });
      queryClient.removeQueries({ queryKey: ['/channels', channelId, 'messages'] });
    }
  });
}

export function useUpdateChannel() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ channelId, data }: { channelId: string; data: ChannelPatchRequest }) =>
      apiClient<ChannelResponse>(`/channels/${channelId}`, {
        method: 'PATCH',
        body: JSON.stringify(data),
      }),
    onSuccess: (_, vars) => {
      queryClient.invalidateQueries({ queryKey: ['/channels'] });
      queryClient.invalidateQueries({ queryKey: ['/channels', vars.channelId] });
    }
  });
}

export function useChannelMembers(channelId: string, options: UseChannelMembersOptions = {}) {
  const role = options.role;
  const q = options.q?.trim() ?? '';
  const enabled = options.enabled ?? true;

  return useQuery({
    queryKey: ['/channels', channelId, 'members', { role: role ?? null, q }],
    queryFn: () => {
      const params = new URLSearchParams();
      if (role) params.set('role', role);
      if (q) params.set('q', q);
      return apiClient<ChannelMembershipListResponse>(`/channels/${channelId}/members?${params.toString()}`);
    },
    enabled: !!channelId && enabled,
  });
}

function useMemberMutation(endpointBuilder: (channelId: string, userId: string) => string, method: 'POST' | 'DELETE' = 'POST') {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ channelId, userId }: { channelId: string; userId: string }) =>
      apiClient(endpointBuilder(channelId, userId), { method }),
    onSuccess: (_, vars) => {
      queryClient.invalidateQueries({ queryKey: ['/channels'] });
      queryClient.invalidateQueries({ queryKey: ['/channels', vars.channelId] });
      queryClient.invalidateQueries({ queryKey: ['/channels', vars.channelId, 'members'] });
    }
  });
}

export function useApproveMember() {
  return useMemberMutation((channelId, userId) => `/channels/${channelId}/members/${userId}/approve`);
}

export function usePromoteMember() {
  return useMemberMutation((channelId, userId) => `/channels/${channelId}/members/${userId}/promote`);
}

export function useDemoteMember() {
  return useMemberMutation((channelId, userId) => `/channels/${channelId}/members/${userId}/demote`);
}

export function useRemoveMember() {
  return useMemberMutation((channelId, userId) => `/channels/${channelId}/members/${userId}`, 'DELETE');
}

export function useUpdateAdminPermissions() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      channelId,
      userId,
      data,
    }: {
      channelId: string;
      userId: string;
      data: AdminPermissionsUpdateRequest;
    }) =>
      apiClient<AdminPermissionsUpdateResponse>(`/channels/${channelId}/members/${userId}/permissions`, {
        method: 'PATCH',
        body: JSON.stringify(data),
      }),
    onSuccess: (_, vars) => {
      queryClient.invalidateQueries({ queryKey: ['/channels'] });
      queryClient.invalidateQueries({ queryKey: ['/channels', vars.channelId] });
      queryClient.invalidateQueries({ queryKey: ['/channels', vars.channelId, 'members'] });
    }
  });
}
