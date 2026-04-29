import { useQuery } from '@tanstack/react-query';
import { apiClient } from '@/services/api/client';
import type { EventListResponse } from '@/types/api';

export function useChannelEvents(channelId: string, limit = 25, enabled = true) {
  return useQuery({
    queryKey: ['/channels', channelId, 'events', { limit }],
    queryFn: () => apiClient<EventListResponse>(`/channels/${channelId}/events?limit=${limit}`),
    enabled: !!channelId && enabled,
  });
}
