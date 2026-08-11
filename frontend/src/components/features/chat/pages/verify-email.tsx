"use client";

import { useEffect, useRef, useState } from "react";
import { AlertCircle, CheckCircle2, Loader2, MailCheck } from "lucide-react";
import Link from "next/link";
import { useTranslations } from "next-intl";

import { useLocalePath } from "@/components/features/chat/lib/locale-path";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { apiClient } from "@/services/api/client";
import { useAuthStore } from "@/store/authStore";
import type { EmailVerificationConfirmResponse, MeResponse } from "@/types/api";

type VerificationState = "reading" | "confirming" | "verified" | "failed" | "auth_required";

export default function VerifyEmailPage() {
  const t = useTranslations("emailVerification");
  const localePath = useLocalePath();
  const isAuthenticated = useAuthStore((state) => state.isAuthenticated);
  const isInitializing = useAuthStore((state) => state.isInitializing);
  const updateUser = useAuthStore((state) => state.updateUser);
  const [token, setToken] = useState<string | null>(null);
  const [state, setState] = useState<VerificationState>("reading");
  const [errorMessage, setErrorMessage] = useState("");
  const started = useRef(false);

  useEffect(() => {
    const fragment = new URLSearchParams(window.location.hash.slice(1));
    const fragmentToken = fragment.get("token");
    setToken(fragmentToken);
    window.history.replaceState(null, "", `${window.location.pathname}${window.location.search}`);
    if (!fragmentToken) {
      setState("failed");
    }
  }, []);

  useEffect(() => {
    if (isInitializing || !token || started.current) return;
    if (!isAuthenticated) {
      setState("auth_required");
      return;
    }

    started.current = true;
    setState("confirming");
    void (async () => {
      try {
        await apiClient<EmailVerificationConfirmResponse>("/auth/email-verification/confirm", {
          method: "POST",
          body: JSON.stringify({ token }),
        });
        const freshUser = await apiClient<MeResponse>("/me");
        updateUser(freshUser);
        setToken(null);
        setState("verified");
      } catch (error) {
        setToken(null);
        setState("failed");
        setErrorMessage(error instanceof Error ? error.message : t("failedDescription"));
      }
    })();
  }, [isAuthenticated, isInitializing, t, token, updateUser]);

  const icon =
    state === "verified" ? (
      <CheckCircle2 className="h-12 w-12 text-emerald-500" />
    ) : state === "failed" || state === "auth_required" ? (
      <AlertCircle className="h-12 w-12 text-amber-500" />
    ) : state === "confirming" || state === "reading" ? (
      <Loader2 className="h-12 w-12 animate-spin text-primary" />
    ) : (
      <MailCheck className="h-12 w-12 text-primary" />
    );

  const title =
    state === "verified"
      ? t("verifiedTitle")
      : state === "failed"
        ? t("failedTitle")
        : state === "auth_required"
          ? t("authRequiredTitle")
          : t("confirmingTitle");

  const description =
    state === "verified"
      ? t("verifiedDescription")
      : state === "failed"
        ? errorMessage || t("failedDescription")
        : state === "auth_required"
          ? t("authRequiredDescription")
          : t("confirmingDescription");

  return (
    <main className="flex min-h-screen items-center justify-center bg-background p-6 text-foreground">
      <Card className="w-full max-w-md rounded-3xl p-8 text-center shadow-xl">
        <div className="mx-auto flex h-20 w-20 items-center justify-center rounded-full bg-muted">{icon}</div>
        <h1 className="mt-6 text-2xl font-bold">{title}</h1>
        <p className="mt-3 text-sm text-muted-foreground">{description}</p>
        <div className="mt-6 flex justify-center gap-3">
          {state === "auth_required" ? (
            <Link href={localePath("/login")}>
              <Button>{t("signIn")}</Button>
            </Link>
          ) : null}
          <Link href={localePath("/app/profile")}>
            <Button variant={state === "auth_required" ? "outline" : "default"}>{t("openProfile")}</Button>
          </Link>
        </div>
      </Card>
    </main>
  );
}
