import { Link } from "wouter";
import { buttonVariants } from "@/components/ui/button";
import { MessageCircle, ShieldCheck, Sparkles, Zap } from "lucide-react";
import { motion } from "framer-motion";
import { useAuthStore } from "@/store/authStore";

const features = [
  {
    title: "Live conversations",
    description: "Real-time messaging that keeps teams in sync without refreshes.",
    icon: MessageCircle,
  },
  {
    title: "Private by default",
    description: "Role-aware access and invite controls protect every channel.",
    icon: ShieldCheck,
  },
  {
    title: "Fast everywhere",
    description: "Built for instant load times on desktop and mobile.",
    icon: Zap,
  },
];

export default function Home() {
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  const user = useAuthStore((s) => s.user);

  return (
    <main className="relative min-h-screen overflow-hidden bg-[radial-gradient(circle_at_20%_20%,hsl(var(--primary)/0.32),transparent_48%),radial-gradient(circle_at_88%_12%,hsl(186_92%_44%/0.18),transparent_40%),linear-gradient(165deg,hsl(232_23%_7%),hsl(228_18%_5%))] text-foreground">
      <div className="pointer-events-none absolute inset-0 bg-[linear-gradient(hsl(0_0%_100%/0.06)_1px,transparent_1px),linear-gradient(90deg,hsl(0_0%_100%/0.06)_1px,transparent_1px)] bg-[size:44px_44px] opacity-20" />

      <div className="relative mx-auto flex min-h-screen w-full max-w-6xl flex-col px-6 pb-16 pt-7 sm:px-10 lg:px-12">
        <header className="flex items-center justify-between">
          <Link href="/" className="inline-flex items-center gap-3">
            <span className="grid h-11 w-11 place-items-center rounded-xl bg-gradient-to-br from-primary to-cyan-300 text-base font-bold text-black shadow-lg shadow-primary/40">
              C
            </span>
            <div>
              <p className="text-xs uppercase tracking-[0.24em] text-muted-foreground">ChatApp</p>
              <p className="text-sm font-medium text-foreground/90">Team messaging, done right</p>
            </div>
          </Link>
          <div className="flex items-center gap-2 sm:gap-3">
            {!isAuthenticated && (
              <Link href="/login" className={buttonVariants({ variant: "ghost", className: "text-foreground/90 hover:bg-white/10" })}>
                Log in
              </Link>
            )}
            <Link
              href={isAuthenticated ? "/app" : "/register"}
              className={buttonVariants({
                className: "rounded-xl bg-white text-slate-900 hover:bg-white/90 px-5 shadow-xl shadow-black/30",
              })}
            >
              {isAuthenticated ? "Open app" : "Create account"}
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
            <span className="inline-flex items-center gap-2 rounded-full border border-white/20 bg-white/8 px-4 py-1.5 text-xs font-medium uppercase tracking-[0.18em] text-white/85">
              <Sparkles className="h-3.5 w-3.5 text-cyan-300" />
              Built for focused conversations
            </span>

            <h1 className="mt-6 text-4xl leading-tight font-semibold tracking-tight sm:text-5xl lg:text-6xl [font-family:var(--font-display)]">
              Welcome{user?.username ? `, ${user.username}` : ""}. Chat with clarity, not chaos.
            </h1>

            <p className="mt-5 max-w-xl text-base leading-relaxed text-slate-300 sm:text-lg">
              Launch channels in seconds, keep discussions organized, and move from idea to action with a workspace your team actually enjoys using.
            </p>

            <div className="mt-8 flex flex-wrap items-center gap-3">
              <Link
                href={isAuthenticated ? "/app" : "/register"}
                className={buttonVariants({
                  size: "lg",
                  className: "h-12 rounded-xl bg-gradient-to-r from-primary to-cyan-300 px-7 text-[15px] font-semibold text-slate-950 shadow-2xl shadow-primary/40 hover:brightness-110",
                })}
              >
                {isAuthenticated ? "Continue to your channels" : "Start chatting now"}
              </Link>
              <Link
                href={isAuthenticated ? "/app/profile" : "/login"}
                className={buttonVariants({
                  variant: "outline",
                  size: "lg",
                  className: "h-12 rounded-xl border-white/20 bg-white/5 px-7 text-[15px] text-foreground hover:bg-white/12",
                })}
              >
                {isAuthenticated ? "Manage profile" : "I already have an account"}
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
            <div className="relative overflow-hidden rounded-3xl border border-white/12 bg-slate-900/70 p-5 shadow-2xl shadow-black/60 backdrop-blur-xl sm:p-6">
              <div className="flex items-center justify-between border-b border-white/10 pb-4">
                <p className="text-sm font-medium text-white/90">Workspace preview</p>
                <span className="rounded-full bg-emerald-400/20 px-2.5 py-1 text-xs text-emerald-300">Live</span>
              </div>
              <div className="space-y-3 pt-4">
                <div className="rounded-2xl border border-white/12 bg-white/6 p-3">
                  <p className="text-xs text-cyan-300"># product</p>
                  <p className="mt-1 text-sm text-slate-200">"Landing page shipped. Feedback is coming in fast."</p>
                </div>
                <div className="rounded-2xl border border-white/12 bg-white/6 p-3">
                  <p className="text-xs text-primary"># engineering</p>
                  <p className="mt-1 text-sm text-slate-200">"WebSocket events are stable. Ready for demo."</p>
                </div>
                <div className="rounded-2xl border border-white/12 bg-white/6 p-3">
                  <p className="text-xs text-emerald-300"># support</p>
                  <p className="mt-1 text-sm text-slate-200">"Resolution time is down 32% this week."</p>
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
              className="rounded-2xl border border-white/12 bg-white/6 p-5 backdrop-blur-sm"
            >
              <feature.icon className="h-5 w-5 text-cyan-300" />
              <h2 className="mt-3 text-base font-semibold text-foreground">{feature.title}</h2>
              <p className="mt-1 text-sm leading-relaxed text-slate-300">{feature.description}</p>
            </motion.article>
          ))}
        </section>
      </div>
    </main>
  );
}
