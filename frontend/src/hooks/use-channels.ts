import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { apiClient } from '@/services/api/client';
import {
  AdminPermissionsUpdateRequest,
  AdminPermissionsUpdateResponse,
  ChannelInviteResponse,
  ChannelListResponse,
  ChannelMembershipListResponse,
  ChannelPatchRequest,
  ChannelResponse,
  JoinOutcomeResponse,
} from '../types/api';
import { useWS } from '@/hooks/use-websocket';
import { isChannelListQueryKey } from '@/hooks/query-keys';

type ChannelScope = 'my' | 'discover';
type ChannelVisibilityFilter = 'public' | 'private';

const CHANNEL_PAGE_LIMIT = 200;
const MAX_CHANNEL_LIST_PAGES = 25;

interface UseChannelsOptions {
  scope?: ChannelScope;
  q?: string;
  visibility?: ChannelVisibilityFilter;
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
  const visibility = options.visibility;
  const enabled = options.enabled ?? true;

  return useQuery({
    queryKey: ['/channels', { scope, q, visibility: visibility ?? null }],
    queryFn: async () => {
      const items: ChannelResponse[] = [];
      let cursor: string | null | undefined = null;
      let pageCount = 0;

      do {
        const params = new URLSearchParams();
        params.set('scope', scope);
        params.set('limit', String(CHANNEL_PAGE_LIMIT));
        if (q) params.set('q', q);
        if (visibility) params.set('visibility', visibility);
        if (cursor) params.set('cursor', cursor);

        const page = await apiClient<ChannelListResponse>(`/channels?${params.toString()}`);
        items.push(...page.items);
        cursor = page.has_more ? page.next_cursor : null;
        pageCount += 1;
      } while (cursor && pageCount < MAX_CHANNEL_LIST_PAGES);

      return items;
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
        predicate: (query) => isChannelListQueryKey(query.queryKey),
      });

      for (const [, channels] of channelQueries) {
        if (!Array.isArray(channels)) continue;
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
  const { emit } = useWS();
  return useMutation({
    mutationFn: (channelId: string) => apiClient<JoinOutcomeResponse>(`/channels/${channelId}/join`, { method: 'POST', body: JSON.stringify({}) }),
    onSuccess: (outcome, channelId) => {
      queryClient.invalidateQueries({ queryKey: ['/channels'] });
      queryClient.invalidateQueries({ queryKey: ['/channels', channelId] });
      queryClient.invalidateQueries({ queryKey: ['/channels', channelId, 'messages'] });
      if (outcome.status === 'joined' || outcome.status === 'already_member') {
        emit('subscribe', { channel_ids: [channelId], from_seq_id: 0 });
      }
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

export function useCreateChannelInvite() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (channelId: string) =>
      apiClient<ChannelInviteResponse>(`/channels/${channelId}/invite`, {
        method: 'POST',
        body: JSON.stringify({ is_generic: true }),
      }),
    onSuccess: (_, channelId) => {
      queryClient.invalidateQueries({ queryKey: ['/channels', channelId, 'events'] });
    },
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
