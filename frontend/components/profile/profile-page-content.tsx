"use client";

import Image from "next/image";
import Link from "next/link";
import { useCurrentUser } from "@/hooks/use-current-user";
import { resolveApiUrl } from "@/lib/env";
import { formatDateTime } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";

function formatLongDate(value?: string | null) {
  if (!value) return "Not available";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Not available";
  return new Intl.DateTimeFormat(undefined, {
    year: "numeric",
    month: "long",
    day: "numeric",
  }).format(date);
}

function formatShortDate(value?: string | null) {
  if (!value) return "Unavailable";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Unavailable";
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
  }).format(date);
}

function getProfileCompleteness(fields: Array<string | null | undefined>) {
  const filled = fields.filter((value) => value && value.trim().length > 0).length;
  return Math.round((filled / fields.length) * 100);
}

function StatCard({ label, value, helper }: { label: string; value: string; helper: string }) {
  return (
    <div className="rounded-2xl border border-white/50 bg-white/70 p-4 shadow-sm backdrop-blur dark:border-slate-700/60 dark:bg-slate-900/50">
      <p className="text-xs font-medium uppercase tracking-[0.22em] text-slate-500 dark:text-slate-400">{label}</p>
      <p className="mt-2 text-xl font-semibold text-slate-950 dark:text-slate-50">{value}</p>
      <p className="mt-1 text-sm text-slate-600 dark:text-slate-300">{helper}</p>
    </div>
  );
}

function InfoRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-start justify-between gap-4 border-b border-slate-200/80 py-3 last:border-b-0 dark:border-slate-800/80">
      <span className="text-sm text-slate-500 dark:text-slate-400">{label}</span>
      <span className="max-w-[60%] text-right text-sm font-medium text-slate-800 dark:text-slate-100">{value}</span>
    </div>
  );
}

function ProfileLoadingState() {
  return (
    <main className="mx-auto w-full max-w-6xl p-4 sm:p-6">
      <div className="overflow-hidden rounded-[28px] border border-slate-200/70 bg-white/80 shadow-sm dark:border-slate-800 dark:bg-slate-950/75">
        <div className="h-40 animate-pulse bg-slate-200/80 dark:bg-slate-800/80" />
        <div className="space-y-4 p-6">
          <div className="h-6 w-48 animate-pulse rounded bg-slate-200 dark:bg-slate-800" />
          <div className="h-4 w-72 animate-pulse rounded bg-slate-200 dark:bg-slate-800" />
          <div className="grid gap-3 md:grid-cols-3">
            {Array.from({ length: 3 }).map((_, index) => (
              <div key={index} className="h-28 animate-pulse rounded-2xl bg-slate-200 dark:bg-slate-800" />
            ))}
          </div>
        </div>
      </div>
    </main>
  );
}

function ProfileErrorState() {
  return (
    <main className="mx-auto grid min-h-[60vh] w-full max-w-3xl place-items-center p-4 sm:p-6">
      <Card className="w-full max-w-xl overflow-hidden">
        <div className="h-2 bg-gradient-to-r from-rose-400 via-orange-300 to-amber-300" />
        <CardContent className="space-y-4 p-6 text-center sm:p-8">
          <Badge className="bg-rose-100 text-rose-700 dark:bg-rose-950/60 dark:text-rose-200">Profile unavailable</Badge>
          <div className="space-y-2">
            <h1 className="text-2xl font-semibold text-slate-950 dark:text-slate-50">We couldn&apos;t load your profile</h1>
            <p className="text-sm text-slate-600 dark:text-slate-300">
              Your session may have expired, or the profile endpoint may be temporarily unavailable.
            </p>
          </div>
          <Link
            href="/login"
            className="inline-flex w-full items-center justify-center rounded-md bg-slate-900 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-slate-700 dark:bg-slate-100 dark:text-slate-900 dark:hover:bg-slate-300 sm:w-auto"
          >
            Return to login
          </Link>
        </CardContent>
      </Card>
    </main>
  );
}

export function ProfilePageContent() {
  const meQuery = useCurrentUser();

  if (meQuery.isLoading) {
    return <ProfileLoadingState />;
  }

  if (!meQuery.data) {
    return <ProfileErrorState />;
  }

  const me = meQuery.data;
  const initials = me.display_name?.trim()?.[0]?.toUpperCase() || me.username.trim().charAt(0).toUpperCase() || "U";
  const avatarSrc = resolveApiUrl(me.avatar_url);
  const displayName = me.display_name || me.username;
  const profileCompleteness = getProfileCompleteness([me.display_name, me.email, me.avatar_url, me.bio]);
  const bioLength = me.bio?.trim().length ?? 0;
  const createdLabel = formatLongDate(me.created_at);
  const updatedLabel = me.updated_at ? formatLongDate(me.updated_at) : "No profile edits yet";

  return (
    <main className="mx-auto w-full max-w-6xl space-y-6 p-4 sm:space-y-8 sm:p-6">
      <section className="relative overflow-hidden rounded-[30px] border border-slate-200/70 bg-white/75 shadow-xl shadow-slate-200/40 backdrop-blur dark:border-slate-800/70 dark:bg-slate-950/75 dark:shadow-black/20">
        <div className="absolute inset-0 bg-[radial-gradient(circle_at_top_left,_rgba(14,165,233,0.18),_transparent_34%),radial-gradient(circle_at_80%_20%,_rgba(244,114,182,0.16),_transparent_28%),linear-gradient(135deg,_rgba(255,255,255,0.7),_rgba(248,250,252,0.35))] dark:bg-[radial-gradient(circle_at_top_left,_rgba(56,189,248,0.16),_transparent_34%),radial-gradient(circle_at_80%_20%,_rgba(244,114,182,0.12),_transparent_28%),linear-gradient(135deg,_rgba(2,6,23,0.78),_rgba(15,23,42,0.45))]" />
        <div className="relative border-b border-white/40 px-6 py-10 dark:border-slate-800/60 sm:px-8">
          <div className="flex flex-col gap-6 lg:flex-row lg:items-end lg:justify-between">
            <div className="flex min-w-0 flex-col gap-5 sm:flex-row sm:items-center">
              <div className="relative shrink-0">
                {avatarSrc ? (
                  <Image
                    src={avatarSrc}
                    alt={me.username}
                    width={112}
                    height={112}
                    unoptimized
                    className="size-24 rounded-[26px] border border-white/60 object-cover shadow-lg shadow-sky-200/50 dark:border-slate-700/70 dark:shadow-sky-950/30 sm:size-28"
                  />
                ) : (
                  <div className="flex size-24 items-center justify-center rounded-[26px] border border-white/60 bg-gradient-to-br from-sky-400 via-cyan-300 to-emerald-300 text-3xl font-semibold text-slate-950 shadow-lg shadow-sky-200/50 dark:border-slate-700/70 dark:text-slate-950 sm:size-28">
                    {initials}
                  </div>
                )}
              </div>
              <div className="min-w-0 space-y-3">
                <div className="flex flex-wrap items-center gap-2">
                  <Badge className="bg-slate-950 text-white dark:bg-slate-100 dark:text-slate-950">Personal profile</Badge>
                  <Badge className="bg-emerald-100 text-emerald-700 dark:bg-emerald-950/60 dark:text-emerald-200">{profileCompleteness}% complete</Badge>
                </div>
                <div>
                  <h1 className="truncate text-3xl font-semibold tracking-tight text-slate-950 dark:text-slate-50 sm:text-4xl">{displayName}</h1>
                  <p className="mt-1 truncate text-sm text-slate-600 dark:text-slate-300">@{me.username}</p>
                </div>
                <p className="max-w-2xl text-sm leading-6 text-slate-700 dark:text-slate-300">
                  {me.bio?.trim() || "Add a bio when profile editing is available to help teammates recognize your role, focus, and current priorities."}
                </p>
              </div>
            </div>

            <div className="grid gap-3 sm:grid-cols-2">
              <StatCard label="Joined" value={formatShortDate(me.created_at)} helper="Account creation date" />
              <StatCard label="Last update" value={me.updated_at ? formatShortDate(me.updated_at) : "No edits"} helper="Latest profile refresh" />
              <StatCard label="Bio status" value={bioLength ? `${bioLength} chars` : "Missing"} helper="Profile summary coverage" />
              <StatCard label="Email" value={me.email ? "Connected" : "Missing"} helper={me.email || "No email exposed by API"} />
            </div>
          </div>
        </div>

        <div className="relative grid gap-4 px-6 py-6 sm:px-8 lg:grid-cols-[1.15fr_0.85fr]">
          <Card className="border-white/60 bg-white/70 shadow-none backdrop-blur dark:border-slate-800/70 dark:bg-slate-950/55">
            <CardHeader className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
              <div>
                <h2 className="text-lg font-semibold text-slate-950 dark:text-slate-50">Profile details</h2>
                <p className="text-sm text-slate-500 dark:text-slate-400">Read-only values from the current backend session.</p>
              </div>
              <Badge>Backend managed</Badge>
            </CardHeader>
            <CardContent className="grid gap-4 sm:grid-cols-2">
              <div className="space-y-2">
                <label className="text-sm font-medium text-slate-700 dark:text-slate-200">Username</label>
                <Input value={me.username} disabled aria-label="Username" className="bg-white/90 dark:bg-slate-950/80" />
              </div>
              <div className="space-y-2">
                <label className="text-sm font-medium text-slate-700 dark:text-slate-200">Display name</label>
                <Input value={me.display_name ?? ""} disabled aria-label="Display name" placeholder="No display name yet" className="bg-white/90 dark:bg-slate-950/80" />
              </div>
              <div className="space-y-2 sm:col-span-2">
                <label className="text-sm font-medium text-slate-700 dark:text-slate-200">Email address</label>
                <Input value={me.email ?? ""} disabled aria-label="Email address" placeholder="No email connected" className="bg-white/90 dark:bg-slate-950/80" />
              </div>
              <div className="space-y-2 sm:col-span-2">
                <label className="text-sm font-medium text-slate-700 dark:text-slate-200">Avatar source</label>
                <Input value={me.avatar_url ?? ""} disabled aria-label="Avatar URL" placeholder="No avatar URL available" className="bg-white/90 dark:bg-slate-950/80" />
              </div>
              <div className="space-y-2 sm:col-span-2">
                <label className="text-sm font-medium text-slate-700 dark:text-slate-200">Bio</label>
                <Textarea
                  value={me.bio ?? ""}
                  disabled
                  aria-label="Bio"
                  placeholder="No bio available"
                  className="min-h-32 resize-none bg-white/90 dark:bg-slate-950/80"
                />
              </div>
              <div className="sm:col-span-2 flex flex-col gap-3 rounded-2xl border border-dashed border-slate-300 bg-slate-50/80 p-4 dark:border-slate-700 dark:bg-slate-900/60">
                <div>
                  <p className="text-sm font-medium text-slate-800 dark:text-slate-100">Editing is not wired up yet</p>
                  <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
                    The frontend is ready to show profile data, but the backend still needs update endpoints for saving profile changes and password updates.
                  </p>
                </div>
                <div className="flex flex-col gap-3 sm:flex-row">
                  <Button disabled className="w-full sm:w-auto">
                    Save changes
                  </Button>
                  <Link
                    href="/settings/sessions"
                    className="inline-flex h-9 w-full items-center justify-center rounded-md bg-slate-100 px-4 text-sm font-medium text-slate-900 transition-colors hover:bg-slate-200 dark:bg-slate-800 dark:text-slate-100 dark:hover:bg-slate-700 sm:w-auto"
                  >
                    Manage sessions
                  </Link>
                </div>
              </div>
            </CardContent>
          </Card>

          <div className="space-y-4">
            <Card className="border-white/60 bg-white/70 shadow-none backdrop-blur dark:border-slate-800/70 dark:bg-slate-950/55">
              <CardHeader>
                <h2 className="text-lg font-semibold text-slate-950 dark:text-slate-50">Account overview</h2>
              </CardHeader>
              <CardContent>
                <InfoRow label="Member since" value={createdLabel} />
                <InfoRow label="Last synced" value={updatedLabel} />
                <InfoRow label="Session email" value={me.email || "No email on record"} />
                <InfoRow label="Profile completeness" value={`${profileCompleteness}%`} />
                <InfoRow label="Recent activity marker" value={formatDateTime(me.updated_at || me.created_at) || "Unavailable"} />
              </CardContent>
            </Card>

            <Card className="overflow-hidden border-slate-900/10 bg-slate-950 text-slate-50 shadow-none dark:border-slate-700">
              <div className="bg-[radial-gradient(circle_at_top_right,_rgba(56,189,248,0.28),_transparent_30%),radial-gradient(circle_at_bottom_left,_rgba(244,114,182,0.2),_transparent_35%)] p-6">
                <p className="text-xs font-medium uppercase tracking-[0.24em] text-sky-200">Security</p>
                <h2 className="mt-3 text-xl font-semibold">Session controls stay separate</h2>
                <p className="mt-2 text-sm leading-6 text-slate-300">
                  Password changes are still blocked by the API, but active sessions are already manageable from the settings area.
                </p>
                <div className="mt-5 flex flex-col gap-3">
                  <Link
                    href="/settings/sessions"
                    className="inline-flex h-9 w-full items-center justify-center rounded-md bg-white px-4 text-sm font-medium text-slate-950 transition-colors hover:bg-slate-200"
                  >
                    Open session settings
                  </Link>
                  <p className="text-xs text-slate-400">Revoke stale devices there without leaving the authenticated workspace.</p>
                </div>
              </div>
            </Card>
          </div>
        </div>
      </section>
    </main>
  );
}
