"use client";

import Link from "next/link";
import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useMutation, useQuery } from "@tanstack/react-query";
import { toast } from "sonner";
import { api, ApiError } from "@/lib/api-client";
import { queryKeys } from "@/lib/query-keys";
import { useAuthBootstrap } from "@/hooks/use-auth-bootstrap";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";

export function InviteClientPage({ token }: { token: string }) {
  const router = useRouter();
  const { status } = useAuthBootstrap();

  const previewQuery = useQuery({
    queryKey: queryKeys.invite(token),
    queryFn: () => api.invitePreview(token),
  });

  const acceptMutation = useMutation({
    mutationFn: () => api.acceptInvite(token),
    onSuccess: (result) => {
      toast.success("Invite accepted");
      router.push(`/app/channels/${result.channel_id}`);
    },
    onError: (error) => toast.error(error instanceof ApiError ? error.message : "Failed to accept invite"),
  });

  useEffect(() => {
    if (status === "unauthenticated") {
      toast.error("Please login first");
      router.replace(`/login?next=${encodeURIComponent(`/invites/${token}`)}`);
    }
  }, [status, router, token]);

  const data = previewQuery.data;

  return (
    <main className="grid min-h-screen place-items-center p-4">
      <Card className="w-full max-w-lg">
        <CardHeader>
          <h1 className="text-xl font-semibold">Invite</h1>
        </CardHeader>
        <CardContent className="space-y-3">
          {previewQuery.isLoading ? <p>Loading invite...</p> : null}
          {data ? (
            <>
              <p className="text-sm">Valid: {data.is_valid ? "yes" : "no"}</p>
              <p className="text-sm">Channel: {data.channel?.name ?? "Unknown"}</p>
              {data.reason ? <p className="text-sm text-red-500">Reason: {data.reason}</p> : null}
            </>
          ) : null}

          <div className="flex gap-2">
            <Button onClick={() => acceptMutation.mutate()} disabled={!data?.is_valid || acceptMutation.isPending}>
              Accept invite
            </Button>
            <Link href="/app">
              <Button variant="secondary">Go to app</Button>
            </Link>
          </div>
        </CardContent>
      </Card>
    </main>
  );
}
