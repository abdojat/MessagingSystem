"use client";

import { useParams, useRouter } from "next/navigation";
import { useQuery, useMutation } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { apiClient } from "@/services/api/client";
import { InviteDetailsResponse } from "@/types/api";
import { Button } from "@/components/ui/button";
import { Hash, LogIn } from "lucide-react";
import { Skeleton } from "@/components/ui/skeleton";
import { useLocalePath } from "@/components/features/chat/lib/locale-path";

function InviteSkeleton() {
  return (
    <div className="min-h-screen bg-background flex flex-col items-center justify-center p-4 relative overflow-hidden">
      <div className="absolute inset-0 z-0 bg-[radial-gradient(circle_at_center,var(--tw-gradient-stops))] from-primary/10 via-background to-background" />
      <div className="relative z-10 bg-card/80 backdrop-blur-2xl border border-border p-10 rounded-[2rem] shadow-2xl shadow-black/20 max-w-md w-full text-center">
        <Skeleton className="h-24 w-24 rounded-3xl mx-auto mb-6" />
        <Skeleton className="h-9 w-56 max-w-full mx-auto mb-3" />
        <Skeleton className="h-4 w-64 max-w-full mx-auto mb-8" />
        <Skeleton className="h-14 w-full rounded-xl" />
      </div>
    </div>
  );
}

export default function Invite() {
  const params = useParams<{ token?: string | string[] }>();
  const token = Array.isArray(params?.token) ? params.token[0] : params?.token;
  const router = useRouter();
  const localePath = useLocalePath();
  const t = useTranslations("invite");
  const commonT = useTranslations("common");

  const { data: invite, isLoading, isError } = useQuery({
    queryKey: ['/invites', token],
    queryFn: () => apiClient<InviteDetailsResponse>(`/invites/${token}`),
    retry: false,
    enabled: Boolean(token),
  });

  const acceptInvite = useMutation({
    mutationFn: () => apiClient(`/invites/${token}/accept`, { method: 'POST' }),
    onSuccess: () => {
      if (invite?.channel?.id) {
        router.push(localePath(`/app/channels/${invite.channel.id}`));
      } else {
        router.push(localePath("/app"));
      }
    }
  });

  if (!token) return null;

  if (isLoading) return <InviteSkeleton />;

  if (isError || !invite || !invite.is_valid) {
    return (
      <div className="min-h-screen bg-background flex flex-col items-center justify-center p-4 text-center">
        <div className="w-20 h-20 bg-destructive/10 text-destructive rounded-full flex items-center justify-center mb-6">
          <Hash className="w-10 h-10" />
        </div>
        <h1 className="text-3xl font-bold text-foreground mb-2">{t("invalidTitle")}</h1>
        <p className="text-muted-foreground mb-8 max-w-md">{t("invalidDescription")}</p>
        <Button onClick={() => router.push(localePath("/app"))} variant="outline" className="h-12 px-8 rounded-xl font-medium">{commonT("actions.returnToApp")}</Button>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-background flex flex-col items-center justify-center p-4 relative overflow-hidden">
      <div className="absolute inset-0 z-0 bg-[radial-gradient(circle_at_center,var(--tw-gradient-stops))] from-primary/10 via-background to-background" />
      
      <div className="relative z-10 bg-card/80 backdrop-blur-2xl border border-border p-10 rounded-[2rem] shadow-2xl shadow-black/20 max-w-md w-full text-center">
        <div className="w-24 h-24 bg-gradient-to-br from-primary to-primary/60 rounded-3xl mx-auto flex items-center justify-center text-primary-foreground shadow-xl shadow-primary/25 mb-6">
          <Hash className="w-12 h-12" />
        </div>
        
        <h1 className="text-3xl font-bold text-foreground tracking-tight mb-2">
          {invite.channel?.name || t("joinChannel")}
        </h1>

        <p className="text-muted-foreground mb-8">
          {t("grantAccess", { visibility: commonT(`visibility.${invite.channel?.visibility || "public"}`) })}
        </p>

        <Button 
          onClick={() => acceptInvite.mutate()}
          disabled={acceptInvite.isPending}
          className="w-full h-14 text-lg font-bold rounded-xl bg-primary hover:bg-primary/90 shadow-lg shadow-primary/25 transition-all hover:-translate-y-0.5"
        >
          <LogIn className="w-5 h-5 mr-2" />
          {acceptInvite.isPending ? t("joining") : t("accept")}
        </Button>
      </div>
    </div>
  );
}
