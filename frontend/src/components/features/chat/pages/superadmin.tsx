"use client";

import { useState } from "react";
import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";
import { Activity, Ban, Hash, MessagesSquare, RefreshCw, ShieldCheck, Users } from "lucide-react";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Badge } from "@/components/ui/badge";
import { Button, buttonVariants } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { AdminEventDisplay, AdminEventType } from "@/components/features/chat/components/AdminEventDisplay";
import { AdminTablePagination } from "@/components/features/chat/components/AdminTablePagination";
import { useLocalePath } from "@/components/features/chat/lib/locale-path";
import { useDebouncedValue } from "@/hooks/use-debounced-value";
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
import { useAuthStore } from "@/store/authStore";

type PendingAction =
  | { kind: "deactivate" | "reactivate" | "revokeSessions"; id: string; label: string }
  | { kind: "suspend" | "restore"; id: string; label: string };

// Implements the error message operation; the page component uses it to prepare or render the interface.
function errorMessage(error: unknown, fallback: string) {
  return error instanceof Error && error.message ? error.message : fallback;
}

// Renders the date cell component; the route adapter uses it for the matching application page.
function DateCell({ value }: { value: string }) {
  const locale = useLocale();
  return <>{new Intl.DateTimeFormat(locale, { dateStyle: "medium", timeStyle: "short" }).format(new Date(value))}</>;
}

// Renders the empty row component; the route adapter uses it for the matching application page.
function EmptyRow({ columns, children }: { columns: number; children: React.ReactNode }) {
  return <TableRow><TableCell colSpan={columns} className="h-28 text-center text-muted-foreground">{children}</TableCell></TableRow>;
}

// Renders the event channel component; the route adapter uses it for the matching application page.
function EventChannel({ name, slug, fallback, href }: { name?: string | null; slug?: string | null; fallback: string; href?: string }) {
  // Return early when `!name && !slug` because the remaining work is not applicable.
  if (!name && !slug) return <span className="text-muted-foreground">{fallback}</span>;
  const content = (
    <div className="min-w-36">
      {name ? <div className="font-medium">{name}</div> : null}
      {slug ? <div className="text-xs text-muted-foreground">#{slug}</div> : null}
    </div>
  );
  // Return early when `!href` because the remaining work is not applicable.
  if (!href) return content;
  return <Link className="block text-primary underline-offset-4 hover:underline focus-visible:underline focus-visible:outline-none" href={href}>{content}</Link>;
}

// Renders the superadmin page; the route adapter uses it for the matching application page.
export default function SuperadminPage() {
  const t = useTranslations("superadmin");
  const user = useAuthStore((state) => state.user);
  const isInitializing = useAuthStore((state) => state.isInitializing);
  const [userSearch, setUserSearch] = useState("");
  const [userStatus, setUserStatus] = useState("all");
  const [channelSearch, setChannelSearch] = useState("");
  const [channelState, setChannelStateFilter] = useState("all");
  const [channelVisibility, setChannelVisibility] = useState("all");
  const [eventSearch, setEventSearch] = useState("");
  const [eventCategory, setEventCategory] = useState("all");
  const [userOffset, setUserOffset] = useState(0);
  const [channelOffset, setChannelOffset] = useState(0);
  const [eventOffset, setEventOffset] = useState(0);
  const [userPageSize, setUserPageSize] = useState(25);
  const [channelPageSize, setChannelPageSize] = useState(25);
  const [eventPageSize, setEventPageSize] = useState(25);
  const [pendingAction, setPendingAction] = useState<PendingAction | null>(null);
  const localePath = useLocalePath();
  const debouncedUserSearch = useDebouncedValue(userSearch.trim());
  const debouncedChannelSearch = useDebouncedValue(channelSearch.trim());
  const debouncedEventSearch = useDebouncedValue(eventSearch.trim());
  const enabled = Boolean(user?.is_superadmin);
  const overview = useAdminOverview(enabled);
  const users = useAdminUsers(
    debouncedUserSearch,
    userStatus === "all" ? null : userStatus === "active",
    userOffset,
    userPageSize,
    enabled,
  );
  const channels = useAdminChannels(
    debouncedChannelSearch,
    channelState === "all" ? "" : channelState,
    channelVisibility === "all" ? "" : channelVisibility,
    channelOffset,
    channelPageSize,
    enabled,
  );
  const events = useAdminEvents(
    debouncedEventSearch,
    eventCategory === "all" ? "" : eventCategory,
    eventOffset,
    eventPageSize,
    enabled,
  );
  const setUserStatusMutation = useSetAdminUserStatus();
  const revokeSessions = useRevokeAdminUserSessions();
  const setChannelState = useSetAdminChannelState();

  // Return early when `isInitializing` because the remaining work is not applicable.
  if (isInitializing) return <div className="p-8"><Skeleton className="h-40 w-full" /></div>;
  // Return early when `!user?.is_superadmin` because the remaining work is not applicable.
  if (!user?.is_superadmin) return <div className="p-8 text-sm text-muted-foreground">{t("forbidden")}</div>;

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

  // Notifies failure; the page component uses it to prepare or render the interface.
  function notifyFailure(error: unknown) {
    toast({ title: t("actions.failed"), description: errorMessage(error, t("actions.tryAgain")), variant: "destructive" });
  }

  // Completes action; the page component uses it to prepare or render the interface.
  function completeAction() {
    toast({ title: t("actions.completed") });
  }

  // Implements the confirm pending action operation; the page component uses it to prepare or render the interface.
  function confirmPendingAction() {
    // Return early when `!pendingAction` because the remaining work is not applicable.
    if (!pendingAction) return;
    const action = pendingAction;
    setPendingAction(null);
    const options = { onSuccess: completeAction, onError: notifyFailure };
    // Choose the appropriate path based on whether `action.kind === "deactivate" || action.kind === "reactivate"` is true.
    if (action.kind === "deactivate" || action.kind === "reactivate") {
      setUserStatusMutation.mutate({ userId: action.id, isActive: action.kind === "reactivate" }, options);
    // Otherwise, run the session-revocation mutation for that admin action.
    } else if (action.kind === "revokeSessions") {
      revokeSessions.mutate(action.id, options);
    // Handle the fallback path when the preceding condition is false.
    } else {
      setChannelState.mutate({ channelId: action.id, restore: action.kind === "restore" }, options);
    }
  }

  const anyActionPending = setUserStatusMutation.isPending || revokeSessions.isPending || setChannelState.isPending;

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
            <div className="flex flex-col gap-2 sm:flex-row">
              <Input value={eventSearch} onChange={(event) => { setEventSearch(event.target.value); setEventOffset(0); }} placeholder={t("events.searchPlaceholder")} className="sm:max-w-md" />
              <Select value={eventCategory} onValueChange={(value) => { setEventCategory(value); setEventOffset(0); }}>
                <SelectTrigger className="sm:w-52" aria-label={t("events.category")}><SelectValue /></SelectTrigger>
                <SelectContent>
                  {(["all", "security", "channels", "messages", "memberships", "uploads", "delivery", "administration", "system"] as const).map((category) => <SelectItem key={category} value={category}>{t(`events.categories.${category}`)}</SelectItem>)}
                </SelectContent>
              </Select>
            </div>
            <Card className="overflow-hidden"><div className="border-b p-4 text-sm font-medium">{t("events.total", { count: events.data?.total ?? 0 })}</div>
              <div className="overflow-x-auto"><Table><TableHeader><TableRow><TableHead>{t("events.details")}</TableHead><TableHead>{t("events.type")}</TableHead><TableHead>{t("events.actor")}</TableHead><TableHead>{t("events.channel")}</TableHead><TableHead>{t("events.time")}</TableHead></TableRow></TableHeader>
                <TableBody>
                  {(events.data?.items ?? []).map((event) => (
                    <TableRow key={event.id}>
                      <TableCell><AdminEventDisplay event={event} /></TableCell>
                      <TableCell><Badge variant="outline"><AdminEventType eventType={event.event_type} /></Badge></TableCell>
                      <TableCell>
                        {event.actor_username && event.actor_user_id ? (
                          <Link
                            className="font-medium text-primary underline-offset-4 hover:underline focus-visible:underline focus-visible:outline-none"
                            href={event.actor_user_id === user.id ? localePath("/app/profile") : localePath(`/app/users/${event.actor_user_id}`)}
                          >
                            @{event.actor_username}
                          </Link>
                        ) : event.actor_username ? `@${event.actor_username}` : t("events.system")}
                      </TableCell>
                      <TableCell>
                        <EventChannel
                          name={event.channel_name}
                          slug={event.channel_slug}
                          fallback={t("events.notChannelScoped")}
                          href={event.channel_id ? localePath(`/app/channels/${event.channel_id}`) : undefined}
                        />
                      </TableCell>
                      <TableCell className="whitespace-nowrap"><DateCell value={event.created_at} /></TableCell>
                    </TableRow>
                  ))}
                  {!events.isLoading && events.data?.items.length === 0 && <EmptyRow columns={5}>{t("events.empty")}</EmptyRow>}
                </TableBody>
              </Table></div>
              {events.isLoading && <Skeleton className="m-4 h-24" />}
              <AdminTablePagination offset={eventOffset} pageSize={eventPageSize} total={events.data?.total ?? 0} onOffsetChange={setEventOffset} onPageSizeChange={(size) => { setEventPageSize(size); setEventOffset(0); }} />
            </Card>
          </TabsContent>

          <TabsContent value="users" className="space-y-3">
            <div className="flex flex-col gap-2 sm:flex-row">
              <Input value={userSearch} onChange={(event) => { setUserSearch(event.target.value); setUserOffset(0); }} placeholder={t("users.searchPlaceholder")} className="sm:max-w-md" />
              <Select value={userStatus} onValueChange={(value) => { setUserStatus(value); setUserOffset(0); }}>
                <SelectTrigger className="sm:w-44" aria-label={t("users.status")}><SelectValue /></SelectTrigger>
                <SelectContent><SelectItem value="all">{t("filters.allStatuses")}</SelectItem><SelectItem value="active">{t("users.active")}</SelectItem><SelectItem value="inactive">{t("users.inactive")}</SelectItem></SelectContent>
              </Select>
            </div>
            <Card className="overflow-hidden"><div className="border-b p-4 text-sm font-medium">{t("users.total", { count: users.data?.total ?? 0 })}</div>
              <div className="overflow-x-auto"><Table><TableHeader><TableRow><TableHead>{t("users.user")}</TableHead><TableHead>{t("users.status")}</TableHead><TableHead>{t("users.sessions")}</TableHead><TableHead>{t("users.created")}</TableHead><TableHead className="text-right">{t("users.actions")}</TableHead></TableRow></TableHeader>
                <TableBody>
                  {(users.data?.items ?? []).map((item) => <TableRow key={item.id}><TableCell><div className="font-medium">{item.display_name || item.username}</div><div className="text-xs text-muted-foreground">@{item.username} · {item.email || "—"}</div></TableCell><TableCell><Badge variant={item.is_active ? "default" : "destructive"}>{item.is_superadmin ? t("users.superadmin") : item.is_active ? t("users.active") : t("users.inactive")}</Badge></TableCell><TableCell>{item.active_session_count}</TableCell><TableCell className="whitespace-nowrap"><DateCell value={item.created_at} /></TableCell><TableCell><div className="flex justify-end gap-2"><Button size="sm" variant="outline" disabled={item.is_superadmin || anyActionPending} onClick={() => setPendingAction({ kind: "revokeSessions", id: item.id, label: `@${item.username}` })}>{t("users.revokeSessions")}</Button><Button size="sm" variant={item.is_active ? "destructive" : "default"} disabled={item.is_superadmin || anyActionPending} onClick={() => setPendingAction({ kind: item.is_active ? "deactivate" : "reactivate", id: item.id, label: `@${item.username}` })}>{item.is_active ? t("users.deactivate") : t("users.reactivate")}</Button></div></TableCell></TableRow>)}
                  {!users.isLoading && users.data?.items.length === 0 && <EmptyRow columns={5}>{t("users.empty")}</EmptyRow>}
                </TableBody>
              </Table></div>
              {users.isLoading && <Skeleton className="m-4 h-24" />}
              <AdminTablePagination offset={userOffset} pageSize={userPageSize} total={users.data?.total ?? 0} onOffsetChange={setUserOffset} onPageSizeChange={(size) => { setUserPageSize(size); setUserOffset(0); }} />
            </Card>
          </TabsContent>

          <TabsContent value="channels" className="space-y-3">
            <div className="flex flex-col gap-2 lg:flex-row">
              <Input value={channelSearch} onChange={(event) => { setChannelSearch(event.target.value); setChannelOffset(0); }} placeholder={t("channels.searchPlaceholder")} className="lg:max-w-md" />
              <Select value={channelState} onValueChange={(value) => { setChannelStateFilter(value); setChannelOffset(0); }}>
                <SelectTrigger className="lg:w-44" aria-label={t("channels.status")}><SelectValue /></SelectTrigger>
                <SelectContent><SelectItem value="all">{t("filters.allStatuses")}</SelectItem><SelectItem value="active">{t("channels.active")}</SelectItem><SelectItem value="suspended">{t("channels.suspended")}</SelectItem></SelectContent>
              </Select>
              <Select value={channelVisibility} onValueChange={(value) => { setChannelVisibility(value); setChannelOffset(0); }}>
                <SelectTrigger className="lg:w-44" aria-label={t("channels.visibility")}><SelectValue /></SelectTrigger>
                <SelectContent><SelectItem value="all">{t("filters.allVisibility")}</SelectItem><SelectItem value="public">{t("channels.public")}</SelectItem><SelectItem value="private">{t("channels.private")}</SelectItem></SelectContent>
              </Select>
            </div>
            <Card className="overflow-hidden"><div className="border-b p-4 text-sm font-medium">{t("channels.total", { count: channels.data?.total ?? 0 })}</div>
              <div className="overflow-x-auto"><Table><TableHeader><TableRow><TableHead>{t("channels.channel")}</TableHead><TableHead>{t("channels.owner")}</TableHead><TableHead>{t("channels.members")}</TableHead><TableHead>{t("channels.messages")}</TableHead><TableHead>{t("channels.status")}</TableHead><TableHead className="text-right">{t("channels.actions")}</TableHead></TableRow></TableHeader>
                <TableBody>
                  {(channels.data?.items ?? []).map((channel) => <TableRow key={channel.id}><TableCell><Link className="block text-primary underline-offset-4 hover:underline focus-visible:underline focus-visible:outline-none" href={localePath(`/app/channels/${channel.id}`)}><div className="font-medium">{channel.name}</div><div className="text-xs text-muted-foreground">#{channel.channel_slug} · {t(`channels.${channel.visibility}`)}</div></Link></TableCell><TableCell>@{channel.owner_username}</TableCell><TableCell>{channel.member_count}</TableCell><TableCell>{channel.message_count}</TableCell><TableCell><Badge variant={channel.deleted_at ? "destructive" : "default"}>{channel.deleted_at ? t("channels.suspended") : t("channels.active")}</Badge></TableCell><TableCell className="text-right"><Button size="sm" variant={channel.deleted_at ? "default" : "destructive"} disabled={anyActionPending} onClick={() => setPendingAction({ kind: channel.deleted_at ? "restore" : "suspend", id: channel.id, label: channel.name })}>{channel.deleted_at ? t("channels.restore") : t("channels.suspend")}</Button></TableCell></TableRow>)}
                  {!channels.isLoading && channels.data?.items.length === 0 && <EmptyRow columns={6}>{t("channels.empty")}</EmptyRow>}
                </TableBody>
              </Table></div>
              {channels.isLoading && <Skeleton className="m-4 h-24" />}
              <AdminTablePagination offset={channelOffset} pageSize={channelPageSize} total={channels.data?.total ?? 0} onOffsetChange={setChannelOffset} onPageSizeChange={(size) => { setChannelPageSize(size); setChannelOffset(0); }} />
            </Card>
          </TabsContent>
        </Tabs>
      </div>

      <AlertDialog open={pendingAction !== null} onOpenChange={(open) => { if (!open) setPendingAction(null); }}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{pendingAction ? t(`confirm.${pendingAction.kind}.title`) : ""}</AlertDialogTitle>
            <AlertDialogDescription>{pendingAction ? t(`confirm.${pendingAction.kind}.description`, { target: pendingAction.label }) : ""}</AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t("confirm.cancel")}</AlertDialogCancel>
            <AlertDialogAction onClick={confirmPendingAction} className={pendingAction?.kind === "deactivate" || pendingAction?.kind === "suspend" || pendingAction?.kind === "revokeSessions" ? "bg-destructive text-destructive-foreground hover:bg-destructive/90" : undefined}>{t("confirm.confirm")}</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
