"use client";

import { useTranslations } from "next-intl";
import {
  Activity,
  FileUp,
  Hash,
  MessageSquare,
  ShieldAlert,
  ShieldCheck,
  UserRoundCog,
  Users,
} from "lucide-react";
import type { AdminEventItem } from "@/types/api";

const EVENT_TITLES: Record<string, string> = {
  "channel.created": "channelCreated",
  "channel.updated": "channelUpdated",
  "channel.deleted": "channelDeleted",
  "channel.slug_collision_resolved": "channelSlugResolved",
  "message.published": "messagePublished",
  "message.encryption_failed": "messageEncryptionFailed",
  "message.decryption_failed": "messageDecryptionFailed",
  "membership.joined": "membershipJoined",
  "membership.approved": "membershipApproved",
  "membership.added": "membershipAdded",
  "membership.left": "membershipLeft",
  "member.promoted": "memberPromoted",
  "member.demoted": "memberDemoted",
  "member.removed": "memberRemoved",
  "member.permissions.updated": "memberPermissionsUpdated",
  "invite.created": "inviteCreated",
  "invite.revoked": "inviteRevoked",
  "invite.accepted": "inviteAccepted",
  "upload.created": "uploadCreated",
  "upload.content_stored": "uploadStored",
  "upload.accessed": "uploadAccessed",
  "upload.store_failed": "uploadStoreFailed",
  "security.login_failed": "loginFailed",
  "security.unauthorized_publish": "unauthorizedPublish",
  "security.unauthorized_read": "unauthorizedRead",
  "security.unauthorized_upload_access": "unauthorizedUploadAccess",
  "security.superadmin_access_denied": "superadminAccessDenied",
  "broker.retry_scheduled": "deliveryRetryScheduled",
  "broker.dead_lettered": "deliveryDeadLettered",
  "broker.manual_retry_requested": "deliveryManualRetry",
  "superadmin.bootstrapped": "superadminBootstrapped",
  "superadmin.user_deactivated": "userDeactivated",
  "superadmin.user_reactivated": "userReactivated",
  "superadmin.user_sessions_revoked": "userSessionsRevoked",
  "superadmin.channel_restored": "channelRestored",
};

const DETAIL_KEYS = [
  "name",
  "target_username",
  "username",
  "identity",
  "role",
  "visibility",
  "join_mode",
  "channel_slug",
  "seq_id",
  "content_type",
  "attachment_count",
  "filename",
  "size_bytes",
  "expected_size_bytes",
  "actual_size_bytes",
  "has_checksum",
  "reason",
  "previous_status",
  "previous_attempt_count",
  "attempt_count",
  "max_attempts",
  "retry_in_seconds",
  "revoked_sessions",
  "manual_retry",
  "superadmin_override",
  "permissions",
  "resolved_slug",
  "requested_slug",
  "message_id",
  "upload_id",
  "outbox_id",
  "target_user_id",
  "user_id",
  "invite_id",
  "channel_id",
] as const;

function humanize(value: string) {
  return value
    .replace(/[._-]+/g, " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function compactReference(value: string) {
  return value.length > 18 ? `${value.slice(0, 8)}…${value.slice(-6)}` : value;
}

function family(eventType: string) {
  const prefix = eventType.split(".", 1)[0];
  if (prefix === "security") return { Icon: ShieldAlert, tone: "text-destructive" };
  if (prefix === "channel") return { Icon: Hash, tone: "text-sky-600 dark:text-sky-400" };
  if (prefix === "message") return { Icon: MessageSquare, tone: "text-violet-600 dark:text-violet-400" };
  if (["membership", "member", "invite"].includes(prefix)) return { Icon: Users, tone: "text-emerald-600 dark:text-emerald-400" };
  if (prefix === "upload") return { Icon: FileUp, tone: "text-amber-600 dark:text-amber-400" };
  if (prefix === "superadmin") return { Icon: UserRoundCog, tone: "text-primary" };
  if (prefix === "broker") return { Icon: Activity, tone: "text-orange-600 dark:text-orange-400" };
  return { Icon: ShieldCheck, tone: "text-muted-foreground" };
}

export function AdminEventType({ eventType }: { eventType: string }) {
  const t = useTranslations("superadmin.eventDisplay");
  const titleKey = EVENT_TITLES[eventType];
  return <>{titleKey ? t(`titles.${titleKey}`) : humanize(eventType)}</>;
}

export function AdminEventDisplay({ event }: { event: AdminEventItem }) {
  const t = useTranslations("superadmin.eventDisplay");
  const titleKey = EVENT_TITLES[event.event_type];
  const { Icon, tone } = family(event.event_type);
  const visibleDetails = DETAIL_KEYS.flatMap((key) => {
    const value = event.details[key];
    return value === undefined || value === null || value === "" ? [] : [[key, value] as const];
  }).slice(0, 6);

  function formatValue(key: string, value: string | number | boolean) {
    if (typeof value === "boolean") return value ? t("yes") : t("no");
    if (key.endsWith("size_bytes") && typeof value === "number") {
      return t("bytes", { count: new Intl.NumberFormat().format(value) });
    }
    if (key.endsWith("_id") && typeof value === "string") return compactReference(value);
    return key === "permissions" ? humanize(String(value)) : String(value);
  }

  return (
    <div className="flex min-w-[18rem] items-start gap-3">
      <div className={`mt-0.5 rounded-md bg-muted p-1.5 ${tone}`}><Icon className="h-4 w-4" /></div>
      <div className="min-w-0 space-y-1.5">
        <div className="font-medium">{titleKey ? t(`titles.${titleKey}`) : humanize(event.event_type)}</div>
        {visibleDetails.length ? (
          <div className="flex max-w-xl flex-wrap gap-x-3 gap-y-1 text-xs text-muted-foreground">
            {visibleDetails.map(([key, value]) => (
              <span key={key}><span className="font-medium text-foreground/75">{t.has(`fields.${key}`) ? t(`fields.${key}`) : humanize(key)}:</span> {formatValue(key, value)}</span>
            ))}
          </div>
        ) : <div className="text-xs text-muted-foreground">{t("noSensitiveDetails")}</div>}
      </div>
    </div>
  );
}
