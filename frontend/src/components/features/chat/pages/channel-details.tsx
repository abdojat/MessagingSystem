"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { FormEvent, useEffect, useMemo, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { format } from "date-fns";
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

function formatDateTime(value?: string | null) {
  if (!value) return "Not available";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Not available";
  return format(date, "PPP p");
}

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
        throw new Error("You need to be signed in before uploading a channel image.");
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
        let message = "Could not upload channel avatar image.";
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
        throw new Error("Upload succeeded but no avatar URL was returned.");
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
            &larr; Back
          </Link>
          <Card className="mt-6 rounded-3xl p-8 text-center">
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

  const isMember = ["owner", "admin", "member"].includes(channel.my_role || "");
  const isOwner = channel.my_role === "owner";
  const canLeave = isMember && channel.my_role !== "owner";
  const channelAvatarUrl = avatarPreviewUrl || resolveApiMediaUrl(channel.avatar_url);
  const canEditChannel = channel.permissions.can_edit_channel;

  const managedMembers = (membersQuery.data?.items ?? []).filter((item) => item.role !== "pending");
  const pendingMembers = (membersQuery.data?.items ?? []).filter((item) => item.role === "pending");

  const hasEditChanges = useMemo(() => {
    const trimmedName = editForm.name.trim();
    const trimmedDescription = editForm.description.trim();
    return (
      trimmedName !== (channel.name ?? "") ||
      trimmedDescription !== (channel.description ?? "") ||
      Boolean(avatarFile) ||
      editForm.visibility !== channel.visibility ||
      editForm.joinMode !== channel.join_mode
    );
  }, [avatarFile, channel, editForm]);

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
          title: "No changes to save",
          description: "Update one or more fields before saving.",
        });
        return;
      }

      updateChannel.mutate(
        { channelId: channel.id, data: payload },
        {
          onSuccess: () => {
            setAvatarFile(null);
            toast({
              title: "Channel updated",
              description: "Channel settings were saved successfully.",
            });
          },
          onError: () => {
            toast({
              title: "Could not update channel",
              description: "Please try again in a moment.",
              variant: "destructive",
            });
          },
        },
      );
    };

    submitUpdate().catch((error: unknown) => {
      toast({
        title: "Could not upload avatar",
        description: getErrorMessage(error, "Please try again in a moment."),
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
              &larr; Back to channel
            </button>
            <h1 className="mt-2 text-3xl font-bold tracking-tight">Channel Details</h1>
            <p className="mt-1 text-muted-foreground">Overview, membership status, and access controls for this channel.</p>
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
                {joinChannel.isPending ? "Joining..." : "Join Channel"}
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
                {leaveChannel.isPending ? "Leaving..." : "Leave Channel"}
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
                    <Badge variant="secondary">{channel.visibility}</Badge>
                    <Badge variant="secondary">{channel.join_mode}</Badge>
                    <Badge>{channel.my_role}</Badge>
                  </div>
                  <h2 className="mt-3 truncate text-3xl font-bold">{channel.name}</h2>
                  <p className="mt-2 max-w-2xl text-sm leading-6 text-muted-foreground">
                    {channel.description?.trim() || "No description has been added for this channel yet."}
                  </p>
                </div>
              </div>
            </div>
          </div>

          <div className="grid gap-4 p-6 sm:grid-cols-2 lg:grid-cols-4">
            <Card className="rounded-2xl p-4">
              <div className="flex items-center gap-2 text-muted-foreground">
                <Users className="h-4 w-4" />
                <span className="text-xs uppercase tracking-[0.18em]">Members</span>
              </div>
              <p className="mt-2 text-2xl font-semibold">{channel.member_count}</p>
            </Card>
            <Card className="rounded-2xl p-4">
              <div className="flex items-center gap-2 text-muted-foreground">
                <Shield className="h-4 w-4" />
                <span className="text-xs uppercase tracking-[0.18em]">Pending</span>
              </div>
              <p className="mt-2 text-2xl font-semibold">{channel.pending_count}</p>
            </Card>
            <Card className="rounded-2xl p-4">
              <div className="flex items-center gap-2 text-muted-foreground">
                <Info className="h-4 w-4" />
                <span className="text-xs uppercase tracking-[0.18em]">Unread</span>
              </div>
              <p className="mt-2 text-2xl font-semibold">{channel.unread_count}</p>
            </Card>
            <Card className="rounded-2xl p-4">
              <div className="flex items-center gap-2 text-muted-foreground">
                <Lock className="h-4 w-4" />
                <span className="text-xs uppercase tracking-[0.18em]">Access</span>
              </div>
              <p className="mt-2 text-sm font-semibold capitalize">{channel.join_mode.replace("_", " ")}</p>
            </Card>
          </div>

          <div className="grid gap-4 border-t border-border/60 p-6 lg:grid-cols-[1.1fr_0.9fr]">
            <Card className="rounded-2xl p-5">
              <h3 className="text-lg font-semibold">Channel overview</h3>
              <div className="mt-4 space-y-4 text-sm">
                <div>
                  <p className="text-muted-foreground">Visibility</p>
                  <p className="mt-1 font-medium capitalize">{channel.visibility}</p>
                </div>
                <div>
                  <p className="text-muted-foreground">Join policy</p>
                  <p className="mt-1 font-medium capitalize">{channel.join_mode.replace("_", " ")}</p>
                </div>
                <div>
                  <p className="text-muted-foreground">Created</p>
                  <p className="mt-1 font-medium">{formatDateTime(channel.created_at)}</p>
                </div>
                <div>
                  <p className="text-muted-foreground">Updated</p>
                  <p className="mt-1 font-medium">{formatDateTime(channel.updated_at)}</p>
                </div>
                <div>
                  <p className="text-muted-foreground">Last activity</p>
                  <p className="mt-1 font-medium">{formatDateTime(channel.last_message_at)}</p>
                </div>
              </div>
            </Card>

            <Card className="rounded-2xl p-5">
              <h3 className="text-lg font-semibold">Your access</h3>
              <div className="mt-4 space-y-3 text-sm">
                <div className="flex items-center justify-between gap-4">
                  <span className="text-muted-foreground">Publish messages</span>
                  <span className="font-medium">{channel.permissions.can_publish ? "Allowed" : "No"}</span>
                </div>
                <div className="flex items-center justify-between gap-4">
                  <span className="text-muted-foreground">Invite members</span>
                  <span className="font-medium">{channel.permissions.can_invite ? "Allowed" : "No"}</span>
                </div>
                <div className="flex items-center justify-between gap-4">
                  <span className="text-muted-foreground">Approve requests</span>
                  <span className="font-medium">{channel.permissions.can_approve ? "Allowed" : "No"}</span>
                </div>
                <div className="flex items-center justify-between gap-4">
                  <span className="text-muted-foreground">Manage members</span>
                  <span className="font-medium">{channel.permissions.can_manage_members ? "Allowed" : "No"}</span>
                </div>
                <div className="flex items-center justify-between gap-4">
                  <span className="text-muted-foreground">Edit channel</span>
                  <span className="font-medium">{channel.permissions.can_edit_channel ? "Allowed" : "No"}</span>
                </div>
              </div>
            </Card>
          </div>

          {(canEditChannel || canManageMembers) ? (
            <div className="grid gap-4 border-t border-border/60 p-6 lg:grid-cols-2">
              {canEditChannel ? (
                <Card className="rounded-2xl p-5">
                  <h3 className="text-lg font-semibold">Edit channel</h3>
                  <p className="mt-1 text-sm text-muted-foreground">Settings for members who can edit channel profile and access behavior.</p>
                  <form className="mt-4 space-y-4" onSubmit={handleEditSubmit}>
                    <div className="grid gap-2">
                      <Label htmlFor="details-channel-name">Name</Label>
                      <Input
                        id="details-channel-name"
                        value={editForm.name}
                        maxLength={255}
                        onChange={(event) => setEditForm((current) => ({ ...current, name: event.target.value }))}
                      />
                    </div>
                    <div className="grid gap-2">
                      <Label htmlFor="details-channel-description">Description</Label>
                      <Textarea
                        id="details-channel-description"
                        value={editForm.description}
                        maxLength={1000}
                        className="min-h-24 resize-none"
                        onChange={(event) => setEditForm((current) => ({ ...current, description: event.target.value }))}
                      />
                    </div>
                    <div className="grid gap-2">
                      <Label htmlFor="details-channel-avatar">Avatar upload</Label>
                      <Input
                        id="details-channel-avatar"
                        type="file"
                        accept="image/*"
                        onChange={(event) => setAvatarFile(event.target.files?.[0] ?? null)}
                      />
                      <p className="text-xs text-muted-foreground">
                        {avatarFile ? `Selected: ${avatarFile.name}` : "Choose an image file to update the channel avatar."}
                      </p>
                    </div>
                    <div className="grid gap-4 sm:grid-cols-2">
                      <div className="grid gap-2">
                        <Label>Visibility</Label>
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
                            <SelectItem value="public">Public</SelectItem>
                            <SelectItem value="private">Private</SelectItem>
                          </SelectContent>
                        </Select>
                      </div>
                      <div className="grid gap-2">
                        <Label>Join mode</Label>
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
                            <SelectItem value="open">Open</SelectItem>
                            <SelectItem value="approval_required">Approval required</SelectItem>
                            <SelectItem value="invite_only">Invite only</SelectItem>
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
                        Reset
                      </Button>
                      <Button type="submit" disabled={updateChannel.isPending || uploadAvatar.isPending || !hasEditChanges}>
                        {updateChannel.isPending || uploadAvatar.isPending ? "Saving..." : "Save changes"}
                      </Button>
                    </div>
                  </form>
                </Card>
              ) : (
                <Card className="rounded-2xl p-5">
                  <h3 className="text-lg font-semibold">Edit channel</h3>
                  <p className="mt-2 text-sm text-muted-foreground">
                    Editing is currently restricted to the owner or admins with edit permission.
                  </p>
                </Card>
              )}

              {canManageMembers ? (
                <Card className="rounded-2xl p-5">
                  <h3 className="text-lg font-semibold">Members & roles</h3>
                  <p className="mt-1 text-sm text-muted-foreground">
                    Manage pending requests, remove access, and owner-only role promotions.
                  </p>

                  <div className="mt-4 space-y-3">
                    <p className="text-sm font-medium">Pending requests</p>
                    {membersQuery.isLoading ? (
                      <div className="space-y-2">
                        <Skeleton className="h-12 w-full rounded-xl" />
                        <Skeleton className="h-12 w-full rounded-xl" />
                      </div>
                    ) : pendingMembers.length === 0 ? (
                      <p className="text-sm text-muted-foreground">No pending requests right now.</p>
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
                                <div className="mt-1 text-xs text-muted-foreground">{member.email || "No email available"}</div>
                              </div>
                              <div className="flex items-center gap-2">
                                <Badge variant={getRoleBadgeVariant(member.role)}>{member.role}</Badge>
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
                                                title: "Request approved",
                                                description: `${member.username} is now a member.`,
                                              });
                                            },
                                            onError: () => {
                                              setActingOn(null);
                                              toast({
                                                title: "Could not approve request",
                                                description: "Please try again.",
                                                variant: "destructive",
                                              });
                                            },
                                          },
                                        ),
                                      )
                                    }
                                  >
                                    <Check className="mr-1 h-4 w-4" />
                                    Approve
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
                                                title: "Request removed",
                                                description: `${member.username} is no longer pending.`,
                                              });
                                            },
                                            onError: () => {
                                              setActingOn(null);
                                              toast({
                                                title: "Could not remove request",
                                                description: "Please try again.",
                                                variant: "destructive",
                                              });
                                            },
                                          },
                                        ),
                                      )
                                    }
                                  >
                                    <UserMinus className="mr-1 h-4 w-4" />
                                    Remove
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
                    <p className="text-sm font-medium">Current members</p>
                    {membersQuery.isLoading ? (
                      <div className="space-y-2">
                        <Skeleton className="h-12 w-full rounded-xl" />
                        <Skeleton className="h-12 w-full rounded-xl" />
                      </div>
                    ) : managedMembers.length === 0 ? (
                      <p className="text-sm text-muted-foreground">No members to display.</p>
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
                                <div className="mt-1 text-xs text-muted-foreground">{member.email || "No email available"}</div>
                              </div>
                              <div className="flex flex-wrap items-center gap-2">
                                <Badge variant={getRoleBadgeVariant(member.role)}>{member.role}</Badge>
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
                                                title: "Member promoted",
                                                description: `${member.username} is now an admin.`,
                                              });
                                            },
                                            onError: () => {
                                              setActingOn(null);
                                              toast({
                                                title: "Could not promote member",
                                                description: "Please try again.",
                                                variant: "destructive",
                                              });
                                            },
                                          },
                                        ),
                                      )
                                    }
                                  >
                                    <ShieldPlus className="mr-1 h-4 w-4" />
                                    Promote
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
                                                title: "Admin demoted",
                                                description: `${member.username} is now a member.`,
                                              });
                                            },
                                            onError: () => {
                                              setActingOn(null);
                                              toast({
                                                title: "Could not demote admin",
                                                description: "Please try again.",
                                                variant: "destructive",
                                              });
                                            },
                                          },
                                        ),
                                      )
                                    }
                                  >
                                    Demote
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
                                                title: "Member removed",
                                                description: `${member.username} no longer has access.`,
                                              });
                                            },
                                            onError: () => {
                                              setActingOn(null);
                                              toast({
                                                title: "Could not remove member",
                                                description: "Please try again.",
                                                variant: "destructive",
                                              });
                                            },
                                          },
                                        ),
                                      )
                                    }
                                  >
                                    <UserMinus className="mr-1 h-4 w-4" />
                                    Remove
                                  </Button>
                                ) : null}
                              </div>
                            </div>
                            {isOwner && isAdmin ? (
                              <div className="mt-3 rounded-lg bg-muted/50 p-3">
                                <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Admin permissions</p>
                                <div className="mt-2 grid gap-2 sm:grid-cols-2">
                                  <div className="flex items-center justify-between rounded-md bg-background/80 px-2 py-1.5">
                                    <span className="text-xs">Publish messages</span>
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
                                    <span className="text-xs">Invite members</span>
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
                                    <span className="text-xs">Approve requests</span>
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
                                    <span className="text-xs">Manage members</span>
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
                                    <span className="text-xs">Edit channel</span>
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
                                                title: "Permissions updated",
                                                description: `${member.username}'s admin permissions were saved.`,
                                              });
                                            },
                                            onError: () => {
                                              setActingOn(null);
                                              toast({
                                                title: "Could not update permissions",
                                                description: "Please try again.",
                                                variant: "destructive",
                                              });
                                            },
                                          },
                                        ),
                                      )
                                    }
                                  >
                                    Save permissions
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
