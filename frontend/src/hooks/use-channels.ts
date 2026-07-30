import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { apiClient } from '@/services/api/client';
import {
  AdminPermissionsUpdateRequest,
  AdminPermissionsUpdateResponse,
  ChannelMembershipListResponse,
  ChannelPatchRequest,
  ChannelResponse,
  JoinOutcomeResponse,
} from '../types/api';
import { useWS } from '@/hooks/use-websocket';
import { isChannelListQueryKey } from '@/hooks/query-keys';

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

// Provides channels behavior; React components use it to access or update application state.
export function useChannels(options: UseChannelsOptions = {}) {
  const scope = options.scope ?? 'my';
  const q = options.q?.trim() ?? '';
  const enabled = options.enabled ?? true;

  return useQuery({
    queryKey: ['/channels', { scope, q }],
    queryFn: () => {
      const params = new URLSearchParams();
      params.set('scope', scope);
      // Run this conditional step only when `q` is true.
      if (q) {
        params.set('q', q);
      }

      return apiClient<{items: ChannelResponse[]}>(`/channels?${params.toString()}`).then(res => res.items);
    },
    enabled,
  });
}

// Provides channel behavior; React components use it to access or update application state.
export function useChannel(channelId: string) {
  const queryClient = useQueryClient();

  return useQuery({
    queryKey: ['/channels', channelId],
    queryFn: () => apiClient<ChannelResponse>(`/channels/${channelId}`),
    initialData: () => {
      const channelQueries = queryClient.getQueriesData<ChannelResponse[]>({
        predicate: (query) => isChannelListQueryKey(query.queryKey),
      });

      // Process each item from `channelQueries` so this step covers the collection.
      for (const [, channels] of channelQueries) {
        // Skip the current item when `!Array.isArray(channels)` and continue processing the rest.
        if (!Array.isArray(channels)) continue;
        const match = channels?.find((channel) => channel.id === channelId);
        // Return early when `match` because the remaining work is not applicable.
        if (match) {
          return match;
        }
      }

      return undefined;
    },
    enabled: !!channelId
  });
}

// Provides create channel behavior; React components use it to access or update application state.
export function useCreateChannel() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (data: any) => apiClient<ChannelResponse>('/channels', { method: 'POST', body: JSON.stringify(data) }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['/channels'] })
  });
}

// Provides join channel behavior; React components use it to access or update application state.
export function useJoinChannel() {
  const queryClient = useQueryClient();
  const { emit } = useWS();
  return useMutation({
    mutationFn: (channelId: string) => apiClient<JoinOutcomeResponse>(`/channels/${channelId}/join`, { method: 'POST', body: JSON.stringify({}) }),
    onSuccess: (outcome, channelId) => {
      queryClient.invalidateQueries({ queryKey: ['/channels'] });
      queryClient.invalidateQueries({ queryKey: ['/channels', channelId] });
      queryClient.invalidateQueries({ queryKey: ['/channels', channelId, 'messages'] });
      // Run this conditional step only when `outcome.status === 'joined' || outcome.status === 'already_member'` is true.
      if (outcome.status === 'joined' || outcome.status === 'already_member') {
        emit('subscribe', { channel_ids: [channelId], from_seq_id: 0 });
      }
    }
  });
}

// Provides leave channel behavior; React components use it to access or update application state.
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

// Provides update channel behavior; React components use it to access or update application state.
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

// Provides channel members behavior; React components use it to access or update application state.
export function useChannelMembers(channelId: string, options: UseChannelMembersOptions = {}) {
  const role = options.role;
  const q = options.q?.trim() ?? '';
  const enabled = options.enabled ?? true;

  return useQuery({
    queryKey: ['/channels', channelId, 'members', { role: role ?? null, q }],
    queryFn: () => {
      const params = new URLSearchParams();
      // Run this conditional step only when `role` is true.
      if (role) params.set('role', role);
      // Run this conditional step only when `q` is true.
      if (q) params.set('q', q);
      return apiClient<ChannelMembershipListResponse>(`/channels/${channelId}/members?${params.toString()}`);
    },
    enabled: !!channelId && enabled,
  });
}

// Provides member mutation behavior; React components use it to access or update application state.
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

// Provides approve member behavior; React components use it to access or update application state.
export function useApproveMember() {
  return useMemberMutation((channelId, userId) => `/channels/${channelId}/members/${userId}/approve`);
}

// Provides promote member behavior; React components use it to access or update application state.
export function usePromoteMember() {
  return useMemberMutation((channelId, userId) => `/channels/${channelId}/members/${userId}/promote`);
}

// Provides demote member behavior; React components use it to access or update application state.
export function useDemoteMember() {
  return useMemberMutation((channelId, userId) => `/channels/${channelId}/members/${userId}/demote`);
}

// Provides remove member behavior; React components use it to access or update application state.
export function useRemoveMember() {
  return useMemberMutation((channelId, userId) => `/channels/${channelId}/members/${userId}`, 'DELETE');
}

// Provides update admin permissions behavior; React components use it to access or update application state.
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
