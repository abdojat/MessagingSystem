import type { CSSProperties } from "react";
import { create } from "zustand";
import { createJSONStorage, persist } from "zustand/middleware";

export type ChatWallpaperId = "default" | "grid" | "aurora" | "paper" | "dots" | "meadow";

export interface ChatWallpaperOption {
  id: ChatWallpaperId;
  style: CSSProperties;
}

export const DEFAULT_CHAT_WALLPAPER_ID: ChatWallpaperId = "default";

export const CHAT_WALLPAPERS: ChatWallpaperOption[] = [
  {
    id: "default",
    style: {
      backgroundColor: "hsl(var(--background))",
      backgroundImage: "linear-gradient(180deg, hsl(var(--background)) 0%, hsl(var(--background) / 0.5) 100%)",
    },
  },
  {
    id: "grid",
    style: {
      backgroundColor: "hsl(var(--background))",
      backgroundImage:
        "linear-gradient(hsl(var(--border) / 0.48) 1px, transparent 1px), linear-gradient(90deg, hsl(var(--border) / 0.48) 1px, transparent 1px), linear-gradient(135deg, hsl(var(--background)) 0%, hsl(var(--muted) / 0.72) 100%)",
      backgroundSize: "28px 28px, 28px 28px, auto",
    },
  },
  {
    id: "aurora",
    style: {
      backgroundColor: "hsl(var(--background))",
      backgroundImage:
        "radial-gradient(circle at 12% 18%, hsl(174 72% 42% / 0.18), transparent 30%), radial-gradient(circle at 88% 12%, hsl(30 92% 56% / 0.14), transparent 26%), radial-gradient(circle at 70% 86%, hsl(334 72% 58% / 0.1), transparent 28%), linear-gradient(160deg, hsl(var(--background)) 0%, hsl(var(--muted) / 0.72) 100%)",
    },
  },
  {
    id: "paper",
    style: {
      backgroundColor: "hsl(var(--background))",
      backgroundImage:
        "linear-gradient(90deg, hsl(0 72% 52% / 0.09) 0 1px, transparent 1px), repeating-linear-gradient(180deg, transparent 0 31px, hsl(207 75% 48% / 0.13) 31px 32px), linear-gradient(180deg, hsl(var(--background)) 0%, hsl(var(--secondary) / 0.76) 100%)",
      backgroundPosition: "64px 0, 0 0, 0 0",
      backgroundSize: "1px 100%, 100% 32px, auto",
    },
  },
  {
    id: "dots",
    style: {
      backgroundColor: "hsl(var(--background))",
      backgroundImage:
        "radial-gradient(circle, hsl(var(--primary) / 0.18) 1px, transparent 1.5px), radial-gradient(circle at 80% 22%, hsl(24 92% 56% / 0.12), transparent 24%), linear-gradient(180deg, hsl(var(--background)) 0%, hsl(var(--muted) / 0.66) 100%)",
      backgroundSize: "22px 22px, auto, auto",
    },
  },
  {
    id: "meadow",
    style: {
      backgroundColor: "hsl(var(--background))",
      backgroundImage:
        "radial-gradient(circle at 16% 18%, hsl(142 58% 42% / 0.14), transparent 30%), radial-gradient(circle at 84% 72%, hsl(45 92% 48% / 0.14), transparent 28%), radial-gradient(circle at 70% 18%, hsl(199 78% 48% / 0.1), transparent 26%), linear-gradient(145deg, hsl(var(--background)) 0%, hsl(var(--muted) / 0.7) 100%)",
    },
  },
];

// Retrieves chat wallpaper by id; hooks and components use it to read or update shared client state.
export function getChatWallpaperById(id: string | null | undefined): ChatWallpaperOption {
  return CHAT_WALLPAPERS.find((wallpaper) => wallpaper.id === id) ?? CHAT_WALLPAPERS[0];
}

interface ChatPreferencesState {
  chatWallpaperId: ChatWallpaperId;
  chatWallpaperByUserId: Record<string, ChatWallpaperId>;
  setChatWallpaperId: (wallpaperId: ChatWallpaperId) => void;
  setChatWallpaperForUser: (userId: string, wallpaperId: ChatWallpaperId) => void;
}

export const useChatPreferencesStore = create<ChatPreferencesState>()(
  persist(
    (set) => ({
      chatWallpaperId: DEFAULT_CHAT_WALLPAPER_ID,
      chatWallpaperByUserId: {},
      setChatWallpaperId: (chatWallpaperId) => set({ chatWallpaperId }),
      setChatWallpaperForUser: (userId, chatWallpaperId) =>
        set((state) => ({
          chatWallpaperByUserId: {
            ...state.chatWallpaperByUserId,
            [userId]: chatWallpaperId,
          },
        })),
    }),
    {
      name: "chatcore-chat-preferences",
      storage: createJSONStorage(() => localStorage),
    },
  ),
);
