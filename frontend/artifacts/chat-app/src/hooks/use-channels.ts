import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { apiClient } from '../lib/apiClient';
import { ChannelResponse } from '../types/api';

export function useChannels() {
  return useQuery({
    queryKey: ['/channels'],
    queryFn: () => apiClient<{items: ChannelResponse[]}>('/channels').then(res => res.items)
  });
}

export function useChannel(channelId: string) {
  const queryClient = useQueryClient();

  return useQuery({
    queryKey: ['/channels', channelId],
    queryFn: () => apiClient<ChannelResponse>(`/channels/${channelId}`),
    initialData: () => {
      const channels = queryClient.getQueryData<ChannelResponse[]>(['/channels']);
      return channels?.find((channel) => channel.id === channelId);
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
