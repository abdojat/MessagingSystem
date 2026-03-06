"use client";

import Link from "next/link";
import Image from "next/image";
import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, Search, Settings } from "lucide-react";
import { toast } from "sonner";
import { api, ApiError } from "@/lib/api-client";
import { queryKeys } from "@/lib/query-keys";
import { formatRelative } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { AppDialog } from "@/components/ui/dialog";
import { AppTabs, AppTabsContent, AppTabsList, AppTabsTrigger } from "@/components/ui/tabs";
import type { ChannelResponse } from "@/types/api";

function ChannelCreateDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  const queryClient = useQueryClient();
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [visibility, setVisibility] = useState<"public" | "private">("public");
  const [joinMode, setJoinMode] = useState<"open" | "invite_only" | "approval_required">("open");

  const createMutation = useMutation({
    mutationFn: () =>
      api.createChannel({
        name,
        description,
        visibility,
        join_mode: joinMode,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["channels"] });
      toast.success("Channel created");
      onOpenChange(false);
      setName("");
      setDescription("");
      setVisibility("public");
      setJoinMode("open");
    },
    onError: (error) => {
      toast.error(error instanceof ApiError ? error.message : "Failed to create channel");
    },
  });

  return (
    <AppDialog open={open} onOpenChange={onOpenChange} title="Create channel">
      <div className="space-y-3">
        <Input placeholder="Channel name" value={name} onChange={(event) => setName(event.target.value)} />
        <Input placeholder="Description" value={description} onChange={(event) => setDescription(event.target.value)} />
        <div className="grid grid-cols-2 gap-2 text-sm">
          <label className="space-y-1">
            <span className="text-slate-500">Visibility</span>
            <select className="h-9 w-full rounded-md border border-slate-300 px-2 dark:border-slate-700 dark:bg-slate-900" value={visibility} onChange={(event) => setVisibility(event.target.value as "public" | "private")}>
              <option value="public">Public</option>
              <option value="private">Private</option>
            </select>
          </label>
          <label className="space-y-1">
            <span className="text-slate-500">Join mode</span>
            <select
              className="h-9 w-full rounded-md border border-slate-300 px-2 dark:border-slate-700 dark:bg-slate-900"
              value={joinMode}
              onChange={(event) => setJoinMode(event.target.value as "open" | "invite_only" | "approval_required")}
            >
              <option value="open">Open</option>
              <option value="invite_only">Invite only</option>
              <option value="approval_required">Approval required</option>
            </select>
          </label>
        </div>
        <Button disabled={!name.trim() || createMutation.isPending} onClick={() => createMutation.mutate()}>
          {createMutation.isPending ? "Creating..." : "Create"}
        </Button>
      </div>
    </AppDialog>
  );
}

function ChannelList({ channels, selectedId }: { channels: ChannelResponse[]; selectedId?: string }) {
  return (
    <div className="space-y-1">
      {channels.map((channel) => (
        <Link
          key={channel.id}
          href={`/app/channels/${channel.id}`}
          className={`block rounded-lg px-3 py-2 transition hover:bg-slate-200/70 dark:hover:bg-slate-800/80 ${selectedId === channel.id ? "bg-slate-200 dark:bg-slate-800" : ""}`}
        >
          <div className="flex items-center justify-between gap-2">
            <p className="truncate text-sm font-medium">{channel.name}</p>
            {channel.unread_count > 0 ? <span className="rounded-full bg-slate-900 px-2 py-0.5 text-xs text-white dark:bg-slate-100 dark:text-slate-900">{channel.unread_count}</span> : null}
          </div>
          <p className="truncate text-xs text-slate-500">{channel.last_message?.content_text ?? "No messages yet"}</p>
          <p className="mt-1 text-[11px] text-slate-400">{channel.last_message_at ? formatRelative(channel.last_message_at) : ""}</p>
        </Link>
      ))}
      {channels.length === 0 ? <p className="px-3 py-6 text-sm text-slate-500">No channels found.</p> : null}
    </div>
  );
}

function ChannelAvatar({ channel }: { channel: ChannelResponse }) {
  const initials = channel.name
    .split(" ")
    .map((part) => part.trim()[0])
    .filter(Boolean)
    .slice(0, 2)
    .join("")
    .toUpperCase();

  if (channel.avatar_url) {
    return <Image src={channel.avatar_url} alt={channel.name} width={36} height={36} className="size-9 rounded-full object-cover" />;
  }

  return (
    <div className="flex size-9 items-center justify-center rounded-full bg-slate-300 text-xs font-semibold text-slate-700 dark:bg-slate-700 dark:text-slate-200">
      {initials || "#"}
    </div>
  );
}

function ChannelAvatarRail({ channels, selectedId }: { channels: ChannelResponse[]; selectedId?: string }) {
  return (
    <div className="flex flex-col items-center gap-2">
      {channels.map((channel) => (
        <Link
          key={channel.id}
          href={`/app/channels/${channel.id}`}
          title={channel.name}
          className={`rounded-xl p-1 transition hover:bg-slate-200/70 dark:hover:bg-slate-800/80 ${selectedId === channel.id ? "bg-slate-200 dark:bg-slate-800" : ""}`}
        >
          <ChannelAvatar channel={channel} />
        </Link>
      ))}
      {channels.length === 0 ? <p className="px-1 text-center text-xs text-slate-500">No channels</p> : null}
    </div>
  );
}

export function Sidebar({ selectedChannelId, isCollapsed = false }: { selectedChannelId?: string; isCollapsed?: boolean }) {
  const [dialogOpen, setDialogOpen] = useState(false);
  const [search, setSearch] = useState("");
  const searchQuery = search.trim() || undefined;

  const myChannelsQuery = useQuery({
    queryKey: queryKeys.channels(`sidebar:my:${searchQuery ?? ""}`),
    queryFn: () => api.listChannels({ scope: "my", q: searchQuery }),
  });

  const discoverChannelsQuery = useQuery({
    queryKey: queryKeys.channels(`sidebar:discover:${searchQuery ?? ""}`),
    queryFn: () => api.listChannels({ scope: "discover", q: searchQuery }),
    enabled: !isCollapsed,
  });

  const myChannels = useMemo(() => myChannelsQuery.data?.items ?? [], [myChannelsQuery.data?.items]);
  const discoverChannels = useMemo(() => discoverChannelsQuery.data?.items ?? [], [discoverChannelsQuery.data?.items]);

  return (
    <aside className="h-full border-r border-slate-200 bg-white/70 backdrop-blur dark:border-slate-800 dark:bg-slate-950/70">
      <div className={isCollapsed ? "p-2" : "space-y-3 p-3"}>
        {isCollapsed ? (
          <ChannelAvatarRail channels={myChannels} selectedId={selectedChannelId} />
        ) : (
          <>
            <div className="flex items-center justify-between">
              <h1 className="text-lg font-semibold">Channels</h1>
              <div className="flex gap-1">
                <Button size="sm" variant="ghost" onClick={() => setDialogOpen(true)}>
                  <Plus className="size-4" />
                </Button>
                <Link href="/settings/sessions">
                  <Button size="sm" variant="ghost">
                    <Settings className="size-4" />
                  </Button>
                </Link>
              </div>
            </div>

            <div className="relative">
              <Search className="pointer-events-none absolute left-2 top-2.5 size-4 text-slate-400" />
              <Input className="pl-8" placeholder="Search channels..." value={search} onChange={(event) => setSearch(event.target.value)} />
            </div>

            <AppTabs defaultValue="mine">
              <AppTabsList className="w-full">
                <AppTabsTrigger value="mine" className="flex-1">
                  My channels
                </AppTabsTrigger>
                <AppTabsTrigger value="discover" className="flex-1">
                  Discover
                </AppTabsTrigger>
              </AppTabsList>
              <AppTabsContent value="mine" className="mt-2">
                <ChannelList channels={myChannels} selectedId={selectedChannelId} />
              </AppTabsContent>
              <AppTabsContent value="discover" className="mt-2">
                <ChannelList channels={discoverChannels} selectedId={selectedChannelId} />
              </AppTabsContent>
            </AppTabs>
          </>
        )}
      </div>

      <ChannelCreateDialog open={dialogOpen} onOpenChange={setDialogOpen} />
    </aside>
  );
}


