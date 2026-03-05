"use client";

import Link from "next/link";
import { LogOut } from "lucide-react";
import { useRouter } from "next/navigation";
import { useMutation } from "@tanstack/react-query";
import { toast } from "sonner";
import { useCurrentUser } from "@/hooks/use-current-user";
import { useWebSocketGateway } from "@/hooks/use-websocket-gateway";
import { api } from "@/lib/api-client";
import { useAuthStore } from "@/store/auth-store";
import { useAppUiStore } from "@/store/app-ui-store";
import { Sidebar } from "@/components/layout/sidebar";
import { Button } from "@/components/ui/button";
import { ThemeToggle } from "@/components/layout/theme-toggle";

export function AppShell({ selectedChannelId, children }: { selectedChannelId?: string; children: React.ReactNode }) {
  const router = useRouter();
  const wsStatus = useAppUiStore((s) => s.wsStatus);
  const { data: me } = useCurrentUser();
  const refreshToken = useAuthStore((s) => s.refreshToken);
  const clearAuth = useAuthStore((s) => s.clearAuth);

  useWebSocketGateway();

  const logoutMutation = useMutation({
    mutationFn: () => (refreshToken ? api.logout(refreshToken) : Promise.resolve({ status: "ok" as const })),
    onSettled: () => {
      clearAuth();
      router.replace("/login");
      toast.success("Logged out");
    },
  });

  return (
    <div className="grid h-screen grid-cols-[300px_1fr]">
      <Sidebar selectedChannelId={selectedChannelId} />
      <div className="flex min-h-0 flex-col">
        <header className="flex h-12 items-center justify-between border-b border-slate-200 bg-white/80 px-4 backdrop-blur dark:border-slate-800 dark:bg-slate-950/80">
          <div className="flex items-center gap-3 text-sm">
            <span className="font-medium">{me?.username ?? "..."}</span>
            <span className="text-xs text-slate-500">ws: {wsStatus}</span>
            <Link href="/app" className="text-xs text-slate-500 hover:text-slate-800 dark:hover:text-slate-100">
              Home
            </Link>
          </div>
          <div className="flex items-center gap-2">
            <ThemeToggle />
            <Button variant="ghost" size="sm" onClick={() => logoutMutation.mutate()}>
              <LogOut className="size-4" />
            </Button>
          </div>
        </header>
        <main className="min-h-0 flex-1 overflow-hidden">{children}</main>
      </div>
    </div>
  );
}

