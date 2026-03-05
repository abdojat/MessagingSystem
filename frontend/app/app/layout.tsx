"use client";

import { useAuthBootstrap } from "@/hooks/use-auth-bootstrap";

export default function AppLayout({ children }: { children: React.ReactNode }) {
  useAuthBootstrap();
  return children;
}

