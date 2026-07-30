"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useMemo, type ReactNode } from "react";
import { useQueries } from "@tanstack/react-query";
import { useLocale, useTranslations } from "next-intl";
import {
  AlertTriangle,
  ArrowLeft,
  CalendarClock,
  CheckCircle2,
  DatabaseZap,
  FileJson,
  Hash,
  Inbox,
  LockKeyhole,
  Mail,
  MessageSquare,
  RefreshCw,
  ServerCrash,
  Settings,
  Shield,
  UserCheck,
  UserMinus,
  UserPlus,
  UserX,
} from "lucide-react";
import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from "@/components/ui/accordion";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { useChannel } from "@/hooks/use-channels";
import { useChannelEventIntegrity, useChannelEvents } from "@/hooks/use-events";
import { useAuthStore } from "@/store/authStore";
import { useLocalePath } from "@/components/features/chat/lib/locale-path";
import { cn } from "@/lib/utils";
import { resolveApiMediaUrl } from "@/lib/mediaUrl";
import { apiClient } from "@/services/api/client";
import { formatDateTimeLocalized, formatNumberLocalized } from "@/lib/i18n-format";
import type { AttachmentItem, ChannelResponse, EventIntegrityResponse, EventResponse, MessageResponse, UserPublicProfile } from "@/types/api";

const EVENT_LIMIT = 100;

type ReferenceMaps = {
  channel: ChannelResponse;
  users: Map<string, UserPublicProfile>;
  loadingUserIds: Set<string>;
  messages: Map<string, MessageResponse>;
  loadingMessageIds: Set<string>;
  uploads: Map<string, AttachmentItem>;
  locale: string;
  t: ReturnType<typeof useTranslations>;
  commonT: ReturnType<typeof useTranslations>;
  profilePathForUser: (userId: string) => string;
};

type ReferenceKind = "user" | "channel" | "message" | "upload" | "invite" | "delivery" | "client" | "internal";

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const UUID_IN_TEXT_RE = /[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}/gi;
const ISO_DATE_RE = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}/;

const USER_ID_KEYS = new Set([
  "actor_user_id",
  "created_by_user_id",
  "invited_by_user_id",
  "owner_user_id",
  "pinned_by_user_id",
  "sender_user_id",
  "target_user_id",
  "user_id",
]);

const MESSAGE_ID_KEYS = new Set(["message_id", "reply_to_message_id", "last_seen_message_id"]);
const UPLOAD_ID_KEYS = new Set(["file_id", "upload_id"]);
const DELIVERY_ID_KEYS = new Set(["outbox_id", "delivery_id"]);
const CLIENT_ID_KEYS = new Set(["client_msg_id"]);

const HIDDEN_TECHNICAL_KEYS = new Set(["id"]);

// Implements the short hash operation; the page component uses it to prepare or render the interface.
function shortHash(value?: string | null) {
  // Return early when `!value` because the remaining work is not applicable.
  if (!value) return "-";
  // Return early when `value.length <= 20` because the remaining work is not applicable.
  if (value.length <= 20) return value;
  return `${value.slice(0, 12)}...${value.slice(-8)}`;
}

// Determines whether record; the page component uses it to prepare or render the interface.
function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

// Determines whether uuid; the page component uses it to prepare or render the interface.
function isUuid(value: unknown): value is string {
  return typeof value === "string" && UUID_RE.test(value);
}

// Implements the unique operation; the page component uses it to prepare or render the interface.
function unique(values: Array<string | null | undefined>) {
  return Array.from(new Set(values.filter((value): value is string => Boolean(value)))).sort();
}

// Implements the title case operation; the page component uses it to prepare or render the interface.
function titleCase(value: string) {
  return value
    .replace(/[._-]+/g, " ")
    .replace(/\s+/g, " ")
    .trim()
    .replace(/\b\w/g, (match) => match.toUpperCase());
}

// Converts key; the page component uses it to prepare or render the interface.
function humanizeKey(key: string, references: ReferenceMaps) {
  const t = references.t;
  const labels: Record<string, string> = {
    actor_user_id: t("fields.actor"),
    admin_permissions: t("fields.adminPermissions"),
    attempt_count: t("fields.attempts"),
    avatar_url: t("fields.avatar"),
    channel_id: t("fields.channel"),
    channel_slug: t("fields.channelSlug"),
    client_msg_id: t("fields.clientRetryToken"),
    content_json: t("fields.messageData"),
    content_text: t("fields.messageText"),
    content_type: t("fields.contentType"),
    deleted_at: t("fields.deleted"),
    edited_at: t("fields.edited"),
    file_id: t("fields.upload"),
    filename: t("fields.fileName"),
    invite_id: t("fields.invite"),
    is_pinned: t("fields.pinned"),
    join_mode: t("fields.joinMode"),
    last_error: t("fields.lastError"),
    max_attempts: t("fields.maxAttempts"),
    message_id: t("fields.message"),
    new_role: t("fields.newRole"),
    outbox_id: t("fields.deliveryJob"),
    previous_attempt_count: t("fields.previousAttempts"),
    previous_status: t("fields.previousStatus"),
    reply_to_message_id: t("fields.replyTo"),
    retry_in_seconds: t("fields.retryDelay"),
    routing_key: t("fields.brokerRoute"),
    sender_display_name: t("fields.senderDisplayName"),
    sender_user_id: t("fields.sender"),
    sender_username: t("fields.senderUsername"),
    seq_id: t("fields.messageNumber"),
    size_bytes: t("fields.fileSize"),
    target_user_id: t("fields.targetMember"),
    updated_at: t("fields.updated"),
    user_id: t("fields.user"),
  };
  return labels[key] ?? titleCase(key);
}

// Provides r display name behavior; React components use it to access or update application state.
function userDisplayName(user?: UserPublicProfile | null) {
  // Return early when `!user` because the remaining work is not applicable.
  if (!user) return null;
  // Return early when `user.display_name?.trim()` because the remaining work is not applicable.
  if (user.display_name?.trim()) return `${user.display_name} (@${user.username})`;
  return `@${user.username}`;
}

// Provides r initial behavior; React components use it to access or update application state.
function userInitial(user?: UserPublicProfile | null) {
  return (user?.display_name || user?.username || "U").slice(0, 1).toUpperCase();
}

// Implements the message preview operation; the page component uses it to prepare or render the interface.
function messagePreview(message: MessageResponse | null | undefined, references: ReferenceMaps) {
  const t = references.t;
  // Return early when `!message` because the remaining work is not applicable.
  if (!message) return null;
  // Return early when `message.deleted_at` because the remaining work is not applicable.
  if (message.deleted_at) return t("references.deletedMessage");
  // Return early when `message.content_text?.trim()` because the remaining work is not applicable.
  if (message.content_text?.trim()) return message.content_text.trim();
  // Return early when `message.content_json` because the remaining work is not applicable.
  if (message.content_json) return t("references.jsonMessage");
  // Return early when `message.attachments?.length` because the remaining work is not applicable.
  if (message.attachments?.length) return t("references.attachments", { count: message.attachments.length });
  return t("references.emptyMessage");
}

// Truncates; the page component uses it to prepare or render the interface.
function truncate(value: string, maxLength = 96) {
  // Return early when `value.length <= maxLength` because the remaining work is not applicable.
  if (value.length <= maxLength) return value;
  return `${value.slice(0, maxLength - 1)}...`;
}

// Masks internal ids; the page component uses it to prepare or render the interface.
function maskInternalIds(value: string) {
  return value.replace(UUID_IN_TEXT_RE, "internal reference");
}

// Formats bytes; the page component uses it to prepare or render the interface.
function formatBytes(value: unknown, references?: ReferenceMaps) {
  // Return early when `typeof value !== "number" || Number.isNaN(value)` because the remaining work is not applicable.
  if (typeof value !== "number" || Number.isNaN(value)) return references?.commonT("notAvailable") ?? "N/A";
  // Return early when `value < 1024` because the remaining work is not applicable.
  if (value < 1024) return `${value} B`;
  const units = ["KB", "MB", "GB"];
  let current = value / 1024;
  let unit = units[0];
  // Repeat this indexed operation while `index < units.length && current >= 1024` remains true.
  for (let index = 1; index < units.length && current >= 1024; index += 1) {
    current /= 1024;
    unit = units[index];
  }
  return `${current.toFixed(current >= 10 ? 0 : 1)} ${unit}`;
}

// Normalizes status; the page component uses it to prepare or render the interface.
function normalizeStatus(value: unknown) {
  // Return early when `typeof value !== "string"` because the remaining work is not applicable.
  if (typeof value !== "string") return String(value);
  return value.replace(/_/g, " ");
}

// Implements the role label operation; the page component uses it to prepare or render the interface.
function roleLabel(value: unknown, references: ReferenceMaps) {
  // Return early when `typeof value !== "string"` because the remaining work is not applicable.
  if (typeof value !== "string") return String(value);
  // Return early when `value === "owner"` because the remaining work is not applicable.
  if (value === "owner") return references.commonT("roles.owner");
  // Return early when `value === "admin"` because the remaining work is not applicable.
  if (value === "admin") return references.commonT("roles.admin");
  // Return early when `value === "member"` because the remaining work is not applicable.
  if (value === "member") return references.commonT("roles.member");
  // Return early when `value === "pending"` because the remaining work is not applicable.
  if (value === "pending") return references.commonT("roles.pending");
  return titleCase(value);
}

// Implements the event category operation; the page component uses it to prepare or render the interface.
function eventCategory(eventType: string) {
  return eventType.split(".")[0] || "event";
}

// Implements the event badge variant operation; the page component uses it to prepare or render the interface.
function eventBadgeVariant(eventType: string): "default" | "secondary" | "destructive" | "outline" {
  // Return early when `eventType.startsWith("security.") || eventType.includes("failed") ||...` because the remaining work is not applicable.
  if (eventType.startsWith("security.") || eventType.includes("failed") || eventType.includes("dead_lettered")) {
    return "destructive";
  }
  // Return early when `eventType.startsWith("broker.")` because the remaining work is not applicable.
  if (eventType.startsWith("broker.")) return "secondary";
  // Return early when `eventType.startsWith("message.")` because the remaining work is not applicable.
  if (eventType.startsWith("message.")) return "default";
  return "outline";
}

// Implements the event icon operation; the page component uses it to prepare or render the interface.
function eventIcon(eventType: string) {
  // Return early when `eventType.startsWith("security.")` because the remaining work is not applicable.
  if (eventType.startsWith("security.")) return LockKeyhole;
  // Return early when `eventType === "channel.created"` because the remaining work is not applicable.
  if (eventType === "channel.created") return Hash;
  // Return early when `eventType === "channel.updated" || eventType === "member.permissions....` because the remaining work is not applicable.
  if (eventType === "channel.updated" || eventType === "member.permissions.updated") return Settings;
  // Return early when `eventType === "channel.deleted"` because the remaining work is not applicable.
  if (eventType === "channel.deleted") return UserX;
  // Return early when `eventType.includes("invite")` because the remaining work is not applicable.
  if (eventType.includes("invite")) return Mail;
  // Return early when `eventType === "membership.joined" || eventType === "membership.added"` because the remaining work is not applicable.
  if (eventType === "membership.joined" || eventType === "membership.added") return UserPlus;
  // Return early when `eventType === "membership.approved" || eventType === "member.promoted"` because the remaining work is not applicable.
  if (eventType === "membership.approved" || eventType === "member.promoted") return UserCheck;
  // Return early when `eventType === "membership.left" || eventType === "member.demoted"` because the remaining work is not applicable.
  if (eventType === "membership.left" || eventType === "member.demoted") return UserMinus;
  // Return early when `eventType === "member.removed"` because the remaining work is not applicable.
  if (eventType === "member.removed") return UserX;
  // Return early when `eventType.startsWith("message.")` because the remaining work is not applicable.
  if (eventType.startsWith("message.")) return MessageSquare;
  // Return early when `eventType === "broker.dead_lettered"` because the remaining work is not applicable.
  if (eventType === "broker.dead_lettered") return ServerCrash;
  // Return early when `eventType.startsWith("broker.")` because the remaining work is not applicable.
  if (eventType.startsWith("broker.")) return DatabaseZap;
  return CalendarClock;
}

// Retrieves event subject user id; the page component uses it to prepare or render the interface.
function getEventSubjectUserId(event: EventResponse) {
  const payload = event.payload ?? {};
  const target = payload.target_user_id ?? payload.user_id ?? payload.sender_user_id ?? event.actor_user_id;
  return isUuid(target) ? target : null;
}

// Retrieves event message id; the page component uses it to prepare or render the interface.
function getEventMessageId(event: EventResponse) {
  const payload = event.payload ?? {};
  // Return early when `isUuid(payload.message_id)` because the remaining work is not applicable.
  if (isUuid(payload.message_id)) return payload.message_id;
  // Return early when `event.event_type.startsWith("message.") && isUuid(payload.id)` because the remaining work is not applicable.
  if (event.event_type.startsWith("message.") && isUuid(payload.id)) return payload.id;
  // Return early when `isUuid(payload.reply_to_message_id)` because the remaining work is not applicable.
  if (isUuid(payload.reply_to_message_id)) return payload.reply_to_message_id;
  return null;
}

// Retrieves reference kind; the page component uses it to prepare or render the interface.
function getReferenceKind(key: string, value: unknown, eventType?: string): ReferenceKind | null {
  // Return early when `key === "channel_id" && isUuid(value)` because the remaining work is not applicable.
  if (key === "channel_id" && isUuid(value)) return "channel";
  // Return early when `USER_ID_KEYS.has(key) && isUuid(value)` because the remaining work is not applicable.
  if (USER_ID_KEYS.has(key) && isUuid(value)) return "user";
  // Return early when `(MESSAGE_ID_KEYS.has(key) || (key === "id" && eventType?.startsWith("...` because the remaining work is not applicable.
  if ((MESSAGE_ID_KEYS.has(key) || (key === "id" && eventType?.startsWith("message."))) && isUuid(value)) return "message";
  // Return early when `UPLOAD_ID_KEYS.has(key) && isUuid(value)` because the remaining work is not applicable.
  if (UPLOAD_ID_KEYS.has(key) && isUuid(value)) return "upload";
  // Return early when `key === "invite_id" && isUuid(value)` because the remaining work is not applicable.
  if (key === "invite_id" && isUuid(value)) return "invite";
  // Return early when `DELIVERY_ID_KEYS.has(key) && isUuid(value)` because the remaining work is not applicable.
  if (DELIVERY_ID_KEYS.has(key) && isUuid(value)) return "delivery";
  // Return early when `CLIENT_ID_KEYS.has(key) && typeof value === "string"` because the remaining work is not applicable.
  if (CLIENT_ID_KEYS.has(key) && typeof value === "string") return "client";
  // Return early when `isUuid(value)` because the remaining work is not applicable.
  if (isUuid(value)) return "internal";
  return null;
}

// Implements the collect references from payload operation; the page component uses it to prepare or render the interface.
function collectReferencesFromPayload(
  value: unknown,
  eventType: string,
  userIds: string[],
  messageIds: string[],
  uploads: Map<string, AttachmentItem>,
) {
  // Run this conditional step only when `Array.isArray(value)` is true.
  if (Array.isArray(value)) {
    value.forEach((item) => collectReferencesFromPayload(item, eventType, userIds, messageIds, uploads));
    return;
  }

  // Return early when `!isRecord(value)` because the remaining work is not applicable.
  if (!isRecord(value)) return;

  // Run this conditional step only when `isUuid(value.file_id)` is true.
  if (isUuid(value.file_id)) {
    uploads.set(value.file_id, {
      file_id: value.file_id,
      filename: typeof value.filename === "string" ? value.filename : undefined,
      content_type: typeof value.content_type === "string" ? value.content_type : undefined,
      public_url: typeof value.public_url === "string" ? value.public_url : "",
      size_bytes: typeof value.size_bytes === "number" ? value.size_bytes : undefined,
    });
  }

  Object.entries(value).forEach(([childKey, childValue]) => {
    const kind = getReferenceKind(childKey, childValue, eventType);
    // Run this conditional step only when `kind === "user" && typeof childValue === "string"` is true.
    if (kind === "user" && typeof childValue === "string") userIds.push(childValue);
    // Run this conditional step only when `kind === "message" && typeof childValue === "string"` is true.
    if (kind === "message" && typeof childValue === "string") messageIds.push(childValue);
    collectReferencesFromPayload(childValue, eventType, userIds, messageIds, uploads);
  });
}

// Implements the collect event references operation; the page component uses it to prepare or render the interface.
function collectEventReferences(events: EventResponse[] | undefined) {
  const userIds: string[] = [];
  const messageIds: string[] = [];
  const uploads = new Map<string, AttachmentItem>();

  // Process each item from `events ?? []` so this step covers the collection.
  for (const event of events ?? []) {
    // Run this conditional step only when `isUuid(event.actor_user_id)` is true.
    if (isUuid(event.actor_user_id)) userIds.push(event.actor_user_id);
    collectReferencesFromPayload(event.payload ?? {}, event.event_type, userIds, messageIds, uploads);
  }

  return {
    userIds: unique(userIds),
    messageIds: unique(messageIds),
    uploads,
  };
}

// Renders the loading reference component; the route adapter uses it for the matching application page.
function LoadingReference({ label }: { label: string }) {
  return (
    <span className="inline-flex min-h-7 items-center gap-2 rounded-md border border-border/70 bg-muted/40 px-2.5 py-1 text-xs text-muted-foreground">
      <span className="h-2 w-2 animate-pulse rounded-full bg-muted-foreground/60" />
      {label}
    </span>
  );
}

// Renders the user reference component; the route adapter uses it for the matching application page.
function UserReference({ userId, references, fallback }: { userId?: string | null; references: ReferenceMaps; fallback?: string }) {
  // Return early when `!userId` because the remaining work is not applicable.
  if (!userId) return <span className="text-muted-foreground">{references.t("references.system")}</span>;
  const user = references.users.get(userId);
  const fallbackLabel = fallback ?? references.t("references.userUnavailable");
  // Return early when `!user && references.loadingUserIds.has(userId)` because the remaining work is not applicable.
  if (!user && references.loadingUserIds.has(userId)) return <LoadingReference label={references.t("references.loadingUser")} />;
  const avatarUrl = resolveApiMediaUrl(user?.avatar_url);

  return (
    <Link
      href={references.profilePathForUser(userId)}
      className="inline-flex min-h-7 max-w-full items-center gap-2 rounded-md border border-border/70 bg-background px-2.5 py-1 text-xs font-medium underline-offset-2 hover:bg-accent hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
    >
      <Avatar className="h-5 w-5">
        {avatarUrl ? <AvatarImage src={avatarUrl} alt={userDisplayName(user) ?? fallbackLabel} /> : null}
        <AvatarFallback className="text-[10px]">{userInitial(user)}</AvatarFallback>
      </Avatar>
      <span className="truncate">{userDisplayName(user) ?? fallbackLabel}</span>
    </Link>
  );
}

// Renders the channel reference component; the route adapter uses it for the matching application page.
function ChannelReference({ references }: { references: ReferenceMaps }) {
  return (
    <span className="inline-flex min-h-7 max-w-full items-center gap-2 rounded-md border border-border/70 bg-background px-2.5 py-1 text-xs font-medium">
      <Hash className="h-3.5 w-3.5 text-primary" />
      <span className="truncate">{references.channel.name}</span>
      {references.channel.channel_slug ? (
        <span className="hidden text-muted-foreground sm:inline">/{references.channel.channel_slug}</span>
      ) : null}
    </span>
  );
}

// Renders the message reference component; the route adapter uses it for the matching application page.
function MessageReference({
  messageId,
  event,
  references,
}: {
  messageId?: string | null;
  event?: EventResponse;
  references: ReferenceMaps;
}) {
  const payload = event?.payload ?? {};
  const id = messageId ?? getEventMessageId(event as EventResponse);
  const message = id ? references.messages.get(id) : undefined;

  // Return early when `id && !message && references.loadingMessageIds.has(id)` because the remaining work is not applicable.
  if (id && !message && references.loadingMessageIds.has(id)) {
    return <LoadingReference label={references.t("references.loadingMessage")} />;
  }

  const seqId = message?.seq_id ?? (typeof payload.seq_id === "number" ? payload.seq_id : null);
  const sender = message?.sender_display_name || message?.sender_username || (typeof payload.sender_username === "string" ? payload.sender_username : null);
  const preview = messagePreview(message, references) ?? (typeof payload.content_type === "string" ? references.t("references.typedMessage", { type: titleCase(payload.content_type) }) : references.t("references.message"));

  return (
    <span className="inline-flex min-h-7 max-w-full items-center gap-2 rounded-md border border-border/70 bg-background px-2.5 py-1 text-xs">
      <MessageSquare className="h-3.5 w-3.5 text-primary" />
      <span className="font-medium">{seqId ? references.t("references.messageNumber", { seq: seqId }) : references.t("references.message")}</span>
      {sender ? <span className="text-muted-foreground">{references.t("references.bySender", { sender })}</span> : null}
      <span className="truncate text-muted-foreground">{truncate(preview, 48)}</span>
    </span>
  );
}

// Renders the upload reference component; the route adapter uses it for the matching application page.
function UploadReference({ uploadId, references }: { uploadId?: string | null; references: ReferenceMaps }) {
  const upload = uploadId ? references.uploads.get(uploadId) : undefined;
  return (
    <span className="inline-flex min-h-7 max-w-full items-center gap-2 rounded-md border border-border/70 bg-background px-2.5 py-1 text-xs">
      <Inbox className="h-3.5 w-3.5 text-primary" />
      <span className="truncate font-medium">{upload?.filename || references.t("references.uploadFile")}</span>
      {upload?.size_bytes ? <span className="text-muted-foreground">{formatBytes(upload.size_bytes, references)}</span> : null}
    </span>
  );
}

// Renders the generic reference component; the route adapter uses it for the matching application page.
function GenericReference({
  kind,
  references,
}: {
  kind: Exclude<ReferenceKind, "user" | "channel" | "message" | "upload">;
  references: ReferenceMaps;
}) {
  const labels: Record<typeof kind, string> = {
    client: references.t("references.clientRetryToken"),
    delivery: references.t("references.deliveryJob"),
    internal: references.t("references.internalReference"),
    invite: references.t("references.inviteLink"),
  };
  return (
    <span className="inline-flex min-h-7 items-center gap-2 rounded-md border border-border/70 bg-background px-2.5 py-1 text-xs text-muted-foreground">
      <FileJson className="h-3.5 w-3.5" />
      {labels[kind]}
    </span>
  );
}

// Renders the reference value component; the route adapter uses it for the matching application page.
function ReferenceValue({
  kind,
  value,
  references,
  event,
}: {
  kind: ReferenceKind;
  value: unknown;
  references: ReferenceMaps;
  event?: EventResponse;
}) {
  const stringValue = typeof value === "string" ? value : null;
  // Return early when `kind === "user"` because the remaining work is not applicable.
  if (kind === "user") return <UserReference userId={stringValue} references={references} />;
  // Return early when `kind === "channel"` because the remaining work is not applicable.
  if (kind === "channel") return <ChannelReference references={references} />;
  // Return early when `kind === "message"` because the remaining work is not applicable.
  if (kind === "message") return <MessageReference messageId={stringValue} event={event} references={references} />;
  // Return early when `kind === "upload"` because the remaining work is not applicable.
  if (kind === "upload") return <UploadReference uploadId={stringValue} references={references} />;
  return <GenericReference kind={kind} references={references} />;
}

// Formats routing key; the page component uses it to prepare or render the interface.
function formatRoutingKey(value: string, references: ReferenceMaps) {
  // Return early when `value.startsWith("channel.")` because the remaining work is not applicable.
  if (value.startsWith("channel.")) return references.t("references.channelBrokerRoute", { name: references.channel.name });
  // Return early when `value.startsWith("user.")` because the remaining work is not applicable.
  if (value.startsWith("user.")) return references.t("references.userDeliveryRoute");
  // Return early when `value.startsWith("dead.")` because the remaining work is not applicable.
  if (value.startsWith("dead.")) return references.t("references.deadLetterBrokerRoute");
  return maskInternalIds(value);
}

// Renders the scalar value component; the route adapter uses it for the matching application page.
function ScalarValue({
  fieldKey,
  value,
  references,
  event,
}: {
  fieldKey: string;
  value: unknown;
  references: ReferenceMaps;
  event?: EventResponse;
}) {
  const referenceKind = getReferenceKind(fieldKey, value, event?.event_type);
  // Return early when `referenceKind` because the remaining work is not applicable.
  if (referenceKind) {
    return <ReferenceValue kind={referenceKind} value={value} references={references} event={event} />;
  }

  // Return early when `value === null || value === undefined || value === ""` because the remaining work is not applicable.
  if (value === null || value === undefined || value === "") {
    return <span className="text-muted-foreground">{references.t("values.notSet")}</span>;
  }

  // Return early when `typeof value === "boolean"` because the remaining work is not applicable.
  if (typeof value === "boolean") {
    return <Badge variant={value ? "default" : "secondary"}>{value ? references.commonT("yes") : references.commonT("no")}</Badge>;
  }

  // Run this conditional step only when `typeof value === "number"` is true.
  if (typeof value === "number") {
    // Return early when `fieldKey === "size_bytes"` because the remaining work is not applicable.
    if (fieldKey === "size_bytes") return <span>{formatBytes(value, references)}</span>;
    // Return early when `fieldKey === "retry_in_seconds"` because the remaining work is not applicable.
    if (fieldKey === "retry_in_seconds") return <span>{references.t("values.seconds", { count: value })}</span>;
    return <span>{formatNumberLocalized(value, references.locale)}</span>;
  }

  // Run this conditional step only when `typeof value === "string"` is true.
  if (typeof value === "string") {
    // Return early when `fieldKey === "routing_key"` because the remaining work is not applicable.
    if (fieldKey === "routing_key") return <span>{formatRoutingKey(value, references)}</span>;
    // Return early when `fieldKey.endsWith("_url") || fieldKey === "url" || fieldKey === "publ...` because the remaining work is not applicable.
    if (fieldKey.endsWith("_url") || fieldKey === "url" || fieldKey === "public_url") {
      return <span>{value.includes("/uploads/") ? references.t("values.privateUploadLink") : maskInternalIds(value)}</span>;
    }
    // Run this conditional step only when `fieldKey === "content_text" && event` is true.
    if (fieldKey === "content_text" && event) {
      const messageId = getEventMessageId(event);
      const message = messageId ? references.messages.get(messageId) : undefined;
      return <span>{message?.content_text ? truncate(message.content_text, 180) : references.t("values.storedMessageText")}</span>;
    }
    // Return early when `fieldKey === "content_type"` because the remaining work is not applicable.
    if (fieldKey === "content_type") return <Badge variant="outline">{titleCase(value)}</Badge>;
    // Return early when `fieldKey === "role" || fieldKey === "new_role"` because the remaining work is not applicable.
    if (fieldKey === "role" || fieldKey === "new_role") return <Badge variant="secondary">{roleLabel(value, references)}</Badge>;
    // Return early when `fieldKey.includes("status")` because the remaining work is not applicable.
    if (fieldKey.includes("status")) return <Badge variant="outline">{normalizeStatus(value)}</Badge>;
    // Return early when `ISO_DATE_RE.test(value)` because the remaining work is not applicable.
    if (ISO_DATE_RE.test(value)) return <span>{formatDateTimeLocalized(value, references.locale, references.commonT("notAvailable"))}</span>;
    return <span className="break-words">{maskInternalIds(value)}</span>;
  }

  return <span>{String(value)}</span>;
}

// Renders the structured value component; the route adapter uses it for the matching application page.
function StructuredValue({
  fieldKey,
  value,
  references,
  event,
  depth = 0,
}: {
  fieldKey: string;
  value: unknown;
  references: ReferenceMaps;
  event?: EventResponse;
  depth?: number;
}) {
  // Run this conditional step only when `Array.isArray(value)` is true.
  if (Array.isArray(value)) {
    // Return early when `value.length === 0` because the remaining work is not applicable.
    if (value.length === 0) return <span className="text-muted-foreground">{references.t("values.none")}</span>;

    return (
      <div className="space-y-2">
        {value.map((item, index) => (
          <div key={index} className="rounded-md border border-border/60 bg-background/70 p-3">
            <StructuredValue fieldKey={fieldKey} value={item} references={references} event={event} depth={depth + 1} />
          </div>
        ))}
      </div>
    );
  }

  // Run this conditional step only when `isRecord(value)` is true.
  if (isRecord(value)) {
    const entries = Object.entries(value).filter(([key]) => !(depth > 0 && HIDDEN_TECHNICAL_KEYS.has(key)));
    // Return early when `entries.length === 0` because the remaining work is not applicable.
    if (entries.length === 0) return <span className="text-muted-foreground">{references.t("values.noDetails")}</span>;

    // Run this conditional step only when `fieldKey === "content_json" && "_enc_v1" in value` is true.
    if (fieldKey === "content_json" && "_enc_v1" in value) {
      const messageId = event ? getEventMessageId(event) : null;
      const message = messageId ? references.messages.get(messageId) : undefined;
      // Return early when `message?.content_json` because the remaining work is not applicable.
      if (message?.content_json) {
        return <StructuredValue fieldKey={fieldKey} value={message.content_json} references={references} event={event} depth={depth + 1} />;
      }
      return <span className="text-muted-foreground">{references.t("values.encryptedJsonContent")}</span>;
    }

    return (
      <div className={cn("grid gap-2", depth === 0 ? "sm:grid-cols-2" : "")}>
        {entries.map(([key, childValue]) => (
          <div key={key} className="rounded-md border border-border/60 bg-background/70 p-3">
            <p className="mb-1 text-xs font-medium uppercase text-muted-foreground">{humanizeKey(key, references)}</p>
            <StructuredValue fieldKey={key} value={childValue} references={references} event={event} depth={depth + 1} />
          </div>
        ))}
      </div>
    );
  }

  return <ScalarValue fieldKey={fieldKey} value={value} references={references} event={event} />;
}

// Renders the structured payload component; the route adapter uses it for the matching application page.
function StructuredPayload({ event, references }: { event: EventResponse; references: ReferenceMaps }) {
  const payload = event.payload ?? {};
  const entries = Object.entries(payload).filter(([key]) => !HIDDEN_TECHNICAL_KEYS.has(key));

  // Return early when `entries.length === 0` because the remaining work is not applicable.
  if (entries.length === 0) {
    return (
      <div className="rounded-md border border-dashed border-border/70 bg-muted/20 p-4 text-sm text-muted-foreground">
        {references.t("values.noAdditionalDetails")}
      </div>
    );
  }

  return (
    <div className="grid gap-3 sm:grid-cols-2">
      {entries.map(([key, value]) => (
        <div key={key} className="rounded-md border border-border/60 bg-muted/20 p-3">
          <p className="mb-2 text-xs font-medium uppercase text-muted-foreground">{humanizeKey(key, references)}</p>
          <StructuredValue fieldKey={key} value={value} references={references} event={event} />
        </div>
      ))}
    </div>
  );
}

// Implements the describe event operation; the page component uses it to prepare or render the interface.
function describeEvent(event: EventResponse, references: ReferenceMaps): { title: string; description: ReactNode } {
  const t = references.t;
  const payload = event.payload ?? {};
  const actor = <UserReference userId={event.actor_user_id} references={references} fallback={t("references.unknownActor")} />;
  const subjectUserId = getEventSubjectUserId(event);
  const subject = <UserReference userId={subjectUserId} references={references} fallback={t("references.unknownUser")} />;
  const target = isUuid(payload.target_user_id) ? (
    <UserReference userId={payload.target_user_id} references={references} fallback={t("references.unknownMember")} />
  ) : subject;
  const channel = <ChannelReference references={references} />;
  const message = <MessageReference event={event} references={references} />;

  // Select the matching behavior for `event.event_type`.
  switch (event.event_type) {
    case "channel.created":
      return { title: t("events.channelCreated.title"), description: <>{actor} {t("events.channelCreated.description")} {channel}</> };
    case "channel.updated":
      return { title: t("events.channelUpdated.title"), description: <>{actor} {t("events.channelUpdated.description")} {channel}</> };
    case "channel.deleted":
      return { title: t("events.channelDeleted.title"), description: <>{actor} {t("events.channelDeleted.description")} {channel}</> };
    case "channel.slug_collision_resolved":
      return { title: t("events.slugAdjusted.title"), description: <>{t("events.slugAdjusted.description")}</> };
    case "membership.joined":
      return { title: t("events.memberJoined.title"), description: <>{subject} {t("events.memberJoined.joined")} {channel} {t("events.memberJoined.as")} {roleLabel(payload.role, references)}</> };
    case "membership.left":
      return { title: t("events.memberLeft.title"), description: <>{subject} {t("events.memberLeft.description")} {channel}</> };
    case "membership.approved":
      return { title: t("events.requestApproved.title"), description: <>{actor} {t("events.requestApproved.description")} {target}</> };
    case "membership.added":
      return { title: t("events.memberAdded.title"), description: <>{actor} {t("events.memberAdded.description")} {target}</> };
    case "member.promoted":
      return { title: t("events.memberPromoted.title"), description: <>{actor} {t("events.memberPromoted.description")} {target}</> };
    case "member.demoted":
      return { title: t("events.memberDemoted.title"), description: <>{actor} {t("events.memberDemoted.description")} {target}</> };
    case "member.removed":
      return { title: t("events.memberRemoved.title"), description: <>{actor} {t("events.memberRemoved.description")} {target}</> };
    case "member.permissions.updated":
      return { title: t("events.permissionsUpdated.title"), description: <>{actor} {t("events.permissionsUpdated.description")} {target}</> };
    case "invite.created":
      return { title: t("events.inviteCreated.title"), description: <>{actor} {t("events.inviteCreated.description")}</> };
    case "invite.revoked":
      return { title: t("events.inviteRevoked.title"), description: <>{actor} {t("events.inviteRevoked.description")}</> };
    case "invite.accepted":
      return { title: t("events.inviteAccepted.title"), description: <>{subject} {t("events.inviteAccepted.description")}</> };
    case "message.published":
      return { title: t("events.messagePublished.title"), description: <>{actor} {t("events.messagePublished.description")} {message}</> };
    case "message.encryption_failed":
      return { title: t("events.encryptionFailed.title"), description: <>{t("events.encryptionFailed.before")} {actor} {t("events.encryptionFailed.after")}</> };
    case "message.decryption_failed":
      return { title: t("events.decryptionFailed.title"), description: <>{t("events.decryptionFailed.description")}</> };
    case "security.unauthorized_publish":
      return { title: t("events.publishBlocked.title"), description: <>{actor} {t("events.publishBlocked.description")}</> };
    case "security.unauthorized_read":
      return { title: t("events.readBlocked.title"), description: <>{actor} {t("events.readBlocked.description")}</> };
    case "broker.retry_scheduled":
      return { title: t("events.brokerRetry.title"), description: <>{t("events.brokerRetry.description")}</> };
    case "broker.dead_lettered":
      return { title: t("events.brokerDeadLettered.title"), description: <>{t("events.brokerDeadLettered.description")}</> };
    case "broker.manual_retry_requested":
      return { title: t("events.manualRetry.title"), description: <>{actor} {t("events.manualRetry.description")}</> };
    default:
      return { title: titleCase(event.event_type), description: <>{t("events.default.description")} {channel}.</> };
  }
}

// Renders the event references component; the route adapter uses it for the matching application page.
function EventReferences({ event, references }: { event: EventResponse; references: ReferenceMaps }) {
  const messageId = getEventMessageId(event);
  const targetUserId = isUuid(event.payload?.target_user_id) ? event.payload.target_user_id : null;
  const subjectUserId = getEventSubjectUserId(event);
  const uploadIds = Object.values(event.payload ?? {})
    .filter((value): value is string => isUuid(value) && references.uploads.has(value));

  return (
    <div className="mt-3 flex flex-wrap gap-2">
      <UserReference userId={event.actor_user_id} references={references} fallback={references.t("references.unknownActor")} />
      <ChannelReference references={references} />
      {targetUserId && targetUserId !== event.actor_user_id ? (
        <UserReference userId={targetUserId} references={references} fallback={references.t("references.unknownMember")} />
      ) : null}
      {subjectUserId && subjectUserId !== event.actor_user_id && subjectUserId !== targetUserId ? (
        <UserReference userId={subjectUserId} references={references} fallback={references.t("references.unknownUser")} />
      ) : null}
      {messageId ? <MessageReference messageId={messageId} event={event} references={references} /> : null}
      {uploadIds.map((uploadId) => (
        <UploadReference key={uploadId} uploadId={uploadId} references={references} />
      ))}
    </div>
  );
}

// Renders the event log item component; the route adapter uses it for the matching application page.
function EventLogItem({ event, references }: { event: EventResponse; references: ReferenceMaps }) {
  const Icon = eventIcon(event.event_type);
  const description = describeEvent(event, references);

  return (
    <div className="grid gap-4 px-6 py-5 sm:grid-cols-[auto_1fr]">
      <div className="flex h-10 w-10 items-center justify-center rounded-md bg-primary/10 text-primary">
        <Icon className="h-5 w-5" />
      </div>
      <div className="min-w-0">
        <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant={eventBadgeVariant(event.event_type)}>{titleCase(event.event_type)}</Badge>
            <Badge variant="outline">{titleCase(eventCategory(event.event_type))}</Badge>
          </div>
          <time className="text-sm text-muted-foreground">{formatDateTimeLocalized(event.created_at, references.locale, references.commonT("notAvailable"))}</time>
        </div>

        <h3 className="mt-3 text-base font-semibold">{description.title}</h3>
        <div className="mt-2 flex flex-wrap items-center gap-2 text-sm text-muted-foreground">{description.description}</div>

        <EventReferences event={event} references={references} />

        <Accordion type="single" collapsible className="mt-4 rounded-md border border-border/60 bg-muted/10 px-4">
          <AccordionItem value="details" className="border-b-0">
            <AccordionTrigger className="py-3 text-sm hover:no-underline">
              {references.t("structuredDetails")}
            </AccordionTrigger>
            <AccordionContent>
              <StructuredPayload event={event} references={references} />
            </AccordionContent>
          </AccordionItem>
        </Accordion>
      </div>
    </div>
  );
}

// Retrieves integrity status; the page component uses it to prepare or render the interface.
function getIntegrityStatus(
  result: EventIntegrityResponse | undefined,
  isFetching: boolean,
  isError: boolean,
  t: ReturnType<typeof useTranslations>,
): { label: string; variant: "default" | "secondary" | "destructive" | "outline" } {
  // Return early when `isFetching` because the remaining work is not applicable.
  if (isFetching) return { label: t("integrity.checking"), variant: "secondary" };
  // Return early when `isError` because the remaining work is not applicable.
  if (isError) return { label: t("integrity.checkFailed"), variant: "destructive" };
  // Return early when `!result` because the remaining work is not applicable.
  if (!result) return { label: t("integrity.notChecked"), variant: "outline" };
  // Return early when `result.valid` because the remaining work is not applicable.
  if (result.valid) return { label: t("integrity.verified"), variant: "default" };
  // Return early when `result.reason === "missing_hash"` because the remaining work is not applicable.
  if (result.reason === "missing_hash") return { label: t("integrity.notInitialized"), variant: "secondary" };
  return { label: t("integrity.broken"), variant: "destructive" };
}

// Renders the channel event log skeleton component; the route adapter uses it for the matching application page.
function ChannelEventLogSkeleton() {
  return (
    <div className="h-full min-h-0 overflow-y-auto bg-background p-6 text-foreground sm:p-8">
      <div className="mx-auto max-w-6xl space-y-6">
        <div className="flex items-center justify-between gap-4">
          <div className="space-y-3">
            <Skeleton className="h-4 w-32" />
            <Skeleton className="h-9 w-48" />
            <Skeleton className="h-4 w-80 max-w-full" />
          </div>
          <div className="flex items-center gap-2">
            <Skeleton className="h-10 w-32 rounded-md" />
            <Skeleton className="h-10 w-28 rounded-md" />
          </div>
        </div>
        <Card className="rounded-md p-6">
          <Skeleton className="h-20 w-full rounded-md" />
          <div className="mt-6 space-y-2">
            <Skeleton className="h-24 w-full rounded-md" />
            <Skeleton className="h-24 w-full rounded-md" />
            <Skeleton className="h-24 w-full rounded-md" />
          </div>
        </Card>
      </div>
    </div>
  );
}

// Renders the channel event log page; the route adapter uses it for the matching application page.
export default function ChannelEventLogPage() {
  const params = useParams<{ channelId?: string | string[] }>();
  const channelId = Array.isArray(params?.channelId) ? params.channelId[0] : params?.channelId;
  const router = useRouter();
  const localePath = useLocalePath();
  const locale = useLocale();
  const t = useTranslations("eventLog");
  const commonT = useTranslations("common");
  const isAuthenticated = useAuthStore((state) => state.isAuthenticated);
  const isInitializing = useAuthStore((state) => state.isInitializing);
  const authUser = useAuthStore((state) => state.user);
  const { data: channel, isLoading, isError, refetch } = useChannel(channelId || "");
  const canManageMembers = channel?.permissions.can_manage_members ?? false;
  const eventsQuery = useChannelEvents(channel?.id || "", EVENT_LIMIT, canManageMembers);
  const integrityQuery = useChannelEventIntegrity(channel?.id || "", false);
  const integrityStatus = getIntegrityStatus(integrityQuery.data, integrityQuery.isFetching, integrityQuery.isError, t);
  const detailsPath = channelId ? localePath(`/app/channels/${channelId}/details`) : localePath("/app");

  const collectedReferences = useMemo(() => collectEventReferences(eventsQuery.data?.items), [eventsQuery.data?.items]);

  const userQueries = useQueries({
    queries: collectedReferences.userIds.map((userId) => ({
      queryKey: ["/users", userId],
      queryFn: () => apiClient<UserPublicProfile>(`/users/${userId}`),
      enabled: canManageMembers && isAuthenticated,
      retry: false,
      staleTime: 5 * 60 * 1000,
    })),
  });

  const messageQueries = useQueries({
    queries: collectedReferences.messageIds.map((messageId) => ({
      queryKey: ["/channels", channel?.id, "messages", messageId],
      queryFn: () => apiClient<MessageResponse>(`/channels/${channel?.id}/messages/${messageId}`),
      enabled: Boolean(channel?.id) && canManageMembers && isAuthenticated,
      retry: false,
      staleTime: 60 * 1000,
    })),
  });

  const references = useMemo<ReferenceMaps | null>(() => {
    // Return early when `!channel` because the remaining work is not applicable.
    if (!channel) return null;

    const users = new Map<string, UserPublicProfile>();
    // Run this conditional step only when `authUser` is true.
    if (authUser) users.set(authUser.id, authUser);
    collectedReferences.userIds.forEach((userId, index) => {
      const data = userQueries[index]?.data;
      // Run this conditional step only when `data` is true.
      if (data) users.set(userId, data);
    });

    const messages = new Map<string, MessageResponse>();
    collectedReferences.messageIds.forEach((messageId, index) => {
      const data = messageQueries[index]?.data;
      // Run this conditional step only when `data` is true.
      if (data) messages.set(messageId, data);
    });

    return {
      channel,
      users,
      loadingUserIds: new Set(collectedReferences.userIds.filter((_, index) => userQueries[index]?.isLoading)),
      messages,
      loadingMessageIds: new Set(collectedReferences.messageIds.filter((_, index) => messageQueries[index]?.isLoading)),
      uploads: collectedReferences.uploads,
      locale,
      t,
      commonT,
      profilePathForUser: (profileUserId: string) =>
        profileUserId === authUser?.id ? localePath("/app/profile") : localePath(`/app/users/${profileUserId}`),
    };
  }, [authUser, channel, collectedReferences, commonT, locale, localePath, messageQueries, t, userQueries]);

  useEffect(() => {
    // Run this conditional step only when `!isInitializing && !isAuthenticated` is true.
    if (!isInitializing && !isAuthenticated) {
      router.replace(localePath("/login"));
    }
  }, [isAuthenticated, isInitializing, localePath, router]);

  // Return early when `isInitializing || isLoading` because the remaining work is not applicable.
  if (isInitializing || isLoading) {
    return <ChannelEventLogSkeleton />;
  }

  // Return early when `!isAuthenticated` because the remaining work is not applicable.
  if (!isAuthenticated) return null;

  // Return early when `isError || !channel` because the remaining work is not applicable.
  if (isError || !channel) {
    return (
      <div className="h-full min-h-0 overflow-y-auto bg-background p-6 text-foreground sm:p-8">
        <div className="mx-auto max-w-3xl">
          <button
            type="button"
            onClick={() => router.push(detailsPath)}
            className="text-primary text-sm font-medium hover:underline"
          >
            {t("actions.backToDetails")}
          </button>
          <Card className="mt-6 rounded-md p-8 text-center">
            <h1 className="text-2xl font-bold">{t("errors.loadChannelTitle")}</h1>
            <p className="mt-2 text-muted-foreground">
              {t("errors.loadChannelDescription")}
            </p>
            <div className="mt-6">
              <Button onClick={() => refetch()}>{commonT("actions.tryAgain")}</Button>
            </div>
          </Card>
        </div>
      </div>
    );
  }

  // Return early when `!canManageMembers` because the remaining work is not applicable.
  if (!canManageMembers) {
    return (
      <div className="h-full min-h-0 overflow-y-auto bg-background p-6 text-foreground sm:p-8">
        <div className="mx-auto max-w-3xl">
          <button
            type="button"
            onClick={() => router.push(localePath(`/app/channels/${channel.id}/details`))}
            className="text-primary text-sm font-medium hover:underline"
          >
            {t("actions.backToDetails")}
          </button>
          <Card className="mt-6 rounded-md p-8 text-center">
            <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-md bg-muted text-muted-foreground">
              <Shield className="h-7 w-7" />
            </div>
            <h1 className="mt-4 text-2xl font-bold">{t("errors.unavailableTitle")}</h1>
            <p className="mt-2 text-muted-foreground">
              {t("errors.unavailableDescription")}
            </p>
          </Card>
        </div>
      </div>
    );
  }

  return (
    <div className="h-full min-h-0 overflow-y-auto bg-background p-6 text-foreground sm:p-8">
      <div className="mx-auto max-w-6xl space-y-6">
        <div className="flex flex-col justify-between gap-4 sm:flex-row sm:items-start">
          <div>
            <button
              type="button"
              onClick={() => router.push(localePath(`/app/channels/${channel.id}/details`))}
              className="inline-flex items-center gap-1 text-primary text-sm font-medium hover:underline"
            >
              <ArrowLeft className="h-4 w-4" />
              {t("actions.backToDetails")}
            </button>
            <h1 className="mt-2 text-3xl font-bold tracking-tight">{t("title")}</h1>
            <p className="mt-1 text-muted-foreground">{t("description", { name: channel.name })}</p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant={integrityStatus.variant}>{t("integrity.badge", { status: integrityStatus.label })}</Badge>
            <Button
              variant="outline"
              onClick={() => integrityQuery.refetch()}
              disabled={integrityQuery.isFetching}
            >
              <Shield className="mr-2 h-4 w-4" />
              {integrityQuery.isFetching ? t("integrity.checking") : t("actions.verifyIntegrity")}
            </Button>
            <Button
              variant="outline"
              onClick={() => eventsQuery.refetch()}
              disabled={eventsQuery.isFetching}
            >
              <RefreshCw className="mr-2 h-4 w-4" />
              {eventsQuery.isFetching ? commonT("actions.refreshing") : commonT("actions.refresh")}
            </Button>
          </div>
        </div>

        <Card className="overflow-hidden rounded-md border-border/60">
          <div className="border-b border-border/60 bg-gradient-to-r from-primary/15 via-primary/5 to-transparent p-6">
            <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
              <div className="flex min-w-0 items-center gap-4">
                <div className="flex h-14 w-14 flex-shrink-0 items-center justify-center rounded-md bg-primary/10 text-primary">
                  <Hash className="h-7 w-7" />
                </div>
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge variant="secondary">{commonT(`visibility.${channel.visibility}`)}</Badge>
                    <Badge>{channel.my_role ? commonT(`roles.${channel.my_role}`) : commonT("roles.none")}</Badge>
                  </div>
                  <h2 className="mt-2 truncate text-xl font-semibold">{channel.name}</h2>
                </div>
              </div>
              <p className="text-sm text-muted-foreground">
                {t("latestEvents", { count: EVENT_LIMIT })}
              </p>
            </div>
          </div>

          <div className="p-6">
            {integrityQuery.data ? (
              <div className="grid gap-3 rounded-md border border-border/70 bg-muted/30 p-4 text-sm sm:grid-cols-2 lg:grid-cols-4">
                <div>
                  <p className="text-xs uppercase text-muted-foreground">{t("integrity.status")}</p>
                  <p className="mt-1 flex items-center gap-2 font-medium">
                    {integrityQuery.data.valid ? <CheckCircle2 className="h-4 w-4 text-primary" /> : <AlertTriangle className="h-4 w-4 text-destructive" />}
                    {integrityStatus.label}
                  </p>
                </div>
                <div>
                  <p className="text-xs uppercase text-muted-foreground">{t("integrity.checkedEvents")}</p>
                  <p className="mt-1 font-medium">{integrityQuery.data.checked_events}</p>
                </div>
                <div>
                  <p className="text-xs uppercase text-muted-foreground">{t("integrity.lastHash")}</p>
                  <p className="mt-1 break-all font-mono text-xs">{shortHash(integrityQuery.data.last_valid_hash)}</p>
                </div>
                <div>
                  <p className="text-xs uppercase text-muted-foreground">{t("integrity.scope")}</p>
                  <p className="mt-1 font-medium">{channel.name}</p>
                </div>
                {!integrityQuery.data.valid ? (
                  <div className="rounded-md border border-destructive/30 bg-destructive/10 p-3 text-sm text-destructive sm:col-span-2 lg:col-span-4">
                    <span className="font-medium">{integrityQuery.data.reason || t("integrity.failed")}</span>
                    {integrityQuery.data.broken_event_id ? (
                      <span className="ml-2 text-xs">{t("integrity.damagedEntry")}</span>
                    ) : null}
                  </div>
                ) : null}
              </div>
            ) : null}
            {integrityQuery.isError ? (
              <p className="mt-3 text-sm text-destructive">{t("errors.verifyFailed")}</p>
            ) : null}
          </div>

          {eventsQuery.isLoading || !references ? (
            <div className="space-y-2 border-t border-border/60 p-6">
              <Skeleton className="h-28 w-full rounded-md" />
              <Skeleton className="h-28 w-full rounded-md" />
              <Skeleton className="h-28 w-full rounded-md" />
            </div>
          ) : eventsQuery.isError ? (
            <div className="border-t border-border/60 p-6">
              <p className="text-sm text-destructive">{t("errors.loadEventsFailed")}</p>
            </div>
          ) : (eventsQuery.data?.items?.length ?? 0) === 0 ? (
            <div className="border-t border-border/60 p-6">
              <p className="text-sm text-muted-foreground">{t("empty")}</p>
            </div>
          ) : (
            <div className="divide-y divide-border/60 border-t border-border/60">
              {eventsQuery.data?.items.map((item) => (
                <EventLogItem key={item.id} event={item} references={references} />
              ))}
              {eventsQuery.data?.has_more ? (
                <p className="px-6 py-4 text-xs text-muted-foreground">{t("moreAvailable")}</p>
              ) : null}
            </div>
          )}
        </Card>
      </div>
    </div>
  );
}
