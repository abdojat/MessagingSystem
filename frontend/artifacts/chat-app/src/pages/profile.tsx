import { Link, Redirect } from "wouter";
import { format } from "date-fns";
import { Avatar, AvatarFallback, AvatarImage } from "../components/ui/avatar";
import { Badge } from "../components/ui/badge";
import { Button } from "../components/ui/button";
import { Card } from "../components/ui/card";
import { useAuthStore } from "../store/authStore";

function formatDate(value?: string | null, fallback = "Not available") {
  if (!value) return fallback;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return fallback;
  return format(date, "PPP");
}

export default function ProfilePage() {
  const user = useAuthStore((state) => state.user);
  const isAuthenticated = useAuthStore((state) => state.isAuthenticated);
  const isInitializing = useAuthStore((state) => state.isInitializing);

  if (isInitializing) {
    return <div className="flex h-full w-full items-center justify-center bg-background"><div className="w-8 h-8 border-4 border-primary border-t-transparent rounded-full animate-spin" /></div>;
  }

  if (!isAuthenticated || !user) {
    return <Redirect to="/login" />;
  }

  const displayName = user.display_name || user.username;
  const initials = displayName.trim().charAt(0).toUpperCase() || "U";
  const completeness = Math.round(([user.display_name, user.email, user.bio, user.avatar_url].filter(Boolean).length / 4) * 100);

  return (
    <div className="h-full min-h-0 overflow-y-auto bg-background p-6 text-foreground sm:p-8">
      <div className="mx-auto max-w-5xl space-y-6">
        <div className="flex items-center justify-between gap-4">
          <div>
            <Link href="/app" className="text-primary text-sm font-medium hover:underline">&larr; Back to App</Link>
            <h1 className="mt-2 text-3xl font-bold tracking-tight">Profile</h1>
            <p className="mt-1 text-muted-foreground">Your account details from the current session.</p>
          </div>
          <Link href="/settings/sessions">
            <Button variant="outline">Manage Sessions</Button>
          </Link>
        </div>

        <Card className="overflow-hidden rounded-3xl border-border/60 bg-card/90 shadow-xl">
          <div className="bg-gradient-to-r from-primary/15 via-primary/5 to-transparent p-6 sm:p-8">
            <div className="flex flex-col gap-6 sm:flex-row sm:items-center sm:justify-between">
              <div className="flex items-center gap-4">
                <Avatar className="h-24 w-24 border-4 border-background shadow-lg">
                  <AvatarImage src={user.avatar_url || undefined} />
                  <AvatarFallback className="text-2xl font-bold">{initials}</AvatarFallback>
                </Avatar>
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge variant="secondary">Personal profile</Badge>
                    <Badge>{completeness}% complete</Badge>
                  </div>
                  <h2 className="mt-3 truncate text-3xl font-bold">{displayName}</h2>
                  <p className="text-muted-foreground">@{user.username}</p>
                  <p className="mt-3 max-w-2xl text-sm leading-6 text-muted-foreground">
                    {user.bio?.trim() || "Add a bio when profile editing is available so teammates can quickly recognize your role."}
                  </p>
                </div>
              </div>
            </div>
          </div>

          <div className="grid gap-4 p-6 sm:grid-cols-2 lg:grid-cols-4">
            <Card className="rounded-2xl p-4">
              <p className="text-xs uppercase tracking-[0.18em] text-muted-foreground">Username</p>
              <p className="mt-2 font-semibold">{user.username}</p>
            </Card>
            <Card className="rounded-2xl p-4">
              <p className="text-xs uppercase tracking-[0.18em] text-muted-foreground">Email</p>
              <p className="mt-2 font-semibold break-all">{user.email || "No email on record"}</p>
            </Card>
            <Card className="rounded-2xl p-4">
              <p className="text-xs uppercase tracking-[0.18em] text-muted-foreground">Created</p>
              <p className="mt-2 font-semibold">{formatDate(user.created_at)}</p>
            </Card>
            <Card className="rounded-2xl p-4">
              <p className="text-xs uppercase tracking-[0.18em] text-muted-foreground">Last updated</p>
              <p className="mt-2 font-semibold">{formatDate(user.updated_at, "No updates yet")}</p>
            </Card>
          </div>

          <div className="grid gap-4 border-t border-border/60 p-6 lg:grid-cols-[1.2fr_0.8fr]">
            <Card className="rounded-2xl p-5">
              <h3 className="text-lg font-semibold">Account details</h3>
              <div className="mt-4 space-y-4 text-sm">
                <div>
                  <p className="text-muted-foreground">Display name</p>
                  <p className="mt-1 font-medium">{user.display_name || "No display name yet"}</p>
                </div>
                <div>
                  <p className="text-muted-foreground">Bio</p>
                  <p className="mt-1 whitespace-pre-wrap font-medium">{user.bio || "No bio yet"}</p>
                </div>
                <div>
                  <p className="text-muted-foreground">Avatar URL</p>
                  <p className="mt-1 break-all font-medium">{user.avatar_url || "No avatar set"}</p>
                </div>
              </div>
            </Card>

            <Card className="rounded-2xl p-5">
              <h3 className="text-lg font-semibold">Editing status</h3>
              <p className="mt-3 text-sm leading-6 text-muted-foreground">
                This page is read-only right now. It restores profile access in the current app, while session management stays under settings.
              </p>
              <div className="mt-4">
                <Link href="/settings/sessions">
                  <Button className="w-full">Open Session Settings</Button>
                </Link>
              </div>
            </Card>
          </div>
        </Card>
      </div>
    </div>
  );
}
