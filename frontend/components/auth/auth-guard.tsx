"use client";

import { Suspense } from "react";
import { useEffect } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { sanitizeNextPath } from "@/lib/auth";
import { useAuthSession } from "@/components/auth/auth-provider";
import { Spinner } from "@/components/ui/spinner";

export function AuthScreen({ label }: { label: string }) {
  return (
    <main className="grid min-h-screen place-items-center p-4">
      <div className="flex items-center gap-3 text-sm text-slate-500">
        <Spinner className="size-4" />
        <span>{label}</span>
      </div>
    </main>
  );
}

export function ProtectedRoute({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const { isReady, isAuthenticated, isLoading } = useAuthSession();

  useEffect(() => {
    if (!isReady || isAuthenticated) {
      return;
    }

    const query = searchParams.toString();
    const next = `${pathname}${query ? `?${query}` : ""}`;
    router.replace(`/login?next=${encodeURIComponent(next)}`);
  }, [isReady, isAuthenticated, pathname, router, searchParams]);

  if (!isReady || isLoading || !isAuthenticated) {
    return <AuthScreen label="Checking your session..." />;
  }

  return <>{children}</>;
}

export function ProtectedRouteBoundary({ children }: { children: React.ReactNode }) {
  return (
    <Suspense fallback={<AuthScreen label="Checking your session..." />}>
      <ProtectedRoute>{children}</ProtectedRoute>
    </Suspense>
  );
}

export function PublicOnlyRoute({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { isReady, isAuthenticated, isLoading } = useAuthSession();

  useEffect(() => {
    if (!isReady || !isAuthenticated) {
      return;
    }

    const next = sanitizeNextPath(searchParams.get("next")) ?? "/app";
    router.replace(next);
  }, [isReady, isAuthenticated, router, searchParams]);

  if (!isReady || isLoading) {
    return <AuthScreen label="Checking your session..." />;
  }

  if (isAuthenticated) {
    return <AuthScreen label="Redirecting..." />;
  }

  return <>{children}</>;
}

export function PublicOnlyRouteBoundary({ children }: { children: React.ReactNode }) {
  return (
    <Suspense fallback={<AuthScreen label="Checking your session..." />}>
      <PublicOnlyRoute>{children}</PublicOnlyRoute>
    </Suspense>
  );
}
