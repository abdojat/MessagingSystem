import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { apiClient } from '@/services/api/client';
import { AttachmentItem, ChannelResponse, MessageResponse, ReactionSummaryResponse } from '../types/api';
import { isChannelListQueryKey } from '@/hooks/query-keys';

// Provides messages behavior; React components use it to access or update application state.
export function useMessages(channelId: string) {
  return useQuery({
    queryKey: ['/channels', channelId, 'messages'],
    queryFn: () => apiClient<{items: MessageResponse[]}>(`/channels/${channelId}/messages?order=desc&limit=50`).then(res => res.items.reverse()),
    enabled: !!channelId
  });
}

// Provides send message behavior; React components use it to access or update application state.
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
      // Run this conditional step only when `content_text?.trim()` is true.
      if (content_text?.trim()) {
        body.content_text = content_text;
      }
      // Run this conditional step only when `attachments?.length` is true.
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
        { predicate: (query) => isChannelListQueryKey(query.queryKey) },
        (old: ChannelResponse[] | undefined) =>
          Array.isArray(old)
            ? old.map((channel) =>
                channel.id === variables.channelId
                  ? {
                      ...channel,
                      last_message: newMessage,
                      last_message_at: newMessage.created_at,
                    }
                  : channel
              )
            : old
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

// Provides mark seen behavior; React components use it to access or update application state.
export function useMarkSeen() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ channelId, lastSeenSeqId }: { channelId: string; lastSeenSeqId: number }) =>
      apiClient<SeenResponse>(`/channels/${channelId}/seen`, {
        method: 'POST',
        body: JSON.stringify({ last_seen_seq_id: lastSeenSeqId }),
      }),
    onSuccess: (seenState, variables) => {
      // Applies seen state; React components use it to access or update application state.
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
        { predicate: (query) => isChannelListQueryKey(query.queryKey) },
        (old: ChannelResponse[] | undefined) =>
          Array.isArray(old)
            ? old.map((channel) => (channel.id === variables.channelId ? applySeenState(channel) : channel))
            : old
      );
    },
  });
}

// Provides toggle reaction behavior; React components use it to access or update application state.
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
      // Return early when `remove` because the remaining work is not applicable.
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
        // Return early when `!old` because the remaining work is not applicable.
        if (!old) return old;
        return old.map((message) => {
          // Return early when `message.id !== variables.messageId` because the remaining work is not applicable.
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
          // Choose the appropriate path based on whether `nextCountValue === 0` is true.
          if (nextCountValue === 0) {
            delete nextCounts[variables.emoji];
          // Handle the fallback path when the preceding condition is false.
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
      // Run this conditional step only when `context?.previousMessages` is true.
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
