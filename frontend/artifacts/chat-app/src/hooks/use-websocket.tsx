import React, { createContext, useContext, useEffect, useRef, useState } from 'react';
import { useAuthStore } from '../store/authStore';
import { useQueryClient } from '@tanstack/react-query';
import { ChannelResponse, MessageResponse } from '../types/api';

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
  const maxBackoff = 30000;

  useEffect(() => {
    if (!isAuthenticated || !accessToken) {
      if (ws.current) {
        ws.current.close();
        ws.current = null;
      }
      return;
    }

    let isUnmounted = false;

    const connect = () => {
      if (isUnmounted) return;
      setStatus('connecting');
      
      const apiBaseUrl = import.meta.env.VITE_API_BASE_URL || '/v1';
      const wsBase = apiBaseUrl.startsWith('http')
        ? apiBaseUrl.replace(/^http/, 'ws')
        : `${window.location.protocol === 'https:' ? 'wss' : 'ws'}://${window.location.host}${apiBaseUrl}`;
      const wsUrl = `${wsBase.replace(/\/$/, '')}/ws`;
      
      ws.current = new WebSocket(wsUrl);

      ws.current.onopen = () => {
        setStatus('connected');
        reconnectAttempt.current = 0;
      };

      ws.current.onmessage = (event) => {
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
            queryClient.setQueryData(
              ['/channels'],
              (old: ChannelResponse[] | undefined) =>
                old?.map((channel) => (channel.id === channelId ? updater(channel) : channel))
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
                const isUnread = msg.sender_user_id !== user?.id && msg.seq_id > lastSeenSeqId && activeChannelId !== msg.channel_id;
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
              const lastSeenSeqId = channel.my_last_seen_seq_id ?? 0;
              const shouldIncrementUnread =
                data.type === 'message' &&
                !isOwnMessage &&
                msg.seq_id > lastSeenSeqId &&
                activeChannelId !== msg.channel_id;

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
          } else if (data.type === 'channel_updated' || data.type === 'membership_update') {
            queryClient.invalidateQueries({ queryKey: ['/channels'] });
          }
        } catch (e) {
          console.error("WS Parse error", e);
        }
      };

      ws.current.onclose = () => {
        setStatus('disconnected');
        ws.current = null;
        if (!isUnmounted) {
          const backoff = Math.min(1000 * Math.pow(2, reconnectAttempt.current), maxBackoff);
          reconnectAttempt.current += 1;
          setTimeout(connect, backoff);
        }
      };
    };

    connect();

    return () => {
      isUnmounted = true;
      if (ws.current) {
        ws.current.close();
      }
    };
  }, [isAuthenticated, accessToken, queryClient, user?.id]);

  const emit = (type: string, payload: any) => {
    if (ws.current?.readyState === WebSocket.OPEN) {
      ws.current.send(JSON.stringify({ type, payload }));
    }
  };

  return (
    <WSContext.Provider value={{ status, emit }}>
      {children}
    </WSContext.Provider>
  );
}

export const useWS = () => useContext(WSContext);
