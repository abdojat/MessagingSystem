"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useAuthSession } from "@/components/auth/auth-provider";
import { Spinner } from "@/components/ui/spinner";

export default function HomePage() {
  const router = useRouter();
  const { isReady, isAuthenticated, isLoading } = useAuthSession();

  useEffect(() => {
    if (!isReady) {
      return;
    }

    router.replace(isAuthenticated ? "/app" : "/login");
  }, [isReady, isAuthenticated, router]);

  return (
    <main className="grid min-h-screen place-items-center p-4 text-sm text-slate-500">
      {!isReady || isLoading ? (
        <div className="flex items-center gap-3">
          <Spinner className="size-4" />
          <p>Checking your session...</p>
        </div>
      ) : null}
    </main>
  );
}
