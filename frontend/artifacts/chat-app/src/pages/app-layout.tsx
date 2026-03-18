import { useAuthStore } from "../store/authStore";
import { Redirect, Route, Switch } from "wouter";
import { AppSidebar } from "../components/AppSidebar";
import ChannelView from "./channel-view";
import ChannelDetailsPage from "./channel-details";
import ProfilePage from "./profile";
import { Hash } from "lucide-react";
import { useWS } from "../hooks/use-websocket";

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

export default function AppLayout() {
  const isAuthenticated = useAuthStore(s => s.isAuthenticated);
  const isInitializing = useAuthStore(s => s.isInitializing);
  const wsStatus = useWS().status;

  if (isInitializing) {
    return <div className="h-screen w-full flex items-center justify-center bg-background"><div className="w-8 h-8 border-4 border-primary border-t-transparent rounded-full animate-spin"></div></div>;
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
