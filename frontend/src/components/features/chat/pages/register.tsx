"use client";

import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { useRegister } from "@/hooks/use-auth";
import { Button } from "@/components/ui/button";
import { ThemeToggle } from "@/components/ThemeToggle";
import { LanguageToggle } from "@/components/LanguageToggle";
import { useLocalePath } from "@/components/features/chat/lib/locale-path";

export default function Register() {
  const [username, setUsername] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const register = useRegister();
  const router = useRouter();
  const localePath = useLocalePath();
  const t = useTranslations("auth.register");
  const commonT = useTranslations("common");

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    register.mutate({ username, email, password }, {
      onSuccess: () => router.push(localePath("/app"))
    });
  };

  return (
    <div className="min-h-screen w-full flex items-center justify-center relative overflow-hidden bg-background">
      <div className="absolute inset-0 z-0">
        <img 
          src="/images/auth-bg.png" 
          alt={commonT("decorativeBackground")}
          className="w-full h-full object-cover opacity-40 mix-blend-screen transform scale-105"
        />
        <div className="absolute inset-0 bg-gradient-to-t from-background via-background/80 to-transparent" />
      </div>
      <div className="absolute right-6 top-6 z-20 flex items-center gap-2">
        <LanguageToggle className="border border-border/70 bg-background/70 text-foreground shadow-sm backdrop-blur hover:bg-accent" />
        <ThemeToggle className="rounded-xl border border-border/70 bg-background/70 text-foreground shadow-sm backdrop-blur hover:bg-accent" />
      </div>

      <div className="relative z-10 w-full max-w-md p-8">
        <div className="text-center mb-10">
          <div className="w-16 h-16 bg-gradient-to-br from-primary to-primary/60 rounded-2xl mx-auto flex items-center justify-center text-3xl font-bold text-white shadow-xl shadow-primary/30 mb-6">
            C
          </div>
          <h1 className="text-3xl font-bold tracking-tight text-foreground">{t("title")}</h1>
          <p className="text-muted-foreground mt-2">{t("subtitle")}</p>
        </div>

        <div className="bg-card/50 backdrop-blur-xl border border-border/50 p-8 rounded-3xl shadow-2xl shadow-black/50">
          <form onSubmit={handleSubmit} className="space-y-5">
            <div>
              <label className="block text-sm font-medium text-foreground mb-2">{t("email")}</label>
              <input
                type="email"
                value={email}
                onChange={e => setEmail(e.target.value)}
                className="w-full px-4 py-3 bg-background border border-border rounded-xl focus:outline-none focus:border-primary focus:ring-2 focus:ring-primary/20 transition-all text-foreground"
                placeholder={t("emailPlaceholder")}
                required
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-foreground mb-2">{t("username")}</label>
              <input
                type="text"
                value={username}
                onChange={e => setUsername(e.target.value)}
                className="w-full px-4 py-3 bg-background border border-border rounded-xl focus:outline-none focus:border-primary focus:ring-2 focus:ring-primary/20 transition-all text-foreground"
                placeholder={t("usernamePlaceholder")}
                required
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-foreground mb-2">{t("password")}</label>
              <input
                type="password"
                value={password}
                onChange={e => setPassword(e.target.value)}
                className="w-full px-4 py-3 bg-background border border-border rounded-xl focus:outline-none focus:border-primary focus:ring-2 focus:ring-primary/20 transition-all text-foreground"
                placeholder={t("passwordPlaceholder")}
                required
              />
            </div>
            
            {register.isError && (
              <div className="p-3 bg-destructive/10 border border-destructive/20 rounded-xl text-destructive text-sm font-medium">
                {(register.error as Error)?.message || t("error")}
              </div>
            )}

            <Button 
              type="submit" 
              className="w-full h-12 text-base font-semibold rounded-xl bg-gradient-to-r from-primary to-primary/90 shadow-lg shadow-primary/25 hover:shadow-primary/40 hover:-translate-y-0.5 transition-all"
              disabled={register.isPending}
            >
              {register.isPending ? t("submitting") : t("submit")}
            </Button>
          </form>

          <div className="mt-6 text-center text-sm text-muted-foreground">
            {t("hasAccount")}{" "}
            <Link href={localePath("/login")} className="font-semibold text-primary hover:text-primary/80 transition-colors">
              {t("signIn")}
            </Link>
          </div>
        </div>
      </div>
    </div>
  );
}
