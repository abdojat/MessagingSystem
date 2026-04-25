import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { apiClient } from '@/services/api/client';
import { ChannelResponse, MessageResponse } from '../types/api';

export function useMessages(channelId: string) {
  return useQuery({
    queryKey: ['/channels', channelId, 'messages'],
    queryFn: () => apiClient<{items: MessageResponse[]}>(`/channels/${channelId}/messages?order=desc&limit=50`).then(res => res.items.reverse()),
    enabled: !!channelId
  });
}

export function useSendMessage() {
  const queryClient = useQueryClient();

  type SendMessageInput = {
    channelId: string;
    content_text: string;
    reply_to_message_id?: string | null;
    reply_to_seq_id?: number | null;
  };

  return useMutation({
    mutationFn: ({ channelId, content_text, reply_to_message_id, reply_to_seq_id }: SendMessageInput) =>
      apiClient<MessageResponse>(`/channels/${channelId}/messages`, {
        method: 'POST',
        body: JSON.stringify({
          content_text,
          reply_to_message_id,
          reply_to_seq_id,
        }),
      }),
    onSuccess: (newMessage, variables) => {
      queryClient.setQueryData(
        ['/channels', variables.channelId, 'messages'],
        (old: MessageResponse[] | undefined) => old ? [...old, newMessage] : [newMessage]
      );
      queryClient.setQueryData(
        ['/channels', variables.channelId],
        (old: ChannelResponse | undefined) => old
          ? {
              ...old,
              last_message: newMessage,
              last_message_at: newMessage.created_at,
            }
          : old
      );
      queryClient.setQueriesData(
        { queryKey: ['/channels'] },
        (old: ChannelResponse[] | undefined) =>
          old?.map((channel) =>
            channel.id === variables.channelId
              ? {
                  ...channel,
                  last_message: newMessage,
                  last_message_at: newMessage.created_at,
                }
              : channel
          )
      );
    }
  });
}

interface SeenResponse {
  channel_id: string;
  user_id: string;
  last_seen_seq_id?: number | null;
  unread_count?: number | null;
}

export function useMarkSeen() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ channelId, lastSeenSeqId }: { channelId: string; lastSeenSeqId: number }) =>
      apiClient<SeenResponse>(`/channels/${channelId}/seen`, {
        method: 'POST',
        body: JSON.stringify({ last_seen_seq_id: lastSeenSeqId }),
      }),
    onSuccess: (seenState, variables) => {
      const applySeenState = (channel: ChannelResponse) => ({
        ...channel,
        my_last_seen_seq_id: seenState.last_seen_seq_id ?? variables.lastSeenSeqId,
        unread_count: seenState.unread_count ?? 0,
      });

      queryClient.setQueryData(
        ['/channels', variables.channelId],
        (old: ChannelResponse | undefined) => (old ? applySeenState(old) : old)
      );
      queryClient.setQueriesData(
        { queryKey: ['/channels'] },
        (old: ChannelResponse[] | undefined) =>
          old?.map((channel) => (channel.id === variables.channelId ? applySeenState(channel) : channel))
      );
    },
  });
}
