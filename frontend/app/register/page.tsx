"use client";

import Link from "next/link";
import { PublicOnlyRouteBoundary } from "@/components/auth/auth-guard";
import { RegisterForm } from "@/components/auth/auth-forms";

export default function RegisterPage() {
  return (
    <PublicOnlyRouteBoundary>
      <main className="grid min-h-screen place-items-center p-4">
        <div className="w-full max-w-md space-y-4">
          <RegisterForm />
          <p className="text-center text-sm text-slate-500">
            Have an account? <Link href="/login" className="underline">Login</Link>
          </p>
        </div>
      </main>
    </PublicOnlyRouteBoundary>
  );
}
