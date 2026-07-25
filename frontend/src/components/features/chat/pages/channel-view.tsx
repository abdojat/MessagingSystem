"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useChannel, useChannelMembers, useJoinChannel } from "@/hooks/use-channels";
import { useMarkSeen, useMessages, useSendMessage, useToggleReaction } from "@/hooks/use-messages";
import { Hash, Settings, Paperclip, Send, SmilePlus, Reply, MoreVertical, X, ChevronDown, ChevronRight, Copy, ArrowUpRight, ImageIcon, Video, Music2, Loader2, Check, UploadCloud, Trash2 } from "lucide-react";
import { useState, useRef, useEffect, type ReactNode } from "react";
import { useLocale, useTranslations } from "next-intl";
import { Button } from "@/components/ui/button";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { AuthenticatedImage } from "@/components/shared/AuthenticatedImage";
import { useAuthStore } from "@/store/authStore";
import { CHAT_WALLPAPERS, getChatWallpaperById, useChatPreferencesStore } from "@/store/chatPreferencesStore";
import { Skeleton } from "@/components/ui/skeleton";
import { toast } from "@/hooks/use-toast";
import type { AttachmentItem, MeResponse, MessageResponse, UpdateMeRequest, UploadContentResponse, UploadCreateResponse } from "@/types/api";
import { useLocalePath } from "@/components/features/chat/lib/locale-path";
import { isProtectedApiMediaUrl, resolveApiMediaUrl } from "@/lib/mediaUrl";
import { cn } from "@/lib/utils";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { apiClient } from "@/services/api/client";
import { getApiBaseUrl } from "@/services/api/runtime";

function ChannelViewSkeleton() {
  return (
    <div className="flex-1 flex flex-col h-full bg-background relative z-0">
      <header className="h-16 border-b border-border bg-background/80 backdrop-blur-md flex items-center justify-between px-6 flex-shrink-0 z-10">
        <div className="flex items-center gap-3">
          <Skeleton className="h-10 w-10 rounded-xl" />
          <div className="space-y-2">
            <Skeleton className="h-4 w-40" />
            <Skeleton className="h-3 w-56" />
          </div>
        </div>
        <Skeleton className="h-10 w-10 rounded-xl" />
      </header>

      <div className="flex-1 overflow-y-auto p-6 space-y-6 bg-gradient-to-b from-background to-background/50">
        {Array.from({ length: 6 }).map((_, index) => (
          <div key={index} className="flex gap-4">
            <Skeleton className="h-10 w-10 rounded-full flex-shrink-0" />
            <div className="flex-1 space-y-3">
              <div className="flex items-center gap-2">
                <Skeleton className="h-3 w-24" />
                <Skeleton className="h-3 w-16" />
              </div>
              <Skeleton className={`h-14 rounded-2xl ${index % 2 === 0 ? "w-80 max-w-full" : "w-64 max-w-full"}`} />
            </div>
          </div>
        ))}
      </div>

      <div className="p-4 bg-background border-t border-border flex-shrink-0">
        <div className="max-w-4xl mx-auto rounded-2xl border border-border/50 p-2 flex items-end gap-2">
          <Skeleton className="h-10 w-10 rounded-xl flex-shrink-0" />
          <Skeleton className="h-12 flex-1 rounded-xl" />
          <Skeleton className="h-10 w-10 rounded-xl flex-shrink-0" />
        </div>
      </div>
    </div>
  );
}
const MAX_REPLY_CHAIN_DEPTH = 12;
const QUICK_REACTIONS = ["\u{1F44D}", "\u{2764}\u{FE0F}", "\u{1F602}", "\u{1F62E}", "\u{1F389}", "\u{1F44E}"] as const;
const MEDIA_ACCEPT = "image/*,video/*,audio/*";
const MAX_MEDIA_ATTACHMENTS = 6;
const MAX_MEDIA_FILE_SIZE_BYTES = 25 * 1024 * 1024;
const MAX_WALLPAPER_FILE_SIZE_BYTES = 10 * 1024 * 1024;

type MediaKind = "image" | "video" | "audio";

type PendingMediaAttachment = {
  id: string;
  file: File;
  contentType: string;
  kind: MediaKind;
};

const MEDIA_EXTENSION_TYPES: Record<string, string> = {
  aac: "audio/aac",
  bmp: "image/bmp",
  flac: "audio/flac",
  gif: "image/gif",
  jpeg: "image/jpeg",
  jpg: "image/jpeg",
  m4a: "audio/mp4",
  mov: "video/quicktime",
  mp3: "audio/mpeg",
  mp4: "video/mp4",
  ogg: "audio/ogg",
  ogv: "video/ogg",
  png: "image/png",
  wav: "audio/wav",
  webm: "video/webm",
  webp: "image/webp",
};

function getMessageMediaKind(contentType?: string | null): MediaKind | null {
  const normalized = contentType?.toLowerCase() || "";
  if (normalized.startsWith("image/")) return "image";
  if (normalized.startsWith("video/")) return "video";
  if (normalized.startsWith("audio/")) return "audio";
  return null;
}

function inferMediaContentType(file: File): string | null {
  const declaredType = file.type?.toLowerCase();
  if (getMessageMediaKind(declaredType)) {
    return declaredType;
  }
  const extension = file.name.split(".").pop()?.toLowerCase() || "";
  const inferredType = MEDIA_EXTENSION_TYPES[extension];
  return getMessageMediaKind(inferredType) ? inferredType : null;
}

function createPendingAttachmentId(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  return `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function formatBytes(value?: number | null): string {
  if (!value || value < 1) return "";
  const units = ["B", "KB", "MB", "GB"];
  let size = value;
  let unitIndex = 0;
  while (size >= 1024 && unitIndex < units.length - 1) {
    size /= 1024;
    unitIndex += 1;
  }
  return `${size >= 10 || unitIndex === 0 ? size.toFixed(0) : size.toFixed(1)} ${units[unitIndex]}`;
}

function getAttachmentUrl(attachment: AttachmentItem): string | undefined {
  return resolveApiMediaUrl(attachment.url || attachment.public_url);
}

function getErrorMessage(error: unknown, fallback: string) {
  if (error instanceof Error && error.message) return error.message;
  return fallback;
}

function resolveUploadTargetUrl(uploadUrl: string): string {
  const apiBaseUrl = getApiBaseUrl();
  if (/^https?:\/\//i.test(uploadUrl)) {
    return uploadUrl;
  }
  if (/^https?:\/\//i.test(apiBaseUrl)) {
    return `${new URL(apiBaseUrl).origin}${uploadUrl.startsWith("/") ? uploadUrl : `/${uploadUrl}`}`;
  }
  return uploadUrl;
}

function cssUrl(value: string): string {
  return `url("${value.replace(/"/g, "%22")}")`;
}

function useAuthenticatedBackgroundImage(src?: string | null, accessToken?: string | null): string | undefined {
  const resolvedSrc = resolveApiMediaUrl(src);
  const needsAuth = isProtectedApiMediaUrl(resolvedSrc);
  const [objectUrl, setObjectUrl] = useState<string | undefined>();
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    setFailed(false);
    setObjectUrl(undefined);
  }, [resolvedSrc, needsAuth, accessToken]);

  useEffect(() => {
    if (!resolvedSrc || !needsAuth || !accessToken) {
      return;
    }

    const fetchSrc = resolvedSrc;
    const controller = new AbortController();
    let localObjectUrl: string | undefined;

    async function loadProtectedImage() {
      try {
        const response = await fetch(fetchSrc, {
          headers: { Authorization: `Bearer ${accessToken}` },
          signal: controller.signal,
        });
        if (!response.ok) {
          throw new Error(`wallpaper request failed: ${response.status}`);
        }
        const contentType = response.headers.get("content-type")?.toLowerCase() || "";
        if (contentType && !contentType.startsWith("image/")) {
          throw new Error("wallpaper response is not an image");
        }
        const blob = await response.blob();
        if (blob.type && !blob.type.toLowerCase().startsWith("image/")) {
          throw new Error("wallpaper blob is not an image");
        }
        localObjectUrl = URL.createObjectURL(blob);
        setObjectUrl(localObjectUrl);
      } catch {
        if (!controller.signal.aborted) {
          setFailed(true);
        }
      }
    }

    void loadProtectedImage();

    return () => {
      controller.abort();
      if (localObjectUrl) {
        URL.revokeObjectURL(localObjectUrl);
      }
    };
  }, [accessToken, needsAuth, resolvedSrc]);

  useEffect(() => {
    return () => {
      if (objectUrl) {
        URL.revokeObjectURL(objectUrl);
      }
    };
  }, [objectUrl]);

  if (!resolvedSrc || failed) {
    return undefined;
  }

  return needsAuth ? objectUrl : resolvedSrc;
}

function AttachmentIcon({ kind }: { kind: MediaKind | null }) {
  if (kind === "image") return <ImageIcon className="h-4 w-4" />;
  if (kind === "video") return <Video className="h-4 w-4" />;
  if (kind === "audio") return <Music2 className="h-4 w-4" />;
  return <Paperclip className="h-4 w-4" />;
}

function getMessageSnippet(message: MessageResponse | undefined, t: ReturnType<typeof useTranslations>): string {
  if (!message) return t("messages.snippet.notLoaded");
  if (message.deleted_at) return t("messages.snippet.deleted");
  if (message.content_type === "text") {
    const text = (message.content_text || "").trim();
    if (!text && message.attachments && message.attachments.length > 0) {
      return t("messages.snippet.attachments", { count: message.attachments.length });
    }
    if (!text) return t("messages.snippet.empty");
    return text.length > 90 ? `${text.slice(0, 90)}...` : text;
  }
  if (message.attachments && message.attachments.length > 0) {
    return t("messages.snippet.attachments", { count: message.attachments.length });
  }
  return t("messages.snippet.structured");
}

async function copyToClipboard(value: string) {
  if (typeof navigator !== "undefined" && navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(value);
    return;
  }

  if (typeof document === "undefined") {
    throw new Error("Clipboard is not available in this environment.");
  }

  const textarea = document.createElement("textarea");
  textarea.value = value;
  textarea.setAttribute("readonly", "");
  textarea.style.position = "absolute";
  textarea.style.left = "-9999px";
  document.body.appendChild(textarea);
  textarea.select();
  const copied = document.execCommand("copy");
  document.body.removeChild(textarea);

  if (!copied) {
    throw new Error("Copy action was blocked by the browser.");
  }
}

function AuthenticatedPlaybackMedia({
  src,
  kind,
  className,
  fallbackLabel,
}: {
  src?: string;
  kind: Exclude<MediaKind, "image">;
  className?: string;
  fallbackLabel: string;
}) {
  const accessToken = useAuthStore((state) => state.accessToken);
  const needsAuth = isProtectedApiMediaUrl(src);
  const [objectUrl, setObjectUrl] = useState<string | undefined>();
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    setFailed(false);
    setObjectUrl(undefined);
  }, [accessToken, kind, needsAuth, src]);

  useEffect(() => {
    if (!src || !needsAuth || !accessToken) {
      return;
    }

    const controller = new AbortController();
    const fetchSrc = src;
    let localObjectUrl: string | undefined;

    async function loadProtectedMedia() {
      try {
        const response = await fetch(fetchSrc, {
          headers: { Authorization: `Bearer ${accessToken}` },
          signal: controller.signal,
        });
        if (!response.ok) {
          throw new Error(`media request failed: ${response.status}`);
        }
        const expectedPrefix = `${kind}/`;
        const contentType = response.headers.get("content-type")?.toLowerCase() || "";
        if (contentType && !contentType.startsWith(expectedPrefix)) {
          throw new Error(`media response is not ${kind}`);
        }
        const blob = await response.blob();
        if (blob.type && !blob.type.toLowerCase().startsWith(expectedPrefix)) {
          throw new Error(`media blob is not ${kind}`);
        }
        localObjectUrl = URL.createObjectURL(blob);
        setObjectUrl(localObjectUrl);
      } catch {
        if (!controller.signal.aborted) {
          setFailed(true);
        }
      }
    }

    void loadProtectedMedia();

    return () => {
      controller.abort();
      if (localObjectUrl) {
        URL.revokeObjectURL(localObjectUrl);
      }
    };
  }, [accessToken, needsAuth, src]);

  const mediaSrc = needsAuth ? objectUrl : src;
  if (failed) {
    return (
      <div className={cn("flex h-20 items-center justify-center text-xs text-muted-foreground", className)}>
        {fallbackLabel}
      </div>
    );
  }
  if (!mediaSrc) {
    return (
      <div className={cn("flex h-20 items-center justify-center", className)}>
        <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
      </div>
    );
  }

  if (kind === "video") {
    return <video src={mediaSrc} controls preload="metadata" className={className} />;
  }

  return <audio src={mediaSrc} controls preload="metadata" className={className} />;
}

function MessageAttachments({ attachments, isMe, className }: { attachments: AttachmentItem[]; isMe: boolean; className?: string }) {
  const commonT = useTranslations("common");
  const visibleAttachments = attachments.filter((attachment) => getAttachmentUrl(attachment));
  if (visibleAttachments.length === 0) return null;

  return (
    <div className={cn("grid max-w-full gap-2", className)}>
      {visibleAttachments.map((attachment) => {
        const kind = getMessageMediaKind(attachment.content_type);
        const url = getAttachmentUrl(attachment);
        const filename = attachment.filename || "attachment";
        const sizeLabel = formatBytes(attachment.size_bytes);
        const labelColor = isMe ? "text-primary-foreground/80" : "text-muted-foreground";
        const shellClassName = cn(
          "overflow-hidden rounded-xl border",
          isMe ? "border-primary-foreground/20 bg-primary-foreground/10" : "border-border/70 bg-background/80"
        );

        return (
          <div key={`${attachment.file_id}-${attachment.filename || "media"}`} className={shellClassName}>
            {kind === "image" && url ? (
              <AuthenticatedImage src={url} alt={filename} className="max-h-80 w-full min-w-64 object-contain" />
            ) : kind === "video" && url ? (
              <AuthenticatedPlaybackMedia src={url} kind="video" className="max-h-80 w-full min-w-64 bg-black" fallbackLabel={commonT("notAvailable")} />
            ) : kind === "audio" && url ? (
              <div className="px-3 pt-3">
                <AuthenticatedPlaybackMedia src={url} kind="audio" className="w-full min-w-64" fallbackLabel={commonT("notAvailable")} />
              </div>
            ) : null}
            <div className={cn("flex min-w-0 items-center gap-2 px-3 py-2 text-xs", labelColor)}>
              <AttachmentIcon kind={kind} />
              <span className="truncate font-medium">{filename}</span>
              {sizeLabel ? <span className="shrink-0 opacity-80">{sizeLabel}</span> : null}
            </div>
          </div>
        );
      })}
    </div>
  );
}

export default function ChannelView() {
  const params = useParams<{ channelId?: string | string[] }>();
  const channelId = Array.isArray(params?.channelId) ? params.channelId[0] : params?.channelId;
  const router = useRouter();
  const localePath = useLocalePath();
  const locale = useLocale();
  const t = useTranslations("channelView");
  const commonT = useTranslations("common");
  const {
    data: channel,
    isLoading: isChannelLoading,
    isError: isChannelError,
    refetch: refetchChannel,
  } = useChannel(channelId || '');
  const { data: messages = [], isLoading: isMessagesLoading } = useMessages(channelId || '');
  const joinChannel = useJoinChannel();
  const sendMessage = useSendMessage();
  const toggleReaction = useToggleReaction();
  const markSeen = useMarkSeen();
  
  const [content, setContent] = useState("");
  const [pendingMedia, setPendingMedia] = useState<PendingMediaAttachment[]>([]);
  const [isUploadingMedia, setIsUploadingMedia] = useState(false);
  const [replyingTo, setReplyingTo] = useState<MessageResponse | null>(null);
  const [collapsedReplyRoots, setCollapsedReplyRoots] = useState<Set<string>>(new Set());
  const [hoveredMessageId, setHoveredMessageId] = useState<string | null>(null);
  const scrollContainerRef = useRef<HTMLDivElement>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const composerRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const wallpaperFileInputRef = useRef<HTMLInputElement>(null);
  const messageRefs = useRef<Record<string, HTMLDivElement | null>>({});
  const lastMarkedSeenSeqRef = useRef<number | null>(null);
  const pendingMediaRef = useRef<PendingMediaAttachment[]>([]);
  const user = useAuthStore(s => s.user);
  const accessToken = useAuthStore(s => s.accessToken);
  const updateUser = useAuthStore(s => s.updateUser);
  const chatWallpaperId = useChatPreferencesStore((state) => state.chatWallpaperId);
  const chatWallpaperByUserId = useChatPreferencesStore((state) => state.chatWallpaperByUserId);
  const setChatWallpaperId = useChatPreferencesStore((state) => state.setChatWallpaperId);
  const setChatWallpaperForUser = useChatPreferencesStore((state) => state.setChatWallpaperForUser);
  const [isUpdatingWallpaper, setIsUpdatingWallpaper] = useState(false);
  const uploadedWallpaperImageUrl = useAuthenticatedBackgroundImage(user?.wallpaper_url, accessToken);
  const isMember = ['owner', 'admin', 'member'].includes(channel?.my_role || '');
  const canCompose = ['owner', 'admin'].includes(channel?.my_role || '');
  const canReplyAsMember = isMember && !canCompose;
  const canUseComposer = canCompose || canReplyAsMember;
  const membersQuery = useChannelMembers(channel?.id || '', {
    enabled: isMember && Boolean(channel?.permissions.can_manage_members),
  });

  const formatTime = (value: string) =>
    new Intl.DateTimeFormat(locale, { hour: "numeric", minute: "2-digit" }).format(new Date(value));

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  useEffect(() => {
    setReplyingTo(null);
    setCollapsedReplyRoots(new Set());
    setPendingMedia([]);
  }, [channelId]);

  useEffect(() => {
    pendingMediaRef.current = pendingMedia;
  }, [pendingMedia]);

  useEffect(() => {
    return () => {
      pendingMediaRef.current = [];
    };
  }, []);

  useEffect(() => {
    if (!channelId || !isMember || messages.length === 0) return;

    const latestMessage = messages[messages.length - 1];
    const latestSeqId = latestMessage?.seq_id;
    const currentSeenSeqId = channel?.my_last_seen_seq_id ?? 0;

    if (!latestSeqId || latestSeqId <= currentSeenSeqId || lastMarkedSeenSeqRef.current === latestSeqId) {
      return;
    }

    const container = scrollContainerRef.current;
    const isNearBottom = !container || container.scrollHeight - container.scrollTop - container.clientHeight < 80;

    if (!isNearBottom) return;

    lastMarkedSeenSeqRef.current = latestSeqId;
    markSeen.mutate(
      { channelId, lastSeenSeqId: latestSeqId },
      {
        onError: () => {
          if (lastMarkedSeenSeqRef.current === latestSeqId) {
            lastMarkedSeenSeqRef.current = null;
          }
        },
      }
    );
  }, [channel?.my_last_seen_seq_id, channelId, isMember, markSeen, messages]);

  if (isChannelLoading) return <ChannelViewSkeleton />;
  if (isChannelError && !channel) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center gap-4 text-center px-6">
        <div className="text-muted-foreground">{t("errors.openFailed")}</div>
        <Button onClick={() => refetchChannel()} className="rounded-full px-6">
          {commonT("actions.tryAgain")}
        </Button>
      </div>
    );
  }
  if (!channel) return <div className="flex-1 flex items-center justify-center text-muted-foreground">{t("errors.notFound")}</div>;

  const channelAvatarUrl = resolveApiMediaUrl(channel.avatar_url);
  const userAvatarUrl = resolveApiMediaUrl(user?.avatar_url);

  const uploadPendingMedia = async (item: PendingMediaAttachment): Promise<{ file_id: string }> => {
    if (!accessToken) {
      throw new Error("missing access token");
    }

    const created = await apiClient<UploadCreateResponse>("/uploads", {
      method: "POST",
      body: JSON.stringify({
        filename: item.file.name,
        content_type: item.contentType,
        size_bytes: item.file.size,
      }),
    });

    const uploadAccessToken = useAuthStore.getState().accessToken;
    if (!uploadAccessToken) {
      throw new Error("missing access token");
    }

    const uploadHeaders = new Headers(created.headers || {});
    uploadHeaders.set("Authorization", `Bearer ${uploadAccessToken}`);
    uploadHeaders.set("Content-Type", item.contentType);

    const response = await fetch(resolveUploadTargetUrl(created.upload_url), {
      method: created.method || "PUT",
      headers: uploadHeaders,
      body: item.file,
    });
    if (!response.ok) {
      throw new Error(`upload failed: ${response.status}`);
    }
    await response.json() as UploadContentResponse;
    return { file_id: created.file_id };
  };

  const saveUserWallpaperUrl = async (wallpaperUrl: string | null): Promise<MeResponse> => {
    const payload: UpdateMeRequest = { wallpaper_url: wallpaperUrl };
    const updatedUser = await apiClient<MeResponse>("/me", {
      method: "PATCH",
      body: JSON.stringify(payload),
    });
    updateUser(updatedUser);
    return updatedUser;
  };

  const uploadWallpaperFile = async (file: File, contentType: string): Promise<string> => {
    if (!accessToken) {
      throw new Error(t("toasts.wallpaperSignInRequired"));
    }

    const created = await apiClient<UploadCreateResponse>("/uploads", {
      method: "POST",
      body: JSON.stringify({
        filename: file.name,
        content_type: contentType,
        size_bytes: file.size,
      }),
    });

    const uploadAccessToken = useAuthStore.getState().accessToken;
    if (!uploadAccessToken) {
      throw new Error(t("toasts.wallpaperSignInRequired"));
    }

    const uploadHeaders = new Headers(created.headers || {});
    uploadHeaders.set("Authorization", `Bearer ${uploadAccessToken}`);
    uploadHeaders.set("Content-Type", contentType);

    const response = await fetch(resolveUploadTargetUrl(created.upload_url), {
      method: created.method || "PUT",
      headers: uploadHeaders,
      body: file,
    });
    if (!response.ok) {
      throw new Error(`upload failed: ${response.status}`);
    }

    const uploaded = (await response.json()) as UploadContentResponse;
    const nextWallpaperUrl = (uploaded.public_url || created.public_url || "").trim();
    if (!nextWallpaperUrl) {
      throw new Error(t("toasts.wallpaperMissingUrl"));
    }
    return nextWallpaperUrl;
  };

  const handleWallpaperSelected = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0] ?? null;
    event.currentTarget.value = "";
    if (!file) return;

    const contentType = inferMediaContentType(file);
    if (!contentType || getMessageMediaKind(contentType) !== "image" || contentType === "image/svg+xml") {
      toast({
        title: t("toasts.wallpaperUnsupportedTitle"),
        description: t("toasts.wallpaperUnsupportedDescription"),
        variant: "destructive",
      });
      return;
    }
    if (file.size > MAX_WALLPAPER_FILE_SIZE_BYTES) {
      toast({
        title: t("toasts.wallpaperTooLargeTitle"),
        description: t("toasts.wallpaperTooLargeDescription", { size: formatBytes(MAX_WALLPAPER_FILE_SIZE_BYTES) }),
        variant: "destructive",
      });
      return;
    }

    setIsUpdatingWallpaper(true);
    try {
      const wallpaperUrl = await uploadWallpaperFile(file, contentType);
      await saveUserWallpaperUrl(wallpaperUrl);
      toast({
        title: t("toasts.wallpaperUploadedTitle"),
        description: t("toasts.wallpaperUploadedDescription"),
      });
    } catch (error) {
      toast({
        title: t("toasts.wallpaperUploadFailedTitle"),
        description: getErrorMessage(error, t("toasts.wallpaperUploadFailedDescription")),
        variant: "destructive",
      });
    } finally {
      setIsUpdatingWallpaper(false);
    }
  };

  const clearCustomWallpaper = async (showToast = true) => {
    if (!user?.wallpaper_url || isUpdatingWallpaper) return;
    setIsUpdatingWallpaper(true);
    try {
      await saveUserWallpaperUrl(null);
      if (showToast) {
        toast({
          title: t("toasts.wallpaperClearedTitle"),
          description: t("toasts.wallpaperClearedDescription"),
        });
      }
    } catch (error) {
      toast({
        title: t("toasts.wallpaperClearFailedTitle"),
        description: getErrorMessage(error, t("toasts.wallpaperClearFailedDescription")),
        variant: "destructive",
      });
    } finally {
      setIsUpdatingWallpaper(false);
    }
  };

  const handleMediaSelected = (event: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(event.target.files ?? []);
    event.currentTarget.value = "";
    if (files.length === 0) return;

    const availableSlots = Math.max(0, MAX_MEDIA_ATTACHMENTS - pendingMedia.length);
    if (availableSlots === 0) {
      toast({
        title: t("toasts.mediaLimitTitle"),
        description: t("toasts.mediaLimitDescription", { count: MAX_MEDIA_ATTACHMENTS }),
        variant: "destructive",
      });
      return;
    }

    let rejectedTypeCount = 0;
    let rejectedSizeCount = 0;
    const accepted: PendingMediaAttachment[] = [];
    for (const file of files.slice(0, availableSlots)) {
      const contentType = inferMediaContentType(file);
      const kind = getMessageMediaKind(contentType);
      if (!contentType || !kind) {
        rejectedTypeCount += 1;
        continue;
      }
      if (file.size > MAX_MEDIA_FILE_SIZE_BYTES) {
        rejectedSizeCount += 1;
        continue;
      }
      accepted.push({
        id: createPendingAttachmentId(),
        file,
        contentType,
        kind,
      });
    }

    if (files.length > availableSlots) {
      toast({
        title: t("toasts.mediaLimitTitle"),
        description: t("toasts.mediaLimitDescription", { count: MAX_MEDIA_ATTACHMENTS }),
        variant: "destructive",
      });
    }
    if (rejectedTypeCount > 0) {
      toast({
        title: t("toasts.mediaUnsupportedTitle"),
        description: t("toasts.mediaUnsupportedDescription"),
        variant: "destructive",
      });
    }
    if (rejectedSizeCount > 0) {
      toast({
        title: t("toasts.mediaTooLargeTitle"),
        description: t("toasts.mediaTooLargeDescription", { size: formatBytes(MAX_MEDIA_FILE_SIZE_BYTES) }),
        variant: "destructive",
      });
    }
    if (accepted.length > 0) {
      setPendingMedia((current) => [...current, ...accepted]);
    }
  };

  const removePendingMedia = (id: string) => {
    setPendingMedia((current) => current.filter((item) => item.id !== id));
  };

  const handleSend = async (e?: React.FormEvent | React.MouseEvent<HTMLButtonElement>) => {
    e?.preventDefault();
    const currentReplyTarget = replyingTo ? messages.find((item) => item.id === replyingTo.id) ?? replyingTo : null;
    const canReplyToTarget = currentReplyTarget && !currentReplyTarget.deleted_at;
    const canSend = canCompose || (canReplyAsMember && !!canReplyToTarget);
    const trimmedContent = content.trim();
    if (!canSend || (!trimmedContent && pendingMedia.length === 0) || !channelId || sendMessage.isPending || isUploadingMedia) return;

    setIsUploadingMedia(true);
    try {
      const attachments = pendingMedia.length > 0 ? await Promise.all(pendingMedia.map(uploadPendingMedia)) : undefined;
      await sendMessage.mutateAsync({
        channelId,
        content_text: trimmedContent || undefined,
        attachments,
        reply_to_message_id: canReplyToTarget ? currentReplyTarget.id : undefined,
        reply_to_seq_id: canReplyToTarget ? currentReplyTarget.seq_id : undefined,
      });
      setContent("");
      setPendingMedia([]);
      setReplyingTo(null);
    } catch {
      toast({
        title: t("toasts.mediaPublishFailedTitle"),
        description: t("toasts.mediaPublishFailedDescription"),
        variant: "destructive",
      });
    } finally {
      setIsUploadingMedia(false);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      void handleSend();
    }
  };

  const messageById = new Map(messages.map((message) => [message.id, message]));
  const replyChildrenById = new Map<string, MessageResponse[]>();
  const memberNameById = new Map(
    (membersQuery.data?.items ?? []).map((member) => [
      member.user_id,
      member.display_name?.trim() || member.username,
    ])
  );
  const memberAvatarById = new Map(
    (membersQuery.data?.items ?? []).map((member) => [
      member.user_id,
      resolveApiMediaUrl(member.avatar_url),
    ])
  );
  for (const message of messages) {
    const parentId = message.reply_to_message_id;
    if (!parentId) continue;
    const children = replyChildrenById.get(parentId);
    if (children) {
      children.push(message);
    } else {
      replyChildrenById.set(parentId, [message]);
    }
  }

  const resolveSenderName = (senderUserId: string | undefined, message?: MessageResponse) => {
    if (!senderUserId) return t("messages.member");
    if (senderUserId === user?.id) return user?.display_name?.trim() || user?.username || t("messages.you");
    const messageDisplayName = message?.sender_display_name?.trim();
    if (messageDisplayName) return messageDisplayName;
    const memberName = memberNameById.get(senderUserId);
    if (memberName) return memberName;
    const messageUsername = message?.sender_username?.trim();
    if (messageUsername) return messageUsername;
    return t("messages.memberWithId", { id: senderUserId.slice(0, 8) });
  };

  const resolveSenderLabel = (message: MessageResponse | undefined) => {
    if (!message) return t("messages.message");
    return resolveSenderName(message.sender_user_id, message);
  };

  const resolveSenderAvatarUrl = (senderUserId: string | undefined, message?: MessageResponse) => {
    if (!senderUserId) return undefined;
    if (senderUserId === user?.id) return userAvatarUrl;
    const messageAvatarUrl = resolveApiMediaUrl(message?.sender_avatar_url);
    if (messageAvatarUrl) return messageAvatarUrl;
    return memberAvatarById.get(senderUserId);
  };

  const getUserProfilePath = (senderUserId: string | undefined) => {
    if (!senderUserId) return null;
    return senderUserId === user?.id ? localePath("/app/profile") : localePath(`/app/users/${senderUserId}`);
  };

  const renderSenderNameLink = (message: MessageResponse, className?: string) => {
    const label = resolveSenderName(message.sender_user_id, message);
    const href = getUserProfilePath(message.sender_user_id);
    if (!href) return <span className={className}>{label}</span>;
    return (
      <Link
        href={href}
        className={cn(
          className,
          "rounded-sm underline-offset-2 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        )}
      >
        {label}
      </Link>
    );
  };

  const renderSenderAvatarLink = (message: MessageResponse, className: string, fallbackClassName?: string) => {
    const label = resolveSenderName(message.sender_user_id, message);
    const avatar = (
      <Avatar className={className}>
        <AvatarImage src={resolveSenderAvatarUrl(message.sender_user_id, message)} alt={label} />
        <AvatarFallback className={fallbackClassName}>{label?.[0]?.toUpperCase() || "#"}</AvatarFallback>
      </Avatar>
    );
    const href = getUserProfilePath(message.sender_user_id);
    if (!href) return avatar;
    return (
      <Link
        href={href}
        className="inline-flex flex-shrink-0 rounded-full focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        aria-label={label}
      >
        {avatar}
      </Link>
    );
  };

  const getDescendantReplyCount = (messageId: string): number => {
    let count = 0;
    const visited = new Set<string>();
    const stack = [...(replyChildrenById.get(messageId) ?? [])];

    while (stack.length > 0) {
      const current = stack.pop();
      if (!current || visited.has(current.id)) continue;
      visited.add(current.id);
      count += 1;
      const children = replyChildrenById.get(current.id);
      if (children && children.length > 0) {
        stack.push(...children);
      }
    }
    return count;
  };

  const jumpToMessage = (messageId: string | null | undefined) => {
    if (!messageId) return;
    setCollapsedReplyRoots((current) => {
      if (current.size === 0) return current;
      const next = new Set(current);
      let changed = false;
      let cursorId: string | null = messageId;
      const visited = new Set<string>();
      while (cursorId && !visited.has(cursorId)) {
        visited.add(cursorId);
        const message = messageById.get(cursorId);
        const parentId = message?.reply_to_message_id ?? null;
        if (!parentId) break;
        if (next.delete(parentId)) {
          changed = true;
        }
        cursorId = parentId;
      }
      return changed ? next : current;
    });
    const scrollToTarget = () => {
      const node = messageRefs.current[messageId];
      if (node) node.scrollIntoView({ behavior: "smooth", block: "center" });
    };
    scrollToTarget();
    requestAnimationFrame(scrollToTarget);
  };

  const toggleCollapsedReplies = (messageId: string) => {
    setCollapsedReplyRoots((current) => {
      const next = new Set(current);
      if (next.has(messageId)) {
        next.delete(messageId);
      } else {
        next.add(messageId);
      }
      return next;
    });
  };

  const focusComposer = () => {
    requestAnimationFrame(() => composerRef.current?.focus());
  };

  const toggleMessageReaction = (emoji: string, message: MessageResponse) => {
    if (!canUseComposer) {
      toast({
        title: t("toasts.reactBlockedTitle"),
        description: t("toasts.reactBlockedDescription"),
        variant: "destructive",
      });
      return;
    }
    if (!channelId || message.deleted_at) return;
    const hasMyReaction = (message.reactions_summary?.my_reaction ?? []).includes(emoji);
    toggleReaction.mutate({ channelId, messageId: message.id, emoji, remove: hasMyReaction });
  };

  const copyMessageText = async (message: MessageResponse) => {
    const text = (message.content_text || "").trim();
    if (message.deleted_at || message.content_type !== "text" || !text) {
      toast({
        title: t("toasts.nothingToCopyTitle"),
        description: t("toasts.nothingToCopyDescription"),
        variant: "destructive",
      });
      return;
    }

    try {
      await copyToClipboard(text);
      toast({
        title: t("toasts.copiedTitle"),
        description: t("toasts.copiedDescription"),
      });
    } catch (_error) {
      const description = t("toasts.clipboardBlocked");
      toast({
        title: t("toasts.copyFailedTitle"),
        description,
        variant: "destructive",
      });
    }
  };

  const activeReplyTarget = replyingTo ? messageById.get(replyingTo.id) ?? replyingTo : null;
  const rootMessages = messages.filter((message) => !message.reply_to_message_id || !messageById.has(message.reply_to_message_id));
  const hasComposerDraft = content.trim().length > 0 || pendingMedia.length > 0;
  const isComposerBusy = sendMessage.isPending || isUploadingMedia;
  const selectedWallpaperId = user?.id ? (chatWallpaperByUserId[user.id] ?? chatWallpaperId) : chatWallpaperId;
  const activeWallpaper = getChatWallpaperById(selectedWallpaperId);
  const hasCustomWallpaper = Boolean(user?.wallpaper_url);
  const customWallpaperStyle = uploadedWallpaperImageUrl
    ? {
        backgroundColor: "hsl(var(--background))",
        backgroundImage: `linear-gradient(180deg, hsl(var(--background) / 0.18) 0%, hsl(var(--background) / 0.62) 100%), ${cssUrl(uploadedWallpaperImageUrl)}`,
        backgroundPosition: "center, center",
        backgroundRepeat: "no-repeat, no-repeat",
        backgroundSize: "cover, cover",
      }
    : null;
  const activeWallpaperStyle = customWallpaperStyle ?? activeWallpaper.style;
  const updateChatWallpaper = (wallpaperId: typeof activeWallpaper.id) => {
    if (user?.id) {
      setChatWallpaperForUser(user.id, wallpaperId);
    } else {
      setChatWallpaperId(wallpaperId);
    }
    if (user?.wallpaper_url) {
      void clearCustomWallpaper(false);
    }
  };

  function renderMessageThread(
    msg: MessageResponse,
    previousSibling?: MessageResponse,
    depth = 0,
    ancestorIds = new Set<string>()
  ): ReactNode {
    if (ancestorIds.has(msg.id)) return null;

    const isMe = msg.sender_user_id === user?.id;
    const isNested = depth > 0;
    const showHeader =
      isNested ||
      !previousSibling ||
      previousSibling.sender_user_id !== msg.sender_user_id ||
      new Date(msg.created_at).getTime() - new Date(previousSibling.created_at).getTime() > 300000;
    const repliedMessage = msg.reply_to_message_id ? messageById.get(msg.reply_to_message_id) : undefined;
    const showReplyContext = Boolean(msg.reply_to_message_id && !repliedMessage);
    const nextAncestorIds = new Set(ancestorIds);
    nextAncestorIds.add(msg.id);
    const childMessages =
      depth >= MAX_REPLY_CHAIN_DEPTH
        ? []
        : (replyChildrenById.get(msg.id) ?? []).filter((child) => !nextAncestorIds.has(child.id));
    const nestedReplyCount = getDescendantReplyCount(msg.id);
    const canCollapseReplies = nestedReplyCount > 0 && childMessages.length > 0;
    const isRepliesCollapsed = collapsedReplyRoots.has(msg.id);
    const isHovered = hoveredMessageId === msg.id;
    const textBody = msg.content_type === "text" ? (msg.content_text || "").trim() : "";
    const hasVisibleBody = Boolean(msg.deleted_at || (msg.content_type === "text" ? textBody : msg.content_json));
    const attachments = msg.attachments ?? [];
    const hasVisibleAttachments = !msg.deleted_at && attachments.some((attachment) => getAttachmentUrl(attachment));

    return (
      <div
        key={msg.id}
        ref={(node) => {
          messageRefs.current[msg.id] = node;
        }}
        className={cn("relative", isNested ? "mt-0" : !showHeader ? "mt-1" : "mt-6")}
      >
        <div className={cn("flex", isNested ? "gap-2" : "gap-3", isMe ? "justify-end" : "justify-start")}>
          {isNested && !isMe ? (
            renderSenderAvatarLink(msg, "mt-1 h-6 w-6 flex-shrink-0 border border-border/70 shadow-sm", "text-[10px]")
          ) : !isNested && !isMe && showHeader ? (
            renderSenderAvatarLink(msg, "w-10 h-10 border border-border shadow-sm flex-shrink-0")
          ) : !isNested && !isMe ? (
            <div className="w-10 flex-shrink-0" />
          ) : null}

          <div className={cn("flex min-w-0 flex-col", isNested ? "max-w-full" : "max-w-[min(85%,42rem)]", isMe ? "items-end" : "items-start")}>
            {showHeader && !isNested && (
              <div className={cn("mb-1 flex items-baseline gap-2", isMe && "justify-end")}>
                {renderSenderNameLink(msg, "font-semibold text-foreground text-sm")}
                <span className="text-[11px] text-muted-foreground">{formatTime(msg.created_at)}</span>
              </div>
            )}

            <div
              className={cn(
                "relative w-fit max-w-full rounded-2xl border px-4 py-2.5 shadow-sm transition-shadow",
                isHovered && "shadow-md",
                isNested && "rounded-xl px-3 py-2 shadow-none",
                isMe
                  ? cn(
                      !isNested && "rounded-br-md shadow-primary/10",
                      isNested ? "border-primary/20 bg-primary/90 text-primary-foreground" : "border-primary/30 bg-primary text-primary-foreground"
                    )
                  : cn(
                      !isNested && "rounded-bl-md",
                      isNested ? "border-border/60 bg-background text-card-foreground" : "border-border/70 bg-card text-card-foreground"
                    )
              )}
              onMouseEnter={() => setHoveredMessageId(msg.id)}
              onMouseMove={() => setHoveredMessageId(msg.id)}
              onMouseLeave={() => setHoveredMessageId((current) => (current === msg.id ? null : current))}
              onFocus={() => setHoveredMessageId(msg.id)}
              onBlur={() => setHoveredMessageId((current) => (current === msg.id ? null : current))}
            >
            {showHeader && isNested && (
              <div className="mb-1 flex items-baseline gap-2">
                {renderSenderNameLink(msg, cn("text-xs font-semibold", isMe ? "text-primary-foreground" : "text-foreground"))}
                <span className={cn("text-[10px]", isMe ? "text-primary-foreground/70" : "text-muted-foreground")}>
                  {formatTime(msg.created_at)}
                </span>
              </div>
            )}

            {showReplyContext && (
              <button
                type="button"
                onClick={() => jumpToMessage(msg.reply_to_message_id)}
                className={cn(
                  "mb-2 block w-full rounded-md border px-2 py-1 text-left transition-colors",
                  isMe
                    ? "border-primary-foreground/20 bg-primary-foreground/10 hover:bg-primary-foreground/15"
                    : "border-border/60 bg-background/80 hover:bg-background"
                )}
              >
                <div className={cn("text-[11px] font-semibold", isMe ? "text-primary-foreground" : "text-primary")}>
                  {t("messages.replyingTo")} {resolveSenderLabel(repliedMessage)}
                  {msg.reply_to_seq_id ? ` (#${msg.reply_to_seq_id})` : ""}
                </div>
                <div className={cn("truncate text-xs", isMe ? "text-primary-foreground/75" : "text-muted-foreground")}>{getMessageSnippet(repliedMessage, t)}</div>
              </button>
            )}

            {hasVisibleAttachments && <MessageAttachments attachments={attachments} isMe={isMe} />}

            {hasVisibleBody && (
              <div className={cn("whitespace-pre-wrap break-words text-sm leading-relaxed", hasVisibleAttachments && "mt-3", isMe ? "text-primary-foreground" : "text-foreground/90")}>
                {msg.deleted_at
                  ? t("messages.deleted")
                  : msg.content_type === "text"
                    ? msg.content_text
                    : JSON.stringify(msg.content_json ?? {}, null, 2)}
              </div>
            )}

            {!msg.deleted_at && Object.keys(msg.reactions_summary?.counts ?? {}).length > 0 && (
              <div className="mt-2 flex flex-wrap gap-1.5">
                {Object.entries(msg.reactions_summary.counts)
                  .sort((a, b) => a[0].localeCompare(b[0]))
                  .map(([emoji, count]) => {
                    const isMine = (msg.reactions_summary?.my_reaction ?? []).includes(emoji);
                    return (
                      <button
                        key={`${msg.id}-reaction-${emoji}`}
                        type="button"
                        className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs transition-colors ${
                          isMine
                            ? isMe
                              ? "border-primary-foreground/40 bg-primary-foreground/20 text-primary-foreground"
                              : "border-primary/50 bg-primary/10 text-primary"
                            : isMe
                              ? "border-primary-foreground/25 bg-primary-foreground/10 text-primary-foreground/90 hover:bg-primary-foreground/15"
                              : "border-border/70 bg-background/80 text-foreground/80 hover:bg-accent"
                        }`}
                        onClick={() => toggleMessageReaction(emoji, msg)}
                        aria-label={isMine
                          ? t("aria.removeReaction", { emoji, seq: msg.seq_id })
                          : t("aria.addReaction", { emoji, seq: msg.seq_id })}
                      >
                        <span>{emoji}</span>
                        <span>{count}</span>
                      </button>
                    );
                  })}
              </div>
            )}

            <div
              className={cn(
                "absolute -top-3 opacity-0 transition-opacity bg-card border border-border rounded-lg shadow-lg flex items-center p-0.5 z-10",
                isHovered && "opacity-100",
                isMe ? "left-0 -translate-x-2" : "right-0 translate-x-2"
              )}
            >
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button
                    size="icon"
                    variant="ghost"
                    className="h-7 w-7 text-muted-foreground hover:text-foreground"
                    aria-label={t("aria.addReactionMenu", { seq: msg.seq_id })}
                  >
                    <SmilePlus className="w-4 h-4" />
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end" className="w-auto min-w-0 p-1">
                  <div className="flex items-center gap-1">
                    {QUICK_REACTIONS.map((emoji) => (
                      <DropdownMenuItem
                        key={`${msg.id}-${emoji}`}
                        className="h-8 w-8 p-0 flex items-center justify-center text-base"
                        onSelect={() => toggleMessageReaction(emoji, msg)}
                        aria-label={t("aria.reactWith", { emoji })}
                      >
                        {emoji}
                      </DropdownMenuItem>
                    ))}
                  </div>
                </DropdownMenuContent>
              </DropdownMenu>
              {(canCompose || canReplyAsMember) && !msg.deleted_at && (
                <Button
                  size="icon"
                  variant="ghost"
                  className="h-7 w-7 text-muted-foreground hover:text-foreground"
                  onClick={() => setReplyingTo(msg)}
                  aria-label={t("aria.replyToMessage", { seq: msg.seq_id })}
                >
                  <Reply className="w-4 h-4" />
                </Button>
              )}
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button size="icon" variant="ghost" className="h-7 w-7 text-muted-foreground hover:text-foreground" aria-label={t("aria.openOptions", { seq: msg.seq_id })}>
                    <MoreVertical className="w-4 h-4" />
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end" className="w-52">
                  {(canCompose || canReplyAsMember) && !msg.deleted_at && (
                    <DropdownMenuItem
                      onSelect={() => {
                        setReplyingTo(msg);
                        focusComposer();
                      }}
                    >
                      <Reply className="mr-2 h-4 w-4" />
                      {t("actions.reply")}
                    </DropdownMenuItem>
                  )}
                  <DropdownMenuItem
                    onSelect={() => {
                      void copyMessageText(msg);
                    }}
                    disabled={Boolean(msg.deleted_at) || msg.content_type !== "text" || !((msg.content_text || "").trim().length > 0)}
                  >
                    <Copy className="mr-2 h-4 w-4" />
                    {t("actions.copyText")}
                  </DropdownMenuItem>
                  {msg.reply_to_message_id && (
                    <DropdownMenuItem onSelect={() => jumpToMessage(msg.reply_to_message_id)}>
                      <ArrowUpRight className="mr-2 h-4 w-4" />
                      {t("actions.jumpToParent")}
                    </DropdownMenuItem>
                  )}
                  {canCollapseReplies && (
                    <>
                      <DropdownMenuSeparator />
                      <DropdownMenuItem onSelect={() => toggleCollapsedReplies(msg.id)}>
                        {isRepliesCollapsed ? t("actions.showReplies") : t("actions.hideReplies")}
                      </DropdownMenuItem>
                    </>
                  )}
                </DropdownMenuContent>
              </DropdownMenu>
            </div>
          </div>

            {canCollapseReplies && (
              <button
                type="button"
                className="mt-1.5 inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-medium text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
                onClick={() => toggleCollapsedReplies(msg.id)}
                aria-expanded={!isRepliesCollapsed}
                aria-label={isRepliesCollapsed
                  ? t("aria.showRepliesFor", { seq: msg.seq_id })
                  : t("aria.hideRepliesFor", { seq: msg.seq_id })}
              >
                {isRepliesCollapsed ? <ChevronRight className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
                <span>
                  {isRepliesCollapsed
                    ? t("messages.showReplyCount", { count: nestedReplyCount })
                    : t("messages.hideReplyCount", { count: nestedReplyCount })}
                </span>
              </button>
            )}

            {!isRepliesCollapsed && childMessages.length > 0 && (
              <div
                className={cn(
                  "mt-2 flex w-fit max-w-full flex-col gap-2",
                  isMe ? "self-end border-r border-border/60 pr-4" : "self-start border-l border-border/60 pl-4",
                  isNested && (isMe ? "mr-2" : "ml-2")
                )}
              >
                {childMessages.map((child, index) => renderMessageThread(child, childMessages[index - 1], depth + 1, nextAncestorIds))}
              </div>
            )}
        </div>

        {isNested && isMe ? (
          renderSenderAvatarLink(msg, "mt-1 h-6 w-6 flex-shrink-0 border border-primary/20 shadow-sm", "text-[10px]")
        ) : !isNested && isMe && showHeader ? (
          renderSenderAvatarLink(msg, "w-10 h-10 border border-border shadow-sm flex-shrink-0")
        ) : !isNested && isMe ? (
          <div className="w-10 flex-shrink-0" />
        ) : null}
        </div>
      </div>
    );
  }

  return (
    <div className="flex-1 flex flex-col h-full bg-background relative z-0">
      {/* Header */}
      <header className="h-16 border-b border-border bg-background/80 backdrop-blur-md flex items-center justify-between px-6 flex-shrink-0 z-10">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-primary/10 flex items-center justify-center text-primary">
            {channelAvatarUrl ? (
              <AuthenticatedImage src={channelAvatarUrl} alt={channel.name} className="w-full h-full rounded-xl object-cover" />
            ) : (
              <Hash className="w-5 h-5" />
            )}
          </div>
          <div>
            <h2 className="font-bold text-foreground leading-tight">{channel.name}</h2>
            <div className="text-xs text-muted-foreground flex items-center gap-2">
              <span>{t("header.members", { count: channel.member_count || 0 })}</span>
              {channel.description && (
                <>
                  <span>&bull;</span>
                  <span className="truncate max-w-[200px]">{channel.description}</span>
                </>
              )}
            </div>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <Popover>
            <Tooltip>
              <TooltipTrigger asChild>
                <PopoverTrigger asChild>
                  <Button
                    size="icon"
                    variant="ghost"
                    className="text-muted-foreground hover:text-foreground"
                    aria-label={t("aria.openWallpaperPicker")}
                  >
                    <ImageIcon className="w-5 h-5" />
                  </Button>
                </PopoverTrigger>
              </TooltipTrigger>
              <TooltipContent>{t("wallpaper.title")}</TooltipContent>
            </Tooltip>
            <PopoverContent align="end" className="w-80 p-3">
              <div className="mb-3">
                <div className="text-sm font-semibold text-popover-foreground">{t("wallpaper.title")}</div>
                <p className="mt-1 text-xs text-muted-foreground">{t("wallpaper.description")}</p>
              </div>
              <input
                ref={wallpaperFileInputRef}
                type="file"
                accept="image/*"
                className="hidden"
                onChange={handleWallpaperSelected}
              />
              <div className="mb-3 flex flex-wrap gap-2">
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => wallpaperFileInputRef.current?.click()}
                  disabled={isUpdatingWallpaper || !user}
                >
                  {isUpdatingWallpaper ? <Loader2 className="mr-2 h-3.5 w-3.5 animate-spin" /> : <UploadCloud className="mr-2 h-3.5 w-3.5" />}
                  {isUpdatingWallpaper ? t("wallpaper.uploading") : t("wallpaper.uploadCustom")}
                </Button>
                {hasCustomWallpaper ? (
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() => void clearCustomWallpaper()}
                    disabled={isUpdatingWallpaper}
                  >
                    <Trash2 className="mr-2 h-3.5 w-3.5" />
                    {t("wallpaper.removeCustom")}
                  </Button>
                ) : null}
              </div>
              {hasCustomWallpaper ? (
                <div className="mb-3 rounded-md border border-primary/30 bg-primary/5 p-2">
                  <span
                    className="relative mb-1.5 block h-16 overflow-hidden rounded-md border border-border/60"
                    style={customWallpaperStyle ?? activeWallpaper.style}
                  >
                    <span className="absolute inset-0 bg-gradient-to-t from-black/10 to-transparent" />
                    <span className="absolute right-1.5 top-1.5 flex h-5 w-5 items-center justify-center rounded-full bg-primary text-primary-foreground shadow-sm">
                      <Check className="h-3.5 w-3.5" />
                    </span>
                  </span>
                  <div className="text-xs font-medium text-popover-foreground">{t("wallpaper.custom")}</div>
                  <p className="mt-0.5 text-[11px] text-muted-foreground">{t("wallpaper.customDescription")}</p>
                </div>
              ) : null}
              <div className="grid grid-cols-2 gap-2">
                {CHAT_WALLPAPERS.map((wallpaper) => {
                  const isSelected = !hasCustomWallpaper && activeWallpaper.id === wallpaper.id;
                  const label = t(`wallpaper.options.${wallpaper.id}`);

                  return (
                    <button
                      key={wallpaper.id}
                      type="button"
                      className={cn(
                        "rounded-md border p-1.5 text-left transition-colors hover:bg-accent focus:outline-none focus:ring-2 focus:ring-ring",
                        isSelected ? "border-primary bg-primary/5" : "border-border/70"
                      )}
                      onClick={() => updateChatWallpaper(wallpaper.id)}
                      aria-label={t("aria.selectWallpaper", { name: label })}
                      aria-pressed={isSelected}
                    >
                      <span className="relative mb-1.5 block h-14 overflow-hidden rounded-md border border-border/60" style={wallpaper.style}>
                        <span className="absolute inset-0 bg-gradient-to-t from-black/10 to-transparent" />
                        {isSelected ? (
                          <span className="absolute right-1.5 top-1.5 flex h-5 w-5 items-center justify-center rounded-full bg-primary text-primary-foreground shadow-sm">
                            <Check className="h-3.5 w-3.5" />
                          </span>
                        ) : null}
                      </span>
                      <span className="block truncate text-xs font-medium text-popover-foreground">{label}</span>
                    </button>
                  );
                })}
              </div>
            </PopoverContent>
          </Popover>
          <Button
            size="icon"
            variant="ghost"
            className="text-muted-foreground hover:text-foreground"
            onClick={() => router.push(localePath(`/app/channels/${channel.id}/details`))}
            aria-label={t("aria.openDetails")}
          >
            <Settings className="w-5 h-5" />
          </Button>
        </div>
      </header>

      {/* Messages Area */}
      <div
        ref={scrollContainerRef}
        className="flex-1 overflow-y-auto p-6 space-y-6 bg-background transition-[background] duration-300"
        style={activeWallpaperStyle}
      >
        {!isMember ? (
          <div className="h-full flex flex-col items-center justify-center text-center">
            <div className="w-20 h-20 rounded-2xl bg-secondary flex items-center justify-center mb-6 shadow-inner">
              <Hash className="w-10 h-10 text-muted-foreground" />
            </div>
            <h3 className="text-2xl font-bold text-foreground mb-2">{t("joinPrompt.title")}</h3>
            <p className="text-muted-foreground mb-8 max-w-md">{t("joinPrompt.description", { name: channel.name })}</p>
            <Button 
              size="lg" 
              onClick={() => joinChannel.mutate(channelId!)}
              disabled={joinChannel.isPending}
              className="bg-primary text-primary-foreground font-semibold px-8 rounded-full shadow-lg shadow-primary/20 hover:-translate-y-0.5 transition-transform"
            >
              {joinChannel.isPending ? t("joinPrompt.joining") : t("joinPrompt.join")}
            </Button>
          </div>
        ) : (
          <>
            {isMessagesLoading ? (
              <div className="space-y-6">
                {Array.from({ length: 5 }).map((_, index) => (
                  <div key={index} className="flex gap-4">
                    <Skeleton className="h-10 w-10 rounded-full flex-shrink-0" />
                    <div className="flex-1 space-y-3">
                      <div className="flex items-center gap-2">
                        <Skeleton className="h-3 w-24" />
                        <Skeleton className="h-3 w-14" />
                      </div>
                      <Skeleton className={`h-14 rounded-2xl ${index % 2 === 0 ? "w-72 max-w-full" : "w-56 max-w-full"}`} />
                    </div>
                  </div>
                ))}
              </div>
            ) : messages.length === 0 ? (
              <div className="h-full flex flex-col items-center justify-center text-center pb-20">
                <div className="w-16 h-16 rounded-full bg-primary/10 flex items-center justify-center mb-4">
                  <Hash className="w-8 h-8 text-primary" />
                </div>
                <h3 className="text-xl font-bold text-foreground mb-1">{t("empty.title", { name: channel.name })}</h3>
                <p className="text-muted-foreground text-sm">{t("empty.description")}</p>
              </div>
            ) : (
              rootMessages.map((msg, i) => renderMessageThread(msg, rootMessages[i - 1]))
            )}
            <div ref={messagesEndRef} />
          </>
        )}
      </div>

      {/* Compose Box */}
      {(canCompose || (canReplyAsMember && !!activeReplyTarget)) && (
        <div className="p-4 bg-background border-t border-border flex-shrink-0">
          <div className="max-w-4xl mx-auto bg-secondary rounded-2xl border border-border/50 shadow-sm focus-within:ring-2 focus-within:ring-primary/20 focus-within:border-primary/30 transition-all p-2 relative">
            {activeReplyTarget && (
              <div className="mb-2 rounded-xl border border-border/60 bg-background/80 px-3 py-2 flex items-start justify-between gap-3">
                <button
                  type="button"
                  className="min-w-0 text-left"
                  onClick={() => jumpToMessage(activeReplyTarget.id)}
                >
                  <div className="text-[11px] font-semibold text-primary">
                    {t("messages.replyingTo")} {resolveSenderLabel(activeReplyTarget)} (#{activeReplyTarget.seq_id})
                  </div>
                  <div className="text-xs text-muted-foreground truncate">{getMessageSnippet(activeReplyTarget, t)}</div>
                </button>
                <Button
                  size="icon"
                  variant="ghost"
                  className="h-7 w-7 text-muted-foreground hover:text-foreground"
                  onClick={() => setReplyingTo(null)}
                  aria-label={t("aria.cancelReply")}
                >
                  <X className="w-4 h-4" />
                </Button>
              </div>
            )}
            {pendingMedia.length > 0 && (
              <div className="mb-2 flex flex-wrap gap-2">
                {pendingMedia.map((item) => (
                  <div
                    key={item.id}
                    className="inline-flex max-w-full items-center gap-2 rounded-xl border border-border/70 bg-background/80 px-2.5 py-1.5 text-xs text-foreground shadow-sm"
                  >
                    <AttachmentIcon kind={item.kind} />
                    <span className="max-w-44 truncate font-medium">{item.file.name}</span>
                    <span className="shrink-0 text-muted-foreground">{formatBytes(item.file.size)}</span>
                    <Button
                      size="icon"
                      variant="ghost"
                      className="h-6 w-6 rounded-md text-muted-foreground hover:text-foreground"
                      onClick={() => removePendingMedia(item.id)}
                      disabled={isComposerBusy}
                      aria-label={t("aria.removeAttachment", { name: item.file.name })}
                    >
                      <X className="h-3.5 w-3.5" />
                    </Button>
                  </div>
                ))}
              </div>
            )}
            <div className="flex items-end gap-2">
              <input
                ref={fileInputRef}
                type="file"
                accept={MEDIA_ACCEPT}
                multiple
                className="hidden"
                onChange={handleMediaSelected}
              />
              <Button
                size="icon"
                variant="ghost"
                className="h-10 w-10 text-muted-foreground hover:bg-background rounded-xl flex-shrink-0 mb-1"
                onClick={() => fileInputRef.current?.click()}
                disabled={isComposerBusy || pendingMedia.length >= MAX_MEDIA_ATTACHMENTS}
                aria-label={t("aria.attachFile")}
              >
                <Paperclip className="w-5 h-5" />
              </Button>
              
              <textarea
                ref={composerRef}
                value={content}
                onChange={e => setContent(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder={canCompose ? t("composer.messagePlaceholder", { name: channel.name }) : t("composer.replyPlaceholder")}
                className="flex-1 bg-transparent border-none focus:ring-0 resize-none max-h-48 min-h-[44px] py-3 text-sm text-foreground placeholder:text-muted-foreground"
                rows={1}
              />

              <Button 
                size="icon" 
                className={`h-10 w-10 rounded-xl flex-shrink-0 mb-1 transition-all ${hasComposerDraft ? 'bg-primary text-primary-foreground shadow-md shadow-primary/20 hover:scale-105' : 'bg-muted text-muted-foreground'}`}
                onClick={handleSend}
                disabled={!hasComposerDraft || isComposerBusy || (canReplyAsMember && !activeReplyTarget)}
                aria-label={t("composer.send")}
              >
                {isComposerBusy ? <Loader2 className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4 translate-x-0.5 -translate-y-0.5" />}
              </Button>
            </div>
          </div>
          <div className="text-center mt-2 text-[10px] text-muted-foreground/60">
            <strong>{t("composer.enter")}</strong> {t("composer.toSend")},{" "}
            <strong>{t("composer.shiftEnter")}</strong> {t("composer.forNewLine")}
          </div>
        </div>
      )}
    </div>
  );
}
