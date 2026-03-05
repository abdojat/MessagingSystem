"use client";

import Link from "next/link";
import { LoginForm } from "@/components/auth/auth-forms";
import { useAuthBootstrap } from "@/hooks/use-auth-bootstrap";

export default function LoginPage() {
  useAuthBootstrap();

  return (
    <main className="grid min-h-screen place-items-center p-4">
      <div className="w-full max-w-md space-y-4">
        <LoginForm />
        <p className="text-center text-sm text-slate-500">
          No account? <Link href="/register" className="underline">Register</Link>
        </p>
      </div>
    </main>
  );
}

