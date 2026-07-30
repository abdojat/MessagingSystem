"use client";

import Link from "next/link";
import { buttonVariants } from "@/components/ui/button";
import { MessageCircle, ShieldCheck, Sparkles, Zap } from "lucide-react";
import { motion } from "framer-motion";
import { useTranslations } from "next-intl";
import { useAuthStore } from "@/store/authStore";
import { ThemeToggle } from "@/components/ThemeToggle";
import { LanguageToggle } from "@/components/LanguageToggle";
import { useLocalePath } from "@/components/features/chat/lib/locale-path";

const featureIcons = [MessageCircle, ShieldCheck, Zap] as const;

// Renders the home component; the route adapter uses it for the matching application page.
export default function Home() {
  const localePath = useLocalePath();
  const t = useTranslations("home");
  const appT = useTranslations("app");
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  const user = useAuthStore((s) => s.user);
  const features = featureIcons.map((icon, index) => ({
    icon,
    title: t(`features.${index}.title`),
    description: t(`features.${index}.description`),
  }));

  return (
    <main className="relative min-h-screen overflow-hidden bg-[radial-gradient(circle_at_20%_20%,hsl(var(--primary)/0.18),transparent_48%),radial-gradient(circle_at_88%_12%,hsl(186_92%_44%/0.12),transparent_40%),linear-gradient(165deg,hsl(210_40%_99%),hsl(220_40%_95%))] text-foreground dark:bg-[radial-gradient(circle_at_20%_20%,hsl(var(--primary)/0.32),transparent_48%),radial-gradient(circle_at_88%_12%,hsl(186_92%_44%/0.18),transparent_40%),linear-gradient(165deg,hsl(232_23%_7%),hsl(228_18%_5%))]">
      <div className="pointer-events-none absolute inset-0 bg-[linear-gradient(hsl(224_20%_20%/0.06)_1px,transparent_1px),linear-gradient(90deg,hsl(224_20%_20%/0.06)_1px,transparent_1px)] bg-[size:44px_44px] opacity-30 dark:bg-[linear-gradient(hsl(0_0%_100%/0.06)_1px,transparent_1px),linear-gradient(90deg,hsl(0_0%_100%/0.06)_1px,transparent_1px)] dark:opacity-20" />

      <div className="relative mx-auto flex min-h-screen w-full max-w-6xl flex-col px-6 pb-16 pt-7 sm:px-10 lg:px-12">
        <header className="flex items-center justify-between">
          <Link href={localePath("/")} className="inline-flex items-center gap-3">
            <span className="grid h-11 w-11 place-items-center rounded-xl bg-gradient-to-br from-primary to-cyan-300 text-base font-bold text-black shadow-lg shadow-primary/40">
              C
            </span>
            <div>
              <p className="text-xs uppercase tracking-[0.24em] text-muted-foreground">{appT("name")}</p>
              <p className="text-sm font-medium text-foreground/90">{appT("tagline")}</p>
            </div>
          </Link>
          <div className="flex items-center gap-2 sm:gap-3">
            <LanguageToggle className="border border-border/70 bg-background/70 text-foreground shadow-sm backdrop-blur hover:bg-accent dark:border-white/12 dark:bg-white/5 dark:hover:bg-white/10" />
            <ThemeToggle className="rounded-xl border border-border/70 bg-background/70 text-foreground shadow-sm backdrop-blur hover:bg-accent dark:border-white/12 dark:bg-white/5 dark:hover:bg-white/10" />
            {!isAuthenticated && (
              <Link href={localePath("/login")} className={buttonVariants({ variant: "ghost", className: "text-foreground/90 hover:bg-black/5 dark:hover:bg-white/10" })}>
                {t("nav.login")}
              </Link>
            )}
            <Link
              href={isAuthenticated ? localePath("/app") : localePath("/register")}
              className={buttonVariants({
                className: "rounded-xl bg-foreground text-background hover:opacity-90 px-5 shadow-xl shadow-primary/15 dark:bg-white dark:text-slate-900 dark:shadow-black/30",
              })}
            >
              {isAuthenticated ? t("nav.openApp") : t("nav.createAccount")}
            </Link>
          </div>
        </header>

        <section className="grid flex-1 grid-cols-1 items-center gap-10 pt-12 lg:grid-cols-[1.15fr_0.85fr] lg:pt-16">
          <motion.div
            initial={{ opacity: 0, y: 22 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.55 }}
            className="max-w-2xl"
          >
            <span className="inline-flex items-center gap-2 rounded-full border border-border/70 bg-background/70 px-4 py-1.5 text-xs font-medium uppercase tracking-[0.18em] text-foreground/80 shadow-sm backdrop-blur dark:border-white/20 dark:bg-white/8 dark:text-white/85">
              <Sparkles className="h-3.5 w-3.5 text-cyan-600 dark:text-cyan-300" />
              {t("eyebrow")}
            </span>

            <h1 className="mt-6 text-4xl leading-tight font-semibold tracking-tight sm:text-5xl lg:text-6xl [font-family:var(--font-display)]">
              {user?.username
                ? t("titleWithName", { username: user.username })
                : t("title")}
            </h1>

            <p className="mt-5 max-w-xl text-base leading-relaxed text-foreground/70 sm:text-lg dark:text-slate-300">
              {t("subtitle")}
            </p>

            <div className="mt-8 flex flex-wrap items-center gap-3">
              <Link
                href={isAuthenticated ? localePath("/app") : localePath("/register")}
                className={buttonVariants({
                  size: "lg",
                  className: "h-12 rounded-xl bg-gradient-to-r from-primary to-cyan-300 px-7 text-[15px] font-semibold text-slate-950 shadow-2xl shadow-primary/40 hover:brightness-110",
              })}
            >
                {isAuthenticated ? t("actions.continue") : t("actions.start")}
              </Link>
              <Link
                href={isAuthenticated ? localePath("/app/profile") : localePath("/login")}
                className={buttonVariants({
                  variant: "outline",
                  size: "lg",
                  className: "h-12 rounded-xl border-border/80 bg-background/75 px-7 text-[15px] text-foreground hover:bg-accent dark:border-white/20 dark:bg-white/5 dark:hover:bg-white/12",
              })}
            >
                {isAuthenticated ? t("actions.profile") : t("actions.alreadyHaveAccount")}
              </Link>
            </div>
          </motion.div>

          <motion.div
            initial={{ opacity: 0, y: 22 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.55, delay: 0.12 }}
            className="relative"
          >
            <div className="absolute -left-10 top-8 h-40 w-40 rounded-full bg-cyan-300/18 blur-3xl" />
            <div className="absolute -right-8 -top-2 h-40 w-40 rounded-full bg-primary/30 blur-3xl" />
            <div className="relative overflow-hidden rounded-3xl border border-border/70 bg-white/70 p-5 shadow-2xl shadow-slate-300/50 backdrop-blur-xl sm:p-6 dark:border-white/12 dark:bg-slate-900/70 dark:shadow-black/60">
              <div className="flex items-center justify-between border-b border-border/80 pb-4 dark:border-white/10">
                <p className="text-sm font-medium text-foreground/90 dark:text-white/90">{t("preview.title")}</p>
                <span className="rounded-full bg-emerald-500/15 px-2.5 py-1 text-xs text-emerald-600 dark:bg-emerald-400/20 dark:text-emerald-300">{t("preview.live")}</span>
              </div>
              <div className="space-y-3 pt-4">
                <div className="rounded-2xl border border-border/80 bg-background/80 p-3 dark:border-white/12 dark:bg-white/6">
                  <p className="text-xs text-cyan-600 dark:text-cyan-300"># {t("preview.channels.product")}</p>
                  <p className="mt-1 text-sm text-foreground/80 dark:text-slate-200">&quot;{t("preview.messages.product")}&quot;</p>
                </div>
                <div className="rounded-2xl border border-border/80 bg-background/80 p-3 dark:border-white/12 dark:bg-white/6">
                  <p className="text-xs text-primary"># {t("preview.channels.engineering")}</p>
                  <p className="mt-1 text-sm text-foreground/80 dark:text-slate-200">&quot;{t("preview.messages.engineering")}&quot;</p>
                </div>
                <div className="rounded-2xl border border-border/80 bg-background/80 p-3 dark:border-white/12 dark:bg-white/6">
                  <p className="text-xs text-emerald-600 dark:text-emerald-300"># {t("preview.channels.support")}</p>
                  <p className="mt-1 text-sm text-foreground/80 dark:text-slate-200">&quot;{t("preview.messages.support")}&quot;</p>
                </div>
              </div>
            </div>
          </motion.div>
        </section>

        <section className="mt-10 grid grid-cols-1 gap-4 sm:grid-cols-3">
          {features.map((feature, index) => (
            <motion.article
              key={feature.title}
              initial={{ opacity: 0, y: 16 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.45, delay: 0.2 + index * 0.08 }}
              className="rounded-2xl border border-border/70 bg-background/70 p-5 shadow-sm backdrop-blur-sm dark:border-white/12 dark:bg-white/6"
            >
              <feature.icon className="h-5 w-5 text-cyan-600 dark:text-cyan-300" />
              <h2 className="mt-3 text-base font-semibold text-foreground">{feature.title}</h2>
              <p className="mt-1 text-sm leading-relaxed text-foreground/70 dark:text-slate-300">{feature.description}</p>
            </motion.article>
          ))}
        </section>
      </div>
    </main>
  );
}
