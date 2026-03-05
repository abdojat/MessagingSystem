"use client";

import { create } from "zustand";

type ConnectionStatus = "disconnected" | "connecting" | "connected" | "reconnecting";

type AppUiState = {
  currentChannelId: string | null;
  wsStatus: ConnectionStatus;
  replyToMessageId: string | null;
  replyToSeqId: number | null;
  setCurrentChannel: (channelId: string | null) => void;
  setWsStatus: (status: ConnectionStatus) => void;
  setReplyTarget: (payload: { messageId: string; seqId: number } | null) => void;
};

export const useAppUiStore = create<AppUiState>((set) => ({
  currentChannelId: null,
  wsStatus: "disconnected",
  replyToMessageId: null,
  replyToSeqId: null,
  setCurrentChannel: (currentChannelId) => set({ currentChannelId }),
  setWsStatus: (wsStatus) => set({ wsStatus }),
  setReplyTarget: (payload) =>
    set({ replyToMessageId: payload?.messageId ?? null, replyToSeqId: payload?.seqId ?? null }),
}));

