import React, { createContext, useContext, useEffect, useRef, useState } from 'react';
import { useAuthStore } from '../store/authStore';
import { useQueryClient } from '@tanstack/react-query';
import { ChannelResponse, MessageResponse } from '../types/api';
import { getWsUrl } from '@/services/api/runtime';
import { isChannelListQueryKey } from '@/hooks/query-keys';

interface WSContextType {
  status: 'connecting' | 'connected' | 'disconnected';
  emit: (type: string, payload: any) => void;
}

const WSContext = createContext<WSContextType>({ status: 'disconnected', emit: () => {} });

// Renders the wsprovider component; React components use it to access or update application state.
export function WSProvider({ children }: { children: React.ReactNode }) {
  const { accessToken, isAuthenticated, user } = useAuthStore();
  const queryClient = useQueryClient();
  const [status, setStatus] = useState<'connecting' | 'connected' | 'disconnected'>('disconnected');
  const ws = useRef<WebSocket | null>(null);
  const reconnectAttempt = useRef(0);
  const reconnectTimer = useRef<number | null>(null);
  const shouldReconnect = useRef(false);
  const maxBackoff = 30000;

  useEffect(() => {
    // Run this conditional step only when `!isAuthenticated || !accessToken` is true.
    if (!isAuthenticated || !accessToken) {
      shouldReconnect.current = false;
      // Run this conditional step only when `reconnectTimer.current !== null` is true.
      if (reconnectTimer.current !== null) {
        window.clearTimeout(reconnectTimer.current);
        reconnectTimer.current = null;
      }
      // Run this conditional step only when `ws.current` is true.
      if (ws.current) {
        ws.current.close();
        ws.current = null;
      }
      setStatus('disconnected');
      return;
    }

    let isUnmounted = false;
    shouldReconnect.current = true;

    // Connects; React components use it to access or update application state.
    const connect = () => {
      // Return early when `isUnmounted || !shouldReconnect.current` because the remaining work is not applicable.
      if (isUnmounted || !shouldReconnect.current) return;
      setStatus('connecting');
      const wsUrl = getWsUrl(accessToken);
      ws.current = new WebSocket(wsUrl);

      ws.current.onopen = () => {
        setStatus('connected');
        reconnectAttempt.current = 0;
        // Run this conditional step only when `reconnectTimer.current !== null` is true.
        if (reconnectTimer.current !== null) {
          window.clearTimeout(reconnectTimer.current);
          reconnectTimer.current = null;
        }
      };

      ws.current.onmessage = (event) => {
        // Attempt this operation and recover from expected failures in the catch block below.
        try {
          const data = JSON.parse(event.data) as { type?: string; payload?: any };
          const payload = data.payload;
          const activeChannelId = window.location.pathname.match(/\/app\/channels\/([^/]+)/)?.[1] ?? null;

          const updateChannelCaches = (
            channelId: string,
            updater: (channel: ChannelResponse) => ChannelResponse
          ) => {
            queryClient.setQueryData(
              ['/channels', channelId],
              (old: ChannelResponse | undefined) => (old ? updater(old) : old)
            );
            queryClient.setQueriesData(
              { predicate: (query) => isChannelListQueryKey(query.queryKey) },
              (old: ChannelResponse[] | undefined) =>
                Array.isArray(old)
                  ? old.map((channel) => (channel.id === channelId ? updater(channel) : channel))
                  : old
            );
          };

          // Choose the appropriate path based on whether `data.type === 'sync' && payload?.messages` is true.
          if (data.type === 'sync' && payload?.messages) {
            // Process each item from `payload.messages as MessageResponse[]` so this step covers the collection.
            for (const msg of payload.messages as MessageResponse[]) {
              queryClient.setQueryData(
                ['/channels', msg.channel_id, 'messages'],
                (old: MessageResponse[] | undefined) => {
                  const items = old ?? [];
                  return items.some((item) => item.id === msg.id) ? items : [...items, msg].sort((a, b) => a.seq_id - b.seq_id);
                }
              );
              updateChannelCaches(msg.channel_id, (channel) => {
                const lastSeenSeqId = channel.my_last_seen_seq_id ?? 0;
                const isReplyMessage = !!(msg.reply_to_message_id || msg.reply_to_seq_id);
                const isUnread =
                  msg.sender_user_id !== user?.id &&
                  msg.seq_id > lastSeenSeqId &&
                  activeChannelId !== msg.channel_id &&
                  !isReplyMessage;
                return {
                  ...channel,
                  last_message: msg,
                  last_message_at: msg.created_at,
                  unread_count: isUnread ? channel.unread_count + 1 : channel.unread_count,
                };
              });
            }
          // Otherwise, update cached channel messages for create or edit events.
          } else if (data.type === 'message' || data.type === 'message_updated') {
            const msg = payload as MessageResponse;
            queryClient.setQueryData(
              ['/channels', msg.channel_id, 'messages'],
              (old: MessageResponse[] | undefined) => {
                const items = old ?? [];
                return items.filter((item) => item.id !== msg.id).concat(msg).sort((a, b) => a.seq_id - b.seq_id);
              }
            );
            updateChannelCaches(msg.channel_id, (channel) => {
              const isOwnMessage = msg.sender_user_id === user?.id;
              const isReplyMessage = !!(msg.reply_to_message_id || msg.reply_to_seq_id);
              const lastSeenSeqId = channel.my_last_seen_seq_id ?? 0;
              const shouldIncrementUnread =
                data.type === 'message' &&
                !isOwnMessage &&
                msg.seq_id > lastSeenSeqId &&
                activeChannelId !== msg.channel_id &&
                !isReplyMessage;

              return {
                ...channel,
                last_message: msg,
                last_message_at: msg.created_at,
                unread_count: shouldIncrementUnread ? channel.unread_count + 1 : channel.unread_count,
              };
            });
          // Otherwise, merge seen-state updates into the cached channel summary.
          } else if (data.type === 'seen') {
            const seenState = payload as {
              channel_id: string;
              user_id: string;
              last_seen_seq_id?: number | null;
              unread_count?: number | null;
            };

            // Run this conditional step only when `seenState.user_id === user?.id` is true.
            if (seenState.user_id === user?.id) {
              updateChannelCaches(seenState.channel_id, (channel) => ({
                ...channel,
                my_last_seen_seq_id: seenState.last_seen_seq_id ?? channel.my_last_seen_seq_id ?? null,
                unread_count: seenState.unread_count ?? 0,
              }));
            }
          // Otherwise, refresh the affected message when its reactions change.
          } else if (data.type === 'reaction_updated') {
            const reactionEvent = payload as {
              channel_id: string;
              message_id: string;
              reactions_summary: {
                counts: Record<string, number>;
                my_reaction: string[];
              };
            };

            queryClient.setQueryData(
              ['/channels', reactionEvent.channel_id, 'messages'],
              (old: MessageResponse[] | undefined) =>
                old?.map((message) =>
                  message.id === reactionEvent.message_id
                    ? {
                        ...message,
                        reactions_summary: {
                          counts: reactionEvent.reactions_summary?.counts ?? {},
                          my_reaction: reactionEvent.reactions_summary?.my_reaction ?? [],
                        },
                      }
                    : message
                )
            );
          // Otherwise, refresh channel data when channel or membership state changes.
          } else if (data.type === 'channel_updated' || data.type === 'membership_update') {
            queryClient.invalidateQueries({ queryKey: ['/channels'] });
            // Run this conditional step only when `data.type === 'membership_update' && payload?.channel_id` is true.
            if (data.type === 'membership_update' && payload?.channel_id) {
              queryClient.invalidateQueries({ queryKey: ['/channels', payload.channel_id] });
              // Run this conditional step only when `payload.user_id === user?.id` is true.
              if (payload.user_id === user?.id) {
                // Choose the appropriate path based on whether `['owner', 'admin', 'member'].includes(payload.new_role)` is true.
                if (['owner', 'admin', 'member'].includes(payload.new_role)) {
                  ws.current?.send(JSON.stringify({
                    type: 'subscribe',
                    payload: { channel_ids: [payload.channel_id], from_seq_id: 0 },
                    ts: new Date().toISOString(),
                  }));
                  queryClient.invalidateQueries({ queryKey: ['/channels', payload.channel_id, 'messages'] });
                // Handle the fallback path when the preceding condition is false.
                } else {
                  ws.current?.send(JSON.stringify({
                    type: 'unsubscribe',
                    payload: { channel_ids: [payload.channel_id] },
                    ts: new Date().toISOString(),
                  }));
                  queryClient.removeQueries({ queryKey: ['/channels', payload.channel_id, 'messages'] });
                }
              }
            }
          }
        // Recover from the attempted operation by applying this error-handling path.
        } catch (e) {
          console.error("WS Parse error", e);
        }
      };

      ws.current.onclose = () => {
        setStatus('disconnected');
        ws.current = null;
        // Run this conditional step only when `!isUnmounted && shouldReconnect.current` is true.
        if (!isUnmounted && shouldReconnect.current) {
          const backoff = Math.min(1000 * Math.pow(2, reconnectAttempt.current), maxBackoff);
          reconnectAttempt.current += 1;
          reconnectTimer.current = window.setTimeout(connect, backoff);
        }
      };
    };

    connect();

    return () => {
      isUnmounted = true;
      shouldReconnect.current = false;
      // Run this conditional step only when `reconnectTimer.current !== null` is true.
      if (reconnectTimer.current !== null) {
        window.clearTimeout(reconnectTimer.current);
        reconnectTimer.current = null;
      }
      // Run this conditional step only when `ws.current` is true.
      if (ws.current) {
        ws.current.close();
        ws.current = null;
      }
    };
  }, [isAuthenticated, accessToken, queryClient, user?.id]);

  // Emits; React components use it to access or update application state.
  const emit = (type: string, payload: any) => {
    // Run this conditional step only when `ws.current?.readyState === WebSocket.OPEN` is true.
    if (ws.current?.readyState === WebSocket.OPEN) {
      ws.current.send(JSON.stringify({ type, payload, ts: new Date().toISOString() }));
    }
  };

  return (
    <WSContext.Provider value={{ status, emit }}>
      {children}
    </WSContext.Provider>
  );
}

// Provides ws behavior; React components use it to access or update application state.
export const useWS = () => useContext(WSContext);
