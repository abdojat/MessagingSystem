"use client";

import { useState } from "react";
import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";
import { Activity, Ban, Hash, MessagesSquare, RefreshCw, ShieldCheck, Users } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button, buttonVariants } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useAuthStore } from "@/store/authStore";
import {
  useAdminChannels,
  useAdminEvents,
  useAdminOverview,
  useAdminUsers,
  useRevokeAdminUserSessions,
  useSetAdminChannelState,
  useSetAdminUserStatus,
} from "@/hooks/use-superadmin";
import { toast } from "@/hooks/use-toast";
import { useLocalePath } from "@/components/features/chat/lib/locale-path";

const PAGE_SIZE = 100;

function errorMessage(error: unknown, fallback: string) {
  return error instanceof Error && error.message ? error.message : fallback;
}

function DateCell({ value }: { value: string }) {
  const locale = useLocale();
  return <>{new Intl.DateTimeFormat(locale, { dateStyle: "medium", timeStyle: "short" }).format(new Date(value))}</>;
}

export default function SuperadminPage() {
  const t = useTranslations("superadmin");
  const user = useAuthStore((state) => state.user);
  const [userSearch, setUserSearch] = useState("");
  const [channelSearch, setChannelSearch] = useState("");
  const [eventType, setEventType] = useState("");
  const [userOffset, setUserOffset] = useState(0);
  const [channelOffset, setChannelOffset] = useState(0);
  const [eventOffset, setEventOffset] = useState(0);
  const localePath = useLocalePath();
  const enabled = Boolean(user?.is_superadmin);
  const overview = useAdminOverview(enabled);
  const users = useAdminUsers(userSearch.trim(), userOffset, enabled);
  const channels = useAdminChannels(channelSearch.trim(), channelOffset, enabled);
  const events = useAdminEvents(eventType.trim(), eventOffset, enabled);
  const setUserStatus = useSetAdminUserStatus();
  const revokeSessions = useRevokeAdminUserSessions();
  const setChannelState = useSetAdminChannelState();

  if (!user?.is_superadmin) {
    return <div className="p-8 text-sm text-muted-foreground">{t("forbidden")}</div>;
  }

  const stats = overview.data
    ? [
        [t("stats.users"), overview.data.total_users, Users],
        [t("stats.activeUsers"), overview.data.active_users, ShieldCheck],
        [t("stats.channels"), overview.data.active_channels, Hash],
        [t("stats.messages"), overview.data.total_messages, MessagesSquare],
        [t("stats.events"), overview.data.total_events, Activity],
        [t("stats.deliveryFailures"), overview.data.delivery_failures, Ban],
      ] as const
    : [];

  function notifyFailure(error: unknown) {
    toast({ title: t("actions.failed"), description: errorMessage(error, t("actions.tryAgain")), variant: "destructive" });
  }

  return (
    <div className="h-full min-h-0 overflow-y-auto bg-background p-6 sm:p-8">
      <div className="mx-auto max-w-7xl space-y-6">
        <div className="flex items-start justify-between gap-4">
          <div>
            <div className="mb-2 flex items-center gap-2 text-primary"><ShieldCheck className="h-5 w-5" /><span className="text-sm font-semibold">{t("eyebrow")}</span></div>
            <h1 className="text-3xl font-bold tracking-tight">{t("title")}</h1>
            <p className="mt-1 text-sm text-muted-foreground">{t("description")}</p>
          </div>
          <div className="flex gap-2">
            <Link className={buttonVariants({ variant: "outline" })} href={localePath("/app/delivery")}>{t("actions.delivery")}</Link>
            <Button variant="outline" onClick={() => { overview.refetch(); users.refetch(); channels.refetch(); events.refetch(); }}>
              <RefreshCw className="mr-2 h-4 w-4" />{t("actions.refresh")}
            </Button>
          </div>
        </div>

        {overview.isLoading ? <Skeleton className="h-28 w-full" /> : (
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6">
            {stats.map(([label, value, Icon]) => (
              <Card key={label} className="p-4"><Icon className="h-5 w-5 text-muted-foreground" /><div className="mt-3 text-2xl font-semibold">{value}</div><div className="text-xs text-muted-foreground">{label}</div></Card>
            ))}
          </div>
        )}

        <Tabs defaultValue="events" className="space-y-4">
          <TabsList><TabsTrigger value="events">{t("tabs.events")}</TabsTrigger><TabsTrigger value="users">{t("tabs.users")}</TabsTrigger><TabsTrigger value="channels">{t("tabs.channels")}</TabsTrigger></TabsList>

          <TabsContent value="events" className="space-y-3">
            <Input value={eventType} onChange={(event) => { setEventType(event.target.value); setEventOffset(0); }} placeholder={t("events.filterPlaceholder")} className="max-w-md" />
            <Card className="overflow-hidden"><div className="border-b p-4 text-sm font-medium">{t("events.total", { count: events.data?.total ?? 0 })}</div>
              <div className="overflow-x-auto"><Table><TableHeader><TableRow><TableHead>{t("events.type")}</TableHead><TableHead>{t("events.actor")}</TableHead><TableHead>{t("events.channel")}</TableHead><TableHead>{t("events.time")}</TableHead><TableHead>{t("events.details")}</TableHead></TableRow></TableHeader>
                <TableBody>{(events.data?.items ?? []).map((event) => <TableRow key={event.id}><TableCell><Badge variant="outline">{event.event_type}</Badge></TableCell><TableCell>{event.actor_username ?? t("events.system")}</TableCell><TableCell>{event.channel_name ?? "—"}</TableCell><TableCell className="whitespace-nowrap"><DateCell value={event.created_at} /></TableCell><TableCell><pre className="max-w-md overflow-hidden text-ellipsis whitespace-nowrap text-xs text-muted-foreground">{JSON.stringify(event.payload)}</pre></TableCell></TableRow>)}</TableBody>
              </Table></div>{events.isLoading && <Skeleton className="m-4 h-24" />}<div className="flex justify-end gap-2 border-t p-3"><Button variant="outline" size="sm" disabled={eventOffset === 0} onClick={() => setEventOffset(Math.max(0, eventOffset - PAGE_SIZE))}>{t("pagination.previous")}</Button><Button variant="outline" size="sm" disabled={eventOffset + PAGE_SIZE >= (events.data?.total ?? 0)} onClick={() => setEventOffset(eventOffset + PAGE_SIZE)}>{t("pagination.next")}</Button></div></Card>
          </TabsContent>

          <TabsContent value="users" className="space-y-3">
            <Input value={userSearch} onChange={(event) => { setUserSearch(event.target.value); setUserOffset(0); }} placeholder={t("users.searchPlaceholder")} className="max-w-md" />
            <Card className="overflow-hidden"><div className="border-b p-4 text-sm font-medium">{t("users.total", { count: users.data?.total ?? 0 })}</div>
              <div className="overflow-x-auto"><Table><TableHeader><TableRow><TableHead>{t("users.user")}</TableHead><TableHead>{t("users.status")}</TableHead><TableHead>{t("users.sessions")}</TableHead><TableHead>{t("users.created")}</TableHead><TableHead className="text-right">{t("users.actions")}</TableHead></TableRow></TableHeader>
                <TableBody>{(users.data?.items ?? []).map((item) => <TableRow key={item.id}><TableCell><div className="font-medium">{item.display_name || item.username}</div><div className="text-xs text-muted-foreground">@{item.username} · {item.email || "—"}</div></TableCell><TableCell><Badge variant={item.is_active ? "default" : "destructive"}>{item.is_superadmin ? t("users.superadmin") : item.is_active ? t("users.active") : t("users.inactive")}</Badge></TableCell><TableCell>{item.active_session_count}</TableCell><TableCell className="whitespace-nowrap"><DateCell value={item.created_at} /></TableCell><TableCell><div className="flex justify-end gap-2"><Button size="sm" variant="outline" disabled={item.is_superadmin || revokeSessions.isPending} onClick={() => revokeSessions.mutate(item.id, { onError: notifyFailure })}>{t("users.revokeSessions")}</Button><Button size="sm" variant={item.is_active ? "destructive" : "default"} disabled={item.is_superadmin || setUserStatus.isPending} onClick={() => setUserStatus.mutate({ userId: item.id, isActive: !item.is_active }, { onError: notifyFailure })}>{item.is_active ? t("users.deactivate") : t("users.reactivate")}</Button></div></TableCell></TableRow>)}</TableBody>
              </Table></div>{users.isLoading && <Skeleton className="m-4 h-24" />}<div className="flex justify-end gap-2 border-t p-3"><Button variant="outline" size="sm" disabled={userOffset === 0} onClick={() => setUserOffset(Math.max(0, userOffset - PAGE_SIZE))}>{t("pagination.previous")}</Button><Button variant="outline" size="sm" disabled={userOffset + PAGE_SIZE >= (users.data?.total ?? 0)} onClick={() => setUserOffset(userOffset + PAGE_SIZE)}>{t("pagination.next")}</Button></div></Card>
          </TabsContent>

          <TabsContent value="channels" className="space-y-3">
            <Input value={channelSearch} onChange={(event) => { setChannelSearch(event.target.value); setChannelOffset(0); }} placeholder={t("channels.searchPlaceholder")} className="max-w-md" />
            <Card className="overflow-hidden"><div className="border-b p-4 text-sm font-medium">{t("channels.total", { count: channels.data?.total ?? 0 })}</div>
              <div className="overflow-x-auto"><Table><TableHeader><TableRow><TableHead>{t("channels.channel")}</TableHead><TableHead>{t("channels.owner")}</TableHead><TableHead>{t("channels.members")}</TableHead><TableHead>{t("channels.messages")}</TableHead><TableHead>{t("channels.status")}</TableHead><TableHead className="text-right">{t("channels.actions")}</TableHead></TableRow></TableHeader>
                <TableBody>{(channels.data?.items ?? []).map((channel) => <TableRow key={channel.id}><TableCell><div className="font-medium">{channel.name}</div><div className="text-xs text-muted-foreground">#{channel.channel_slug} · {channel.visibility}</div></TableCell><TableCell>@{channel.owner_username}</TableCell><TableCell>{channel.member_count}</TableCell><TableCell>{channel.message_count}</TableCell><TableCell><Badge variant={channel.deleted_at ? "destructive" : "default"}>{channel.deleted_at ? t("channels.suspended") : t("channels.active")}</Badge></TableCell><TableCell className="text-right"><Button size="sm" variant={channel.deleted_at ? "default" : "destructive"} disabled={setChannelState.isPending} onClick={() => setChannelState.mutate({ channelId: channel.id, restore: Boolean(channel.deleted_at) }, { onError: notifyFailure })}>{channel.deleted_at ? t("channels.restore") : t("channels.suspend")}</Button></TableCell></TableRow>)}</TableBody>
              </Table></div>{channels.isLoading && <Skeleton className="m-4 h-24" />}<div className="flex justify-end gap-2 border-t p-3"><Button variant="outline" size="sm" disabled={channelOffset === 0} onClick={() => setChannelOffset(Math.max(0, channelOffset - PAGE_SIZE))}>{t("pagination.previous")}</Button><Button variant="outline" size="sm" disabled={channelOffset + PAGE_SIZE >= (channels.data?.total ?? 0)} onClick={() => setChannelOffset(channelOffset + PAGE_SIZE)}>{t("pagination.next")}</Button></div></Card>
          </TabsContent>
        </Tabs>
      </div>
    </div>
  );
}
