"use client";

import Link from "next/link";
import { LogOut, PanelLeftClose, PanelLeftOpen } from "lucide-react";
import { useRouter } from "next/navigation";
import { useMutation } from "@tanstack/react-query";
import { toast } from "sonner";
import { useCurrentUser } from "@/hooks/use-current-user";
import { useWebSocketGateway } from "@/hooks/use-websocket-gateway";
import { api } from "@/lib/api-client";
import { useAuthStore } from "@/store/auth-store";
import { useAppUiStore } from "@/store/app-ui-store";
import { useResizablePanel } from "@/hooks/use-resizable-panel";
import { Sidebar } from "@/components/layout/sidebar";
import { Button } from "@/components/ui/button";
import { ThemeToggle } from "@/components/layout/theme-toggle";

export function AppShell({ selectedChannelId, children }: { selectedChannelId?: string; children: React.ReactNode }) {
  const collapsedSidebarWidth = 72;
  const sidebarCollapseThreshold = 320;
  const router = useRouter();
  const wsStatus = useAppUiStore((s) => s.wsStatus);
  const { data: me } = useCurrentUser();
  const refreshToken = useAuthStore((s) => s.refreshToken);
  const clearAuth = useAuthStore((s) => s.clearAuth);
  const { width: sidebarWidth, isCollapsed: isSidebarCollapsed, beginResize, open: openSidebar, close: closeSidebar } = useResizablePanel({
    initialWidth: 360,
    minWidth: collapsedSidebarWidth,
    maxWidth: 520,
    minRemainingWidth: 520,
    collapsedWidth: collapsedSidebarWidth,
    collapseThreshold: sidebarCollapseThreshold,
    minExpandedWidth: sidebarCollapseThreshold,
    collapseOnThreshold: true,
    storageKey: "layout:left-sidebar-width",
  });

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
    <div className="grid h-screen overflow-hidden" style={{ gridTemplateColumns: `${sidebarWidth}px 8px minmax(0, 1fr)` }}>
      <Sidebar selectedChannelId={selectedChannelId} isCollapsed={isSidebarCollapsed} />
      <div
        role="separator"
        aria-orientation="vertical"
        aria-label="Resize channels sidebar"
        className="group relative cursor-col-resize"
        onMouseDown={(event) => beginResize(event, "growWithPointer")}
      >
        <div className="absolute inset-y-0 left-1/2 w-px -translate-x-1/2 bg-slate-200 transition-colors group-hover:bg-slate-400 dark:bg-slate-800 dark:group-hover:bg-slate-500" />
      </div>
      <div className="flex min-h-0 flex-col">
        <header className="flex h-12 items-center justify-between border-b border-slate-200 bg-white/80 px-4 backdrop-blur dark:border-slate-800 dark:bg-slate-950/80">
          <div className="flex items-center gap-3 text-sm">
            <Button
              variant="ghost"
              size="sm"
              onClick={isSidebarCollapsed ? openSidebar : closeSidebar}
              aria-label={isSidebarCollapsed ? "Show channels sidebar" : "Hide channels sidebar"}
            >
              {isSidebarCollapsed ? <PanelLeftOpen className="size-4" /> : <PanelLeftClose className="size-4" />}
            </Button>
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
