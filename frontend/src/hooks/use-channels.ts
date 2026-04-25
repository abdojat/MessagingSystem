import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { apiClient } from '@/services/api/client';
import { ChannelResponse } from '../types/api';

type ChannelScope = 'my' | 'discover';

interface UseChannelsOptions {
  scope?: ChannelScope;
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
