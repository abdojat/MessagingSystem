"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect } from "react";
import { useLocale, useTranslations } from "next-intl";
import { AtSign, CalendarDays, Clock3, IdCard, UserCircle2 } from "lucide-react";

import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { useUserProfile } from "@/hooks/use-users";
import { useAuthStore } from "@/store/authStore";
import { useLocalePath } from "@/components/features/chat/lib/locale-path";
import { resolveApiMediaUrl } from "@/lib/mediaUrl";
import {
  formatDateLocalized,
  formatDateTimeLocalized,
  formatRelativeTimeStrictLocalized,
} from "@/lib/i18n-format";

function getInitials(value: string) {
  return (
    value
      .split(" ")
      .filter(Boolean)
      .slice(0, 2)
      .map((segment) => segment[0]?.toUpperCase() || "")
      .join("") || "U"
  );
}

function PublicProfileSkeleton() {
  return (
    <div className="h-full min-h-0 overflow-y-auto bg-background p-6 text-foreground sm:p-8">
      <div className="mx-auto max-w-4xl space-y-6">
        <div className="space-y-3">
          <Skeleton className="h-4 w-28" />
          <Skeleton className="h-9 w-48" />
          <Skeleton className="h-4 w-80 max-w-full" />
        </div>
        <Card className="overflow-hidden rounded-3xl border-border/60">
          <div className="p-6 sm:p-8">
            <div className="flex items-center gap-4">
              <Skeleton className="h-24 w-24 rounded-full" />
              <div className="min-w-0 flex-1 space-y-3">
                <Skeleton className="h-6 w-32 rounded-full" />
                <Skeleton className="h-9 w-56 max-w-full" />
                <Skeleton className="h-4 w-36" />
                <Skeleton className="h-4 w-full max-w-xl" />
              </div>
            </div>
          </div>
          <div className="grid gap-4 border-t border-border/60 p-6 sm:grid-cols-3">
            <Skeleton className="h-24 rounded-2xl" />
            <Skeleton className="h-24 rounded-2xl" />
            <Skeleton className="h-24 rounded-2xl" />
          </div>
        </Card>
      </div>
    </div>
  );
}

export default function PublicProfilePage() {
  const params = useParams<{ userId?: string | string[] }>();
  const userId = Array.isArray(params?.userId) ? params.userId[0] : params?.userId;
  const router = useRouter();
  const localePath = useLocalePath();
  const locale = useLocale();
  const t = useTranslations("publicProfile");
  const commonT = useTranslations("common");
  const currentUser = useAuthStore((state) => state.user);
  const isAuthenticated = useAuthStore((state) => state.isAuthenticated);
  const isInitializing = useAuthStore((state) => state.isInitializing);
  const isOwnProfile = Boolean(userId && currentUser?.id === userId);
  const profileQuery = useUserProfile(userId || "", Boolean(isAuthenticated && !isOwnProfile));

  useEffect(() => {
    if (!isInitializing && (!isAuthenticated || !userId)) {
      router.replace(localePath("/login"));
    }
  }, [isAuthenticated, isInitializing, localePath, router, userId]);

  useEffect(() => {
    if (!isInitializing && isAuthenticated && isOwnProfile) {
      router.replace(localePath("/app/profile"));
    }
  }, [isAuthenticated, isInitializing, isOwnProfile, localePath, router]);

  if (isInitializing || isOwnProfile || profileQuery.isLoading) {
    return <PublicProfileSkeleton />;
  }

  if (!isAuthenticated) return null;

  if (profileQuery.isError || !profileQuery.data) {
    return (
      <div className="h-full min-h-0 overflow-y-auto bg-background p-6 text-foreground sm:p-8">
        <div className="mx-auto max-w-3xl">
          <Link href={localePath("/app")} className="text-sm font-medium text-primary hover:underline">
            {commonT("actions.returnToApp")}
          </Link>
          <Card className="mt-6 rounded-3xl p-8 text-center">
            <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-2xl bg-muted text-muted-foreground">
              <UserCircle2 className="h-7 w-7" />
            </div>
            <h1 className="mt-4 text-2xl font-bold">{t("errors.loadTitle")}</h1>
            <p className="mt-2 text-muted-foreground">{t("errors.loadDescription")}</p>
            <div className="mt-6 flex justify-center gap-2">
              <Button variant="outline" onClick={() => router.push(localePath("/app"))}>
                {commonT("actions.returnToApp")}
              </Button>
              <Button onClick={() => profileQuery.refetch()}>{commonT("actions.tryAgain")}</Button>
            </div>
          </Card>
        </div>
      </div>
    );
  }

  const profile = profileQuery.data;
  const displayName = profile.display_name?.trim() || profile.username;
  const avatarUrl = resolveApiMediaUrl(profile.avatar_url);
  const createdAtLabel = formatDateLocalized(profile.created_at, locale, commonT("notAvailable"));
  const createdAtRelative = formatRelativeTimeStrictLocalized(profile.created_at, locale, commonT("unknown"));
  const updatedAtLabel = formatDateTimeLocalized(profile.updated_at, locale, commonT("notAvailable"));

  return (
    <div className="h-full min-h-0 overflow-y-auto bg-background p-6 text-foreground sm:p-8">
      <div className="mx-auto max-w-4xl space-y-6 pb-6">
        <div>
          <Link href={localePath("/app")} className="text-sm font-medium text-primary hover:underline">
            {commonT("actions.returnToApp")}
          </Link>
          <h1 className="mt-2 text-3xl font-bold tracking-tight">{t("title")}</h1>
          <p className="mt-1 text-muted-foreground">{t("description")}</p>
        </div>

        <Card className="overflow-hidden rounded-3xl border-border/60 bg-card/90 shadow-xl">
          <div className="bg-gradient-to-r from-primary/15 via-primary/5 to-transparent p-6 sm:p-8">
            <div className="flex flex-col gap-6 sm:flex-row sm:items-center">
              <Avatar className="h-24 w-24 border-4 border-background shadow-lg">
                <AvatarImage src={avatarUrl} alt={displayName} />
                <AvatarFallback className="text-2xl font-bold">{getInitials(displayName)}</AvatarFallback>
              </Avatar>
              <div className="min-w-0">
                <Badge variant="secondary">{t("badges.public")}</Badge>
                <h2 className="mt-3 truncate text-3xl font-bold">{displayName}</h2>
                <p className="text-muted-foreground">@{profile.username}</p>
                <p className="mt-3 max-w-2xl whitespace-pre-wrap text-sm leading-6 text-muted-foreground">
                  {profile.bio?.trim() || t("empty.noBio")}
                </p>
              </div>
            </div>
          </div>

          <div className="grid gap-4 p-6 sm:grid-cols-3">
            <div className="rounded-2xl border border-border/60 bg-background/40 p-4">
              <div className="flex items-center gap-2 text-muted-foreground">
                <AtSign className="h-4 w-4" />
                <span className="text-xs uppercase tracking-[0.18em]">{t("stats.username")}</span>
              </div>
              <p className="mt-2 break-all font-semibold">@{profile.username}</p>
            </div>

            <div className="rounded-2xl border border-border/60 bg-background/40 p-4">
              <div className="flex items-center gap-2 text-muted-foreground">
                <CalendarDays className="h-4 w-4" />
                <span className="text-xs uppercase tracking-[0.18em]">{t("stats.memberSince")}</span>
              </div>
              <p className="mt-2 font-semibold">{createdAtLabel}</p>
              <p className="mt-2 text-xs text-muted-foreground">{createdAtRelative}</p>
            </div>

            <div className="rounded-2xl border border-border/60 bg-background/40 p-4">
              <div className="flex items-center gap-2 text-muted-foreground">
                <Clock3 className="h-4 w-4" />
                <span className="text-xs uppercase tracking-[0.18em]">{t("stats.lastUpdated")}</span>
              </div>
              <p className="mt-2 font-semibold">{updatedAtLabel}</p>
            </div>
          </div>

          <div className="border-t border-border/60 p-6">
            <div className="rounded-2xl border border-border/60 bg-background/40 p-5">
              <h3 className="flex items-center gap-2 text-lg font-semibold">
                <IdCard className="h-5 w-5 text-primary" />
                {t("sections.identity")}
              </h3>
              <div className="mt-4 grid gap-3 sm:grid-cols-2">
                <div className="rounded-xl border border-border/60 bg-background/40 p-3">
                  <p className="text-xs uppercase tracking-[0.14em] text-muted-foreground">{t("rows.displayName")}</p>
                  <p className="mt-1 break-words text-sm font-medium">
                    {profile.display_name?.trim() || t("empty.noDisplayName")}
                  </p>
                </div>
                <div className="rounded-xl border border-border/60 bg-background/40 p-3">
                  <p className="text-xs uppercase tracking-[0.14em] text-muted-foreground">{t("rows.userId")}</p>
                  <p className="mt-1 break-all text-sm font-medium">{profile.id}</p>
                </div>
              </div>
            </div>
          </div>
        </Card>
      </div>
    </div>
  );
}
