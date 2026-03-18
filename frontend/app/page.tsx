"use client";

import { useAuthBootstrap } from "@/hooks/use-auth-bootstrap";

export default function HomePage() {
  const { isLoading } = useAuthBootstrap();

  return (
    <main className="grid min-h-screen place-items-center p-4 text-sm text-slate-500">
      {isLoading ? <p>Checking your session...</p> : null}
    </main>
  );
}
