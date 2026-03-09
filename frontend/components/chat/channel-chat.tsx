"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { PanelRightClose, PanelRightOpen, Pencil, Pin, Reply, Send, SmilePlus, Trash2 } from "lucide-react";
import Image from "next/image";
import { useRouter } from "next/navigation";
import { toast } from "sonner";
import { api, ApiError } from "@/lib/api-client";
import { resolveApiUrl } from "@/lib/env";
import { queryKeys } from "@/lib/query-keys";
import { cn, formatDateTime } from "@/lib/utils";
import { useAppUiStore } from "@/store/app-ui-store";
import { useCurrentUser } from "@/hooks/use-current-user";
import { useResizablePanel } from "@/hooks/use-resizable-panel";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { EmptyState } from "@/components/ui/empty-state";
import { AppTabs, AppTabsContent, AppTabsList, AppTabsTrigger } from "@/components/ui/tabs";
import type { ChannelMemberItem, ChannelResponse, InviteListItem, MessageResponse } from "@/types/api";

function canManagePins(channel: ChannelResponse) {
  // Assumption: pin moderation follows manage-members capability when explicit pin permission is unavailable.
  return channel.permissions.can_manage_members || channel.my_role === "owner" || channel.my_role === "admin";
}

function canDeleteMessage(message: MessageResponse, channel: ChannelResponse, myUserId?: string) {
  // Assumption: sender can delete own messages; moderators with member-management can delete any message.
  return message.sender_user_id === myUserId || channel.permissions.can_manage_members;
}

function canEditMessage(message: MessageResponse, myUserId?: string) {
  // Assumption: only original sender can edit; backend remains source of truth for final authorization.
  return message.sender_user_id === myUserId;
}

function MessageRow({
  message,
  channel,
  onReply,
}: {
  message: MessageResponse;
  channel: ChannelResponse;
  onReply: (message: MessageResponse) => void;
}) {
  const { data: me } = useCurrentUser();
  const queryClient = useQueryClient();
  const [editing, setEditing] = useState(false);
  const [editText, setEditText] = useState(message.content_text ?? "");

  const editMutation = useMutation({
    mutationFn: () => api.editMessage(channel.id, message.id, { content_text: editText }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.messages(channel.id) });
      setEditing(false);
    },
    onError: (error) => toast.error(error instanceof ApiError ? error.message : "Failed to edit"),
  });

  const deleteMutation = useMutation({
    mutationFn: () => api.deleteMessage(channel.id, message.id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: queryKeys.messages(channel.id) }),
    onError: (error) => toast.error(error instanceof ApiError ? error.message : "Failed to delete"),
  });

  const pinMutation = useMutation({
    mutationFn: () => (message.is_pinned ? api.unpinMessage(channel.id, message.id) : api.pinMessage(channel.id, message.id)),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.messages(channel.id) });
      queryClient.invalidateQueries({ queryKey: queryKeys.pins(channel.id) });
    },
    onError: (error) => toast.error(error instanceof ApiError ? error.message : "Failed to update pin"),
  });

  const reactMutation = useMutation({
    mutationFn: (emoji: string) =>
      message.reactions_summary.my_reaction.includes(emoji)
        ? api.removeReaction(channel.id, message.id, emoji)
        : api.addReaction(channel.id, message.id, emoji),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: queryKeys.messages(channel.id) }),
    onError: (error) => toast.error(error instanceof ApiError ? error.message : "Reaction failed"),
  });

  return (
    <div className="rounded-lg border border-slate-200 bg-white p-3 dark:border-slate-800 dark:bg-slate-900" data-seq-id={message.seq_id}>
      <div className="mb-2 flex items-center justify-between text-xs text-slate-500">
        <span>seq #{message.seq_id}</span>
        <span>{formatDateTime(message.created_at)}</span>
      </div>

      {editing ? (
        <div className="space-y-2">
          <Textarea value={editText} onChange={(event) => setEditText(event.target.value)} />
          <div className="flex gap-2">
            <Button size="sm" onClick={() => editMutation.mutate()} disabled={!editText.trim()}>
              Save
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setEditing(false)}>
              Cancel
            </Button>
          </div>
        </div>
      ) : (
        <>
          {message.deleted_at ? <p className="italic text-slate-400">Message deleted</p> : null}
          {message.content_type === "text" && message.content_text ? <p className="whitespace-pre-wrap text-sm">{message.content_text}</p> : null}
          {message.content_type === "json" && message.content_json ? (
            <pre className="overflow-x-auto rounded bg-slate-100 p-2 text-xs dark:bg-slate-800">{JSON.stringify(message.content_json, null, 2)}</pre>
          ) : null}
          {message.attachments?.length ? (
            <div className="mt-2 space-y-1">
              {message.attachments.map((attachment, index) => {
                const publicUrl = resolveApiUrl(String(attachment.public_url ?? attachment.url ?? ""));
                const contentType = String(attachment.content_type ?? "");
                if (!publicUrl) return null;
                if (contentType.startsWith("image/")) {
                  return (
                    <Image
                      key={`${message.id}-${index}`}
                      src={publicUrl}
                      alt="attachment"
                      width={480}
                      height={320}
                      className="max-h-64 w-auto rounded object-contain"
                    />
                  );
                }
                return (
                  <a key={`${message.id}-${index}`} href={publicUrl} target="_blank" rel="noreferrer" className="text-sm text-blue-600 hover:underline">
                    {String(attachment.filename ?? "Attachment")}
                  </a>
                );
              })}
            </div>
          ) : null}
        </>
      )}

      <div className="mt-3 flex flex-wrap items-center gap-1">
        {Object.entries(message.reactions_summary.counts).map(([emoji, count]) => (
          <button
            key={emoji}
            className={cn(
              "rounded-full border px-2 py-0.5 text-xs",
              message.reactions_summary.my_reaction.includes(emoji) ? "border-slate-900 bg-slate-900 text-white dark:border-slate-100 dark:bg-slate-100 dark:text-slate-900" : "border-slate-300",
            )}
            onClick={() => reactMutation.mutate(emoji)}
          >
            {emoji} {count}
          </button>
        ))}
        <Button size="sm" variant="ghost" onClick={() => reactMutation.mutate(":thumbs_up:")}>
          <SmilePlus className="size-4" />
        </Button>
        <Button size="sm" variant="ghost" onClick={() => onReply(message)}>
          <Reply className="size-4" />
        </Button>
        {canEditMessage(message, me?.id) ? (
          <Button size="sm" variant="ghost" onClick={() => setEditing(true)}>
            Edit
          </Button>
        ) : null}
        {canDeleteMessage(message, channel, me?.id) ? (
          <Button size="sm" variant="ghost" onClick={() => deleteMutation.mutate()}>
            <Trash2 className="size-4" />
          </Button>
        ) : null}
        {canManagePins(channel) ? (
          <Button size="sm" variant="ghost" onClick={() => pinMutation.mutate()}>
            <Pin className={cn("size-4", message.is_pinned ? "fill-current" : "")} />
          </Button>
        ) : null}
      </div>
    </div>
  );
}

function Composer({ channel }: { channel: ChannelResponse }) {
  const queryClient = useQueryClient();
  const replyToMessageId = useAppUiStore((s) => s.replyToMessageId);
  const replyToSeqId = useAppUiStore((s) => s.replyToSeqId);
  const setReplyTarget = useAppUiStore((s) => s.setReplyTarget);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  const [text, setText] = useState("");
  const [files, setFiles] = useState<File[]>([]);
  const [isDragging, setIsDragging] = useState(false);

  const addFiles = (incoming: File[]) => {
    if (!incoming.length) return;
    setFiles((current) => [...current, ...incoming]);
  };

  const sendMutation = useMutation({
    mutationFn: async () => {
      const attachments: Array<Record<string, unknown>> = [];
      for (const file of files) {
        const upload = await api.uploadFile(file);

        attachments.push({
          file_id: upload.file_id,
          filename: file.name,
          content_type: file.type || "application/octet-stream",
          public_url: upload.public_url,
          size_bytes: file.size,
        });
      }

      const payload: Record<string, unknown> = {
        client_msg_id: crypto.randomUUID(),
        attachments,
      };

      if (text.trim()) {
        payload.content_text = text;
      }

      if (replyToMessageId) payload.reply_to_message_id = replyToMessageId;
      if (replyToSeqId) payload.reply_to_seq_id = replyToSeqId;

      return api.sendMessage(channel.id, payload);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.messages(channel.id) });
      setText("");
      setFiles([]);
      setReplyTarget(null);
    },
    onError: (error) => {
      if (error instanceof ApiError) {
        toast.error(error.message);
        return;
      }
      toast.error("Failed to send message");
    },
  });

  if (!channel.permissions.can_publish) {
    return null;
  }

  return (
    <div className="border-t border-slate-200 bg-white p-3 dark:border-slate-800 dark:bg-slate-950">
      {replyToSeqId ? (
        <div className="mb-2 flex items-center justify-between rounded-md bg-slate-100 px-3 py-2 text-xs dark:bg-slate-800">
          <span>Replying to seq #{replyToSeqId}</span>
          <button onClick={() => setReplyTarget(null)}>Clear</button>
        </div>
      ) : null}

      <div
        className={cn(
          "mb-2 rounded-md border border-dashed px-3 py-2 text-xs text-slate-500 transition-colors",
          isDragging ? "border-slate-900 bg-slate-100 dark:border-slate-100 dark:bg-slate-800" : "border-slate-300 dark:border-slate-700",
        )}
        onDragEnter={(event) => {
          event.preventDefault();
          setIsDragging(true);
        }}
        onDragOver={(event) => {
          event.preventDefault();
          setIsDragging(true);
        }}
        onDragLeave={(event) => {
          event.preventDefault();
          if (event.currentTarget.contains(event.relatedTarget as Node | null)) return;
          setIsDragging(false);
        }}
        onDrop={(event) => {
          event.preventDefault();
          setIsDragging(false);
          addFiles(Array.from(event.dataTransfer.files ?? []));
        }}
      >
        <div className="flex items-center justify-between gap-2">
          <span>{isDragging ? "Drop files to attach" : "Drag and drop files here, or click to browse"}</span>
          <Button size="sm" variant="ghost" onClick={() => fileInputRef.current?.click()}>
            Choose files
          </Button>
        </div>
        {!!files.length ? <p className="mt-1 truncate">{files.map((file) => file.name).join(", ")}</p> : null}
        <input
          ref={fileInputRef}
          type="file"
          multiple
          className="hidden"
          onChange={(event) => addFiles(Array.from(event.target.files ?? []))}
        />
      </div>

      <Textarea
        value={text}
        onChange={(event) => setText(event.target.value)}
        placeholder="Write a message"
        onKeyDown={(event) => {
          if (event.key === "Enter" && !event.shiftKey) {
            event.preventDefault();
            if (!sendMutation.isPending && (text.trim() || files.length > 0)) {
              sendMutation.mutate();
            }
          }
        }}
      />

      <div className="mt-2 flex justify-end">
        <Button onClick={() => sendMutation.mutate()} disabled={sendMutation.isPending || (!text.trim() && files.length === 0)}>
          <Send className="mr-2 size-4" />
          Send
        </Button>
      </div>
    </div>
  );
}

function ChannelDetailsPanel({ channelId, channel }: { channelId: string; channel: ChannelResponse }) {
  const queryClient = useQueryClient();
  const router = useRouter();
  const [inviteToken, setInviteToken] = useState("");
  const [latestInviteLink, setLatestInviteLink] = useState<string | null>(null);
  const [isEditingDetails, setIsEditingDetails] = useState(false);
  const [editName, setEditName] = useState(channel.name);
  const [editDescription, setEditDescription] = useState(channel.description ?? "");
  const [editAvatarUrl, setEditAvatarUrl] = useState(channel.avatar_url ?? "");
  const [editVisibility, setEditVisibility] = useState<ChannelResponse["visibility"]>(channel.visibility);
  const [editJoinMode, setEditJoinMode] = useState<ChannelResponse["join_mode"]>(channel.join_mode);
  const avatarInputRef = useRef<HTMLInputElement | null>(null);

  const membersQuery = useQuery({
    queryKey: queryKeys.channelMembers(channelId, ""),
    queryFn: () => api.members(channelId),
    enabled: channel.my_role !== "none",
  });

  const requestsQuery = useQuery({
    queryKey: queryKeys.channelRequests(channelId, ""),
    queryFn: () => api.requests(channelId),
    enabled: channel.permissions.can_approve,
  });

  const invitesQuery = useQuery({
    queryKey: queryKeys.channelInvites(channelId, ""),
    queryFn: () => api.listInvites(channelId),
    enabled: channel.permissions.can_invite,
  });

  const pinsQuery = useQuery({
    queryKey: queryKeys.pins(channelId),
    queryFn: () => api.listPins(channelId),
    enabled: channel.my_role !== "none",
  });

  const joinMutation = useMutation({
    mutationFn: () => api.joinChannel(channelId, inviteToken || undefined),
    onSuccess: (result) => {
      toast.success(result.message);
      queryClient.invalidateQueries({ queryKey: ["channels"] });
      queryClient.invalidateQueries({ queryKey: queryKeys.channel(channelId) });
    },
    onError: (error) => toast.error(error instanceof ApiError ? error.message : "Join failed"),
  });
  const leaveMutation = useMutation({
    mutationFn: () => api.leaveChannel(channelId),
    onSuccess: () => {
      toast.success("You left the channel");
      queryClient.invalidateQueries({ queryKey: ["channels"] });
      queryClient.invalidateQueries({ queryKey: queryKeys.channel(channelId) });
      router.replace("/app");
    },
    onError: (error) => toast.error(error instanceof ApiError ? error.message : "Leave failed"),
  });

  const createInvite = useMutation({
    mutationFn: () => api.createInvite(channelId, { is_generic: true, expires_in_hours: 72 }),
    onSuccess: (result) => {
      const inviteLink =
        typeof window === "undefined" ? `/invites/${result.token}` : `${window.location.origin}/invites/${result.token}`;
      setLatestInviteLink(inviteLink);
      toast.success("Invite link created");
      queryClient.invalidateQueries({ queryKey: queryKeys.channelInvites(channelId, "") });
    },
    onError: (error) => toast.error(error instanceof ApiError ? error.message : "Failed to create invite"),
  });

  const approveMutation = useMutation({
    mutationFn: (userId: string) => api.approveMember(channelId, userId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.channelRequests(channelId, "") });
      queryClient.invalidateQueries({ queryKey: queryKeys.channelMembers(channelId, "") });
      queryClient.invalidateQueries({ queryKey: ["channels"] });
    },
  });

  const promoteMutation = useMutation({
    mutationFn: (user: ChannelMemberItem) => (user.role === "admin" ? api.demoteMember(channelId, user.user_id) : api.promoteMember(channelId, user.user_id)),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: queryKeys.channelMembers(channelId, "") }),
  });

  const removeMutation = useMutation({
    mutationFn: (userId: string) => api.removeMember(channelId, userId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: queryKeys.channelMembers(channelId, "") }),
  });

  const revokeInvite = useMutation({
    mutationFn: (inviteId: string) => api.revokeInvite(channelId, inviteId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: queryKeys.channelInvites(channelId, "") }),
  });

  const patchMutation = useMutation({
    mutationFn: (patch: Partial<Pick<ChannelResponse, "name" | "description" | "avatar_url" | "visibility" | "join_mode">>) => api.patchChannel(channelId, patch),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["channels"] });
      queryClient.invalidateQueries({ queryKey: queryKeys.channel(channelId) });
    },
    onError: (error) => toast.error(error instanceof ApiError ? error.message : "Update failed"),
  });

  const avatarUploadMutation = useMutation({
    mutationFn: async (file: File) => {
      const upload = await api.uploadFile(file);
      return upload.public_url ?? `/v1/uploads/${upload.file_id}/content`;
    },
    onSuccess: (avatarUrl) => {
      setEditAvatarUrl(avatarUrl);
    },
    onError: (error) => toast.error(error instanceof ApiError ? error.message : "Avatar upload failed"),
  });

  const resetEditForm = useCallback(() => {
    setEditName(channel.name);
    setEditDescription(channel.description ?? "");
    setEditAvatarUrl(channel.avatar_url ?? "");
    setEditVisibility(channel.visibility);
    setEditJoinMode(channel.join_mode);
  }, [channel.avatar_url, channel.description, channel.join_mode, channel.name, channel.visibility]);

  const avatarSrc = resolveApiUrl(channel.avatar_url);
  const initials = channel.name
    .split(" ")
    .map((part) => part.trim()[0])
    .filter(Boolean)
    .slice(0, 2)
    .join("")
    .toUpperCase();

  return (
    <Card className="h-full overflow-auto p-3">
      <div className="space-y-2">
        <div className="flex items-start justify-between gap-2">
          <h3 className="font-semibold">Details</h3>
          {channel.permissions.can_edit_channel && !isEditingDetails ? (
            <Button
              size="sm"
              variant="secondary"
              onClick={() => {
                resetEditForm();
                setIsEditingDetails(true);
              }}
            >
              <Pencil className="mr-2 size-4" />
              Edit
            </Button>
          ) : null}
        </div>
        <div className="flex items-center gap-3 rounded-lg border border-slate-200 p-2 dark:border-slate-800">
          {avatarSrc ? (
            <Image src={avatarSrc} alt={channel.name} width={56} height={56} unoptimized className="size-14 rounded-full object-cover" />
          ) : (
            <div className="flex size-14 items-center justify-center rounded-full bg-slate-300 text-sm font-semibold text-slate-700 dark:bg-slate-700 dark:text-slate-200">
              {initials || "#"}
            </div>
          )}
          <div className="min-w-0">
            <p className="truncate text-sm font-medium">{channel.name}</p>
            <p className="text-xs text-slate-500">
              {channel.visibility} / {channel.join_mode}
            </p>
            <p className="text-xs text-slate-500">My role: {channel.my_role}</p>
          </div>
        </div>
        {!isEditingDetails ? <p className="text-sm text-slate-600 dark:text-slate-300">{channel.description || "No description"}</p> : null}

        {channel.my_role === "none" ? (
          <div className="space-y-2 rounded-lg border border-slate-200 p-2 dark:border-slate-800">
            {channel.join_mode === "invite_only" ? <Input placeholder="Invite token" value={inviteToken} onChange={(event) => setInviteToken(event.target.value)} /> : null}
            <Button size="sm" onClick={() => joinMutation.mutate()}>
              Join channel
            </Button>
          </div>
        ) : null}
        {channel.my_role !== "none" ? (
          <div className="space-y-2 rounded-lg border border-slate-200 p-2 dark:border-slate-800">
            <Button
              size="sm"
              variant="danger"
              onClick={() => leaveMutation.mutate()}
              disabled={leaveMutation.isPending || channel.my_role === "owner"}
            >
              {leaveMutation.isPending ? "Leaving..." : "Leave channel"}
            </Button>
            {channel.my_role === "owner" ? (
              <p className="text-xs text-slate-500">Owners cannot leave the channel until ownership is transferred.</p>
            ) : null}
          </div>
        ) : null}

        {channel.permissions.can_edit_channel && isEditingDetails ? (
          <div className="space-y-2 rounded-lg border border-slate-200 p-2 dark:border-slate-800">
            <h4 className="text-sm font-medium">Edit channel</h4>
            <Input value={editName} onChange={(event) => setEditName(event.target.value)} />
            <Input
              value={editDescription}
              onChange={(event) => setEditDescription(event.target.value)}
              placeholder="Description"
            />
            <Input
              value={editAvatarUrl}
              placeholder="Avatar URL"
              onChange={(event) => setEditAvatarUrl(event.target.value)}
            />
            <div className="grid grid-cols-2 gap-2 text-sm">
              <label className="space-y-1">
                <span className="text-slate-500">Visibility</span>
                <select
                  className="h-9 w-full rounded-md border border-slate-300 px-2 dark:border-slate-700 dark:bg-slate-900"
                  value={editVisibility}
                  onChange={(event) => setEditVisibility(event.target.value as ChannelResponse["visibility"])}
                >
                  <option value="public">Public</option>
                  <option value="private">Private</option>
                </select>
              </label>
              <label className="space-y-1">
                <span className="text-slate-500">Join mode</span>
                <select
                  className="h-9 w-full rounded-md border border-slate-300 px-2 dark:border-slate-700 dark:bg-slate-900"
                  value={editJoinMode}
                  onChange={(event) => setEditJoinMode(event.target.value as ChannelResponse["join_mode"])}
                >
                  <option value="open">Open</option>
                  <option value="invite_only">Invite only</option>
                  <option value="approval_required">Approval required</option>
                </select>
              </label>
            </div>
            <div className="flex items-center gap-2">
              <Button size="sm" variant="secondary" onClick={() => avatarInputRef.current?.click()} disabled={avatarUploadMutation.isPending || patchMutation.isPending}>
                {avatarUploadMutation.isPending ? "Uploading..." : "Upload avatar image"}
              </Button>
              {editAvatarUrl.trim() ? (
                <Button size="sm" variant="ghost" onClick={() => setEditAvatarUrl("")} disabled={patchMutation.isPending}>
                  Remove avatar
                </Button>
              ) : null}
            </div>
            {editAvatarUrl.trim() ? (
              <Image
                src={resolveApiUrl(editAvatarUrl) ?? editAvatarUrl}
                alt="Avatar preview"
                width={64}
                height={64}
                unoptimized
                className="size-16 rounded-full object-cover"
              />
            ) : null}
            <input
              ref={avatarInputRef}
              type="file"
              accept="image/*"
              className="hidden"
              onChange={(event) => {
                const file = event.target.files?.[0];
                if (!file) return;
                avatarUploadMutation.mutate(file);
                event.target.value = "";
              }}
            />
            <div className="flex items-center gap-2">
              <Button
                size="sm"
                onClick={() => {
                  const patch: Partial<Pick<ChannelResponse, "name" | "description" | "avatar_url" | "visibility" | "join_mode">> = {};
                  const nextName = editName.trim();
                  const nextDescription = editDescription.trim();
                  const nextAvatar = editAvatarUrl.trim();
                  if (nextName && nextName !== channel.name) patch.name = nextName;
                  if (nextDescription !== (channel.description ?? "").trim()) patch.description = nextDescription || null;
                  if (nextAvatar !== (channel.avatar_url ?? "").trim()) patch.avatar_url = nextAvatar || null;
                  if (editVisibility !== channel.visibility) patch.visibility = editVisibility;
                  if (editJoinMode !== channel.join_mode) patch.join_mode = editJoinMode;
                  if (!Object.keys(patch).length) {
                    setIsEditingDetails(false);
                    return;
                  }
                  patchMutation.mutate(patch, {
                    onSuccess: () => {
                      setIsEditingDetails(false);
                    },
                  });
                }}
                disabled={!editName.trim() || patchMutation.isPending}
              >
                {patchMutation.isPending ? "Saving..." : "Save"}
              </Button>
              <Button
                size="sm"
                variant="ghost"
                onClick={() => {
                  resetEditForm();
                  setIsEditingDetails(false);
                }}
                disabled={patchMutation.isPending}
              >
                Cancel
              </Button>
            </div>
          </div>
        ) : null}
      </div>

      <AppTabs defaultValue="pins" className="mt-4">
        <AppTabsList className="w-full">
          <AppTabsTrigger value="pins" className="flex-1">
            Pins
          </AppTabsTrigger>
          <AppTabsTrigger value="members" className="flex-1">
            Members
          </AppTabsTrigger>
          <AppTabsTrigger value="invites" className="flex-1">
            Invites
          </AppTabsTrigger>
        </AppTabsList>

        <AppTabsContent value="pins" className="mt-2 space-y-2">
          {(pinsQuery.data?.items ?? []).map((pin) => (
            <div key={pin.id} className="rounded-md border border-slate-200 p-2 text-xs dark:border-slate-800">
              <p>#{pin.seq_id}</p>
              <p className="truncate">{pin.content_text ?? "JSON message"}</p>
            </div>
          ))}
        </AppTabsContent>

        <AppTabsContent value="members" className="mt-2 space-y-2">
          {(membersQuery.data?.items ?? []).map((member) => (
            <div key={member.user_id} className="rounded-md border border-slate-200 p-2 text-xs dark:border-slate-800">
              <p className="font-medium">
                {member.username} ({member.role})
              </p>
              {channel.my_role === "owner" || (channel.my_role === "admin" && member.role === "member") ? (
                <div className="mt-1 flex gap-1">
                  {(channel.my_role === "owner" || member.role === "member") && (
                    <Button size="sm" variant="ghost" onClick={() => promoteMutation.mutate(member)}>
                      {member.role === "admin" ? "Demote" : "Promote"}
                    </Button>
                  )}
                  <Button size="sm" variant="ghost" onClick={() => removeMutation.mutate(member.user_id)}>
                    Remove
                  </Button>
                </div>
              ) : null}
            </div>
          ))}

          {channel.permissions.can_approve ? (
            <div className="space-y-1">
              <p className="text-xs font-medium">Pending requests</p>
              {(requestsQuery.data?.items ?? []).map((req) => (
                <div key={req.user_id} className="flex items-center justify-between rounded-md border border-slate-200 p-2 text-xs dark:border-slate-800">
                  <span>{req.username}</span>
                  <Button size="sm" onClick={() => approveMutation.mutate(req.user_id)}>
                    Approve
                  </Button>
                </div>
              ))}
            </div>
          ) : null}
        </AppTabsContent>

        <AppTabsContent value="invites" className="mt-2 space-y-2">
          {channel.permissions.can_invite ? (
            <div className="space-y-2">
              <Button size="sm" onClick={() => createInvite.mutate()} disabled={createInvite.isPending}>
                {createInvite.isPending ? "Creating..." : "Create invite link"}
              </Button>
              {latestInviteLink ? (
                <div className="rounded-md border border-slate-200 p-2 text-xs dark:border-slate-800">
                  <p className="mb-1 text-slate-500">Latest invite link</p>
                  <Input readOnly value={latestInviteLink} />
                  <div className="mt-2 flex gap-2">
                    <Button
                      size="sm"
                      variant="secondary"
                      onClick={async () => {
                        try {
                          await navigator.clipboard.writeText(latestInviteLink);
                          toast.success("Invite link copied");
                        } catch {
                          toast.error("Could not copy link");
                        }
                      }}
                    >
                      Copy link
                    </Button>
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() => window.open(latestInviteLink, "_blank", "noopener,noreferrer")}
                    >
                      Open link
                    </Button>
                  </div>
                </div>
              ) : null}
            </div>
          ) : null}
          {(invitesQuery.data?.items ?? []).map((invite: InviteListItem) => (
            <div key={invite.id} className="rounded-md border border-slate-200 p-2 text-xs dark:border-slate-800">
              <p>{invite.masked_token}</p>
              <p className="text-slate-500">expires: {formatDateTime(invite.expires_at)}</p>
              {channel.permissions.can_invite ? (
                <Button size="sm" variant="ghost" onClick={() => revokeInvite.mutate(invite.id)}>
                  Revoke
                </Button>
              ) : null}
            </div>
          ))}
        </AppTabsContent>
      </AppTabs>
    </Card>
  );
}

export function ChannelChat({ channelId }: { channelId: string }) {
  const queryClient = useQueryClient();
  const listRef = useRef<HTMLDivElement | null>(null);
  const visibilityObserverRef = useRef<IntersectionObserver | null>(null);
  const latestMessageItemsRef = useRef<MessageResponse[]>([]);
  const initialScrollDoneRef = useRef(false);
  const renderedSeenSeqRef = useRef<number>(0);
  const sentSeenSeqRef = useRef<number>(0);
  const queuedSeenSeqRef = useRef<number>(0);
  const lastRenderedSeqRef = useRef<number | null>(null);
  const setCurrentChannel = useAppUiStore((s) => s.setCurrentChannel);
  const setReplyTarget = useAppUiStore((s) => s.setReplyTarget);
  const { width: detailsWidth, isCollapsed: isDetailsCollapsed, beginResize, open: openDetails, close: closeDetails } = useResizablePanel({
    initialWidth: 320,
    minWidth: 320,
    maxWidth: 560,
    minRemainingWidth: 460,
    collapseThreshold: 220,
    storageKey: "layout:channel-details-width",
  });

  const channelQuery = useQuery({
    queryKey: queryKeys.channel(channelId),
    queryFn: () => api.getChannel(channelId),
  });

  const messagesQuery = useInfiniteQuery({
    queryKey: queryKeys.messages(channelId),
    queryFn: ({ pageParam }) => api.listMessages(channelId, { order: "desc", limit: 30, before_seq_id: pageParam }),
    initialPageParam: undefined as number | undefined,
    getNextPageParam: (lastPage) => lastPage.next_before_seq_id ?? undefined,
    enabled: channelQuery.isSuccess && channelQuery.data.my_role !== "none",
  });
  const channel = channelQuery.data;

  const markSeenMutation = useMutation({
    mutationFn: (seqId: number) => api.markSeen(channelId, seqId),
    onSuccess: (result, requestedSeq) => {
      sentSeenSeqRef.current = Math.max(sentSeenSeqRef.current, requestedSeq, result.last_seen_seq_id ?? 0);
      queryClient.setQueryData<ChannelResponse>(queryKeys.channel(channelId), (current) =>
        current
          ? {
              ...current,
              my_last_seen_seq_id: result.last_seen_seq_id,
              unread_count: result.unread_count ?? 0,
            }
          : current,
      );
      queryClient.setQueriesData<{ items: ChannelResponse[] }>({ queryKey: ["channels"] }, (current) => {
        if (!current) return current;
        return {
          ...current,
          items: current.items.map((channel) =>
            channel.id === channelId
              ? {
                  ...channel,
                  my_last_seen_seq_id: result.last_seen_seq_id,
                  unread_count: result.unread_count ?? 0,
                }
              : channel,
          ),
        };
      });
    },
    onSettled: () => {
      const queued = queuedSeenSeqRef.current;
      if (queued > sentSeenSeqRef.current) {
        queuedSeenSeqRef.current = 0;
        markSeenMutation.mutate(queued);
      }
    },
  });

  const markSeenForRenderedSeq = useCallback(
    (seqId: number) => {
      renderedSeenSeqRef.current = Math.max(renderedSeenSeqRef.current, seqId);
      const targetSeq = renderedSeenSeqRef.current;
      if (targetSeq <= sentSeenSeqRef.current) return;
      if (markSeenMutation.isPending) {
        queuedSeenSeqRef.current = Math.max(queuedSeenSeqRef.current, targetSeq);
        return;
      }
      markSeenMutation.mutate(targetSeq);
    },
    [markSeenMutation],
  );

  const markSeenForFullyVisibleMessages = useCallback(() => {
    const listElement = listRef.current;
    if (!listElement) return;

    const containerRect = listElement.getBoundingClientRect();
    const fullyVisibleSeqIds = latestMessageItemsRef.current
      .filter((message) => {
        const element = listElement.querySelector<HTMLElement>(`[data-seq-id="${message.seq_id}"]`);
        if (!element) return false;
        const rect = element.getBoundingClientRect();
        return rect.top >= containerRect.top && rect.bottom <= containerRect.bottom;
      })
      .map((message) => message.seq_id);

    if (!fullyVisibleSeqIds.length) return;
    markSeenForRenderedSeq(Math.max(...fullyVisibleSeqIds));
  }, [markSeenForRenderedSeq]);

  useEffect(() => {
    setCurrentChannel(channelId);
    return () => {
      setCurrentChannel(null);
      setReplyTarget(null);
    };
  }, [channelId, setCurrentChannel, setReplyTarget]);

  const messageItems = useMemo(() => {
    const pages = messagesQuery.data?.pages ?? [];
    const merged = pages.flatMap((page) => page.items);
    return [...merged].sort((a, b) => a.seq_id - b.seq_id);
  }, [messagesQuery.data]);

  useEffect(() => {
    latestMessageItemsRef.current = messageItems;
  }, [messageItems]);

  useEffect(() => {
    sentSeenSeqRef.current = 0;
    renderedSeenSeqRef.current = 0;
    queuedSeenSeqRef.current = 0;
    initialScrollDoneRef.current = false;
    lastRenderedSeqRef.current = null;
  }, [channelId]);

  useEffect(() => {
    const serverSeen = channelQuery.data?.my_last_seen_seq_id ?? 0;
    sentSeenSeqRef.current = Math.max(sentSeenSeqRef.current, serverSeen);
    renderedSeenSeqRef.current = Math.max(renderedSeenSeqRef.current, serverSeen);
  }, [channelId, channelQuery.data?.my_last_seen_seq_id]);

  useEffect(() => {
    const lastSeq = messageItems.length ? messageItems[messageItems.length - 1].seq_id : null;
    const prevSeq = lastRenderedSeqRef.current;

    if (lastSeq !== null && prevSeq !== null && lastSeq > prevSeq && listRef.current) {
      listRef.current.scrollTo({ top: listRef.current.scrollHeight, behavior: "smooth" });
    }

    lastRenderedSeqRef.current = lastSeq;
  }, [messageItems]);

  useEffect(() => {
    const listElement = listRef.current;
    if (!listElement || channel?.my_role === "none") return;

    if (visibilityObserverRef.current) {
      visibilityObserverRef.current.disconnect();
    }

    visibilityObserverRef.current = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting && entry.intersectionRatio >= 1)) {
          markSeenForFullyVisibleMessages();
        }
      },
      {
        root: listElement,
        threshold: [1],
      },
    );

    listElement.querySelectorAll<HTMLElement>("[data-seq-id]").forEach((element) => {
      visibilityObserverRef.current?.observe(element);
    });

    markSeenForFullyVisibleMessages();

    return () => {
      visibilityObserverRef.current?.disconnect();
      visibilityObserverRef.current = null;
    };
  }, [channel?.my_role, messageItems, markSeenForFullyVisibleMessages]);

  useEffect(() => {
    if (initialScrollDoneRef.current) return;
    const listElement = listRef.current;
    if (!listElement || !messageItems.length || channel?.my_role === "none") return;

    const firstUnreadSeq =
      messageItems.find((message) => message.seq_id > (channel?.my_last_seen_seq_id ?? 0))?.seq_id ?? null;

    if (firstUnreadSeq !== null) {
      const unreadElement = listElement.querySelector<HTMLElement>(`[data-seq-id="${firstUnreadSeq}"]`);
      unreadElement?.scrollIntoView({ block: "start", behavior: "auto" });
    } else {
      listElement.scrollTo({ top: listElement.scrollHeight, behavior: "auto" });
    }

    initialScrollDoneRef.current = true;
  }, [channel?.my_last_seen_seq_id, channel?.my_role, messageItems]);

  if (channelQuery.isLoading) {
    return <div className="p-6">Loading channel...</div>;
  }

  if (channelQuery.error || !channelQuery.data) {
    return <div className="p-6">Failed to load channel</div>;
  }

  const resolvedChannel = channelQuery.data;

  return (
    <div
      className="grid h-full overflow-hidden"
      style={{
        gridTemplateColumns: `minmax(0, 1fr) ${isDetailsCollapsed ? 0 : 8}px ${isDetailsCollapsed ? 0 : Math.max(320, detailsWidth)}px`,
      }}
    >
      <section className="flex min-h-0 flex-col">
        <header className="border-b border-slate-200 bg-white/80 px-4 py-3 dark:border-slate-800 dark:bg-slate-950/80">
          <div className="flex items-start justify-between gap-3">
            <div>
              <h2 className="text-lg font-semibold">{resolvedChannel.name}</h2>
              <p className="text-xs text-slate-500">
                {resolvedChannel.member_count} members • {resolvedChannel.pending_count} pending • {resolvedChannel.unread_count} unread
              </p>
            </div>
            <Button
              size="sm"
              variant="ghost"
              onClick={isDetailsCollapsed ? openDetails : closeDetails}
              aria-label={isDetailsCollapsed ? "Show channel details sidebar" : "Hide channel details sidebar"}
            >
              {isDetailsCollapsed ? <PanelRightOpen className="size-4" /> : <PanelRightClose className="size-4" />}
            </Button>
          </div>
        </header>

        {resolvedChannel.my_role === "none" ? (
          <div className="p-4">
            <EmptyState title="You are not a member" description="Join from the details panel to start messaging." />
          </div>
        ) : (
          <>
            <div ref={listRef} className="flex-1 space-y-2 overflow-auto bg-slate-50 p-3 dark:bg-slate-950">
              {messagesQuery.hasNextPage ? (
                <div className="flex justify-center">
                  <Button size="sm" variant="secondary" onClick={() => messagesQuery.fetchNextPage()} disabled={messagesQuery.isFetchingNextPage}>
                    {messagesQuery.isFetchingNextPage ? "Loading..." : "Load older"}
                  </Button>
                </div>
              ) : null}

              {messageItems.map((message) => (
                <MessageRow
                  key={message.id}
                  message={message}
                  channel={resolvedChannel}
                  onReply={(target) => setReplyTarget({ messageId: target.id, seqId: target.seq_id })}
                />
              ))}

              <div className="h-4" />
            </div>

            <Composer channel={resolvedChannel} />
          </>
        )}
      </section>

      {!isDetailsCollapsed ? (
        <div
          role="separator"
          aria-orientation="vertical"
          aria-label="Resize channel details sidebar"
          className="group relative cursor-col-resize"
          onMouseDown={(event) => beginResize(event, "growOppositePointer")}
        >
          <div className="absolute inset-y-0 left-1/2 w-px -translate-x-1/2 bg-slate-200 transition-colors group-hover:bg-slate-400 dark:bg-slate-800 dark:group-hover:bg-slate-500" />
        </div>
      ) : (
        <div />
      )}

      <ChannelDetailsPanel channelId={channelId} channel={resolvedChannel} />
    </div>
  );
}
