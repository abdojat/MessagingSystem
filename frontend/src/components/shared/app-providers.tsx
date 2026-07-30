"use client";

import { ReactNode, useState } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ThemeProvider } from "@/components/theme-provider";
import { TooltipProvider } from "@/components/ui/tooltip";
import { Toaster } from "@/components/ui/toaster";
import { WSProvider } from "@/hooks/use-websocket";

interface AppProvidersProps {
  children: ReactNode;
}

// Renders the app providers component; parent React views use it to render or control the interface.
export function AppProviders({ children }: AppProvidersProps) {
  const [queryClient] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            retry: 1,
            refetchOnWindowFocus: false,
          },
        },
      }),
  );

  return (
    <QueryClientProvider client={queryClient}>
      <ThemeProvider>
        <TooltipProvider>
          <WSProvider>
            {children}
            <Toaster />
          </WSProvider>
        </TooltipProvider>
      </ThemeProvider>
    </QueryClientProvider>
  );
}

