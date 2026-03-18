import { useParams, useLocation } from "wouter";
import { useQuery, useMutation } from "@tanstack/react-query";
import { apiClient } from "../lib/apiClient";
import { InviteDetailsResponse } from "../types/api";
import { Button } from "../components/ui/button";
import { Hash, LogIn } from "lucide-react";

export default function Invite() {
  const { token } = useParams();
  const [, setLocation] = useLocation();

  const { data: invite, isLoading, isError } = useQuery({
    queryKey: ['/invites', token],
    queryFn: () => apiClient<InviteDetailsResponse>(`/invites/${token}`),
    retry: false
  });

  const acceptInvite = useMutation({
    mutationFn: () => apiClient(`/invites/${token}/accept`, { method: 'POST' }),
    onSuccess: () => {
      if (invite?.channel?.id) {
        setLocation(`/app/channels/${invite.channel.id}`);
      } else {
        setLocation('/app');
      }
    }
  });

  if (isLoading) return <div className="min-h-screen flex items-center justify-center bg-background"><div className="w-8 h-8 border-4 border-primary border-t-transparent rounded-full animate-spin" /></div>;

  if (isError || !invite || !invite.is_valid) {
    return (
      <div className="min-h-screen bg-background flex flex-col items-center justify-center p-4 text-center">
        <div className="w-20 h-20 bg-destructive/10 text-destructive rounded-full flex items-center justify-center mb-6">
          <Hash className="w-10 h-10" />
        </div>
        <h1 className="text-3xl font-bold text-foreground mb-2">Invalid Invite</h1>
        <p className="text-muted-foreground mb-8 max-w-md">This invite link is invalid, expired, or no longer available.</p>
        <Button onClick={() => setLocation('/app')} variant="outline" className="h-12 px-8 rounded-xl font-medium">Return to App</Button>
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
          {invite.channel?.name || "Join Channel"}
        </h1>

        <p className="text-muted-foreground mb-8">
          This invite grants access to a {invite.channel?.visibility || 'public'} channel.
        </p>

        <Button 
          onClick={() => acceptInvite.mutate()}
          disabled={acceptInvite.isPending}
          className="w-full h-14 text-lg font-bold rounded-xl bg-primary hover:bg-primary/90 shadow-lg shadow-primary/25 transition-all hover:-translate-y-0.5"
        >
          <LogIn className="w-5 h-5 mr-2" />
          {acceptInvite.isPending ? "Joining..." : "Accept Invite"}
        </Button>
      </div>
    </div>
  );
}
