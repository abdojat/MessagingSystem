"use client";

import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { useAuthBootstrap } from "@/hooks/use-auth-bootstrap";
import { api, ApiError } from "@/lib/api-client";
import { queryKeys } from "@/lib/query-keys";
import { formatDateTime } from "@/lib/utils";
import { useAuthStore } from "@/store/auth-store";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";

export default function SessionsPage() {
  const queryClient = useQueryClient();
  useAuthBootstrap();
  const clearAuth = useAuthStore((s) => s.clearAuth);

  const sessionsQuery = useQuery({
    queryKey: queryKeys.sessions,
    queryFn: api.sessions,
  });

  const revokeMutation = useMutation({
    mutationFn: (sessionId: string) => api.revokeSession(sessionId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: queryKeys.sessions }),
    onError: (error) => toast.error(error instanceof ApiError ? error.message : "Failed to revoke session"),
  });

  const logoutAllMutation = useMutation({
    mutationFn: api.logoutAll,
    onSuccess: () => {
      clearAuth();
      toast.success("All sessions logged out");
    },
    onError: (error) => toast.error(error instanceof ApiError ? error.message : "Failed to logout all"),
  });

  return (
    <main className="mx-auto min-h-screen max-w-3xl p-6">
      <div className="mb-4 flex items-center justify-between">
        <h1 className="text-2xl font-semibold">Sessions</h1>
        <Link href="/app" className="text-sm underline">
          Back to app
        </Link>
      </div>

      <Card>
        <CardHeader className="flex items-center justify-between">
          <span>Active sessions</span>
          <Button variant="danger" size="sm" onClick={() => logoutAllMutation.mutate()}>
            Logout all
          </Button>
        </CardHeader>
        <CardContent className="space-y-2">
          {(sessionsQuery.data?.items ?? []).map((session) => (
            <div key={session.id} className="flex items-center justify-between rounded-md border border-slate-200 p-3 text-sm dark:border-slate-800">
              <div>
                <p>{session.user_agent || "Unknown agent"}</p>
                <p className="text-xs text-slate-500">
                  {session.ip || "No IP"} • expires {formatDateTime(session.expires_at)}
                </p>
              </div>
              <Button size="sm" variant="ghost" onClick={() => revokeMutation.mutate(session.id)}>
                Revoke
              </Button>
            </div>
          ))}
          {sessionsQuery.data?.items.length === 0 ? <p className="text-sm text-slate-500">No sessions found.</p> : null}
        </CardContent>
      </Card>
    </main>
  );
}

