"use client";

import { useEffect, useState } from "react";
import { AppProviders } from "@/components/shared/app-providers";
import { useInitializeAuth } from "@/hooks/use-auth";

interface ChatClientRootProps {
  children: React.ReactNode;
}

export function ChatClientRoot({ children }: ChatClientRootProps) {
  const [mounted, setMounted] = useState(false);

  useInitializeAuth();

  useEffect(() => {
    setMounted(true);
  }, []);

  if (!mounted) {
    return null;
  }

  return <AppProviders>{children}</AppProviders>;
}
