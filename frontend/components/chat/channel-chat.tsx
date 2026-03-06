"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { PanelRightClose, PanelRightOpen, Pin, Reply, Send, SmilePlus, Trash2 } from "lucide-react";
import Image from "next/image";
import { toast } from "sonner";
import { api, ApiError } from "@/lib/api-client";
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
  onSeenAnchor,
}: {
  message: MessageResponse;
  channel: ChannelResponse;
  onReply: (message: MessageResponse) => void;
  onSeenAnchor: (seqId: number) => void;
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
        <button className="hover:underline" onMouseEnter={() => onSeenAnchor(message.seq_id)}>
          {formatDateTime(message.created_at)}
        </button>
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
                const publicUrl = String(attachment.public_url ?? attachment.url ?? "");
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
        const create = await api.createUpload({ filename: file.name, content_type: file.type || "application/octet-stream", size_bytes: file.size });

        const uploadResponse = await fetch(create.upload_url, {
          method: create.method,
          headers: create.headers,
          body: file,
        });

        let publicUrl = create.public_url;

        if (!uploadResponse.ok) {
          const completion = await api.completeUpload(create.file_id, file);
          publicUrl = completion.public_url;
        }

        attachments.push({
          file_id: create.file_id,
          filename: file.name,
          content_type: file.type || "application/octet-stream",
          public_url: publicUrl,
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
  const [inviteToken, setInviteToken] = useState("");

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

  const createInvite = useMutation({
    mutationFn: () => api.createInvite(channelId, { is_generic: true, expires_in_hours: 72 }),
    onSuccess: (result) => {
      toast.success(`Invite token: ${result.token}`);
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
    mutationFn: (patch: Partial<Pick<ChannelResponse, "name" | "description" | "visibility" | "join_mode">>) => api.patchChannel(channelId, patch),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["channels"] });
      queryClient.invalidateQueries({ queryKey: queryKeys.channel(channelId) });
    },
    onError: (error) => toast.error(error instanceof ApiError ? error.message : "Update failed"),
  });

  return (
    <Card className="h-full overflow-auto p-3">
      <div className="space-y-2">
        <h3 className="font-semibold">Details</h3>
        <p className="text-sm text-slate-600 dark:text-slate-300">{channel.description || "No description"}</p>
        <p className="text-xs text-slate-500">
          {channel.visibility} / {channel.join_mode}
        </p>
        <p className="text-xs text-slate-500">My role: {channel.my_role}</p>

        {channel.my_role === "none" ? (
          <div className="space-y-2 rounded-lg border border-slate-200 p-2 dark:border-slate-800">
            {channel.join_mode === "invite_only" ? <Input placeholder="Invite token" value={inviteToken} onChange={(event) => setInviteToken(event.target.value)} /> : null}
            <Button size="sm" onClick={() => joinMutation.mutate()}>
              Join channel
            </Button>
          </div>
        ) : null}

        {channel.permissions.can_edit_channel ? (
          <div className="space-y-2 rounded-lg border border-slate-200 p-2 dark:border-slate-800">
            <h4 className="text-sm font-medium">Quick edit</h4>
            <Input defaultValue={channel.name} onBlur={(event) => event.target.value !== channel.name && patchMutation.mutate({ name: event.target.value })} />
            <Input
              defaultValue={channel.description ?? ""}
              onBlur={(event) => event.target.value !== (channel.description ?? "") && patchMutation.mutate({ description: event.target.value })}
            />
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
            <Button size="sm" onClick={() => createInvite.mutate()}>
              Create generic invite
            </Button>
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
  const seenAnchorRef = useRef<number>(0);
  const setCurrentChannel = useAppUiStore((s) => s.setCurrentChannel);
  const setReplyTarget = useAppUiStore((s) => s.setReplyTarget);
  const { width: detailsWidth, isCollapsed: isDetailsCollapsed, beginResize, open: openDetails, close: closeDetails } = useResizablePanel({
    initialWidth: 320,
    minWidth: 0,
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

  const markSeenMutation = useMutation({
    mutationFn: (seqId: number) => api.markSeen(channelId, seqId),
    onSuccess: (result) => {
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
  });

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

  if (channelQuery.isLoading) {
    return <div className="p-6">Loading channel...</div>;
  }

  if (channelQuery.error || !channelQuery.data) {
    return <div className="p-6">Failed to load channel</div>;
  }

  const channel = channelQuery.data;

  return (
    <div className="grid h-full overflow-hidden" style={{ gridTemplateColumns: `minmax(0, 1fr) ${isDetailsCollapsed ? 0 : 8}px ${detailsWidth}px` }}>
      <section className="flex min-h-0 flex-col">
        <header className="border-b border-slate-200 bg-white/80 px-4 py-3 dark:border-slate-800 dark:bg-slate-950/80">
          <div className="flex items-start justify-between gap-3">
            <div>
              <h2 className="text-lg font-semibold">{channel.name}</h2>
              <p className="text-xs text-slate-500">
                {channel.member_count} members • {channel.pending_count} pending • {channel.unread_count} unread
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

        {channel.my_role === "none" ? (
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
                  channel={channel}
                  onReply={(target) => setReplyTarget({ messageId: target.id, seqId: target.seq_id })}
                  onSeenAnchor={(seqId) => {
                    seenAnchorRef.current = Math.max(seenAnchorRef.current, seqId);
                  }}
                />
              ))}

              <div className="h-4" />
            </div>

            <div className="px-3 pb-2 text-right">
              <Button
                size="sm"
                variant="ghost"
                onClick={() => {
                  if (seenAnchorRef.current > 0) {
                    markSeenMutation.mutate(seenAnchorRef.current);
                  }
                }}
              >
                Mark seen
              </Button>
            </div>

            <Composer channel={channel} />
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

      <ChannelDetailsPanel channelId={channelId} channel={channel} />
    </div>
  );
}
