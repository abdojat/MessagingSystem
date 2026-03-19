import { useAuthStore } from "../store/authStore";
import { Redirect, Route, Switch } from "wouter";
import { AppSidebar } from "../components/AppSidebar";
import ChannelView from "./channel-view";
import ChannelDetailsPage from "./channel-details";
import ProfilePage from "./profile";
import { Hash } from "lucide-react";
import { useWS } from "../hooks/use-websocket";
import { Skeleton } from "../components/ui/skeleton";

function EmptyState() {
  return (
    <div className="flex-1 flex flex-col items-center justify-center bg-background h-screen">
      <div className="w-24 h-24 rounded-full bg-primary/10 flex items-center justify-center mb-6">
        <Hash className="w-12 h-12 text-primary" />
      </div>
      <h2 className="text-2xl font-bold text-foreground mb-2">Welcome to ChatCore</h2>
      <p className="text-muted-foreground max-w-md text-center">
        Select a channel from the sidebar to start messaging, or create a new one to gather your team.
      </p>
    </div>
  );
}

function AppLayoutSkeleton() {
  return (
    <div className="flex h-screen w-full bg-background overflow-hidden relative">
      <div className="w-72 h-screen flex flex-col bg-sidebar border-r border-sidebar-border shadow-2xl z-10 flex-shrink-0">
        <div className="p-4 border-b border-sidebar-border flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Skeleton className="h-8 w-8 rounded-xl" />
            <Skeleton className="h-5 w-24" />
          </div>
          <div className="flex items-center gap-2">
            <Skeleton className="h-8 w-8 rounded-lg" />
            <Skeleton className="h-8 w-8 rounded-lg" />
          </div>
        </div>
        <div className="p-3">
          <Skeleton className="h-10 w-full rounded-xl" />
        </div>
        <div className="flex-1 px-3 py-2 space-y-6">
          {Array.from({ length: 3 }).map((_, sectionIndex) => (
            <div key={sectionIndex} className="space-y-3">
              <Skeleton className="h-3 w-24" />
              {Array.from({ length: 3 }).map((__, itemIndex) => (
                <div key={itemIndex} className="flex items-center gap-3 rounded-xl px-3 py-2">
                  <Skeleton className="h-8 w-8 rounded-lg" />
                  <div className="flex-1 space-y-2">
                    <Skeleton className="h-3 w-20" />
                    <Skeleton className="h-3 w-32" />
                  </div>
                </div>
              ))}
            </div>
          ))}
        </div>
      </div>
      <div className="flex-1 h-full p-6 space-y-6">
        <div className="flex items-center justify-between">
          <div className="space-y-2">
            <Skeleton className="h-8 w-48" />
            <Skeleton className="h-4 w-80 max-w-full" />
          </div>
          <Skeleton className="h-10 w-28 rounded-xl" />
        </div>
        <Skeleton className="h-40 w-full rounded-3xl" />
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {Array.from({ length: 3 }).map((_, cardIndex) => (
            <Skeleton key={cardIndex} className="h-32 w-full rounded-3xl" />
          ))}
        </div>
      </div>
    </div>
  );
}

export default function AppLayout() {
  const isAuthenticated = useAuthStore(s => s.isAuthenticated);
  const isInitializing = useAuthStore(s => s.isInitializing);
  const wsStatus = useWS().status;

  if (isInitializing) {
    return <AppLayoutSkeleton />;
  }

  if (!isAuthenticated) {
    return <Redirect to="/login" />;
  }

  return (
    <div className="flex h-screen w-full bg-background overflow-hidden relative">
      <AppSidebar />
      <div className="flex-1 relative h-full flex flex-col min-w-0">
        {/* WS Connection Status Banner */}
        {wsStatus !== 'connected' && (
          <div className={`absolute top-0 left-0 right-0 py-1.5 px-4 text-xs font-medium text-center z-50 transition-colors ${wsStatus === 'connecting' ? 'bg-yellow-500/20 text-yellow-500' : 'bg-destructive/20 text-destructive'}`}>
            {wsStatus === 'connecting' ? 'Connecting to chat...' : 'Disconnected. Reconnecting...'}
          </div>
        )}

        <Switch>
          <Route path="/app" component={EmptyState} />
          <Route path="/app/profile" component={ProfilePage} />
          <Route path="/app/channels/:channelId/details" component={ChannelDetailsPage} />
          <Route path="/app/channels/:channelId" component={ChannelView} />
        </Switch>
      </div>
    </div>
  );
}
