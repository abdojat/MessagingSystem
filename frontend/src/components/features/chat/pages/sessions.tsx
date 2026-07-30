"use client";

import { useDeleteSession, useLogoutAll, useSessions } from "@/hooks/use-auth";
import { useLocale, useTranslations } from "next-intl";
import { Button } from "@/components/ui/button";
import { Laptop, Smartphone, Globe, ShieldAlert } from "lucide-react";
import Link from "next/link";
import { Skeleton } from "@/components/ui/skeleton";
import { useLocalePath } from "@/components/features/chat/lib/locale-path";
import { formatDateTimeLocalized } from "@/lib/i18n-format";

function SessionsSkeleton() {
  return (
    <div className="grid gap-4">
      {Array.from({ length: 3 }).map((_, index) => (
        <div key={index} className="p-6 rounded-2xl border border-border bg-card shadow-sm flex flex-col sm:flex-row gap-6 items-start sm:items-center">
          <Skeleton className="h-14 w-14 rounded-xl" />
          <div className="flex-1 min-w-0 space-y-3">
            <Skeleton className="h-6 w-40" />
            <Skeleton className="h-4 w-64 max-w-full" />
            <Skeleton className="h-4 w-56 max-w-full" />
            <Skeleton className="h-4 w-60 max-w-full" />
          </div>
          <Skeleton className="h-10 w-32 rounded-xl" />
        </div>
      ))}
    </div>
  );
}

export default function Sessions() {
  const localePath = useLocalePath();
  const locale = useLocale();
  const t = useTranslations("sessions");
  const commonT = useTranslations("common");
  const { data: sessions = [], isLoading } = useSessions();
  const deleteSession = useDeleteSession();
  const logoutAll = useLogoutAll();

  const getDeviceIcon = (agent?: string | null) => {
    const ua = (agent || '').toLowerCase();
    if (ua.includes('mobile') || ua.includes('android') || ua.includes('iphone')) return <Smartphone className="w-6 h-6" />;
    if (ua.includes('mac') || ua.includes('windows') || ua.includes('linux')) return <Laptop className="w-6 h-6" />;
    return <Globe className="w-6 h-6" />;
  };

  return (
    <div className="min-h-screen bg-background text-foreground p-8">
      <div className="max-w-4xl mx-auto">
        <div className="flex items-center justify-between mb-8">
          <div>
            <Link href={localePath("/app")} className="text-primary text-sm font-medium hover:underline mb-2 inline-block">{commonT("actions.backToApp")}</Link>
            <h1 className="text-3xl font-bold tracking-tight">{t("title")}</h1>
            <p className="text-muted-foreground mt-1">{t("description")}</p>
          </div>
          <Button 
            variant="destructive" 
            onClick={() => logoutAll.mutate()}
            disabled={logoutAll.isPending || sessions.length === 0}
            className="shadow-sm shadow-destructive/20"
          >
            <ShieldAlert className="w-4 h-4 mr-2" />
            {t("terminateAll")}
          </Button>
        </div>

        {isLoading ? (
          <SessionsSkeleton />
        ) : (
          <div className="grid gap-4">
            {sessions.length === 0 ? (
              <div className="rounded-2xl border border-border bg-card p-6 text-sm text-muted-foreground">
                {t("empty")}
              </div>
            ) : sessions.map(session => (
              <div key={session.id} className="p-6 rounded-2xl border border-border bg-card shadow-sm flex flex-col sm:flex-row gap-6 items-start sm:items-center">
                <div className="p-4 rounded-xl bg-secondary text-muted-foreground">
                  {getDeviceIcon(session.user_agent)}
                </div>
                
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-3 mb-1">
                    <h3 className="font-semibold text-foreground text-lg truncate">
                      {session.user_agent ? session.user_agent.split(' ')[0] : t("unknownDevice")}
                    </h3>
                  </div>
                  <div className="text-sm text-muted-foreground space-y-0.5">
                    <p>{t("ipAddress")}: <span className="font-medium text-foreground/80">{session.ip || t("unknown")}</span></p>
                    <p>{t("started")}: {formatDateTimeLocalized(session.created_at, locale, commonT("notAvailable"))}</p>
                    <p>{t("expires")}: {formatDateTimeLocalized(session.expires_at, locale, commonT("notAvailable"))}</p>
                    {session.revoked_at && <p>{t("revoked")}: {formatDateTimeLocalized(session.revoked_at, locale, commonT("notAvailable"))}</p>}
                  </div>
                </div>

                <Button 
                  variant="outline" 
                  className="border-destructive/20 text-destructive hover:bg-destructive hover:text-destructive-foreground hover:border-destructive transition-colors"
                  onClick={() => deleteSession.mutate(session.id)}
                  disabled={deleteSession.isPending || !!session.revoked_at}
                >
                  {session.revoked_at ? t("revoked") : t("revokeAccess")}
                </Button>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
