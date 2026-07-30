"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { useLocale, useTranslations } from "next-intl";
import {
  Activity,
  CheckCircle2,
  CircleDashed,
  Clock3,
  Copy,
  Download,
  Mail,
  RefreshCcw,
  ShieldCheck,
  UserCircle2,
} from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";

import { useSessions } from "@/hooks/use-auth";
import { toast } from "@/hooks/use-toast";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { Button, buttonVariants } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Progress } from "@/components/ui/progress";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import { apiClient } from "@/services/api/client";
import { getApiBaseUrl } from "@/services/api/runtime";
import { useAuthStore } from "@/store/authStore";
import type { MeResponse, UpdateMeRequest } from "@/types/api";
import { useLocalePath } from "@/components/features/chat/lib/locale-path";
import { resolveApiMediaUrl } from "@/lib/mediaUrl";
import {
  formatDateLocalized,
  formatDateTimeLocalized,
  formatRelativeTimeStrictLocalized,
} from "@/lib/i18n-format";

type ProfileChecklistItem = {
  id: string;
  label: string;
  hint: string;
  completed: boolean;
};

type ProfileFormState = {
  display_name: string;
  email: string;
  bio: string;
};

type UploadCreateResponse = {
  file_id: string;
  upload_url: string;
  method?: string;
  headers?: Record<string, string>;
  public_url?: string | null;
};

type UploadContentResponse = {
  file_id: string;
  public_url: string;
};

function normalizeFormValue(value: string): string | null {
  const normalized = value.trim();
  return normalized || null;
}

function getErrorMessage(error: unknown, fallback: string) {
  if (error instanceof Error && error.message) return error.message;
  return fallback;
}

async function copyToClipboard(value: string) {
  if (typeof navigator !== "undefined" && navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(value);
    return;
  }

  if (typeof document === "undefined") {
    throw new Error("Clipboard is not available in this environment.");
  }

  const textarea = document.createElement("textarea");
  textarea.value = value;
  textarea.setAttribute("readonly", "");
  textarea.style.position = "absolute";
  textarea.style.left = "-9999px";
  document.body.appendChild(textarea);
  textarea.select();
  const copied = document.execCommand("copy");
  document.body.removeChild(textarea);

  if (!copied) {
    throw new Error("Copy action was blocked by the browser.");
  }
}

function downloadProfileSnapshot(user: MeResponse, activeSessionCount: number) {
  const payload = {
    exported_at: new Date().toISOString(),
    active_session_count: activeSessionCount,
    profile: user,
  };

  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
  const objectUrl = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = objectUrl;
  link.download = `profile-${user.username}-snapshot.json`;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(objectUrl);
}

function ProfileSkeleton() {
  return (
    <div className="h-full min-h-0 overflow-y-auto bg-background p-6 text-foreground sm:p-8">
      <div className="mx-auto max-w-5xl space-y-6">
        <div className="flex items-center justify-between gap-4">
          <div className="space-y-3">
            <Skeleton className="h-4 w-24" />
            <Skeleton className="h-9 w-40" />
            <Skeleton className="h-4 w-72 max-w-full" />
          </div>
          <div className="flex gap-2">
            <Skeleton className="h-10 w-36 rounded-xl" />
            <Skeleton className="h-10 w-36 rounded-xl" />
          </div>
        </div>

        <Card className="overflow-hidden rounded-3xl border-border/60 bg-card/90 shadow-xl">
          <div className="p-6 sm:p-8">
            <div className="flex flex-col gap-6 sm:flex-row sm:items-center sm:justify-between">
              <div className="flex items-center gap-4">
                <Skeleton className="h-24 w-24 rounded-full" />
                <div className="min-w-0 space-y-3">
                  <div className="flex flex-wrap items-center gap-2">
                    <Skeleton className="h-6 w-28 rounded-full" />
                    <Skeleton className="h-6 w-24 rounded-full" />
                  </div>
                  <Skeleton className="h-9 w-48 max-w-full" />
                  <Skeleton className="h-4 w-28" />
                  <Skeleton className="h-4 w-96 max-w-full" />
                </div>
              </div>
              <div className="flex gap-2">
                <Skeleton className="h-9 w-32 rounded-xl" />
                <Skeleton className="h-9 w-32 rounded-xl" />
              </div>
            </div>
          </div>

          <div className="grid gap-4 p-6 sm:grid-cols-2 lg:grid-cols-4">
            {Array.from({ length: 4 }).map((_, index) => (
              <Card key={index} className="rounded-2xl p-4 space-y-3">
                <Skeleton className="h-3 w-20" />
                <Skeleton className="h-5 w-28" />
                <Skeleton className="h-2 w-full" />
              </Card>
            ))}
          </div>

          <div className="border-t border-border/60 p-6">
            <Skeleton className="h-10 w-80 max-w-full rounded-lg" />
            <div className="mt-4 grid gap-4 lg:grid-cols-[1.15fr_0.85fr]">
              <Card className="rounded-2xl p-5 space-y-4">
                <Skeleton className="h-6 w-36" />
                {Array.from({ length: 4 }).map((_, index) => (
                  <div key={index} className="space-y-2">
                    <Skeleton className="h-3 w-24" />
                    <Skeleton className="h-4 w-72 max-w-full" />
                  </div>
                ))}
              </Card>
              <Card className="rounded-2xl p-5 space-y-4">
                <Skeleton className="h-6 w-44" />
                {Array.from({ length: 4 }).map((_, index) => (
                  <div key={index} className="flex items-center justify-between gap-3">
                    <Skeleton className="h-4 w-40" />
                    <Skeleton className="h-5 w-16 rounded-full" />
                  </div>
                ))}
              </Card>
            </div>
          </div>
        </Card>
      </div>
    </div>
  );
}

export default function ProfilePage() {
  const router = useRouter();
  const localePath = useLocalePath();
  const locale = useLocale();
  const t = useTranslations("profile");
  const commonT = useTranslations("common");
  const user = useAuthStore((state) => state.user);
  const isAuthenticated = useAuthStore((state) => state.isAuthenticated);
  const isInitializing = useAuthStore((state) => state.isInitializing);
  const accessToken = useAuthStore((state) => state.accessToken);
  const updateUser = useAuthStore((state) => state.updateUser);
  const { data: sessions = [], isLoading: isSessionsLoading } = useSessions(isAuthenticated);
  const [lastSyncedAt, setLastSyncedAt] = useState<Date | null>(null);
  const [avatarFile, setAvatarFile] = useState<File | null>(null);
  const [formState, setFormState] = useState<ProfileFormState>({
    display_name: user?.display_name ?? "",
    email: user?.email ?? "",
    bio: user?.bio ?? "",
  });

  useEffect(() => {
    if (!user) return;
    setFormState({
      display_name: user.display_name ?? "",
      email: user.email ?? "",
      bio: user.bio ?? "",
    });
  }, [user?.id, user?.updated_at, user?.display_name, user?.email, user?.bio]);

  useEffect(() => {
    setAvatarFile(null);
  }, [user?.avatar_url, user?.updated_at]);

  useEffect(() => {
    if (!isInitializing && (!isAuthenticated || !user)) {
      router.replace(localePath("/login"));
    }
  }, [isAuthenticated, isInitializing, localePath, router, user]);

  const refreshProfile = useMutation({
    mutationFn: () => apiClient<MeResponse>("/me"),
    onSuccess: (freshUser) => {
      updateUser(freshUser);
      setLastSyncedAt(new Date());
      toast({
        title: t("toasts.refreshedTitle"),
        description: t("toasts.refreshedDescription"),
      });
    },
    onError: (error: unknown) => {
      toast({
        title: t("toasts.refreshFailedTitle"),
        description: getErrorMessage(error, t("toasts.refreshFailedDescription")),
        variant: "destructive",
      });
    },
  });

  const buildUpdatePayload = (currentUser: MeResponse): UpdateMeRequest => {
    const payload: UpdateMeRequest = {};
    const nextDisplayName = normalizeFormValue(formState.display_name);
    const nextEmail = normalizeFormValue(formState.email);
    const nextBio = normalizeFormValue(formState.bio);

    if ((currentUser.display_name?.trim() || null) !== nextDisplayName) {
      payload.display_name = nextDisplayName;
    }
    if ((currentUser.email?.trim() || null) !== nextEmail) {
      payload.email = nextEmail;
    }
    if ((currentUser.bio?.trim() || null) !== nextBio) {
      payload.bio = nextBio;
    }

    return payload;
  };

  const updateProfile = useMutation({
    mutationFn: (payload: UpdateMeRequest) =>
      apiClient<MeResponse>("/me", {
        method: "PATCH",
        body: JSON.stringify(payload),
      }),
    onSuccess: (updatedUser) => {
      updateUser(updatedUser);
      setLastSyncedAt(new Date());
      toast({
        title: t("toasts.updatedTitle"),
        description: t("toasts.updatedDescription"),
      });
    },
    onError: (error: unknown) => {
      toast({
        title: t("toasts.updateFailedTitle"),
        description: getErrorMessage(error, t("toasts.updateFailedDescription")),
        variant: "destructive",
      });
    },
  });

  const uploadAvatar = useMutation({
    mutationFn: async (file: File): Promise<string> => {
      if (!accessToken) {
        throw new Error(t("errors.signInBeforeUpload"));
      }

      const created = await apiClient<UploadCreateResponse>("/uploads", {
        method: "POST",
        body: JSON.stringify({
          filename: file.name,
          content_type: file.type || "application/octet-stream",
          size_bytes: file.size,
        }),
      });

      const uploadAccessToken = useAuthStore.getState().accessToken;
      if (!uploadAccessToken) {
        throw new Error(t("errors.signInBeforeUpload"));
      }

      const apiBaseUrl = getApiBaseUrl();
      const uploadUrl = /^https?:\/\//i.test(created.upload_url)
        ? created.upload_url
        : /^https?:\/\//i.test(apiBaseUrl)
          ? `${new URL(apiBaseUrl).origin}${created.upload_url.startsWith("/") ? created.upload_url : `/${created.upload_url}`}`
          : created.upload_url;

      const uploadHeaders = new Headers(created.headers || {});
      uploadHeaders.set("Authorization", `Bearer ${uploadAccessToken}`);
      if (!uploadHeaders.has("Content-Type")) {
        uploadHeaders.set("Content-Type", file.type || "application/octet-stream");
      }

      const putResponse = await fetch(uploadUrl, {
        method: created.method || "PUT",
        headers: uploadHeaders,
        body: file,
      });

      if (!putResponse.ok) {
        let message = t("errors.avatarUpload");
        try {
          const error = (await putResponse.json()) as { detail?: { message?: string } | string };
          if (typeof error.detail === "string") {
            message = error.detail;
          } else if (error.detail?.message) {
            message = error.detail.message;
          }
        } catch {
        }
        throw new Error(message);
      }

      const uploaded = (await putResponse.json()) as UploadContentResponse;
      const nextAvatarUrl = normalizeFormValue(uploaded.public_url || created.public_url || "");
      if (!nextAvatarUrl) {
        throw new Error(t("errors.avatarMissingUrl"));
      }
      return nextAvatarUrl;
    },
  });

  const avatarPreviewUrl = useMemo(() => {
    if (avatarFile) return URL.createObjectURL(avatarFile);
    return resolveApiMediaUrl(user?.avatar_url);
  }, [avatarFile, user?.avatar_url]);

  useEffect(() => {
    if (!avatarFile || !avatarPreviewUrl) return;
    return () => URL.revokeObjectURL(avatarPreviewUrl);
  }, [avatarFile, avatarPreviewUrl]);

  if (isInitializing) {
    return <ProfileSkeleton />;
  }

  if (!isAuthenticated || !user) return null;

  const updatePayload = buildUpdatePayload(user);
  const hasProfileChanges = Object.keys(updatePayload).length > 0 || Boolean(avatarFile);

  const displayName = user.display_name?.trim() || user.username;
  const initials =
    displayName
      .split(" ")
      .filter(Boolean)
      .slice(0, 2)
      .map((segment) => segment[0]?.toUpperCase() || "")
      .join("") || "U";

  const checklist: ProfileChecklistItem[] = [
    {
      id: "display_name",
      label: t("checklist.displayName.label"),
      hint: t("checklist.displayName.hint"),
      completed: Boolean(user.display_name?.trim()),
    },
    {
      id: "email",
      label: t("checklist.email.label"),
      hint: t("checklist.email.hint"),
      completed: Boolean(user.email?.trim()),
    },
    {
      id: "bio",
      label: t("checklist.bio.label"),
      hint: t("checklist.bio.hint"),
      completed: Boolean(user.bio?.trim()),
    },
    {
      id: "avatar",
      label: t("checklist.avatar.label"),
      hint: t("checklist.avatar.hint"),
      completed: Boolean(user.avatar_url?.trim()),
    },
  ];

  const completedItems = checklist.filter((item) => item.completed).length;
  const completion = Math.round((completedItems / checklist.length) * 100);

  const activeSessions = sessions.filter((session) => !session.revoked_at);
  const soonestSessionExpiry =
    activeSessions
      .map((session) => new Date(session.expires_at))
      .filter((date) => !Number.isNaN(date.getTime()))
      .sort((a, b) => a.getTime() - b.getTime())[0] || null;

  const profileRows = [
    { label: t("rows.userId"), value: user.id, copyValue: user.id },
    { label: t("rows.username"), value: `@${user.username}`, copyValue: user.username },
    {
      label: t("rows.displayName"),
      value: user.display_name?.trim() || t("empty.noDisplayName"),
      copyValue: user.display_name?.trim(),
    },
    {
      label: t("rows.email"),
      value: user.email?.trim() || t("empty.noEmail"),
      copyValue: user.email?.trim(),
    },
  ];

  const handleCopy = async (label: string, value?: string | null) => {
    const safeValue = value?.trim();
    if (!safeValue) {
      toast({
        title: t("toasts.copyMissingTitle", { label }),
        description: t("toasts.copyMissingDescription", { label }),
        variant: "destructive",
      });
      return;
    }

    try {
      await copyToClipboard(safeValue);
      toast({
        title: t("toasts.copiedTitle", { label }),
        description: t("toasts.copiedDescription"),
      });
    } catch (_error) {
      toast({
        title: t("toasts.copyFailedTitle"),
        description: t("toasts.clipboardBlocked"),
        variant: "destructive",
      });
    }
  };

  const handleDownloadProfile = () => {
    try {
      downloadProfileSnapshot(user, activeSessions.length);
      toast({
        title: t("toasts.exportedTitle"),
        description: t("toasts.exportedDescription"),
      });
    } catch (error) {
      toast({
        title: t("toasts.exportFailedTitle"),
        description: getErrorMessage(error, t("toasts.exportFailedDescription")),
        variant: "destructive",
      });
    }
  };

  const handleFormChange = (field: keyof ProfileFormState, value: string) => {
    setFormState((previous) => ({ ...previous, [field]: value }));
  };

  const handleResetForm = () => {
    setFormState({
      display_name: user.display_name ?? "",
      email: user.email ?? "",
      bio: user.bio ?? "",
    });
    setAvatarFile(null);
  };

  const handleSaveProfile = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const payload = buildUpdatePayload(user);
    if (avatarFile) {
      try {
        payload.avatar_url = await uploadAvatar.mutateAsync(avatarFile);
      } catch (error) {
        toast({
          title: t("toasts.avatarUploadFailedTitle"),
          description: getErrorMessage(error, t("toasts.avatarUploadFailedDescription")),
          variant: "destructive",
        });
        return;
      }
    }

    if (!Object.keys(payload).length) {
      toast({
        title: t("toasts.noChangesTitle"),
        description: t("toasts.noChangesDescription"),
      });
      return;
    }
    updateProfile.mutate(payload);
  };

  return (
    <div className="h-full min-h-0 overflow-y-auto bg-background p-6 text-foreground sm:p-8">
      <div className="mx-auto max-w-5xl space-y-6 pb-6">
        <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <Link href={localePath("/app")} className="text-primary text-sm font-medium hover:underline">{commonT("actions.backToApp")}</Link>
            <h1 className="mt-2 text-3xl font-bold tracking-tight">{t("title")}</h1>
            <p className="mt-1 text-muted-foreground">
              {t("description")}
            </p>
            <p className="mt-2 text-xs text-muted-foreground">
              {lastSyncedAt
                ? t("lastSynced", { value: formatDateTimeLocalized(lastSyncedAt, locale, commonT("notAvailable")) })
                : t("lastServerUpdate", {
                    value: formatRelativeTimeStrictLocalized(user.updated_at, locale, t("noUpdatesYet")),
                  })}
            </p>
          </div>
        </div>

        <Card className="overflow-hidden rounded-3xl border-border/60 bg-card/90 shadow-xl">
          <div className="bg-gradient-to-r from-primary/15 via-primary/5 to-transparent p-6 sm:p-8">
            <div className="flex flex-col gap-6 lg:flex-row lg:items-center lg:justify-between">
              <div className="flex items-center gap-4">
                <Avatar className="h-24 w-24 border-4 border-background shadow-lg">
                  <AvatarImage src={avatarPreviewUrl} />
                  <AvatarFallback className="text-2xl font-bold">{initials}</AvatarFallback>
                </Avatar>
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge variant="secondary">{t("badges.personal")}</Badge>
                    <Badge>{t("badges.complete", { percent: completion })}</Badge>
                    <Badge variant="outline">{t("badges.activeSessions", { count: activeSessions.length })}</Badge>
                  </div>
                  <h2 className="mt-3 truncate text-3xl font-bold">{displayName}</h2>
                  <p className="text-muted-foreground">@{user.username}</p>
                  <p className="mt-3 max-w-2xl text-sm leading-6 text-muted-foreground">
                    {user.bio?.trim() || t("empty.noBio")}
                  </p>
                </div>
              </div>

              <div className="flex flex-wrap gap-2">
                <Link href={localePath("/app/delivery")} className={buttonVariants({ variant: "outline" })}>
                  <Activity className="mr-2 h-4 w-4" />
                  {t("actions.deliveryMonitor")}
                </Link>
                <Button variant="secondary" onClick={() => void handleCopy(t("rows.username"), user.username)}>
                  <Copy className="mr-2 h-4 w-4" />
                  {t("actions.copyUsername")}
                </Button>
              </div>
            </div>
          </div>

          <div className="grid gap-4 p-6 sm:grid-cols-2 lg:grid-cols-4">
            <Card className="rounded-2xl p-4">
              <div className="flex items-center gap-2 text-muted-foreground">
                <UserCircle2 className="h-4 w-4" />
                <span className="text-xs uppercase tracking-[0.18em]">{t("stats.profileHealth")}</span>
              </div>
              <p className="mt-2 text-xl font-semibold">{completion}%</p>
              <Progress value={completion} className="mt-3 h-2" />
            </Card>

            <Card className="rounded-2xl p-4">
              <div className="flex items-center gap-2 text-muted-foreground">
                <Clock3 className="h-4 w-4" />
                <span className="text-xs uppercase tracking-[0.18em]">{t("stats.memberSince")}</span>
              </div>
              <p className="mt-2 font-semibold">{formatDateLocalized(user.created_at, locale, commonT("notAvailable"))}</p>
              <p className="mt-2 text-xs text-muted-foreground">{formatRelativeTimeStrictLocalized(user.created_at, locale, commonT("unknown"))}</p>
            </Card>

            <Card className="rounded-2xl p-4">
              <div className="flex items-center gap-2 text-muted-foreground">
                <Mail className="h-4 w-4" />
                <span className="text-xs uppercase tracking-[0.18em]">{t("stats.emailStatus")}</span>
              </div>
              <p className="mt-2 font-semibold">{user.email?.trim() ? t("status.configured") : t("status.missing")}</p>
              <p className="mt-2 text-xs text-muted-foreground break-all">{user.email?.trim() || t("empty.noEmailAddress")}</p>
            </Card>

            <Card className="rounded-2xl p-4">
              <div className="flex items-center gap-2 text-muted-foreground">
                <ShieldCheck className="h-4 w-4" />
                <span className="text-xs uppercase tracking-[0.18em]">{t("stats.security")}</span>
              </div>
              <p className="mt-2 font-semibold">
                {isSessionsLoading ? t("status.checkingSessions") : t("status.activeCount", { count: activeSessions.length })}
              </p>
              <p className="mt-2 text-xs text-muted-foreground">
                {soonestSessionExpiry
                  ? t("status.nextExpiration", {
                      value: formatDateTimeLocalized(soonestSessionExpiry, locale, commonT("notAvailable")),
                    })
                  : t("status.noActiveSessions")}
              </p>
            </Card>
          </div>

          <div className="border-t border-border/60 p-6">
            <Tabs defaultValue="overview" className="w-full">
              <TabsList className="mb-4 w-full justify-start overflow-x-auto">
                <TabsTrigger value="overview">{t("tabs.overview")}</TabsTrigger>
                <TabsTrigger value="security">{t("tabs.security")}</TabsTrigger>
              </TabsList>

              <TabsContent value="overview" className="mt-0">
                <div className="grid gap-4 lg:grid-cols-[1.15fr_0.85fr]">
                  <Card className="rounded-2xl p-5">
                    <h3 className="text-lg font-semibold">{t("sections.accountDetails")}</h3>
                    <div className="mt-4 space-y-3">
                      {profileRows.map((row) => (
                        <div key={row.label} className="rounded-xl border border-border/60 bg-background/40 p-3">
                          <div className="flex items-start justify-between gap-3">
                            <div className="min-w-0">
                              <p className="text-xs uppercase tracking-[0.14em] text-muted-foreground">{row.label}</p>
                              <p className="mt-1 break-all text-sm font-medium">{row.value}</p>
                            </div>
                            {row.copyValue ? (
                              <Button
                                size="icon"
                                variant="ghost"
                                onClick={() => void handleCopy(row.label, row.copyValue)}
                                aria-label={t("actions.copyLabel", { label: row.label })}
                              >
                                <Copy className="h-4 w-4" />
                              </Button>
                            ) : null}
                          </div>
                        </div>
                      ))}

                      <div className="rounded-xl border border-border/60 bg-background/40 p-3">
                        <p className="text-xs uppercase tracking-[0.14em] text-muted-foreground">{t("rows.bio")}</p>
                        <p className="mt-1 whitespace-pre-wrap text-sm font-medium">
                          {user.bio?.trim() || t("empty.noBio")}
                        </p>
                      </div>
                    </div>
                  </Card>

                  <Card className="rounded-2xl p-5">
                    <h3 className="text-lg font-semibold">{t("sections.completionChecklist")}</h3>
                    <p className="mt-2 text-sm text-muted-foreground">
                      {t("completionSummary", { completed: completedItems, total: checklist.length })}
                    </p>
                    <Progress value={completion} className="mt-4 h-2" />

                    <div className="mt-4 space-y-3">
                      {checklist.map((item) => (
                        <div key={item.id} className="flex items-center gap-3 rounded-xl border border-border/60 p-3">
                          {item.completed ? (
                            <CheckCircle2 className="h-4 w-4 shrink-0 text-emerald-500" />
                          ) : (
                            <CircleDashed className="h-4 w-4 shrink-0 text-muted-foreground" />
                          )}
                          <div className="min-w-0">
                            <p className="text-sm font-medium">{item.label}</p>
                            <p className="text-xs text-muted-foreground">{item.hint}</p>
                          </div>
                          <Badge variant={item.completed ? "default" : "outline"} className="ml-auto">
                            {item.completed ? t("status.done") : t("status.missing")}
                          </Badge>
                        </div>
                      ))}
                    </div>
                  </Card>
                </div>
              </TabsContent>

              <TabsContent value="security" className="mt-0">
                <div className="grid gap-4 lg:grid-cols-2">
                  <Card className="rounded-2xl p-5">
                    <h3 className="text-lg font-semibold">{t("sections.sessionStatus")}</h3>
                    <p className="mt-2 text-sm text-muted-foreground">
                      {t("sessionDescription")}
                    </p>

                    <div className="mt-4 space-y-3 text-sm">
                      <div className="flex items-center justify-between gap-4">
                        <span className="text-muted-foreground">{t("sessionRows.activeSessions")}</span>
                        <span className="font-medium">
                          {isSessionsLoading ? commonT("loading") : activeSessions.length}
                        </span>
                      </div>
                      <div className="flex items-center justify-between gap-4">
                        <span className="text-muted-foreground">{t("sessionRows.nextExpiry")}</span>
                        <span className="text-right font-medium">
                          {soonestSessionExpiry
                            ? formatDateTimeLocalized(soonestSessionExpiry, locale, commonT("notAvailable"))
                            : commonT("notAvailable")}
                        </span>
                      </div>
                      <div className="flex items-center justify-between gap-4">
                        <span className="text-muted-foreground">{t("sessionRows.lastProfileUpdate")}</span>
                        <span className="font-medium">{formatDateTimeLocalized(user.updated_at, locale, t("noUpdatesYet"))}</span>
                      </div>
                    </div>

                    <div className="mt-5">
                      <Link href={localePath("/settings/sessions")}>
                        <Button className="w-full">
                          <ShieldCheck className="mr-2 h-4 w-4" />
                          {t("actions.openSessionSettings")}
                        </Button>
                      </Link>
                    </div>
                  </Card>

                  <Card className="rounded-2xl p-5">
                    <h3 className="text-lg font-semibold">{t("sections.editProfile")}</h3>
                    <p className="mt-2 text-sm text-muted-foreground">
                      {t("editDescription")}
                    </p>
                    <form className="mt-4 space-y-3" onSubmit={handleSaveProfile}>
                      <div>
                        <label htmlFor="display-name" className="text-xs uppercase tracking-[0.14em] text-muted-foreground">
                          {t("fields.displayName")}
                        </label>
                        <Input
                          id="display-name"
                          value={formState.display_name}
                          onChange={(event) => handleFormChange("display_name", event.target.value)}
                          placeholder={t("fields.displayNamePlaceholder")}
                          maxLength={128}
                        />
                      </div>
                      <div>
                        <label htmlFor="email" className="text-xs uppercase tracking-[0.14em] text-muted-foreground">
                          {t("fields.email")}
                        </label>
                        <Input
                          id="email"
                          type="email"
                          value={formState.email}
                          onChange={(event) => handleFormChange("email", event.target.value)}
                          placeholder={t("fields.emailPlaceholder")}
                        />
                      </div>
                      <div>
                        <label htmlFor="avatar-file" className="text-xs uppercase tracking-[0.14em] text-muted-foreground">
                          {t("fields.profilePicture")}
                        </label>
                        <Input
                          id="avatar-file"
                          type="file"
                          accept="image/*"
                          onChange={(event) => {
                            const file = event.target.files?.[0] ?? null;
                            setAvatarFile(file);
                          }}
                        />
                        <p className="mt-1 text-xs text-muted-foreground">
                          {avatarFile ? t("fields.selectedFile", { name: avatarFile.name }) : t("fields.avatarHint")}
                        </p>
                        {avatarFile && avatarPreviewUrl ? (
                          <div className="mt-2">
                            <img
                              src={avatarPreviewUrl}
                              alt={t("fields.avatarPreviewAlt")}
                              className="h-16 w-16 rounded-full border border-border/70 object-cover"
                            />
                          </div>
                        ) : null}
                      </div>
                      <div>
                        <label htmlFor="bio" className="text-xs uppercase tracking-[0.14em] text-muted-foreground">
                          {t("fields.bio")}
                        </label>
                        <Textarea
                          id="bio"
                          value={formState.bio}
                          onChange={(event) => handleFormChange("bio", event.target.value)}
                          placeholder={t("fields.bioPlaceholder")}
                          maxLength={2000}
                          rows={4}
                        />
                      </div>
                      <div className="flex flex-wrap gap-2">
                        <Button type="submit" disabled={updateProfile.isPending || uploadAvatar.isPending || !hasProfileChanges}>
                          {updateProfile.isPending || uploadAvatar.isPending ? commonT("actions.saving") : t("actions.saveChanges")}
                        </Button>
                        <Button
                          type="button"
                          variant="outline"
                          onClick={handleResetForm}
                          disabled={updateProfile.isPending || uploadAvatar.isPending || !hasProfileChanges}
                        >
                          {commonT("actions.reset")}
                        </Button>
                      </div>
                    </form>
                  </Card>
                </div>
              </TabsContent>
            </Tabs>
          </div>
        </Card>
      </div>
    </div>
  );
}
