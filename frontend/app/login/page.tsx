"use client";

import Link from "next/link";
import { Suspense } from "react";
import { AuthScreen, PublicOnlyRouteBoundary } from "@/components/auth/auth-guard";
import { LoginForm } from "@/components/auth/auth-forms";

export default function LoginPage() {
  return (
    <PublicOnlyRouteBoundary>
      <main className="grid min-h-screen place-items-center p-4">
        <div className="w-full max-w-md space-y-4">
          <Suspense fallback={<AuthScreen label="Loading sign in..." />}>
            <LoginForm />
          </Suspense>
          <p className="text-center text-sm text-slate-500">
            No account? <Link href="/register" className="underline">Register</Link>
          </p>
        </div>
      </main>
    </PublicOnlyRouteBoundary>
  );
}
