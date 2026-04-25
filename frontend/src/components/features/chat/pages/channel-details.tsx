"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect } from "react";
import { format } from "date-fns";
import { ArrowLeft, DoorOpen, Hash, Info, Lock, Shield, UserPlus, Users } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { useChannel, useJoinChannel, useLeaveChannel } from "@/hooks/use-channels";
import { useAuthStore } from "@/store/authStore";
import { useLocalePath } from "@/components/features/chat/lib/locale-path";

function formatDateTime(value?: string | null) {
  if (!value) return "Not available";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Not available";
  return format(date, "PPP p");
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
              <Card key={index} className="rounded-2xl p-4 space-y-3">
                <Skeleton className="h-3 w-20" />
                <Skeleton className="h-8 w-16" />
              </Card>
            ))}
          </div>

          <div className="grid gap-4 border-t border-border/60 p-6 lg:grid-cols-[1.1fr_0.9fr]">
            {Array.from({ length: 2 }).map((_, index) => (
              <Card key={index} className="rounded-2xl p-5 space-y-4">
                <Skeleton className="h-6 w-40" />
                {Array.from({ length: 5 }).map((__, rowIndex) => (
                  <div key={rowIndex} className="space-y-2">
                    <Skeleton className="h-3 w-28" />
                    <Skeleton className="h-4 w-40" />
                  </div>
                ))}
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
  const { data: channel, isLoading, isError, refetch } = useChannel(channelId || "");
  const joinChannel = useJoinChannel();
  const leaveChannel = useLeaveChannel();

  useEffect(() => {
    if (!isInitializing && !isAuthenticated) {
      router.replace(localePath("/login"));
    }
  }, [isAuthenticated, isInitializing, localePath, router]);

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
          <Link href={channelId ? localePath(`/app/channels/${channelId}`) : localePath("/app")} className="text-primary text-sm font-medium hover:underline">&larr; Back</Link>
          <Card className="mt-6 rounded-3xl p-8 text-center">
            <h1 className="text-2xl font-bold">We couldn&apos;t load this channel</h1>
            <p className="mt-2 text-muted-foreground">The channel may not exist anymore, or your session needs to be refreshed.</p>
            <div className="mt-6">
              <Button onClick={() => refetch()}>Try Again</Button>
            </div>
          </Card>
        </div>
      </div>
    );
  }

  const isMember = ["owner", "admin", "member"].includes(channel.my_role || "");
  const canLeave = isMember && channel.my_role !== "owner";

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
                onClick={() => joinChannel.mutate(channel.id, { onSuccess: () => router.push(localePath(`/app/channels/${channel.id}`)) })}
                disabled={joinChannel.isPending}
              >
                <UserPlus className="mr-2 h-4 w-4" />
                {joinChannel.isPending ? "Joining..." : "Join Channel"}
              </Button>
            ) : null}
            {canLeave ? (
              <Button
                variant="outline"
                onClick={() => leaveChannel.mutate(channel.id, { onSuccess: () => router.push(localePath("/app")) })}
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
                  {channel.avatar_url ? (
                    <img src={channel.avatar_url} alt={channel.name} className="h-full w-full rounded-3xl object-cover" />
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
        </Card>
      </div>
    </div>
  );
}
