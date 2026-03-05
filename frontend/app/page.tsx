"use client";

import Link from "next/link";
import { useAuthBootstrap } from "@/hooks/use-auth-bootstrap";

export default function HomePage() {
  const { status, isLoading } = useAuthBootstrap();

  if (isLoading) {
    return <main className="grid min-h-screen place-items-center">Loading...</main>;
  }

  return (
    <main className="grid min-h-screen place-items-center px-6 text-center">
      <div>
        <h1 className="text-3xl font-semibold">Channel Chat</h1>
        <p className="mt-2 text-slate-500">Status: {status}</p>
        <div className="mt-4 flex justify-center gap-3">
          <Link className="underline" href="/login">
            Login
          </Link>
          <Link className="underline" href="/register">
            Register
          </Link>
          <Link className="underline" href="/app">
            App
          </Link>
        </div>
      </div>
    </main>
  );
}

