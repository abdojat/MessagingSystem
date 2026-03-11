"use client";

import Image from "next/image";
import Link from "next/link";
import { useCurrentUser } from "@/hooks/use-current-user";
import { resolveApiUrl } from "@/lib/env";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Button } from "@/components/ui/button";

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

export function ProfilePageContent() {
  const meQuery = useCurrentUser();

  if (meQuery.isLoading) {
    return <div className="p-4 sm:p-6">Loading profile...</div>;
  }

  if (!meQuery.data) {
    return <div className="p-4 sm:p-6">Failed to load profile.</div>;
  }

  const me = meQuery.data;
  const initials = me.display_name?.trim()?.[0]?.toUpperCase() || me.username.trim().charAt(0).toUpperCase() || "U";
  const avatarSrc = resolveApiUrl(me.avatar_url);

  return (
    <main className="mx-auto w-full max-w-5xl space-y-4 p-4 sm:space-y-6 sm:p-6">
      <Card>
        <CardHeader>
          <h1 className="text-xl font-semibold sm:text-2xl">Profile</h1>
        </CardHeader>
        <CardContent>
          <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
            <div className="flex min-w-0 items-center gap-4">
              {avatarSrc ? (
                <Image src={avatarSrc} alt={me.username} width={72} height={72} unoptimized className="size-16 rounded-full object-cover sm:size-[72px]" />
              ) : (
                <div className="flex size-16 items-center justify-center rounded-full bg-slate-300 text-lg font-semibold text-slate-700 dark:bg-slate-700 dark:text-slate-200 sm:size-[72px]">
                  {initials}
                </div>
              )}
              <div className="min-w-0">
                <p className="truncate text-lg font-semibold">{me.display_name || me.username}</p>
                <p className="truncate text-sm text-slate-500">@{me.username}</p>
                <p className="truncate text-sm text-slate-500">{me.email || "No email set"}</p>
              </div>
            </div>
            <div className="grid grid-cols-2 gap-3 text-xs text-slate-500 sm:text-sm">
              <div>
                <p className="font-medium text-slate-700 dark:text-slate-200">Joined</p>
                <p>{formatLongDate(me.created_at)}</p>
              </div>
              <div>
                <p className="font-medium text-slate-700 dark:text-slate-200">Last updated</p>
                <p>{formatLongDate(me.updated_at)}</p>
              </div>
              <div>
                <p className="font-medium text-slate-700 dark:text-slate-200">Account role</p>
                <p>Not exposed by API</p>
              </div>
              <div>
                <p className="font-medium text-slate-700 dark:text-slate-200">Email verification</p>
                <p>Not exposed by API</p>
              </div>
            </div>
          </div>
          <div className="mt-4 rounded-lg border border-slate-200 p-3 text-sm dark:border-slate-800">
            <p className="font-medium">Bio</p>
            <p className="mt-1 whitespace-pre-wrap break-words text-slate-600 dark:text-slate-300">{me.bio || "No bio provided."}</p>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <h2 className="text-lg font-semibold">Edit Profile</h2>
        </CardHeader>
        <CardContent className="space-y-3">
          <p className="text-sm text-slate-500">Profile update endpoints are not currently available in the backend API. Fields are shown read-only.</p>
          <Input value={me.username} disabled aria-label="Username" />
          <Input value={me.display_name ?? ""} placeholder="Display name" disabled aria-label="Display name" />
          <Input value={me.email ?? ""} placeholder="Email" disabled aria-label="Email" />
          <Input value={me.avatar_url ?? ""} placeholder="Avatar URL" disabled aria-label="Avatar URL" />
          <Textarea value={me.bio ?? ""} placeholder="Bio" disabled aria-label="Bio" />
          <Button disabled className="w-full sm:w-auto">
            Save changes
          </Button>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <h2 className="text-lg font-semibold">Security</h2>
        </CardHeader>
        <CardContent className="space-y-3">
          <p className="text-sm text-slate-500">Password change endpoint is not currently available in the backend API.</p>
          <Button disabled className="w-full sm:w-auto">
            Change password
          </Button>
          <div>
            <Link href="/settings/sessions" className="text-sm underline">
              Manage active sessions
            </Link>
          </div>
        </CardContent>
      </Card>
    </main>
  );
}
