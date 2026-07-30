"use client";

import { useEffect, useState } from "react";
import { AppProviders } from "@/components/shared/app-providers";
import { useInitializeAuth } from "@/hooks/use-auth";

interface ChatClientRootProps {
  children: React.ReactNode;
}

// Renders the chat client root component; parent React views use it to render or control the interface.
export function ChatClientRoot({ children }: ChatClientRootProps) {
  const [mounted, setMounted] = useState(false);

  useInitializeAuth();

  useEffect(() => {
    setMounted(true);
  }, []);

  // Return early when `!mounted` because the remaining work is not applicable.
  if (!mounted) {
    return null;
  }

  return <AppProviders>{children}</AppProviders>;
}
