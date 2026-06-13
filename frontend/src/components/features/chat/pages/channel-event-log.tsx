"use client";

import { useParams, useRouter } from "next/navigation";
import { useEffect } from "react";
import { format } from "date-fns";
import { ArrowLeft, Hash, RefreshCw, Shield } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useChannel } from "@/hooks/use-channels";
import { useChannelEventIntegrity, useChannelEvents } from "@/hooks/use-events";
import { useAuthStore } from "@/store/authStore";
import { useLocalePath } from "@/components/features/chat/lib/locale-path";
import type { EventIntegrityResponse } from "@/types/api";

const EVENT_LIMIT = 100;

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

function formatPayload(payload?: Record<string, unknown> | null) {
  return JSON.stringify(payload ?? {}, null, 2);
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
            <Skeleton className="h-10 w-32 rounded-xl" />
            <Skeleton className="h-10 w-28 rounded-xl" />
          </div>
        </div>
        <Card className="rounded-3xl p-6">
          <Skeleton className="h-20 w-full rounded-2xl" />
          <div className="mt-6 space-y-2">
            <Skeleton className="h-10 w-full rounded-lg" />
            <Skeleton className="h-10 w-full rounded-lg" />
            <Skeleton className="h-10 w-full rounded-lg" />
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
  const { data: channel, isLoading, isError, refetch } = useChannel(channelId || "");
  const canManageMembers = channel?.permissions.can_manage_members ?? false;
  const eventsQuery = useChannelEvents(channel?.id || "", EVENT_LIMIT, canManageMembers);
  const integrityQuery = useChannelEventIntegrity(channel?.id || "", false);
  const integrityStatus = getIntegrityStatus(integrityQuery.data, integrityQuery.isFetching, integrityQuery.isError);
  const detailsPath = channelId ? localePath(`/app/channels/${channelId}/details`) : localePath("/app");

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
          <Card className="mt-6 rounded-3xl p-8 text-center">
            <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-2xl bg-muted text-muted-foreground">
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

        <Card className="overflow-hidden rounded-3xl border-border/60">
          <div className="border-b border-border/60 bg-gradient-to-r from-primary/15 via-primary/5 to-transparent p-6">
            <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
              <div className="flex min-w-0 items-center gap-4">
                <div className="flex h-14 w-14 flex-shrink-0 items-center justify-center rounded-2xl bg-primary/10 text-primary">
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
              <div className="grid gap-3 rounded-xl border border-border/70 bg-muted/30 p-4 text-sm sm:grid-cols-2 lg:grid-cols-4">
                <div>
                  <p className="text-xs uppercase text-muted-foreground">Status</p>
                  <p className="mt-1 font-medium">{integrityStatus.label}</p>
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
                  <p className="mt-1 break-all font-mono text-xs">{integrityQuery.data.scope}</p>
                </div>
                {!integrityQuery.data.valid ? (
                  <div className="rounded-lg border border-destructive/30 bg-destructive/10 p-3 text-sm text-destructive sm:col-span-2 lg:col-span-4">
                    <span className="font-medium">{integrityQuery.data.reason || "integrity check failed"}</span>
                    {integrityQuery.data.broken_event_id ? (
                      <span className="ml-2 break-all font-mono text-xs">{integrityQuery.data.broken_event_id}</span>
                    ) : null}
                  </div>
                ) : null}
              </div>
            ) : null}
            {integrityQuery.isError ? (
              <p className="mt-3 text-sm text-destructive">Could not verify audit integrity. Please try again.</p>
            ) : null}

            {eventsQuery.isLoading ? (
              <div className="mt-4 space-y-2">
                <Skeleton className="h-10 w-full rounded-lg" />
                <Skeleton className="h-10 w-full rounded-lg" />
                <Skeleton className="h-10 w-full rounded-lg" />
              </div>
            ) : eventsQuery.isError ? (
              <p className="mt-4 text-sm text-destructive">Could not load event log. Please try again.</p>
            ) : (eventsQuery.data?.items?.length ?? 0) === 0 ? (
              <p className="mt-4 text-sm text-muted-foreground">No events recorded yet for this channel.</p>
            ) : (
              <div className="mt-4 overflow-x-auto">
                <Table className="min-w-[920px]">
                  <TableHeader>
                    <TableRow>
                      <TableHead>Time</TableHead>
                      <TableHead>Type</TableHead>
                      <TableHead>Actor</TableHead>
                      <TableHead>Channel</TableHead>
                      <TableHead>Details</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {eventsQuery.data?.items.map((item) => (
                      <TableRow key={item.id}>
                        <TableCell className="min-w-44">{formatDateTime(item.created_at)}</TableCell>
                        <TableCell className="min-w-44 font-medium">{item.event_type}</TableCell>
                        <TableCell className="min-w-44 font-mono text-xs">{item.actor_user_id || "-"}</TableCell>
                        <TableCell className="min-w-44 font-mono text-xs">{item.channel_id || "-"}</TableCell>
                        <TableCell className="max-w-[360px]">
                          <pre className="whitespace-pre-wrap break-words text-xs text-muted-foreground">
                            {formatPayload(item.payload)}
                          </pre>
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
                {eventsQuery.data?.has_more ? (
                  <p className="mt-3 text-xs text-muted-foreground">More events are available through the API.</p>
                ) : null}
              </div>
            )}
          </div>
        </Card>
      </div>
    </div>
  );
}
