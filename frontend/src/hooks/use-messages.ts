import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { apiClient } from '@/services/api/client';
import { AttachmentItem, ChannelResponse, MessageResponse, ReactionSummaryResponse } from '../types/api';

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
    content_text?: string | null;
    attachments?: Pick<AttachmentItem, "file_id">[] | null;
    reply_to_message_id?: string | null;
    reply_to_seq_id?: number | null;
  };

  return useMutation({
    mutationFn: ({ channelId, content_text, attachments, reply_to_message_id, reply_to_seq_id }: SendMessageInput) => {
      const body: Record<string, unknown> = {
        reply_to_message_id,
        reply_to_seq_id,
      };
      if (content_text?.trim()) {
        body.content_text = content_text;
      }
      if (attachments?.length) {
        body.attachments = attachments;
      }
      return apiClient<MessageResponse>(`/channels/${channelId}/messages`, {
        method: 'POST',
        body: JSON.stringify(body),
      });
    },
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

export function useToggleReaction() {
  const queryClient = useQueryClient();

  type ToggleReactionInput = {
    channelId: string;
    messageId: string;
    emoji: string;
    remove?: boolean;
  };

  return useMutation({
    mutationFn: async ({ channelId, messageId, emoji, remove }: ToggleReactionInput) => {
      if (remove) {
        return apiClient<ReactionSummaryResponse>(
          `/channels/${channelId}/messages/${messageId}/reactions/${encodeURIComponent(emoji)}`,
          { method: 'DELETE' }
        );
      }
      return apiClient<ReactionSummaryResponse>(`/channels/${channelId}/messages/${messageId}/reactions`, {
        method: 'POST',
        body: JSON.stringify({ emoji }),
      });
    },
    onMutate: async (variables) => {
      const queryKey = ['/channels', variables.channelId, 'messages'] as const;
      await queryClient.cancelQueries({ queryKey });
      const previousMessages = queryClient.getQueryData<MessageResponse[]>(queryKey);

      queryClient.setQueryData<MessageResponse[]>(queryKey, (old) => {
        if (!old) return old;
        return old.map((message) => {
          if (message.id !== variables.messageId) return message;
          const prevCounts = message.reactions_summary?.counts ?? {};
          const prevMine = message.reactions_summary?.my_reaction ?? [];
          const currentlyReacted = prevMine.includes(variables.emoji);
          const shouldRemove = variables.remove ?? currentlyReacted;

          const nextMine = shouldRemove
            ? prevMine.filter((item) => item !== variables.emoji)
            : Array.from(new Set([...prevMine, variables.emoji]));
          const nextCountValue = Math.max(0, (prevCounts[variables.emoji] ?? 0) + (shouldRemove ? -1 : 1));
          const nextCounts = { ...prevCounts };
          if (nextCountValue === 0) {
            delete nextCounts[variables.emoji];
          } else {
            nextCounts[variables.emoji] = nextCountValue;
          }

          return {
            ...message,
            reactions_summary: {
              counts: nextCounts,
              my_reaction: nextMine,
            },
          };
        });
      });

      return { previousMessages, queryKey };
    },
    onError: (_error, _variables, context) => {
      if (context?.previousMessages) {
        queryClient.setQueryData(context.queryKey, context.previousMessages);
      }
    },
    onSuccess: (summary, variables) => {
      queryClient.setQueryData<MessageResponse[]>(
        ['/channels', variables.channelId, 'messages'],
        (old) =>
          old?.map((message) =>
            message.id === variables.messageId
              ? {
                  ...message,
                  reactions_summary: {
                    counts: summary.counts ?? {},
                    my_reaction: summary.my_reaction ?? [],
                  },
                }
              : message
          )
      );
    },
  });
}
