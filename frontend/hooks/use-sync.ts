"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api-client";
import { queryKeys } from "@/lib/query-keys";
import type { ChannelResponse, MessageListResponse, MessageResponse } from "@/types/api";

function upsertMessage(items: MessageResponse[], incoming: MessageResponse) {
  const existing = items.findIndex((item) => item.id === incoming.id || (incoming.client_msg_id && item.client_msg_id === incoming.client_msg_id));
  if (existing >= 0) {
    const copy = [...items];
    copy[existing] = incoming;
    return copy;
  }
  return [incoming, ...items].sort((a, b) => b.seq_id - a.seq_id);
}

export function useSync() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async () => {
      const channels = queryClient.getQueriesData<{ items: ChannelResponse[] }>({ queryKey: ["channels"] });
      const merged = channels.flatMap(([, data]) => data?.items ?? []);
      const seenByChannel = new Map<string, number | null>();
      merged.forEach((channel) => {
        seenByChannel.set(channel.id, channel.my_last_seen_seq_id ?? 0);
      });
      return api.sync({
        channels: Array.from(seenByChannel.entries()).map(([channel_id, last_seen_seq_id]) => ({ channel_id, last_seen_seq_id })),
        limit: 300,
      });
    },
    onSuccess: (result) => {
      if (result.channel_updates.length > 0 || result.membership_updates.length > 0) {
        queryClient.invalidateQueries({ queryKey: ["channels"] });
      }

      for (const message of result.messages) {
        queryClient.setQueryData(
          queryKeys.messages(message.channel_id),
          (current:
            | {
                pages: MessageListResponse[];
                pageParams: Array<number | undefined>;
              }
            | undefined) => {
            if (!current) return current;
            const firstPage = current.pages[0];
            if (!firstPage) return current;
            const updatedFirst: MessageListResponse = {
              ...firstPage,
              items: upsertMessage(firstPage.items, message),
            };
            return { ...current, pages: [updatedFirst, ...current.pages.slice(1)] };
          },
        );
      }
    },
  });
}

