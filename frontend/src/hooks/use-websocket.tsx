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
    if (!isAuthenticated || !accessToken) {
      shouldReconnect.current = false;
      if (reconnectTimer.current !== null) {
        window.clearTimeout(reconnectTimer.current);
        reconnectTimer.current = null;
      }
      if (ws.current) {
        ws.current.close();
        ws.current = null;
      }
      setStatus('disconnected');
      return;
    }

    let isUnmounted = false;
    shouldReconnect.current = true;

    const connect = () => {
      if (isUnmounted || !shouldReconnect.current) return;
      setStatus('connecting');
      const wsUrl = getWsUrl(accessToken);
      ws.current = new WebSocket(wsUrl);

      ws.current.onopen = () => {
        setStatus('connected');
        reconnectAttempt.current = 0;
        if (reconnectTimer.current !== null) {
          window.clearTimeout(reconnectTimer.current);
          reconnectTimer.current = null;
        }
      };

      ws.current.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data) as { type?: string; payload?: any };
          const payload = data.payload;
          const activeChannelId = window.location.pathname.match(/\/app\/channels\/([^/]+)/)?.[1] ?? null;

          // Applies one channel update to both its detail cache and every cached
          // channel list so WebSocket events remain consistent across the UI.
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

          if (data.type === 'sync' && payload?.messages) {
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
          } else if (data.type === 'seen') {
            const seenState = payload as {
              channel_id: string;
              user_id: string;
              last_seen_seq_id?: number | null;
              unread_count?: number | null;
            };

            if (seenState.user_id === user?.id) {
              updateChannelCaches(seenState.channel_id, (channel) => ({
                ...channel,
                my_last_seen_seq_id: seenState.last_seen_seq_id ?? channel.my_last_seen_seq_id ?? null,
                unread_count: seenState.unread_count ?? 0,
              }));
            }
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
          } else if (data.type === 'channel_updated' || data.type === 'membership_update') {
            queryClient.invalidateQueries({ queryKey: ['/channels'] });
            if (data.type === 'membership_update' && payload?.channel_id) {
              queryClient.invalidateQueries({ queryKey: ['/channels', payload.channel_id] });
              if (payload.user_id === user?.id) {
                // Membership changes alter which broker-backed channels this
                // socket is allowed to receive, so resubscribe immediately.
                if (['owner', 'admin', 'member'].includes(payload.new_role)) {
                  ws.current?.send(JSON.stringify({
                    type: 'subscribe',
                    payload: { channel_ids: [payload.channel_id], from_seq_id: 0 },
                    ts: new Date().toISOString(),
                  }));
                  queryClient.invalidateQueries({ queryKey: ['/channels', payload.channel_id, 'messages'] });
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
        } catch (e) {
          console.error("WS Parse error", e);
        }
      };

      ws.current.onclose = () => {
        setStatus('disconnected');
        ws.current = null;
        if (!isUnmounted && shouldReconnect.current) {
          // Exponential backoff keeps reconnects responsive at first without
          // hammering the backend during a longer outage.
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
      if (reconnectTimer.current !== null) {
        window.clearTimeout(reconnectTimer.current);
        reconnectTimer.current = null;
      }
      if (ws.current) {
        ws.current.close();
        ws.current = null;
      }
    };
  }, [isAuthenticated, accessToken, queryClient, user?.id]);

  const emit = (type: string, payload: any) => {
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

export const useWS = () => useContext(WSContext);
