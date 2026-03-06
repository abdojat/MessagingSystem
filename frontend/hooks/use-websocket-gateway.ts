"use client";

import { useEffect, useMemo, useRef } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { API_BASE_URL, toWebSocketUrl } from "@/lib/env";
import { queryKeys } from "@/lib/query-keys";
import { getAccessToken, useAuthStore } from "@/store/auth-store";
import { useAppUiStore } from "@/store/app-ui-store";
import { useSync } from "@/hooks/use-sync";
import type { ChannelResponse, MessageListResponse, MessageResponse, WsEnvelope } from "@/types/api";

function upsertMessage(items: MessageResponse[], incoming: MessageResponse) {
  const existingIndex = items.findIndex((m) => m.id === incoming.id || (incoming.client_msg_id && m.client_msg_id === incoming.client_msg_id));
  if (existingIndex >= 0) {
    const clone = [...items];
    clone[existingIndex] = incoming;
    return clone;
  }
  return [incoming, ...items].sort((a, b) => b.seq_id - a.seq_id);
}

export function useWebSocketGateway() {
  const status = useAuthStore((s) => s.status);
  const setWsStatus = useAppUiStore((s) => s.setWsStatus);
  const activeChannel = useAppUiStore((s) => s.currentChannelId);
  const queryClient = useQueryClient();
  const syncMutation = useSync();

  const wsRef = useRef<WebSocket | null>(null);
  const reconnectAttempt = useRef(0);
  const reconnectTimer = useRef<NodeJS.Timeout | null>(null);
  const activeChannelRef = useRef<string | null>(activeChannel);
  const wsUrl = useMemo(() => toWebSocketUrl(API_BASE_URL), []);
  const triggerSync = syncMutation.mutate;

  useEffect(() => {
    activeChannelRef.current = activeChannel;
  }, [activeChannel]);

  useEffect(() => {
    if (status !== "authenticated") {
      if (wsRef.current) {
        wsRef.current.close();
        wsRef.current = null;
      }
      setWsStatus("disconnected");
      return;
    }

    let isUnmounted = false;

    const connect = () => {
      if (isUnmounted) return;
      setWsStatus(reconnectAttempt.current > 0 ? "reconnecting" : "connecting");

      const ws = new WebSocket(wsUrl);
      wsRef.current = ws;

        ws.onopen = () => {
          reconnectAttempt.current = 0;
          setWsStatus("connected");
          const token = getAccessToken();
          ws.send(JSON.stringify({ type: "auth", payload: { token } }));
          triggerSync();
        };

      ws.onclose = () => {
        if (isUnmounted) return;
        setWsStatus("disconnected");
        reconnectAttempt.current += 1;
        const delay = Math.min(30_000, 1_000 * 2 ** reconnectAttempt.current);
        reconnectTimer.current = setTimeout(connect, delay);
      };

      ws.onerror = () => {
        setWsStatus("reconnecting");
      };

      ws.onmessage = (event) => {
        try {
          const envelope = JSON.parse(event.data) as WsEnvelope;
          if (envelope.type === "message") {
            queryClient.setQueryData(
              queryKeys.messages(envelope.channel_id),
              (current:
                | {
                    pages: MessageListResponse[];
                    pageParams: Array<number | undefined>;
                  }
                | undefined) => {
                if (!current) return current;
                const first = current.pages[0];
                if (!first) return current;
                const updatedFirst: MessageListResponse = {
                  ...first,
                  items: upsertMessage(first.items, envelope.message),
                };
                return { ...current, pages: [updatedFirst, ...current.pages.slice(1)] };
              },
            );

            queryClient.setQueriesData<{ items: ChannelResponse[] }>(
              { queryKey: ["channels"] },
              (current) => {
                if (!current) return current;
                return {
                  ...current,
                  items: current.items.map((channel) => {
                    if (channel.id !== envelope.channel_id) return channel;
                    const isOpen = activeChannelRef.current === channel.id;
                    return {
                      ...channel,
                      last_message: envelope.message,
                      last_message_at: envelope.message.created_at,
                      unread_count: isOpen ? channel.unread_count : channel.unread_count + 1,
                    };
                  }),
                };
              },
            );
            return;
          }

          if (envelope.type === "seen") {
            queryClient.setQueriesData<{ items: ChannelResponse[] }>({ queryKey: ["channels"] }, (current) => {
              if (!current) return current;
              return {
                ...current,
                items: current.items.map((channel) =>
                  channel.id === envelope.channel_id
                    ? {
                        ...channel,
                        my_last_seen_seq_id: envelope.last_seen_seq_id,
                        unread_count: 0,
                      }
                    : channel,
                ),
              };
            });
            return;
          }

          if (envelope.type === "membership_update" || envelope.type === "channel_updated" || envelope.type === "sync") {
            queryClient.invalidateQueries({ queryKey: ["channels"] });
            return;
          }

          if (envelope.type === "error") {
            toast.error(envelope.message ?? "Realtime error");
          }
        } catch {
          toast.error("Failed to process realtime message");
        }
      };
    };

    connect();

    const onVisible = () => {
      if (document.visibilityState === "visible") {
        triggerSync();
      }
    };

    document.addEventListener("visibilitychange", onVisible);

    return () => {
      isUnmounted = true;
      document.removeEventListener("visibilitychange", onVisible);
      if (reconnectTimer.current) {
        clearTimeout(reconnectTimer.current);
      }
      if (wsRef.current) {
        wsRef.current.close();
      }
    };
  }, [status, wsUrl, setWsStatus, triggerSync, queryClient]);
}

