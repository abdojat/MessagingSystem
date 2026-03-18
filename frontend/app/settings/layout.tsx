"use client";

import { ProtectedRouteBoundary } from "@/components/auth/auth-guard";

export default function SettingsLayout({ children }: { children: React.ReactNode }) {
  return <ProtectedRouteBoundary>{children}</ProtectedRouteBoundary>;
}
