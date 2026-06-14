"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { FormEvent, useEffect, useMemo, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { useLocale, useTranslations } from "next-intl";
import {
  Check,
  DoorOpen,
  Hash,
  Info,
  Lock,
  Shield,
  ShieldPlus,
  UserMinus,
  UserPlus,
  Users,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  useApproveMember,
  useChannel,
  useChannelMembers,
  useDemoteMember,
  useJoinChannel,
  useLeaveChannel,
  usePromoteMember,
  useRemoveMember,
  useUpdateAdminPermissions,
  useUpdateChannel,
} from "@/hooks/use-channels";
import { toast } from "@/hooks/use-toast";
import { apiClient } from "@/services/api/client";
import { getApiBaseUrl } from "@/services/api/runtime";
import { useAuthStore } from "@/store/authStore";
import { useLocalePath } from "@/components/features/chat/lib/locale-path";
import { resolveApiMediaUrl } from "@/lib/mediaUrl";
import { formatDateTimeLocalized } from "@/lib/i18n-format";
import type { AdminPermissions, ChannelMembershipItem, ChannelPatchRequest } from "@/types/api";

type UploadCreateResponse = {
  file_id: string;
  upload_url: string;
  method?: string;
  headers?: Record<string, string>;
  public_url?: string | null;
};

type UploadContentResponse = {
  file_id: string;
  public_url: string;
};

function getRoleBadgeVariant(role: ChannelMembershipItem["role"]): "default" | "secondary" | "outline" {
  if (role === "owner") return "default";
  if (role === "admin") return "secondary";
  return "outline";
}

const defaultAdminPermissions: AdminPermissions = {
  can_publish: true,
  can_invite: true,
  can_approve: true,
  can_manage_members: true,
  can_edit_channel: false,
};

function normalizeAdminPermissions(permissions?: AdminPermissions | null): AdminPermissions {
  return {
    ...defaultAdminPermissions,
    ...(permissions ?? {}),
  };
}

function getErrorMessage(error: unknown, fallback: string) {
  if (error instanceof Error && error.message) return error.message;
  return fallback;
}

function ChannelDetailsSkeleton() {
  return (
    <div className="h-full min-h-0 overflow-y-auto bg-background p-6 text-foreground sm:p-8">
      <div className="mx-auto max-w-5xl space-y-6">
        <div className="flex items-center justify-between gap-4">
          <div className="space-y-3">
            <Skeleton className="h-4 w-28" />
            <Skeleton className="h-9 w-56" />
            <Skeleton className="h-4 w-80 max-w-full" />
          </div>
          <div className="flex items-center gap-2">
            <Skeleton className="h-10 w-32 rounded-xl" />
            <Skeleton className="h-10 w-32 rounded-xl" />
          </div>
        </div>

        <Card className="overflow-hidden rounded-3xl border-border/60">
          <div className="p-6 sm:p-8">
            <div className="flex flex-col gap-5 sm:flex-row sm:items-start sm:justify-between">
              <div className="flex items-center gap-4">
                <Skeleton className="h-20 w-20 rounded-3xl" />
                <div className="min-w-0 space-y-3">
                  <div className="flex flex-wrap items-center gap-2">
                    <Skeleton className="h-6 w-20 rounded-full" />
                    <Skeleton className="h-6 w-24 rounded-full" />
                    <Skeleton className="h-6 w-16 rounded-full" />
                  </div>
                  <Skeleton className="h-9 w-52 max-w-full" />
                  <Skeleton className="h-4 w-96 max-w-full" />
                </div>
              </div>
            </div>
          </div>

          <div className="grid gap-4 p-6 sm:grid-cols-2 lg:grid-cols-4">
            {Array.from({ length: 4 }).map((_, index) => (
              <Card key={index} className="space-y-3 rounded-2xl p-4">
                <Skeleton className="h-3 w-20" />
                <Skeleton className="h-8 w-16" />
              </Card>
            ))}
          </div>
        </Card>
      </div>
    </div>
  );
}

export default function ChannelDetailsPage() {
  const params = useParams<{ channelId?: string | string[] }>();
  const channelId = Array.isArray(params?.channelId) ? params.channelId[0] : params?.channelId;
  const router = useRouter();
  const localePath = useLocalePath();
  const locale = useLocale();
  const t = useTranslations("channelDetails");
  const commonT = useTranslations("common");
  const isAuthenticated = useAuthStore((state) => state.isAuthenticated);
  const isInitializing = useAuthStore((state) => state.isInitializing);
  const currentUser = useAuthStore((state) => state.user);
  const accessToken = useAuthStore((state) => state.accessToken);
  const { data: channel, isLoading, isError, refetch } = useChannel(channelId || "");
  const joinChannel = useJoinChannel();
  const leaveChannel = useLeaveChannel();
  const updateChannel = useUpdateChannel();
  const approveMember = useApproveMember();
  const promoteMember = usePromoteMember();
  const demoteMember = useDemoteMember();
  const removeMember = useRemoveMember();
  const updateAdminPermissions = useUpdateAdminPermissions();
  const [actingOn, setActingOn] = useState<string | null>(null);
  const [adminPermissionDrafts, setAdminPermissionDrafts] = useState<Record<string, AdminPermissions>>({});
  const [editForm, setEditForm] = useState({
    name: "",
    description: "",
    visibility: "public" as "public" | "private",
    joinMode: "open" as "open" | "approval_required" | "invite_only",
  });
  const [avatarFile, setAvatarFile] = useState<File | null>(null);

  const uploadAvatar = useMutation({
    mutationFn: async (file: File): Promise<string> => {
      if (!accessToken) {
        throw new Error(t("errors.signInBeforeUpload"));
      }

      const created = await apiClient<UploadCreateResponse>("/uploads", {
        method: "POST",
        body: JSON.stringify({
          filename: file.name,
          content_type: file.type || "application/octet-stream",
          size_bytes: file.size,
        }),
      });

      const apiBaseUrl = getApiBaseUrl();
      const uploadUrl = /^https?:\/\//i.test(created.upload_url)
        ? created.upload_url
        : /^https?:\/\//i.test(apiBaseUrl)
          ? `${new URL(apiBaseUrl).origin}${created.upload_url.startsWith("/") ? created.upload_url : `/${created.upload_url}`}`
          : created.upload_url;

      const uploadHeaders = new Headers(created.headers || {});
      uploadHeaders.set("Authorization", `Bearer ${accessToken}`);
      if (!uploadHeaders.has("Content-Type")) {
        uploadHeaders.set("Content-Type", file.type || "application/octet-stream");
      }

      const putResponse = await fetch(uploadUrl, {
        method: created.method || "PUT",
        headers: uploadHeaders,
        body: file,
      });

      if (!putResponse.ok) {
        let message = t("errors.avatarUpload");
        try {
          const error = (await putResponse.json()) as { detail?: { message?: string } | string };
          if (typeof error.detail === "string") {
            message = error.detail;
          } else if (error.detail?.message) {
            message = error.detail.message;
          }
        } catch {
          // Keep default message.
        }
        throw new Error(message);
      }

      const uploaded = (await putResponse.json()) as UploadContentResponse;
      const nextAvatarUrl = (uploaded.public_url || created.public_url || "").trim();
      if (!nextAvatarUrl) {
        throw new Error(t("errors.avatarMissingUrl"));
      }
      return nextAvatarUrl;
    },
  });

  const avatarPreviewUrl = useMemo(() => {
    if (!avatarFile) return null;
    return URL.createObjectURL(avatarFile);
  }, [avatarFile]);

  useEffect(() => {
    if (!avatarFile || !avatarPreviewUrl) return;
    return () => URL.revokeObjectURL(avatarPreviewUrl);
  }, [avatarFile, avatarPreviewUrl]);

  const canManageMembers = channel?.permissions.can_manage_members ?? false;
  const membersQuery = useChannelMembers(channel?.id || "", { enabled: canManageMembers });

  useEffect(() => {
    if (!isInitializing && !isAuthenticated) {
      router.replace(localePath("/login"));
    }
  }, [isAuthenticated, isInitializing, localePath, router]);

  useEffect(() => {
    if (!channel) return;
    setEditForm({
      name: channel.name ?? "",
      description: channel.description ?? "",
      visibility: channel.visibility,
      joinMode: channel.join_mode,
    });
    setAvatarFile(null);
  }, [channel]);

  useEffect(() => {
    const adminMembers = (membersQuery.data?.items ?? []).filter((member) => member.role === "admin");
    setAdminPermissionDrafts((current) => {
      const next: Record<string, AdminPermissions> = {};
      for (const adminMember of adminMembers) {
        next[adminMember.user_id] = current[adminMember.user_id] ?? normalizeAdminPermissions(adminMember.admin_permissions);
      }
      return next;
    });
  }, [membersQuery.data?.items]);

  if (isInitializing) {
    return <ChannelDetailsSkeleton />;
  }

  if (!isAuthenticated) return null;

  if (isLoading) {
    return <ChannelDetailsSkeleton />;
  }

  if (isError || !channel) {
    return (
      <div className="h-full min-h-0 overflow-y-auto bg-background p-6 text-foreground">
        <div className="mx-auto max-w-3xl">
          <Link
            href={channelId ? localePath(`/app/channels/${channelId}`) : localePath("/app")}
            className="text-primary text-sm font-medium hover:underline"
          >
            {commonT("actions.back")}
          </Link>
          <Card className="mt-6 rounded-3xl p-8 text-center">
            <h1 className="text-2xl font-bold">{t("errors.loadTitle")}</h1>
            <p className="mt-2 text-muted-foreground">
              {t("errors.loadDescription")}
            </p>
            <div className="mt-6">
              <Button onClick={() => refetch()}>{commonT("actions.tryAgain")}</Button>
            </div>
          </Card>
        </div>
      </div>
    );
  }

  const isMember = ["owner", "admin", "member"].includes(channel.my_role || "");
  const isOwner = channel.my_role === "owner";
  const canLeave = isMember && channel.my_role !== "owner";
  const channelAvatarUrl = avatarPreviewUrl || resolveApiMediaUrl(channel.avatar_url);
  const canEditChannel = channel.permissions.can_edit_channel;

  const managedMembers = (membersQuery.data?.items ?? []).filter((item) => item.role !== "pending");
  const pendingMembers = (membersQuery.data?.items ?? []).filter((item) => item.role === "pending");

  const formatDateTime = (value?: string | null) => formatDateTimeLocalized(value, locale, commonT("notAvailable"));
  const visibilityLabel = (value: "public" | "private") => commonT(`visibility.${value}`);
  const joinModeLabel = (value: "open" | "approval_required" | "invite_only") => {
    if (value === "approval_required") return commonT("joinMode.approvalRequired");
    if (value === "invite_only") return commonT("joinMode.inviteOnly");
    return commonT("joinMode.open");
  };
  const roleLabel = (role?: string | null) => {
    if (role === "owner") return commonT("roles.owner");
    if (role === "admin") return commonT("roles.admin");
    if (role === "member") return commonT("roles.member");
    if (role === "pending") return commonT("roles.pending");
    return commonT("roles.none");
  };

  const trimmedName = editForm.name.trim();
  const trimmedDescription = editForm.description.trim();
  const hasEditChanges =
    trimmedName !== (channel.name ?? "") ||
    trimmedDescription !== (channel.description ?? "") ||
    Boolean(avatarFile) ||
    editForm.visibility !== channel.visibility ||
    editForm.joinMode !== channel.join_mode;

  function runMemberAction(
    key: string,
    action: () => void,
  ) {
    setActingOn(key);
    action();
  }

  function handleEditSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!canEditChannel) return;
    if (!channel) return;

    const submitUpdate = async () => {
      const payload: ChannelPatchRequest = {};
      const trimmedName = editForm.name.trim();
      const trimmedDescription = editForm.description.trim();

      if (trimmedName && trimmedName !== (channel.name ?? "")) payload.name = trimmedName;
      if (trimmedDescription !== (channel.description ?? "")) payload.description = trimmedDescription || null;
      if (avatarFile) {
        payload.avatar_url = await uploadAvatar.mutateAsync(avatarFile);
      }
      if (editForm.visibility !== channel.visibility) payload.visibility = editForm.visibility;
      if (editForm.joinMode !== channel.join_mode) payload.join_mode = editForm.joinMode;

      if (Object.keys(payload).length === 0) {
        toast({
          title: t("toasts.noChangesTitle"),
          description: t("toasts.noChangesDescription"),
        });
        return;
      }

      updateChannel.mutate(
        { channelId: channel.id, data: payload },
        {
          onSuccess: () => {
            setAvatarFile(null);
            toast({
              title: t("toasts.updatedTitle"),
              description: t("toasts.updatedDescription"),
            });
          },
          onError: () => {
            toast({
              title: t("toasts.updateFailedTitle"),
              description: commonT("tryAgainLater"),
              variant: "destructive",
            });
          },
        },
      );
    };

    submitUpdate().catch((error: unknown) => {
      toast({
        title: t("toasts.avatarUploadFailedTitle"),
        description: getErrorMessage(error, commonT("tryAgainLater")),
        variant: "destructive",
      });
    });
  }

  return (
    <div className="h-full min-h-0 overflow-y-auto bg-background p-6 text-foreground sm:p-8">
      <div className="mx-auto max-w-5xl space-y-6">
        <div className="flex items-center justify-between gap-4">
          <div>
            <button
              type="button"
              onClick={() => router.push(localePath(`/app/channels/${channel.id}`))}
              className="text-primary text-sm font-medium hover:underline"
            >
              {t("actions.backToChannel")}
            </button>
            <h1 className="mt-2 text-3xl font-bold tracking-tight">{t("title")}</h1>
            <p className="mt-1 text-muted-foreground">{t("description")}</p>
          </div>
          <div className="flex items-center gap-2">
            {!isMember ? (
              <Button
                onClick={() =>
                  joinChannel.mutate(channel.id, {
                    onSuccess: () => router.push(localePath(`/app/channels/${channel.id}`)),
                  })
                }
                disabled={joinChannel.isPending}
              >
                <UserPlus className="mr-2 h-4 w-4" />
                {joinChannel.isPending ? t("actions.joining") : t("actions.join")}
              </Button>
            ) : null}
            {canLeave ? (
              <Button
                variant="outline"
                onClick={() =>
                  leaveChannel.mutate(channel.id, {
                    onSuccess: () => router.push(localePath("/app")),
                  })
                }
                disabled={leaveChannel.isPending}
              >
                <DoorOpen className="mr-2 h-4 w-4" />
                {leaveChannel.isPending ? t("actions.leaving") : t("actions.leave")}
              </Button>
            ) : null}
          </div>
        </div>

        <Card className="overflow-hidden rounded-3xl border-border/60">
          <div className="bg-gradient-to-r from-primary/15 via-primary/5 to-transparent p-6 sm:p-8">
            <div className="flex flex-col gap-5 sm:flex-row sm:items-start sm:justify-between">
              <div className="flex items-center gap-4">
                <div className="flex h-20 w-20 items-center justify-center rounded-3xl bg-primary/10 text-primary">
                  {channelAvatarUrl ? (
                    <img src={channelAvatarUrl} alt={channel.name} className="h-full w-full rounded-3xl object-cover" />
                  ) : (
                    <Hash className="h-10 w-10" />
                  )}
                </div>
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge variant="secondary">{visibilityLabel(channel.visibility)}</Badge>
                    <Badge variant="secondary">{joinModeLabel(channel.join_mode)}</Badge>
                    <Badge>{roleLabel(channel.my_role)}</Badge>
                  </div>
                  <h2 className="mt-3 truncate text-3xl font-bold">{channel.name}</h2>
                  <p className="mt-2 max-w-2xl text-sm leading-6 text-muted-foreground">
                    {channel.description?.trim() || t("empty.noDescription")}
                  </p>
                </div>
              </div>
            </div>
          </div>

          <div className="grid gap-4 p-6 sm:grid-cols-2 lg:grid-cols-4">
            <Card className="rounded-2xl p-4">
              <div className="flex items-center gap-2 text-muted-foreground">
                <Users className="h-4 w-4" />
                <span className="text-xs uppercase tracking-[0.18em]">{t("stats.members")}</span>
              </div>
              <p className="mt-2 text-2xl font-semibold">{channel.member_count}</p>
            </Card>
            <Card className="rounded-2xl p-4">
              <div className="flex items-center gap-2 text-muted-foreground">
                <Shield className="h-4 w-4" />
                <span className="text-xs uppercase tracking-[0.18em]">{t("stats.pending")}</span>
              </div>
              <p className="mt-2 text-2xl font-semibold">{channel.pending_count}</p>
            </Card>
            <Card className="rounded-2xl p-4">
              <div className="flex items-center gap-2 text-muted-foreground">
                <Info className="h-4 w-4" />
                <span className="text-xs uppercase tracking-[0.18em]">{t("stats.unread")}</span>
              </div>
              <p className="mt-2 text-2xl font-semibold">{channel.unread_count}</p>
            </Card>
            <Card className="rounded-2xl p-4">
              <div className="flex items-center gap-2 text-muted-foreground">
                <Lock className="h-4 w-4" />
                <span className="text-xs uppercase tracking-[0.18em]">{t("stats.access")}</span>
              </div>
              <p className="mt-2 text-sm font-semibold">{joinModeLabel(channel.join_mode)}</p>
            </Card>
          </div>

          <div className="grid gap-4 border-t border-border/60 p-6 lg:grid-cols-[1.1fr_0.9fr]">
            <Card className="rounded-2xl p-5">
              <h3 className="text-lg font-semibold">{t("sections.overview")}</h3>
              <div className="mt-4 space-y-4 text-sm">
                <div>
                  <p className="text-muted-foreground">{t("fields.visibility")}</p>
                  <p className="mt-1 font-medium">{visibilityLabel(channel.visibility)}</p>
                </div>
                <div>
                  <p className="text-muted-foreground">{t("fields.joinPolicy")}</p>
                  <p className="mt-1 font-medium">{joinModeLabel(channel.join_mode)}</p>
                </div>
                <div>
                  <p className="text-muted-foreground">{t("fields.created")}</p>
                  <p className="mt-1 font-medium">{formatDateTime(channel.created_at)}</p>
                </div>
                <div>
                  <p className="text-muted-foreground">{t("fields.updated")}</p>
                  <p className="mt-1 font-medium">{formatDateTime(channel.updated_at)}</p>
                </div>
                <div>
                  <p className="text-muted-foreground">{t("fields.lastActivity")}</p>
                  <p className="mt-1 font-medium">{formatDateTime(channel.last_message_at)}</p>
                </div>
              </div>
            </Card>

            <Card className="rounded-2xl p-5">
              <h3 className="text-lg font-semibold">{t("sections.yourAccess")}</h3>
              <div className="mt-4 space-y-3 text-sm">
                <div className="flex items-center justify-between gap-4">
                  <span className="text-muted-foreground">{t("permissions.publish")}</span>
                  <span className="font-medium">{channel.permissions.can_publish ? commonT("allowed") : commonT("no")}</span>
                </div>
                <div className="flex items-center justify-between gap-4">
                  <span className="text-muted-foreground">{t("permissions.invite")}</span>
                  <span className="font-medium">{channel.permissions.can_invite ? commonT("allowed") : commonT("no")}</span>
                </div>
                <div className="flex items-center justify-between gap-4">
                  <span className="text-muted-foreground">{t("permissions.approve")}</span>
                  <span className="font-medium">{channel.permissions.can_approve ? commonT("allowed") : commonT("no")}</span>
                </div>
                <div className="flex items-center justify-between gap-4">
                  <span className="text-muted-foreground">{t("permissions.manageMembers")}</span>
                  <span className="font-medium">{channel.permissions.can_manage_members ? commonT("allowed") : commonT("no")}</span>
                </div>
                <div className="flex items-center justify-between gap-4">
                  <span className="text-muted-foreground">{t("permissions.editChannel")}</span>
                  <span className="font-medium">{channel.permissions.can_edit_channel ? commonT("allowed") : commonT("no")}</span>
                </div>
              </div>
            </Card>
          </div>

          {canManageMembers ? (
            <div className="border-t border-border/60 p-6">
              <Card className="rounded-2xl p-5">
                <div className="flex flex-col justify-between gap-4 sm:flex-row sm:items-center">
                  <div>
                    <h3 className="text-lg font-semibold">{t("sections.eventLog")}</h3>
                    <p className="mt-1 text-sm text-muted-foreground">{t("eventLogDescription")}</p>
                  </div>
                  <Button
                    variant="outline"
                    onClick={() => router.push(localePath(`/app/channels/${channel.id}/details/event-log`))}
                  >
                    <Shield className="mr-2 h-4 w-4" />
                    {t("actions.openEventLog")}
                  </Button>
                </div>
              </Card>
            </div>
          ) : null}

          {(canEditChannel || canManageMembers) ? (
            <div className="grid gap-4 border-t border-border/60 p-6 lg:grid-cols-2">
              {canEditChannel ? (
                <Card className="rounded-2xl p-5">
                  <h3 className="text-lg font-semibold">{t("sections.editChannel")}</h3>
                  <p className="mt-1 text-sm text-muted-foreground">{t("editDescription")}</p>
                  <form className="mt-4 space-y-4" onSubmit={handleEditSubmit}>
                    <div className="grid gap-2">
                      <Label htmlFor="details-channel-name">{t("fields.name")}</Label>
                      <Input
                        id="details-channel-name"
                        value={editForm.name}
                        maxLength={255}
                        onChange={(event) => setEditForm((current) => ({ ...current, name: event.target.value }))}
                      />
                    </div>
                    <div className="grid gap-2">
                      <Label htmlFor="details-channel-description">{t("fields.description")}</Label>
                      <Textarea
                        id="details-channel-description"
                        value={editForm.description}
                        maxLength={1000}
                        className="min-h-24 resize-none"
                        onChange={(event) => setEditForm((current) => ({ ...current, description: event.target.value }))}
                      />
                    </div>
                    <div className="grid gap-2">
                      <Label htmlFor="details-channel-avatar">{t("fields.avatarUpload")}</Label>
                      <Input
                        id="details-channel-avatar"
                        type="file"
                        accept="image/*"
                        onChange={(event) => setAvatarFile(event.target.files?.[0] ?? null)}
                      />
                      <p className="text-xs text-muted-foreground">
                        {avatarFile ? t("fields.selectedFile", { name: avatarFile.name }) : t("fields.avatarHint")}
                      </p>
                      {avatarFile && avatarPreviewUrl ? (
                        <div>
                          <img
                            src={avatarPreviewUrl}
                            alt={t("fields.avatarPreviewAlt")}
                            className="h-16 w-16 rounded-xl border border-border/70 object-cover"
                          />
                        </div>
                      ) : null}
                    </div>
                    <div className="grid gap-4 sm:grid-cols-2">
                      <div className="grid gap-2">
                        <Label>{t("fields.visibility")}</Label>
                        <Select
                          value={editForm.visibility}
                          onValueChange={(value: "public" | "private") =>
                            setEditForm((current) => ({ ...current, visibility: value }))
                          }
                        >
                          <SelectTrigger>
                            <SelectValue />
                          </SelectTrigger>
                          <SelectContent>
                            <SelectItem value="public">{commonT("visibility.public")}</SelectItem>
                            <SelectItem value="private">{commonT("visibility.private")}</SelectItem>
                          </SelectContent>
                        </Select>
                      </div>
                      <div className="grid gap-2">
                        <Label>{t("fields.joinMode")}</Label>
                        <Select
                          value={editForm.joinMode}
                          onValueChange={(value: "open" | "approval_required" | "invite_only") =>
                            setEditForm((current) => ({ ...current, joinMode: value }))
                          }
                        >
                          <SelectTrigger>
                            <SelectValue />
                          </SelectTrigger>
                          <SelectContent>
                            <SelectItem value="open">{commonT("joinMode.open")}</SelectItem>
                            <SelectItem value="approval_required">{commonT("joinMode.approvalRequired")}</SelectItem>
                            <SelectItem value="invite_only">{commonT("joinMode.inviteOnly")}</SelectItem>
                          </SelectContent>
                        </Select>
                      </div>
                    </div>
                    <div className="flex items-center justify-end gap-2 pt-1">
                      <Button
                        type="button"
                        variant="outline"
                        onClick={() => {
                          setEditForm({
                            name: channel.name ?? "",
                            description: channel.description ?? "",
                            visibility: channel.visibility,
                            joinMode: channel.join_mode,
                          });
                          setAvatarFile(null);
                        }}
                        disabled={updateChannel.isPending || uploadAvatar.isPending}
                      >
                        {commonT("actions.reset")}
                      </Button>
                      <Button type="submit" disabled={updateChannel.isPending || uploadAvatar.isPending || !hasEditChanges}>
                        {updateChannel.isPending || uploadAvatar.isPending ? commonT("actions.saving") : commonT("actions.saveChanges")}
                      </Button>
                    </div>
                  </form>
                </Card>
              ) : (
                <Card className="rounded-2xl p-5">
                  <h3 className="text-lg font-semibold">{t("sections.editChannel")}</h3>
                  <p className="mt-2 text-sm text-muted-foreground">
                    {t("editRestricted")}
                  </p>
                </Card>
              )}

              {canManageMembers ? (
                <Card className="rounded-2xl p-5">
                  <h3 className="text-lg font-semibold">{t("sections.membersRoles")}</h3>
                  <p className="mt-1 text-sm text-muted-foreground">
                    {t("membersDescription")}
                  </p>

                  <div className="mt-4 space-y-3">
                    <p className="text-sm font-medium">{t("sections.pendingRequests")}</p>
                    {membersQuery.isLoading ? (
                      <div className="space-y-2">
                        <Skeleton className="h-12 w-full rounded-xl" />
                        <Skeleton className="h-12 w-full rounded-xl" />
                      </div>
                    ) : pendingMembers.length === 0 ? (
                      <p className="text-sm text-muted-foreground">{t("empty.noPendingRequests")}</p>
                    ) : (
                      pendingMembers.map((member) => {
                        const isSelf = member.user_id === currentUser?.id;
                        const approveKey = `approve:${member.user_id}`;
                        const removeKey = `remove:${member.user_id}`;
                        return (
                          <div key={member.user_id} className="rounded-xl border border-border/60 p-3">
                            <div className="flex flex-wrap items-center justify-between gap-3">
                              <div>
                                <div className="font-medium leading-none">{member.username}</div>
                                <div className="mt-1 text-xs text-muted-foreground">{member.email || t("empty.noEmailAvailable")}</div>
                              </div>
                              <div className="flex items-center gap-2">
                                <Badge variant={getRoleBadgeVariant(member.role)}>{roleLabel(member.role)}</Badge>
                                {channel.permissions.can_approve ? (
                                  <Button
                                    size="sm"
                                    variant="outline"
                                    disabled={approveMember.isPending || actingOn === approveKey}
                                    onClick={() =>
                                      runMemberAction(approveKey, () =>
                                        approveMember.mutate(
                                          { channelId: channel.id, userId: member.user_id },
                                          {
                                            onSuccess: () => {
                                              setActingOn(null);
                                              toast({
                                                title: t("toasts.requestApprovedTitle"),
                                                description: t("toasts.requestApprovedDescription", { username: member.username }),
                                              });
                                            },
                                            onError: () => {
                                              setActingOn(null);
                                              toast({
                                                title: t("toasts.approveFailedTitle"),
                                                description: commonT("tryAgain"),
                                                variant: "destructive",
                                              });
                                            },
                                          },
                                        ),
                                      )
                                    }
                                  >
                                    <Check className="mr-1 h-4 w-4" />
                                    {t("actions.approve")}
                                  </Button>
                                ) : null}
                                {!isSelf ? (
                                  <Button
                                    size="sm"
                                    variant="destructive"
                                    disabled={removeMember.isPending || actingOn === removeKey}
                                    onClick={() =>
                                      runMemberAction(removeKey, () =>
                                        removeMember.mutate(
                                          { channelId: channel.id, userId: member.user_id },
                                          {
                                            onSuccess: () => {
                                              setActingOn(null);
                                              toast({
                                                title: t("toasts.requestRemovedTitle"),
                                                description: t("toasts.requestRemovedDescription", { username: member.username }),
                                              });
                                            },
                                            onError: () => {
                                              setActingOn(null);
                                              toast({
                                                title: t("toasts.removeRequestFailedTitle"),
                                                description: commonT("tryAgain"),
                                                variant: "destructive",
                                              });
                                            },
                                          },
                                        ),
                                      )
                                    }
                                  >
                                    <UserMinus className="mr-1 h-4 w-4" />
                                    {t("actions.remove")}
                                  </Button>
                                ) : null}
                              </div>
                            </div>
                          </div>
                        );
                      })
                    )}
                  </div>

                  <div className="mt-6 space-y-3">
                    <p className="text-sm font-medium">{t("sections.currentMembers")}</p>
                    {membersQuery.isLoading ? (
                      <div className="space-y-2">
                        <Skeleton className="h-12 w-full rounded-xl" />
                        <Skeleton className="h-12 w-full rounded-xl" />
                      </div>
                    ) : managedMembers.length === 0 ? (
                      <p className="text-sm text-muted-foreground">{t("empty.noMembers")}</p>
                    ) : (
                      managedMembers.map((member) => {
                        const isSelf = member.user_id === currentUser?.id;
                        const promoteKey = `promote:${member.user_id}`;
                        const demoteKey = `demote:${member.user_id}`;
                        const removeKey = `remove:${member.user_id}`;
                        const permissionsKey = `permissions:${member.user_id}`;
                        const canPromote = isOwner && member.role === "member";
                        const canDemote = isOwner && member.role === "admin";
                        const canRemove =
                          !isSelf &&
                          member.role !== "owner" &&
                          (isOwner || (channel.my_role === "admin" && member.role === "member"));
                        const isAdmin = member.role === "admin";
                        const baselinePermissions = normalizeAdminPermissions(member.admin_permissions);
                        const draftPermissions = adminPermissionDrafts[member.user_id] ?? baselinePermissions;
                        const hasPermissionChanges =
                          draftPermissions.can_publish !== baselinePermissions.can_publish ||
                          draftPermissions.can_invite !== baselinePermissions.can_invite ||
                          draftPermissions.can_approve !== baselinePermissions.can_approve ||
                          draftPermissions.can_manage_members !== baselinePermissions.can_manage_members ||
                          draftPermissions.can_edit_channel !== baselinePermissions.can_edit_channel;

                        return (
                          <div key={member.user_id} className="rounded-xl border border-border/60 p-3">
                            <div className="flex flex-wrap items-center justify-between gap-3">
                              <div>
                                <div className="font-medium leading-none">{member.username}</div>
                                <div className="mt-1 text-xs text-muted-foreground">{member.email || t("empty.noEmailAvailable")}</div>
                              </div>
                              <div className="flex flex-wrap items-center gap-2">
                                <Badge variant={getRoleBadgeVariant(member.role)}>{roleLabel(member.role)}</Badge>
                                {canPromote ? (
                                  <Button
                                    size="sm"
                                    variant="outline"
                                    disabled={promoteMember.isPending || actingOn === promoteKey}
                                    onClick={() =>
                                      runMemberAction(promoteKey, () =>
                                        promoteMember.mutate(
                                          { channelId: channel.id, userId: member.user_id },
                                          {
                                            onSuccess: () => {
                                              setActingOn(null);
                                              toast({
                                                title: t("toasts.memberPromotedTitle"),
                                                description: t("toasts.memberPromotedDescription", { username: member.username }),
                                              });
                                            },
                                            onError: () => {
                                              setActingOn(null);
                                              toast({
                                                title: t("toasts.promoteFailedTitle"),
                                                description: commonT("tryAgain"),
                                                variant: "destructive",
                                              });
                                            },
                                          },
                                        ),
                                      )
                                    }
                                  >
                                    <ShieldPlus className="mr-1 h-4 w-4" />
                                    {t("actions.promote")}
                                  </Button>
                                ) : null}
                                {canDemote ? (
                                  <Button
                                    size="sm"
                                    variant="outline"
                                    disabled={demoteMember.isPending || actingOn === demoteKey}
                                    onClick={() =>
                                      runMemberAction(demoteKey, () =>
                                        demoteMember.mutate(
                                          { channelId: channel.id, userId: member.user_id },
                                          {
                                            onSuccess: () => {
                                              setActingOn(null);
                                              toast({
                                                title: t("toasts.adminDemotedTitle"),
                                                description: t("toasts.adminDemotedDescription", { username: member.username }),
                                              });
                                            },
                                            onError: () => {
                                              setActingOn(null);
                                              toast({
                                                title: t("toasts.demoteFailedTitle"),
                                                description: commonT("tryAgain"),
                                                variant: "destructive",
                                              });
                                            },
                                          },
                                        ),
                                      )
                                    }
                                  >
                                    {t("actions.demote")}
                                  </Button>
                                ) : null}
                                {canRemove ? (
                                  <Button
                                    size="sm"
                                    variant="destructive"
                                    disabled={removeMember.isPending || actingOn === removeKey}
                                    onClick={() =>
                                      runMemberAction(removeKey, () =>
                                        removeMember.mutate(
                                          { channelId: channel.id, userId: member.user_id },
                                          {
                                            onSuccess: () => {
                                              setActingOn(null);
                                              toast({
                                                title: t("toasts.memberRemovedTitle"),
                                                description: t("toasts.memberRemovedDescription", { username: member.username }),
                                              });
                                            },
                                            onError: () => {
                                              setActingOn(null);
                                              toast({
                                                title: t("toasts.removeMemberFailedTitle"),
                                                description: commonT("tryAgain"),
                                                variant: "destructive",
                                              });
                                            },
                                          },
                                        ),
                                      )
                                    }
                                  >
                                    <UserMinus className="mr-1 h-4 w-4" />
                                    {t("actions.remove")}
                                  </Button>
                                ) : null}
                              </div>
                            </div>
                            {isOwner && isAdmin ? (
                              <div className="mt-3 rounded-lg bg-muted/50 p-3">
                                <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">{t("sections.adminPermissions")}</p>
                                <div className="mt-2 grid gap-2 sm:grid-cols-2">
                                  <div className="flex items-center justify-between rounded-md bg-background/80 px-2 py-1.5">
                                    <span className="text-xs">{t("permissions.publish")}</span>
                                    <Switch
                                      checked={draftPermissions.can_publish}
                                      onCheckedChange={(checked) =>
                                        setAdminPermissionDrafts((current) => ({
                                          ...current,
                                          [member.user_id]: { ...draftPermissions, can_publish: checked },
                                        }))
                                      }
                                    />
                                  </div>
                                  <div className="flex items-center justify-between rounded-md bg-background/80 px-2 py-1.5">
                                    <span className="text-xs">{t("permissions.invite")}</span>
                                    <Switch
                                      checked={draftPermissions.can_invite}
                                      onCheckedChange={(checked) =>
                                        setAdminPermissionDrafts((current) => ({
                                          ...current,
                                          [member.user_id]: { ...draftPermissions, can_invite: checked },
                                        }))
                                      }
                                    />
                                  </div>
                                  <div className="flex items-center justify-between rounded-md bg-background/80 px-2 py-1.5">
                                    <span className="text-xs">{t("permissions.approve")}</span>
                                    <Switch
                                      checked={draftPermissions.can_approve}
                                      onCheckedChange={(checked) =>
                                        setAdminPermissionDrafts((current) => ({
                                          ...current,
                                          [member.user_id]: { ...draftPermissions, can_approve: checked },
                                        }))
                                      }
                                    />
                                  </div>
                                  <div className="flex items-center justify-between rounded-md bg-background/80 px-2 py-1.5">
                                    <span className="text-xs">{t("permissions.manageMembers")}</span>
                                    <Switch
                                      checked={draftPermissions.can_manage_members}
                                      onCheckedChange={(checked) =>
                                        setAdminPermissionDrafts((current) => ({
                                          ...current,
                                          [member.user_id]: { ...draftPermissions, can_manage_members: checked },
                                        }))
                                      }
                                    />
                                  </div>
                                  <div className="flex items-center justify-between rounded-md bg-background/80 px-2 py-1.5">
                                    <span className="text-xs">{t("permissions.editChannel")}</span>
                                    <Switch
                                      checked={draftPermissions.can_edit_channel}
                                      onCheckedChange={(checked) =>
                                        setAdminPermissionDrafts((current) => ({
                                          ...current,
                                          [member.user_id]: { ...draftPermissions, can_edit_channel: checked },
                                        }))
                                      }
                                    />
                                  </div>
                                </div>
                                <div className="mt-3 flex justify-end">
                                  <Button
                                    size="sm"
                                    disabled={!hasPermissionChanges || updateAdminPermissions.isPending || actingOn === permissionsKey}
                                    onClick={() =>
                                      runMemberAction(permissionsKey, () =>
                                        updateAdminPermissions.mutate(
                                          {
                                            channelId: channel.id,
                                            userId: member.user_id,
                                            data: draftPermissions,
                                          },
                                          {
                                            onSuccess: () => {
                                              setActingOn(null);
                                              toast({
                                                title: t("toasts.permissionsUpdatedTitle"),
                                                description: t("toasts.permissionsUpdatedDescription", { username: member.username }),
                                              });
                                            },
                                            onError: () => {
                                              setActingOn(null);
                                              toast({
                                                title: t("toasts.permissionsFailedTitle"),
                                                description: commonT("tryAgain"),
                                                variant: "destructive",
                                              });
                                            },
                                          },
                                        ),
                                      )
                                    }
                                  >
                                    {t("actions.savePermissions")}
                                  </Button>
                                </div>
                              </div>
                            ) : null}
                          </div>
                        );
                      })
                    )}
                  </div>
                </Card>
              ) : null}
            </div>
          ) : null}
        </Card>
      </div>
    </div>
  );
}
