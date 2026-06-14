"use client";

import { useParams, useRouter } from "next/navigation";
import { useEffect, useMemo, type ReactNode } from "react";
import { useQueries } from "@tanstack/react-query";
import { format } from "date-fns";
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
import type { AttachmentItem, ChannelResponse, EventIntegrityResponse, EventResponse, MessageResponse, User } from "@/types/api";

const EVENT_LIMIT = 100;

type UserPublicProfile = User & {
  bio?: string | null;
  created_at?: string;
  updated_at?: string | null;
};

type ReferenceMaps = {
  channel: ChannelResponse;
  users: Map<string, UserPublicProfile>;
  loadingUserIds: Set<string>;
  messages: Map<string, MessageResponse>;
  loadingMessageIds: Set<string>;
  uploads: Map<string, AttachmentItem>;
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

function formatDateTime(value?: string | null) {
  if (!value) return "Not available";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Not available";
  return format(date, "PPP p");
}

function shortHash(value?: string | null) {
  if (!value) return "-";
  if (value.length <= 20) return value;
  return `${value.slice(0, 12)}...${value.slice(-8)}`;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function isUuid(value: unknown): value is string {
  return typeof value === "string" && UUID_RE.test(value);
}

function unique(values: Array<string | null | undefined>) {
  return Array.from(new Set(values.filter((value): value is string => Boolean(value)))).sort();
}

function titleCase(value: string) {
  return value
    .replace(/[._-]+/g, " ")
    .replace(/\s+/g, " ")
    .trim()
    .replace(/\b\w/g, (match) => match.toUpperCase());
}

function humanizeKey(key: string) {
  const labels: Record<string, string> = {
    actor_user_id: "Actor",
    admin_permissions: "Admin permissions",
    attempt_count: "Attempts",
    avatar_url: "Avatar",
    channel_id: "Channel",
    channel_slug: "Channel slug",
    client_msg_id: "Client retry token",
    content_json: "Message data",
    content_text: "Message text",
    content_type: "Content type",
    deleted_at: "Deleted",
    edited_at: "Edited",
    file_id: "Upload",
    filename: "File name",
    invite_id: "Invite",
    is_pinned: "Pinned",
    join_mode: "Join mode",
    last_error: "Last error",
    max_attempts: "Max attempts",
    message_id: "Message",
    new_role: "New role",
    outbox_id: "Delivery job",
    previous_attempt_count: "Previous attempts",
    previous_status: "Previous status",
    reply_to_message_id: "Reply to",
    retry_in_seconds: "Retry delay",
    routing_key: "Broker route",
    sender_display_name: "Sender display name",
    sender_user_id: "Sender",
    sender_username: "Sender username",
    seq_id: "Message number",
    size_bytes: "File size",
    target_user_id: "Target member",
    updated_at: "Updated",
    user_id: "User",
  };
  return labels[key] ?? titleCase(key);
}

function userDisplayName(user?: UserPublicProfile | null) {
  if (!user) return null;
  if (user.display_name?.trim()) return `${user.display_name} (@${user.username})`;
  return `@${user.username}`;
}

function userInitial(user?: UserPublicProfile | null) {
  return (user?.display_name || user?.username || "U").slice(0, 1).toUpperCase();
}

function messagePreview(message?: MessageResponse | null) {
  if (!message) return null;
  if (message.deleted_at) return "Deleted message";
  if (message.content_text?.trim()) return message.content_text.trim();
  if (message.content_json) return "JSON message";
  if (message.attachments?.length) return `${message.attachments.length} attachment${message.attachments.length === 1 ? "" : "s"}`;
  return "Empty message";
}

function truncate(value: string, maxLength = 96) {
  if (value.length <= maxLength) return value;
  return `${value.slice(0, maxLength - 1)}...`;
}

function maskInternalIds(value: string) {
  return value.replace(UUID_IN_TEXT_RE, "internal reference");
}

function formatBytes(value: unknown) {
  if (typeof value !== "number" || Number.isNaN(value)) return "Not available";
  if (value < 1024) return `${value} B`;
  const units = ["KB", "MB", "GB"];
  let current = value / 1024;
  let unit = units[0];
  for (let index = 1; index < units.length && current >= 1024; index += 1) {
    current /= 1024;
    unit = units[index];
  }
  return `${current.toFixed(current >= 10 ? 0 : 1)} ${unit}`;
}

function normalizeStatus(value: unknown) {
  if (typeof value !== "string") return String(value);
  return value.replace(/_/g, " ");
}

function roleLabel(value: unknown) {
  return typeof value === "string" ? titleCase(value) : String(value);
}

function eventCategory(eventType: string) {
  return eventType.split(".")[0] || "event";
}

function eventBadgeVariant(eventType: string): "default" | "secondary" | "destructive" | "outline" {
  if (eventType.startsWith("security.") || eventType.includes("failed") || eventType.includes("dead_lettered")) {
    return "destructive";
  }
  if (eventType.startsWith("broker.")) return "secondary";
  if (eventType.startsWith("message.")) return "default";
  return "outline";
}

function eventIcon(eventType: string) {
  if (eventType.startsWith("security.")) return LockKeyhole;
  if (eventType === "channel.created") return Hash;
  if (eventType === "channel.updated" || eventType === "member.permissions.updated") return Settings;
  if (eventType === "channel.deleted") return UserX;
  if (eventType.includes("invite")) return Mail;
  if (eventType === "membership.joined" || eventType === "membership.added") return UserPlus;
  if (eventType === "membership.approved" || eventType === "member.promoted") return UserCheck;
  if (eventType === "membership.left" || eventType === "member.demoted") return UserMinus;
  if (eventType === "member.removed") return UserX;
  if (eventType.startsWith("message.")) return MessageSquare;
  if (eventType === "broker.dead_lettered") return ServerCrash;
  if (eventType.startsWith("broker.")) return DatabaseZap;
  return CalendarClock;
}

function getEventSubjectUserId(event: EventResponse) {
  const payload = event.payload ?? {};
  const target = payload.target_user_id ?? payload.user_id ?? payload.sender_user_id ?? event.actor_user_id;
  return isUuid(target) ? target : null;
}

function getEventMessageId(event: EventResponse) {
  const payload = event.payload ?? {};
  if (isUuid(payload.message_id)) return payload.message_id;
  if (event.event_type.startsWith("message.") && isUuid(payload.id)) return payload.id;
  if (isUuid(payload.reply_to_message_id)) return payload.reply_to_message_id;
  return null;
}

function getReferenceKind(key: string, value: unknown, eventType?: string): ReferenceKind | null {
  if (key === "channel_id" && isUuid(value)) return "channel";
  if (USER_ID_KEYS.has(key) && isUuid(value)) return "user";
  if ((MESSAGE_ID_KEYS.has(key) || (key === "id" && eventType?.startsWith("message."))) && isUuid(value)) return "message";
  if (UPLOAD_ID_KEYS.has(key) && isUuid(value)) return "upload";
  if (key === "invite_id" && isUuid(value)) return "invite";
  if (DELIVERY_ID_KEYS.has(key) && isUuid(value)) return "delivery";
  if (CLIENT_ID_KEYS.has(key) && typeof value === "string") return "client";
  if (isUuid(value)) return "internal";
  return null;
}

function collectReferencesFromPayload(
  value: unknown,
  eventType: string,
  userIds: string[],
  messageIds: string[],
  uploads: Map<string, AttachmentItem>,
) {
  if (Array.isArray(value)) {
    value.forEach((item) => collectReferencesFromPayload(item, eventType, userIds, messageIds, uploads));
    return;
  }

  if (!isRecord(value)) return;

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
    if (kind === "user" && typeof childValue === "string") userIds.push(childValue);
    if (kind === "message" && typeof childValue === "string") messageIds.push(childValue);
    collectReferencesFromPayload(childValue, eventType, userIds, messageIds, uploads);
  });
}

function collectEventReferences(events: EventResponse[] | undefined) {
  const userIds: string[] = [];
  const messageIds: string[] = [];
  const uploads = new Map<string, AttachmentItem>();

  for (const event of events ?? []) {
    if (isUuid(event.actor_user_id)) userIds.push(event.actor_user_id);
    collectReferencesFromPayload(event.payload ?? {}, event.event_type, userIds, messageIds, uploads);
  }

  return {
    userIds: unique(userIds),
    messageIds: unique(messageIds),
    uploads,
  };
}

function LoadingReference({ label }: { label: string }) {
  return (
    <span className="inline-flex min-h-7 items-center gap-2 rounded-md border border-border/70 bg-muted/40 px-2.5 py-1 text-xs text-muted-foreground">
      <span className="h-2 w-2 animate-pulse rounded-full bg-muted-foreground/60" />
      {label}
    </span>
  );
}

function UserReference({ userId, references, fallback = "User not available" }: { userId?: string | null; references: ReferenceMaps; fallback?: string }) {
  if (!userId) return <span className="text-muted-foreground">System</span>;
  const user = references.users.get(userId);
  if (!user && references.loadingUserIds.has(userId)) return <LoadingReference label="Loading user" />;
  const avatarUrl = resolveApiMediaUrl(user?.avatar_url);

  return (
    <span className="inline-flex min-h-7 max-w-full items-center gap-2 rounded-md border border-border/70 bg-background px-2.5 py-1 text-xs font-medium">
      <Avatar className="h-5 w-5">
        {avatarUrl ? <AvatarImage src={avatarUrl} alt={userDisplayName(user) ?? fallback} /> : null}
        <AvatarFallback className="text-[10px]">{userInitial(user)}</AvatarFallback>
      </Avatar>
      <span className="truncate">{userDisplayName(user) ?? fallback}</span>
    </span>
  );
}

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

  if (id && !message && references.loadingMessageIds.has(id)) {
    return <LoadingReference label="Loading message" />;
  }

  const seqId = message?.seq_id ?? (typeof payload.seq_id === "number" ? payload.seq_id : null);
  const sender = message?.sender_display_name || message?.sender_username || (typeof payload.sender_username === "string" ? payload.sender_username : null);
  const preview = messagePreview(message) ?? (typeof payload.content_type === "string" ? `${titleCase(payload.content_type)} message` : "Message");

  return (
    <span className="inline-flex min-h-7 max-w-full items-center gap-2 rounded-md border border-border/70 bg-background px-2.5 py-1 text-xs">
      <MessageSquare className="h-3.5 w-3.5 text-primary" />
      <span className="font-medium">{seqId ? `Message #${seqId}` : "Message"}</span>
      {sender ? <span className="text-muted-foreground">by {sender}</span> : null}
      <span className="truncate text-muted-foreground">{truncate(preview, 48)}</span>
    </span>
  );
}

function UploadReference({ uploadId, references }: { uploadId?: string | null; references: ReferenceMaps }) {
  const upload = uploadId ? references.uploads.get(uploadId) : undefined;
  return (
    <span className="inline-flex min-h-7 max-w-full items-center gap-2 rounded-md border border-border/70 bg-background px-2.5 py-1 text-xs">
      <Inbox className="h-3.5 w-3.5 text-primary" />
      <span className="truncate font-medium">{upload?.filename || "Upload file"}</span>
      {upload?.size_bytes ? <span className="text-muted-foreground">{formatBytes(upload.size_bytes)}</span> : null}
    </span>
  );
}

function GenericReference({ kind }: { kind: Exclude<ReferenceKind, "user" | "channel" | "message" | "upload"> }) {
  const labels: Record<typeof kind, string> = {
    client: "Client retry token",
    delivery: "Delivery job",
    internal: "Internal reference",
    invite: "Invite link",
  };
  return (
    <span className="inline-flex min-h-7 items-center gap-2 rounded-md border border-border/70 bg-background px-2.5 py-1 text-xs text-muted-foreground">
      <FileJson className="h-3.5 w-3.5" />
      {labels[kind]}
    </span>
  );
}

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
  if (kind === "user") return <UserReference userId={stringValue} references={references} />;
  if (kind === "channel") return <ChannelReference references={references} />;
  if (kind === "message") return <MessageReference messageId={stringValue} event={event} references={references} />;
  if (kind === "upload") return <UploadReference uploadId={stringValue} references={references} />;
  return <GenericReference kind={kind} />;
}

function formatRoutingKey(value: string, references: ReferenceMaps) {
  if (value.startsWith("channel.")) return `${references.channel.name} broker route`;
  if (value.startsWith("user.")) return "User delivery route";
  if (value.startsWith("dead.")) return "Dead-letter broker route";
  return maskInternalIds(value);
}

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
  if (referenceKind) {
    return <ReferenceValue kind={referenceKind} value={value} references={references} event={event} />;
  }

  if (value === null || value === undefined || value === "") {
    return <span className="text-muted-foreground">Not set</span>;
  }

  if (typeof value === "boolean") {
    return <Badge variant={value ? "default" : "secondary"}>{value ? "Yes" : "No"}</Badge>;
  }

  if (typeof value === "number") {
    if (fieldKey === "size_bytes") return <span>{formatBytes(value)}</span>;
    if (fieldKey === "retry_in_seconds") return <span>{value} seconds</span>;
    return <span>{value.toLocaleString()}</span>;
  }

  if (typeof value === "string") {
    if (fieldKey === "routing_key") return <span>{formatRoutingKey(value, references)}</span>;
    if (fieldKey.endsWith("_url") || fieldKey === "url" || fieldKey === "public_url") {
      return <span>{value.includes("/uploads/") ? "Private upload link" : maskInternalIds(value)}</span>;
    }
    if (fieldKey === "content_text" && event) {
      const messageId = getEventMessageId(event);
      const message = messageId ? references.messages.get(messageId) : undefined;
      return <span>{message?.content_text ? truncate(message.content_text, 180) : "Stored message text"}</span>;
    }
    if (fieldKey === "content_type") return <Badge variant="outline">{titleCase(value)}</Badge>;
    if (fieldKey === "role" || fieldKey === "new_role") return <Badge variant="secondary">{roleLabel(value)}</Badge>;
    if (fieldKey.includes("status")) return <Badge variant="outline">{normalizeStatus(value)}</Badge>;
    if (ISO_DATE_RE.test(value)) return <span>{formatDateTime(value)}</span>;
    return <span className="break-words">{maskInternalIds(value)}</span>;
  }

  return <span>{String(value)}</span>;
}

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
  if (Array.isArray(value)) {
    if (value.length === 0) return <span className="text-muted-foreground">None</span>;

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

  if (isRecord(value)) {
    const entries = Object.entries(value).filter(([key]) => !(depth > 0 && HIDDEN_TECHNICAL_KEYS.has(key)));
    if (entries.length === 0) return <span className="text-muted-foreground">No details</span>;

    if (fieldKey === "content_json" && "_enc_v1" in value) {
      const messageId = event ? getEventMessageId(event) : null;
      const message = messageId ? references.messages.get(messageId) : undefined;
      if (message?.content_json) {
        return <StructuredValue fieldKey={fieldKey} value={message.content_json} references={references} event={event} depth={depth + 1} />;
      }
      return <span className="text-muted-foreground">Encrypted JSON message content</span>;
    }

    return (
      <div className={cn("grid gap-2", depth === 0 ? "sm:grid-cols-2" : "")}>
        {entries.map(([key, childValue]) => (
          <div key={key} className="rounded-md border border-border/60 bg-background/70 p-3">
            <p className="mb-1 text-xs font-medium uppercase text-muted-foreground">{humanizeKey(key)}</p>
            <StructuredValue fieldKey={key} value={childValue} references={references} event={event} depth={depth + 1} />
          </div>
        ))}
      </div>
    );
  }

  return <ScalarValue fieldKey={fieldKey} value={value} references={references} event={event} />;
}

function StructuredPayload({ event, references }: { event: EventResponse; references: ReferenceMaps }) {
  const payload = event.payload ?? {};
  const entries = Object.entries(payload).filter(([key]) => !HIDDEN_TECHNICAL_KEYS.has(key));

  if (entries.length === 0) {
    return (
      <div className="rounded-md border border-dashed border-border/70 bg-muted/20 p-4 text-sm text-muted-foreground">
        No additional details were recorded for this event.
      </div>
    );
  }

  return (
    <div className="grid gap-3 sm:grid-cols-2">
      {entries.map(([key, value]) => (
        <div key={key} className="rounded-md border border-border/60 bg-muted/20 p-3">
          <p className="mb-2 text-xs font-medium uppercase text-muted-foreground">{humanizeKey(key)}</p>
          <StructuredValue fieldKey={key} value={value} references={references} event={event} />
        </div>
      ))}
    </div>
  );
}

function describeEvent(event: EventResponse, references: ReferenceMaps): { title: string; description: ReactNode } {
  const payload = event.payload ?? {};
  const actor = <UserReference userId={event.actor_user_id} references={references} fallback="Unknown actor" />;
  const subjectUserId = getEventSubjectUserId(event);
  const subject = <UserReference userId={subjectUserId} references={references} fallback="Unknown user" />;
  const target = isUuid(payload.target_user_id) ? (
    <UserReference userId={payload.target_user_id} references={references} fallback="Unknown member" />
  ) : subject;
  const channel = <ChannelReference references={references} />;
  const message = <MessageReference event={event} references={references} />;

  switch (event.event_type) {
    case "channel.created":
      return { title: "Channel created", description: <>{actor} created {channel}</> };
    case "channel.updated":
      return { title: "Channel settings updated", description: <>{actor} changed the channel settings for {channel}</> };
    case "channel.deleted":
      return { title: "Channel deleted", description: <>{actor} deleted {channel}</> };
    case "channel.slug_collision_resolved":
      return { title: "Channel slug adjusted", description: <>The requested channel slug was already taken, so a safe alternative was assigned.</> };
    case "membership.joined":
      return { title: "Member joined", description: <>{subject} joined {channel} as {roleLabel(payload.role)}</> };
    case "membership.left":
      return { title: "Member left", description: <>{subject} left {channel}</> };
    case "membership.approved":
      return { title: "Join request approved", description: <>{actor} approved {target}</> };
    case "membership.added":
      return { title: "Member added", description: <>{actor} added {target}</> };
    case "member.promoted":
      return { title: "Member promoted", description: <>{actor} promoted {target} to admin</> };
    case "member.demoted":
      return { title: "Member demoted", description: <>{actor} changed {target} back to member</> };
    case "member.removed":
      return { title: "Member removed", description: <>{actor} removed {target} from the channel</> };
    case "member.permissions.updated":
      return { title: "Admin permissions updated", description: <>{actor} updated permissions for {target}</> };
    case "invite.created":
      return { title: "Invite created", description: <>{actor} created a channel invite</> };
    case "invite.revoked":
      return { title: "Invite revoked", description: <>{actor} revoked a channel invite</> };
    case "invite.accepted":
      return { title: "Invite accepted", description: <>{subject} accepted a channel invite</> };
    case "message.published":
      return { title: "Message published", description: <>{actor} published {message}</> };
    case "message.encryption_failed":
      return { title: "Message encryption failed", description: <>A message from {actor} could not be encrypted before storage.</> };
    case "message.decryption_failed":
      return { title: "Message decryption failed", description: <>A stored message could not be decrypted for delivery.</> };
    case "security.unauthorized_publish":
      return { title: "Publish blocked", description: <>{actor} tried to publish without permission.</> };
    case "security.unauthorized_read":
      return { title: "Read blocked", description: <>{actor} tried to read channel data without permission.</> };
    case "broker.retry_scheduled":
      return { title: "Broker retry scheduled", description: <>RabbitMQ delivery failed temporarily. The worker scheduled another attempt.</> };
    case "broker.dead_lettered":
      return { title: "Broker delivery dead-lettered", description: <>RabbitMQ delivery failed too many times and moved to the dead-letter flow.</> };
    case "broker.manual_retry_requested":
      return { title: "Manual retry requested", description: <>{actor} asked the worker to retry a failed delivery job.</> };
    default:
      return { title: titleCase(event.event_type), description: <>Audit event recorded for {channel}.</> };
  }
}

function EventReferences({ event, references }: { event: EventResponse; references: ReferenceMaps }) {
  const messageId = getEventMessageId(event);
  const targetUserId = isUuid(event.payload?.target_user_id) ? event.payload.target_user_id : null;
  const subjectUserId = getEventSubjectUserId(event);
  const uploadIds = Object.values(event.payload ?? {})
    .filter((value): value is string => isUuid(value) && references.uploads.has(value));

  return (
    <div className="mt-3 flex flex-wrap gap-2">
      <UserReference userId={event.actor_user_id} references={references} fallback="Unknown actor" />
      <ChannelReference references={references} />
      {targetUserId && targetUserId !== event.actor_user_id ? (
        <UserReference userId={targetUserId} references={references} fallback="Unknown member" />
      ) : null}
      {subjectUserId && subjectUserId !== event.actor_user_id && subjectUserId !== targetUserId ? (
        <UserReference userId={subjectUserId} references={references} fallback="Unknown user" />
      ) : null}
      {messageId ? <MessageReference messageId={messageId} event={event} references={references} /> : null}
      {uploadIds.map((uploadId) => (
        <UploadReference key={uploadId} uploadId={uploadId} references={references} />
      ))}
    </div>
  );
}

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
          <time className="text-sm text-muted-foreground">{formatDateTime(event.created_at)}</time>
        </div>

        <h3 className="mt-3 text-base font-semibold">{description.title}</h3>
        <div className="mt-2 flex flex-wrap items-center gap-2 text-sm text-muted-foreground">{description.description}</div>

        <EventReferences event={event} references={references} />

        <Accordion type="single" collapsible className="mt-4 rounded-md border border-border/60 bg-muted/10 px-4">
          <AccordionItem value="details" className="border-b-0">
            <AccordionTrigger className="py-3 text-sm hover:no-underline">
              Structured details
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

function getIntegrityStatus(
  result: EventIntegrityResponse | undefined,
  isFetching: boolean,
  isError: boolean,
): { label: string; variant: "default" | "secondary" | "destructive" | "outline" } {
  if (isFetching) return { label: "Checking...", variant: "secondary" };
  if (isError) return { label: "Check failed", variant: "destructive" };
  if (!result) return { label: "Not checked", variant: "outline" };
  if (result.valid) return { label: "Verified", variant: "default" };
  if (result.reason === "missing_hash") return { label: "Not initialized", variant: "secondary" };
  return { label: "Broken", variant: "destructive" };
}

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

export default function ChannelEventLogPage() {
  const params = useParams<{ channelId?: string | string[] }>();
  const channelId = Array.isArray(params?.channelId) ? params.channelId[0] : params?.channelId;
  const router = useRouter();
  const localePath = useLocalePath();
  const isAuthenticated = useAuthStore((state) => state.isAuthenticated);
  const isInitializing = useAuthStore((state) => state.isInitializing);
  const authUser = useAuthStore((state) => state.user);
  const { data: channel, isLoading, isError, refetch } = useChannel(channelId || "");
  const canManageMembers = channel?.permissions.can_manage_members ?? false;
  const eventsQuery = useChannelEvents(channel?.id || "", EVENT_LIMIT, canManageMembers);
  const integrityQuery = useChannelEventIntegrity(channel?.id || "", false);
  const integrityStatus = getIntegrityStatus(integrityQuery.data, integrityQuery.isFetching, integrityQuery.isError);
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
    if (!channel) return null;

    const users = new Map<string, UserPublicProfile>();
    if (authUser) users.set(authUser.id, authUser);
    collectedReferences.userIds.forEach((userId, index) => {
      const data = userQueries[index]?.data;
      if (data) users.set(userId, data);
    });

    const messages = new Map<string, MessageResponse>();
    collectedReferences.messageIds.forEach((messageId, index) => {
      const data = messageQueries[index]?.data;
      if (data) messages.set(messageId, data);
    });

    return {
      channel,
      users,
      loadingUserIds: new Set(collectedReferences.userIds.filter((_, index) => userQueries[index]?.isLoading)),
      messages,
      loadingMessageIds: new Set(collectedReferences.messageIds.filter((_, index) => messageQueries[index]?.isLoading)),
      uploads: collectedReferences.uploads,
    };
  }, [authUser, channel, collectedReferences, messageQueries, userQueries]);

  useEffect(() => {
    if (!isInitializing && !isAuthenticated) {
      router.replace(localePath("/login"));
    }
  }, [isAuthenticated, isInitializing, localePath, router]);

  if (isInitializing || isLoading) {
    return <ChannelEventLogSkeleton />;
  }

  if (!isAuthenticated) return null;

  if (isError || !channel) {
    return (
      <div className="h-full min-h-0 overflow-y-auto bg-background p-6 text-foreground sm:p-8">
        <div className="mx-auto max-w-3xl">
          <button
            type="button"
            onClick={() => router.push(detailsPath)}
            className="text-primary text-sm font-medium hover:underline"
          >
            &larr; Back to details
          </button>
          <Card className="mt-6 rounded-md p-8 text-center">
            <h1 className="text-2xl font-bold">We couldn&apos;t load this channel</h1>
            <p className="mt-2 text-muted-foreground">
              The channel may not exist anymore, or your session needs to be refreshed.
            </p>
            <div className="mt-6">
              <Button onClick={() => refetch()}>Try Again</Button>
            </div>
          </Card>
        </div>
      </div>
    );
  }

  if (!canManageMembers) {
    return (
      <div className="h-full min-h-0 overflow-y-auto bg-background p-6 text-foreground sm:p-8">
        <div className="mx-auto max-w-3xl">
          <button
            type="button"
            onClick={() => router.push(localePath(`/app/channels/${channel.id}/details`))}
            className="text-primary text-sm font-medium hover:underline"
          >
            &larr; Back to details
          </button>
          <Card className="mt-6 rounded-md p-8 text-center">
            <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-md bg-muted text-muted-foreground">
              <Shield className="h-7 w-7" />
            </div>
            <h1 className="mt-4 text-2xl font-bold">Event log unavailable</h1>
            <p className="mt-2 text-muted-foreground">
              You need member-management permission to view audit events for this channel.
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
              Back to details
            </button>
            <h1 className="mt-2 text-3xl font-bold tracking-tight">Event Log</h1>
            <p className="mt-1 text-muted-foreground">Recent security and system events for {channel.name}.</p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant={integrityStatus.variant}>Audit integrity: {integrityStatus.label}</Badge>
            <Button
              variant="outline"
              onClick={() => integrityQuery.refetch()}
              disabled={integrityQuery.isFetching}
            >
              <Shield className="mr-2 h-4 w-4" />
              {integrityQuery.isFetching ? "Checking..." : "Verify integrity"}
            </Button>
            <Button
              variant="outline"
              onClick={() => eventsQuery.refetch()}
              disabled={eventsQuery.isFetching}
            >
              <RefreshCw className="mr-2 h-4 w-4" />
              {eventsQuery.isFetching ? "Refreshing..." : "Refresh"}
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
                    <Badge variant="secondary">{channel.visibility}</Badge>
                    <Badge>{channel.my_role}</Badge>
                  </div>
                  <h2 className="mt-2 truncate text-xl font-semibold">{channel.name}</h2>
                </div>
              </div>
              <p className="text-sm text-muted-foreground">
                Showing the latest {EVENT_LIMIT} channel-scoped events.
              </p>
            </div>
          </div>

          <div className="p-6">
            {integrityQuery.data ? (
              <div className="grid gap-3 rounded-md border border-border/70 bg-muted/30 p-4 text-sm sm:grid-cols-2 lg:grid-cols-4">
                <div>
                  <p className="text-xs uppercase text-muted-foreground">Status</p>
                  <p className="mt-1 flex items-center gap-2 font-medium">
                    {integrityQuery.data.valid ? <CheckCircle2 className="h-4 w-4 text-primary" /> : <AlertTriangle className="h-4 w-4 text-destructive" />}
                    {integrityStatus.label}
                  </p>
                </div>
                <div>
                  <p className="text-xs uppercase text-muted-foreground">Checked events</p>
                  <p className="mt-1 font-medium">{integrityQuery.data.checked_events}</p>
                </div>
                <div>
                  <p className="text-xs uppercase text-muted-foreground">Last hash</p>
                  <p className="mt-1 break-all font-mono text-xs">{shortHash(integrityQuery.data.last_valid_hash)}</p>
                </div>
                <div>
                  <p className="text-xs uppercase text-muted-foreground">Scope</p>
                  <p className="mt-1 font-medium">{channel.name}</p>
                </div>
                {!integrityQuery.data.valid ? (
                  <div className="rounded-md border border-destructive/30 bg-destructive/10 p-3 text-sm text-destructive sm:col-span-2 lg:col-span-4">
                    <span className="font-medium">{integrityQuery.data.reason || "integrity check failed"}</span>
                    {integrityQuery.data.broken_event_id ? (
                      <span className="ml-2 text-xs">A damaged audit entry was found in this channel.</span>
                    ) : null}
                  </div>
                ) : null}
              </div>
            ) : null}
            {integrityQuery.isError ? (
              <p className="mt-3 text-sm text-destructive">Could not verify audit integrity. Please try again.</p>
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
              <p className="text-sm text-destructive">Could not load event log. Please try again.</p>
            </div>
          ) : (eventsQuery.data?.items?.length ?? 0) === 0 ? (
            <div className="border-t border-border/60 p-6">
              <p className="text-sm text-muted-foreground">No events recorded yet for this channel.</p>
            </div>
          ) : (
            <div className="divide-y divide-border/60 border-t border-border/60">
              {eventsQuery.data?.items.map((item) => (
                <EventLogItem key={item.id} event={item} references={references} />
              ))}
              {eventsQuery.data?.has_more ? (
                <p className="px-6 py-4 text-xs text-muted-foreground">More events are available through the API.</p>
              ) : null}
            </div>
          )}
        </Card>
      </div>
    </div>
  );
}
