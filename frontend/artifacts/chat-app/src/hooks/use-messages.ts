import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { apiClient } from '../lib/apiClient';
import { MessageResponse } from '../types/api';

export function useMessages(channelId: string) {
  return useQuery({
    queryKey: ['/channels', channelId, 'messages'],
    queryFn: () => apiClient<{items: MessageResponse[]}>(`/channels/${channelId}/messages?order=desc&limit=50`).then(res => res.items.reverse()),
    enabled: !!channelId
  });
}

export function useSendMessage() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ channelId, content_text }: { channelId: string, content_text: string }) => 
      apiClient<MessageResponse>(`/channels/${channelId}/messages`, {
        method: 'POST',
        body: JSON.stringify({ content_text })
      }),
    onSuccess: (newMessage, variables) => {
      queryClient.setQueryData(
        ['/channels', variables.channelId, 'messages'],
        (old: MessageResponse[] | undefined) => old ? [...old, newMessage] : [newMessage]
      );
    }
  });
}
