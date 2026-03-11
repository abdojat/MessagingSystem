"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { AppShell } from "@/components/layout/app-shell";
import { useAuthBootstrap } from "@/hooks/use-auth-bootstrap";
import { api } from "@/lib/api-client";
import { queryKeys } from "@/lib/query-keys";

export default function AppHomePage() {
  const router = useRouter();
  const { status } = useAuthBootstrap();

  const channelsQuery = useQuery({
    queryKey: queryKeys.channels("root"),
    queryFn: () => api.listChannels(),
    enabled: status === "authenticated",
  });

  useEffect(() => {
    const first = channelsQuery.data?.items.find((item) => item.my_role !== "none") ?? channelsQuery.data?.items[0];
    if (first) {
      router.replace(`/app/channels/${first.id}`);
    }
  }, [channelsQuery.data, router]);

  return (
    <AppShell>
      <div className="grid h-full place-items-center p-4 text-center">Select a channel from the sidebar.</div>
    </AppShell>
  );
}
