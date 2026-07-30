import { useQuery } from '@tanstack/react-query';
import { apiClient } from '@/services/api/client';
import type { EventIntegrityResponse, EventListResponse } from '@/types/api';

export function useChannelEvents(channelId: string, limit = 25, enabled = true) {
  return useQuery({
    queryKey: ['/channels', channelId, 'events', { limit }],
    queryFn: () => apiClient<EventListResponse>(`/channels/${channelId}/events?limit=${limit}`),
    enabled: !!channelId && enabled,
  });
}

export function useChannelEventIntegrity(channelId: string, enabled = false) {
  return useQuery({
    queryKey: ['/channels', channelId, 'events', 'integrity'],
    queryFn: () => apiClient<EventIntegrityResponse>(`/channels/${channelId}/events/integrity`),
    enabled: !!channelId && enabled,
  });
}
