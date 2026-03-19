import { Switch, Route, Router as WouterRouter } from "wouter";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Toaster } from "@/components/ui/toaster";
import { TooltipProvider } from "@/components/ui/tooltip";
import { ThemeProvider } from "@/components/theme-provider";
import { useInitializeAuth } from "./hooks/use-auth";
import { WSProvider } from "./hooks/use-websocket";

import Login from "./pages/login";
import Register from "./pages/register";
import AppLayout from "./pages/app-layout";
import Sessions from "./pages/sessions";
import Invite from "./pages/invite";
import ProfilePage from "./pages/profile";
import Home from "./pages/home";
import NotFound from "./pages/not-found";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      refetchOnWindowFocus: false,
    }
  }
});

function AppRouter() {
  useInitializeAuth();

  return (
    <Switch>
      <Route path="/" component={Home} />
      <Route path="/app/profile" component={AppLayout} />
      <Route path="/app/channels/:channelId/details" component={AppLayout} />
      <Route path="/app/channels/:channelId" component={AppLayout} />
      <Route path="/app" component={AppLayout} />
      <Route path="/profile" component={ProfilePage} />
      <Route path="/login" component={Login} />
      <Route path="/register" component={Register} />
      <Route path="/settings/sessions" component={Sessions} />
      <Route path="/invites/:token" component={Invite} />
      <Route component={NotFound} />
    </Switch>
  );
}

function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <ThemeProvider>
        <TooltipProvider>
          <WSProvider>
            <WouterRouter base={import.meta.env.BASE_URL.replace(/\/$/, "")}>
              <AppRouter />
            </WouterRouter>
            <Toaster />
          </WSProvider>
        </TooltipProvider>
      </ThemeProvider>
    </QueryClientProvider>
  );
}

export default App;
