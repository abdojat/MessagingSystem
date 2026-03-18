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
  const { accessToken, isAuthenticated } = useAuthStore();
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

          if (data.type === 'sync' && payload?.messages) {
            for (const msg of payload.messages as MessageResponse[]) {
              queryClient.setQueryData(
                ['/channels', msg.channel_id, 'messages'],
                (old: MessageResponse[] | undefined) => {
                  const items = old ?? [];
                  return items.some((item) => item.id === msg.id) ? items : [...items, msg].sort((a, b) => a.seq_id - b.seq_id);
                }
              );
            }
            queryClient.invalidateQueries({ queryKey: ['/channels'] });
          } else if (data.type === 'message' || data.type === 'message_updated') {
            const msg = payload as MessageResponse;
            queryClient.setQueryData(
              ['/channels', msg.channel_id, 'messages'],
              (old: MessageResponse[] | undefined) => {
                const items = old ?? [];
                return items.filter((item) => item.id !== msg.id).concat(msg).sort((a, b) => a.seq_id - b.seq_id);
              }
            );
            queryClient.setQueryData(
              ['/channels', msg.channel_id],
              (old: ChannelResponse | undefined) => old ? { ...old, last_message: msg, last_message_at: msg.created_at } : old
            );
            queryClient.invalidateQueries({ queryKey: ['/channels'] });
          } else if (data.type === 'channel_updated' || data.type === 'membership_update' || data.type === 'seen') {
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
  }, [isAuthenticated, accessToken, queryClient]);

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
