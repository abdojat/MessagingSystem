import { FormEvent, useEffect, useMemo, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { format, formatDistanceToNowStrict } from "date-fns";
import {
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
import { Link, Redirect } from "wouter";

import { useSessions } from "../hooks/use-auth";
import { toast } from "../hooks/use-toast";
import { Avatar, AvatarFallback, AvatarImage } from "../components/ui/avatar";
import { Badge } from "../components/ui/badge";
import { Button } from "../components/ui/button";
import { Card } from "../components/ui/card";
import { Input } from "../components/ui/input";
import { Progress } from "../components/ui/progress";
import { Skeleton } from "../components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "../components/ui/tabs";
import { Textarea } from "../components/ui/textarea";
import { apiClient } from "../lib/apiClient";
import { getApiBaseUrl } from "../lib/runtimeConfig";
import { useAuthStore } from "../store/authStore";
import type { MeResponse, UpdateMeRequest } from "../types/api";

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

function formatDate(value?: string | null, fallback = "Not available") {
  if (!value) return fallback;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return fallback;
  return format(date, "PPP");
}

function formatDateTime(value?: string | null, fallback = "Not available") {
  if (!value) return fallback;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return fallback;
  return format(date, "PPP p");
}

function formatRelativeTime(value?: string | null, fallback = "No updates yet") {
  if (!value) return fallback;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return fallback;
  return `${formatDistanceToNowStrict(date)} ago`;
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

  const refreshProfile = useMutation({
    mutationFn: () => apiClient<MeResponse>("/me"),
    onSuccess: (freshUser) => {
      updateUser(freshUser);
      setLastSyncedAt(new Date());
      toast({
        title: "Profile refreshed",
        description: "Your account details are now synced with the latest server data.",
      });
    },
    onError: (error: unknown) => {
      toast({
        title: "Refresh failed",
        description: getErrorMessage(error, "We couldn't refresh your profile right now."),
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
        title: "Profile updated",
        description: "Your profile changes were saved successfully.",
      });
    },
    onError: (error: unknown) => {
      toast({
        title: "Update failed",
        description: getErrorMessage(error, "We couldn't save your profile changes."),
        variant: "destructive",
      });
    },
  });

  const uploadAvatar = useMutation({
    mutationFn: async (file: File): Promise<string> => {
      if (!accessToken) {
        throw new Error("You need to be signed in before uploading a profile image.");
      }

      const created = await apiClient<UploadCreateResponse>("/uploads", {
        method: "POST",
        body: JSON.stringify({
          filename: file.name,
          content_type: file.type || "application/octet-stream",
          size_bytes: file.size,
        }),
      });

      const apiBaseUrl = getApiBaseUrl();
      const uploadUrl = /^https?:\/\//i.test(created.upload_url)
        ? created.upload_url
        : /^https?:\/\//i.test(apiBaseUrl)
          ? `${new URL(apiBaseUrl).origin}${created.upload_url.startsWith("/") ? created.upload_url : `/${created.upload_url}`}`
          : created.upload_url;

      const uploadHeaders = new Headers(created.headers || {});
      uploadHeaders.set("Authorization", `Bearer ${accessToken}`);
      if (!uploadHeaders.has("Content-Type")) {
        uploadHeaders.set("Content-Type", file.type || "application/octet-stream");
      }

      const putResponse = await fetch(uploadUrl, {
        method: created.method || "PUT",
        headers: uploadHeaders,
        body: file,
      });

      if (!putResponse.ok) {
        let message = "Could not upload avatar image.";
        try {
          const error = (await putResponse.json()) as { detail?: { message?: string } | string };
          if (typeof error.detail === "string") {
            message = error.detail;
          } else if (error.detail?.message) {
            message = error.detail.message;
          }
        } catch {
          // Keep default message.
        }
        throw new Error(message);
      }

      const uploaded = (await putResponse.json()) as UploadContentResponse;
      const nextAvatarUrl = normalizeFormValue(uploaded.public_url || created.public_url || "");
      if (!nextAvatarUrl) {
        throw new Error("Upload succeeded but no avatar URL was returned.");
      }
      return nextAvatarUrl;
    },
  });

  if (isInitializing) {
    return <ProfileSkeleton />;
  }

  if (!isAuthenticated || !user) {
    return <Redirect to="/login" />;
  }

  const updatePayload = buildUpdatePayload(user);
  const hasProfileChanges = Object.keys(updatePayload).length > 0 || Boolean(avatarFile);

  const avatarPreviewUrl = useMemo(() => {
    if (avatarFile) return URL.createObjectURL(avatarFile);
    return user.avatar_url || undefined;
  }, [avatarFile, user.avatar_url]);

  useEffect(() => {
    if (!avatarFile || !avatarPreviewUrl) return;
    return () => URL.revokeObjectURL(avatarPreviewUrl);
  }, [avatarFile, avatarPreviewUrl]);

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
      label: "Display name",
      hint: "Makes your identity clearer across channels and mentions.",
      completed: Boolean(user.display_name?.trim()),
    },
    {
      id: "email",
      label: "Email address",
      hint: "Required for account recovery and invite flows.",
      completed: Boolean(user.email?.trim()),
    },
    {
      id: "bio",
      label: "Bio",
      hint: "Adds role context so teammates know what you own.",
      completed: Boolean(user.bio?.trim()),
    },
    {
      id: "avatar",
      label: "Avatar image",
      hint: "Helps teammates find you quickly in busy conversations.",
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
    { label: "User ID", value: user.id, copyValue: user.id },
    { label: "Username", value: `@${user.username}`, copyValue: user.username },
    {
      label: "Display name",
      value: user.display_name?.trim() || "No display name set",
      copyValue: user.display_name?.trim(),
    },
    {
      label: "Email",
      value: user.email?.trim() || "No email on record",
      copyValue: user.email?.trim(),
    },
    {
      label: "Avatar URL",
      value: user.avatar_url?.trim() || "No avatar URL set",
      copyValue: user.avatar_url?.trim(),
    },
  ];

  const handleCopy = async (label: string, value?: string | null) => {
    const safeValue = value?.trim();
    if (!safeValue) {
      toast({
        title: `No ${label.toLowerCase()} available`,
        description: `Set ${label.toLowerCase()} first, then try again.`,
        variant: "destructive",
      });
      return;
    }

    try {
      await copyToClipboard(safeValue);
      toast({
        title: `${label} copied`,
        description: "It is now in your clipboard.",
      });
    } catch (error) {
      toast({
        title: "Copy failed",
        description: getErrorMessage(error, "Clipboard access was blocked by the browser."),
        variant: "destructive",
      });
    }
  };

  const handleDownloadProfile = () => {
    try {
      downloadProfileSnapshot(user, activeSessions.length);
      toast({
        title: "Profile exported",
        description: "A JSON snapshot has been downloaded.",
      });
    } catch (error) {
      toast({
        title: "Export failed",
        description: getErrorMessage(error, "The profile snapshot could not be generated."),
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
          title: "Avatar upload failed",
          description: getErrorMessage(error, "We couldn't upload your profile image."),
          variant: "destructive",
        });
        return;
      }
    }

    if (!Object.keys(payload).length) {
      toast({
        title: "No changes to save",
        description: "Update a field first, then try again.",
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
            <Link href="/app" className="text-primary text-sm font-medium hover:underline">&larr; Back to App</Link>
            <h1 className="mt-2 text-3xl font-bold tracking-tight">Profile</h1>
            <p className="mt-1 text-muted-foreground">
              Review your account details, monitor profile health.
            </p>
            <p className="mt-2 text-xs text-muted-foreground">
              {lastSyncedAt
                ? `Last synced ${format(lastSyncedAt, "PPP p")}`
                : `Last server update ${formatRelativeTime(user.updated_at)}`}
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
                    <Badge variant="secondary">Personal profile</Badge>
                    <Badge>{completion}% complete</Badge>
                    <Badge variant="outline">{activeSessions.length} active sessions</Badge>
                  </div>
                  <h2 className="mt-3 truncate text-3xl font-bold">{displayName}</h2>
                  <p className="text-muted-foreground">@{user.username}</p>
                  <p className="mt-3 max-w-2xl text-sm leading-6 text-muted-foreground">
                    {user.bio?.trim() || "No bio set yet."}
                  </p>
                </div>
              </div>

              <div className="flex flex-wrap gap-2">
                <Button variant="secondary" onClick={() => void handleCopy("Username", user.username)}>
                  <Copy className="mr-2 h-4 w-4" />
                  Copy Username
                </Button>
              </div>
            </div>
          </div>

          <div className="grid gap-4 p-6 sm:grid-cols-2 lg:grid-cols-4">
            <Card className="rounded-2xl p-4">
              <div className="flex items-center gap-2 text-muted-foreground">
                <UserCircle2 className="h-4 w-4" />
                <span className="text-xs uppercase tracking-[0.18em]">Profile health</span>
              </div>
              <p className="mt-2 text-xl font-semibold">{completion}%</p>
              <Progress value={completion} className="mt-3 h-2" />
            </Card>

            <Card className="rounded-2xl p-4">
              <div className="flex items-center gap-2 text-muted-foreground">
                <Clock3 className="h-4 w-4" />
                <span className="text-xs uppercase tracking-[0.18em]">Member since</span>
              </div>
              <p className="mt-2 font-semibold">{formatDate(user.created_at)}</p>
              <p className="mt-2 text-xs text-muted-foreground">{formatRelativeTime(user.created_at, "Unknown")}</p>
            </Card>

            <Card className="rounded-2xl p-4">
              <div className="flex items-center gap-2 text-muted-foreground">
                <Mail className="h-4 w-4" />
                <span className="text-xs uppercase tracking-[0.18em]">Email status</span>
              </div>
              <p className="mt-2 font-semibold">{user.email?.trim() ? "Configured" : "Missing"}</p>
              <p className="mt-2 text-xs text-muted-foreground break-all">{user.email?.trim() || "No email address on record."}</p>
            </Card>

            <Card className="rounded-2xl p-4">
              <div className="flex items-center gap-2 text-muted-foreground">
                <ShieldCheck className="h-4 w-4" />
                <span className="text-xs uppercase tracking-[0.18em]">Security</span>
              </div>
              <p className="mt-2 font-semibold">
                {isSessionsLoading ? "Checking sessions..." : `${activeSessions.length} active`}
              </p>
              <p className="mt-2 text-xs text-muted-foreground">
                {soonestSessionExpiry
                  ? `Next expiration ${format(soonestSessionExpiry, "PPP p")}`
                  : "No active sessions found."}
              </p>
            </Card>
          </div>

          <div className="border-t border-border/60 p-6">
            <Tabs defaultValue="overview" className="w-full">
              <TabsList className="mb-4 w-full justify-start overflow-x-auto">
                <TabsTrigger value="overview">Overview</TabsTrigger>
                <TabsTrigger value="security">Security</TabsTrigger>
              </TabsList>

              <TabsContent value="overview" className="mt-0">
                <div className="grid gap-4 lg:grid-cols-[1.15fr_0.85fr]">
                  <Card className="rounded-2xl p-5">
                    <h3 className="text-lg font-semibold">Account details</h3>
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
                                aria-label={`Copy ${row.label}`}
                              >
                                <Copy className="h-4 w-4" />
                              </Button>
                            ) : null}
                          </div>
                        </div>
                      ))}

                      <div className="rounded-xl border border-border/60 bg-background/40 p-3">
                        <p className="text-xs uppercase tracking-[0.14em] text-muted-foreground">Bio</p>
                        <p className="mt-1 whitespace-pre-wrap text-sm font-medium">
                          {user.bio?.trim() || "No bio set yet."}
                        </p>
                      </div>
                    </div>
                  </Card>

                  <Card className="rounded-2xl p-5">
                    <h3 className="text-lg font-semibold">Completion checklist</h3>
                    <p className="mt-2 text-sm text-muted-foreground">
                      {completedItems} of {checklist.length} key profile fields are currently filled.
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
                            {item.completed ? "Done" : "Missing"}
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
                    <h3 className="text-lg font-semibold">Session status</h3>
                    <p className="mt-2 text-sm text-muted-foreground">
                      Keep this list clean to reduce account exposure on old or shared devices.
                    </p>

                    <div className="mt-4 space-y-3 text-sm">
                      <div className="flex items-center justify-between gap-4">
                        <span className="text-muted-foreground">Active sessions</span>
                        <span className="font-medium">
                          {isSessionsLoading ? "Loading..." : activeSessions.length}
                        </span>
                      </div>
                      <div className="flex items-center justify-between gap-4">
                        <span className="text-muted-foreground">Next session expiry</span>
                        <span className="text-right font-medium">
                          {soonestSessionExpiry ? format(soonestSessionExpiry, "PPP p") : "Not available"}
                        </span>
                      </div>
                      <div className="flex items-center justify-between gap-4">
                        <span className="text-muted-foreground">Last profile update</span>
                        <span className="font-medium">{formatDateTime(user.updated_at, "No updates yet")}</span>
                      </div>
                    </div>

                    <div className="mt-5">
                      <Link href="/settings/sessions">
                        <Button className="w-full">
                          <ShieldCheck className="mr-2 h-4 w-4" />
                          Open Session Settings
                        </Button>
                      </Link>
                    </div>
                  </Card>

                  <Card className="rounded-2xl p-5">
                    <h3 className="text-lg font-semibold">Edit profile</h3>
                    <p className="mt-2 text-sm text-muted-foreground">
                      Keep your identity details accurate for mentions, invites, and teammates.
                    </p>
                    <form className="mt-4 space-y-3" onSubmit={handleSaveProfile}>
                      <div>
                        <label htmlFor="display-name" className="text-xs uppercase tracking-[0.14em] text-muted-foreground">
                          Display name
                        </label>
                        <Input
                          id="display-name"
                          value={formState.display_name}
                          onChange={(event) => handleFormChange("display_name", event.target.value)}
                          placeholder="How your name appears in chats"
                          maxLength={128}
                        />
                      </div>
                      <div>
                        <label htmlFor="email" className="text-xs uppercase tracking-[0.14em] text-muted-foreground">
                          Email
                        </label>
                        <Input
                          id="email"
                          type="email"
                          value={formState.email}
                          onChange={(event) => handleFormChange("email", event.target.value)}
                          placeholder="name@example.com"
                        />
                      </div>
                      <div>
                        <label htmlFor="avatar-file" className="text-xs uppercase tracking-[0.14em] text-muted-foreground">
                          Profile picture
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
                          {avatarFile ? `Selected: ${avatarFile.name}` : "Upload an image to use as your avatar."}
                        </p>
                      </div>
                      <div>
                        <label htmlFor="bio" className="text-xs uppercase tracking-[0.14em] text-muted-foreground">
                          Bio
                        </label>
                        <Textarea
                          id="bio"
                          value={formState.bio}
                          onChange={(event) => handleFormChange("bio", event.target.value)}
                          placeholder="Share your role, focus, or current responsibilities."
                          maxLength={2000}
                          rows={4}
                        />
                      </div>
                      <div className="flex flex-wrap gap-2">
                        <Button type="submit" disabled={updateProfile.isPending || uploadAvatar.isPending || !hasProfileChanges}>
                          {updateProfile.isPending || uploadAvatar.isPending ? "Saving..." : "Save Changes"}
                        </Button>
                        <Button
                          type="button"
                          variant="outline"
                          onClick={handleResetForm}
                          disabled={updateProfile.isPending || uploadAvatar.isPending || !hasProfileChanges}
                        >
                          Reset
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
