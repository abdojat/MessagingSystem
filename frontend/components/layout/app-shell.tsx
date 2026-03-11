"use client";

import Link from "next/link";
import { useState } from "react";
import { LogOut, PanelLeftClose, PanelLeftOpen } from "lucide-react";
import { useRouter } from "next/navigation";
import { useMutation } from "@tanstack/react-query";
import { toast } from "sonner";
import { useCurrentUser } from "@/hooks/use-current-user";
import { useWebSocketGateway } from "@/hooks/use-websocket-gateway";
import { useMediaQuery } from "@/hooks/use-media-query";
import { api } from "@/lib/api-client";
import { cn } from "@/lib/utils";
import { useAuthStore } from "@/store/auth-store";
import { useAppUiStore } from "@/store/app-ui-store";
import { useResizablePanel } from "@/hooks/use-resizable-panel";
import { Sidebar } from "@/components/layout/sidebar";
import { Button } from "@/components/ui/button";
import { ThemeToggle } from "@/components/layout/theme-toggle";

export function AppShell({ selectedChannelId, children }: { selectedChannelId?: string; children: React.ReactNode }) {
  const collapsedSidebarWidth = 72;
  const sidebarCollapseThreshold = 320;
  const isMobile = useMediaQuery("(max-width: 1023px)");
  const router = useRouter();
  const wsStatus = useAppUiStore((s) => s.wsStatus);
  const { data: me } = useCurrentUser();
  const refreshToken = useAuthStore((s) => s.refreshToken);
  const clearAuth = useAuthStore((s) => s.clearAuth);
  const [mobileSidebarOpen, setMobileSidebarOpen] = useState(false);
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

  const toggleSidebar = () => {
    if (isMobile) {
      setMobileSidebarOpen((current) => !current);
      return;
    }
    if (isSidebarCollapsed) {
      openSidebar();
      return;
    }
    closeSidebar();
  };

  return (
    <div className={cn("h-dvh overflow-hidden", isMobile ? "flex" : "grid")} style={isMobile ? undefined : { gridTemplateColumns: `${sidebarWidth}px 8px minmax(0, 1fr)` }}>
      {!isMobile ? (
        <>
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
        </>
      ) : null}
      <div className="flex min-h-0 min-w-0 flex-1 flex-col">
        <header className="flex h-12 items-center justify-between border-b border-slate-200 bg-white/80 px-3 backdrop-blur sm:px-4 dark:border-slate-800 dark:bg-slate-950/80">
          <div className="flex min-w-0 items-center gap-2 text-sm sm:gap-3">
            <Button variant="ghost" size="sm" onClick={toggleSidebar} aria-label={isMobile || isSidebarCollapsed ? "Show channels sidebar" : "Hide channels sidebar"}>
              {isMobile || isSidebarCollapsed ? <PanelLeftOpen className="size-4" /> : <PanelLeftClose className="size-4" />}
            </Button>
            <span className="truncate font-medium">{me?.username ?? "..."}</span>
            <span className="hidden text-xs text-slate-500 sm:inline">ws: {wsStatus}</span>
            <Link href="/app" className="hidden text-xs text-slate-500 hover:text-slate-800 sm:inline dark:hover:text-slate-100">
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
        <main className="min-h-0 min-w-0 flex-1 overflow-hidden">{children}</main>
      </div>

      {isMobile && mobileSidebarOpen ? (
        <div className="fixed inset-0 z-40 lg:hidden">
          <button className="absolute inset-0 bg-black/40" onClick={() => setMobileSidebarOpen(false)} aria-label="Close channels sidebar" />
          <div className="relative h-full w-[min(88vw,360px)] border-r border-slate-200 bg-white/90 backdrop-blur dark:border-slate-800 dark:bg-slate-950/90">
            <Sidebar selectedChannelId={selectedChannelId} onNavigate={() => setMobileSidebarOpen(false)} />
          </div>
        </div>
      ) : null}
    </div>
  );
}
