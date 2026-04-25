"use client";

import { type FormEvent, useEffect, useState } from "react";
import { Globe, Lock, ShieldCheck, Sparkles, Users } from "lucide-react";
import { useRouter } from "next/navigation";

import { useCreateChannel } from "@/hooks/use-channels";
import { toast } from "@/hooks/use-toast";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { useLocalePath } from "@/components/features/chat/lib/locale-path";

type CreateChannelDialogProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
};

type Visibility = "public" | "private";
type JoinMode = "open" | "approval_required" | "invite_only";

const presets: Array<{
  id: string;
  title: string;
  description: string;
  visibility: Visibility;
  joinMode: JoinMode;
  icon: typeof Globe;
}> = [
  {
    id: "community",
    title: "Open room",
    description: "Public and easy to join for fast-moving team spaces.",
    visibility: "public",
    joinMode: "open",
    icon: Globe,
  },
  {
    id: "screened",
    title: "Screened room",
    description: "Public discovery with approvals before people enter.",
    visibility: "public",
    joinMode: "approval_required",
    icon: ShieldCheck,
  },
  {
    id: "private",
    title: "Private room",
    description: "Invite-only access for leadership, ops, or sensitive work.",
    visibility: "private",
    joinMode: "invite_only",
    icon: Lock,
  },
];

const visibilityOptions = [
  {
    value: "public" as const,
    label: "Public",
    description: "Anyone in the workspace can discover this channel.",
  },
  {
    value: "private" as const,
    label: "Private",
    description: "Only invited people can find and access this channel.",
  },
];

const joinModeOptions = [
  {
    value: "open" as const,
    label: "Open join",
    description: "People can join immediately.",
  },
  {
    value: "approval_required" as const,
    label: "Approval required",
    description: "Requests are visible before someone is admitted.",
  },
  {
    value: "invite_only" as const,
    label: "Invite only",
    description: "Only direct invites can grant access.",
  },
];

const initialForm = {
  name: "",
  description: "",
  visibility: "public" as Visibility,
  joinMode: "open" as JoinMode,
};

export function CreateChannelDialog({
  open,
  onOpenChange,
}: CreateChannelDialogProps) {
  const router = useRouter();
  const localePath = useLocalePath();
  const createChannel = useCreateChannel();
  const [form, setForm] = useState(initialForm);

  useEffect(() => {
    if (!open) {
      setForm(initialForm);
    }
  }, [open]);

  const selectedVisibility = visibilityOptions.find(
    (option) => option.value === form.visibility,
  );
  const selectedJoinMode = joinModeOptions.find(
    (option) => option.value === form.joinMode,
  );

  function applyPreset(visibility: Visibility, joinMode: JoinMode) {
    setForm((current) => ({
      ...current,
      visibility,
      joinMode,
    }));
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    const trimmedName = form.name.trim();
    const trimmedDescription = form.description.trim();

    if (!trimmedName) {
      toast({
        title: "Channel name required",
        description: "Give the new channel a short, clear name first.",
        variant: "destructive",
      });
      return;
    }

    createChannel.mutate(
      {
        name: trimmedName,
        description: trimmedDescription || undefined,
        visibility: form.visibility,
        join_mode: form.joinMode,
      },
      {
        onSuccess: (channel) => {
          onOpenChange(false);
          router.push(localePath(`/app/channels/${channel.id}`));
          toast({
            title: "Channel created",
            description: `${channel.name} is ready for your team.`,
          });
        },
        onError: () => {
          toast({
            title: "Could not create channel",
            description: "Please try again in a moment.",
            variant: "destructive",
          });
        },
      },
    );
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="flex max-h-[calc(100vh-2rem)] w-[calc(100vw-1.5rem)] flex-col overflow-hidden border-white/10 bg-gradient-to-br from-background via-background to-muted/30 p-0 shadow-2xl sm:max-w-2xl">
        <div className="relative flex-shrink-0">
          <div className="absolute inset-x-0 top-0 h-36 bg-[radial-gradient(circle_at_top_left,_hsl(var(--primary)/0.22),_transparent_55%),radial-gradient(circle_at_top_right,_hsl(var(--accent)/0.18),_transparent_40%)]" />
          <div className="relative border-b border-border/60 px-6 pb-6 pt-7 sm:px-7">
            <DialogHeader className="space-y-3 text-left">
              <div className="inline-flex w-fit items-center gap-2 rounded-full border border-primary/20 bg-primary/10 px-3 py-1 text-xs font-semibold uppercase tracking-[0.24em] text-primary">
                <Sparkles className="h-3.5 w-3.5" />
                New channel
              </div>
              <div className="space-y-1">
                <DialogTitle className="text-2xl font-semibold tracking-tight">
                  Create a space people want to join
                </DialogTitle>
                <DialogDescription className="max-w-xl text-sm leading-6">
                  Set the tone with a clear name, a little context, and the right access model for your team.
                </DialogDescription>
              </div>
            </DialogHeader>
          </div>
        </div>

        <form onSubmit={handleSubmit} className="flex-1 overflow-y-auto px-6 pb-6 pt-6 sm:px-7 sm:pb-7">
          <div className="space-y-6">
          <div className="grid gap-3 sm:grid-cols-3">
            {presets.map((preset) => {
              const Icon = preset.icon;
              const isActive =
                form.visibility === preset.visibility && form.joinMode === preset.joinMode;

              return (
                <button
                  key={preset.id}
                  type="button"
                  onClick={() => applyPreset(preset.visibility, preset.joinMode)}
                  className={`rounded-2xl border p-4 text-left transition-all ${
                    isActive
                      ? "border-primary/50 bg-primary/10 shadow-lg shadow-primary/10"
                      : "border-border/60 bg-card/70 hover:border-primary/30 hover:bg-accent/30"
                  }`}
                >
                  <div className="mb-3 flex h-10 w-10 items-center justify-center rounded-xl bg-background/80 text-primary shadow-sm">
                    <Icon className="h-5 w-5" />
                  </div>
                  <div className="font-semibold text-foreground">{preset.title}</div>
                  <div className="mt-1 text-sm leading-5 text-muted-foreground">
                    {preset.description}
                  </div>
                </button>
              );
            })}
          </div>

          <div className="grid gap-5">
            <div className="grid gap-2">
              <Label htmlFor="channel-name">Channel name</Label>
              <Input
                id="channel-name"
                value={form.name}
                onChange={(event) =>
                  setForm((current) => ({ ...current, name: event.target.value }))
                }
                placeholder="Marketing standup"
                maxLength={80}
                autoFocus
              />
              <p className="text-xs text-muted-foreground">
                Keep it short and recognizable so people can find it fast.
              </p>
            </div>

            <div className="grid gap-2">
              <Label htmlFor="channel-description">Description</Label>
              <Textarea
                id="channel-description"
                value={form.description}
                onChange={(event) =>
                  setForm((current) => ({ ...current, description: event.target.value }))
                }
                placeholder="What belongs here, who should use it, and how often the team checks in."
                className="min-h-28 resize-none"
                maxLength={240}
              />
            </div>

            <div className="grid gap-4 sm:grid-cols-2">
              <div className="grid gap-2">
                <Label>Visibility</Label>
                <Select
                  value={form.visibility}
                  onValueChange={(value: Visibility) =>
                    setForm((current) => ({ ...current, visibility: value }))
                  }
                >
                  <SelectTrigger>
                    <SelectValue placeholder="Choose visibility" />
                  </SelectTrigger>
                  <SelectContent>
                    {visibilityOptions.map((option) => (
                      <SelectItem key={option.value} value={option.value}>
                        {option.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <p className="text-xs text-muted-foreground">
                  {selectedVisibility?.description}
                </p>
              </div>

              <div className="grid gap-2">
                <Label>Join access</Label>
                <Select
                  value={form.joinMode}
                  onValueChange={(value: JoinMode) =>
                    setForm((current) => ({ ...current, joinMode: value }))
                  }
                >
                  <SelectTrigger>
                    <SelectValue placeholder="Choose join mode" />
                  </SelectTrigger>
                  <SelectContent>
                    {joinModeOptions.map((option) => (
                      <SelectItem key={option.value} value={option.value}>
                        {option.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <p className="text-xs text-muted-foreground">
                  {selectedJoinMode?.description}
                </p>
              </div>
            </div>
          </div>

          <div className="rounded-2xl border border-border/60 bg-card/60 p-4">
            <div className="flex items-start gap-3">
              <div className="mt-0.5 flex h-10 w-10 items-center justify-center rounded-xl bg-primary/10 text-primary">
                <Users className="h-5 w-5" />
              </div>
              <div className="space-y-1">
                <div className="font-medium text-foreground">
                  {form.visibility === "public" ? "Easy to discover" : "Kept intentionally private"}
                </div>
                <div className="text-sm leading-6 text-muted-foreground">
                  {form.visibility === "public"
                    ? "People across the workspace will be able to see this channel in discovery."
                    : "Only invited members will know this channel exists."}{" "}
                  {form.joinMode === "open" && "Anyone who sees it can join immediately."}
                  {form.joinMode === "approval_required" &&
                    "New joiners will wait for approval before entering."}
                  {form.joinMode === "invite_only" &&
                    "Membership is controlled strictly through invitations."}
                </div>
              </div>
            </div>
          </div>

          <DialogFooter className="gap-2 sm:justify-between">
            <div className="text-xs text-muted-foreground">
              You can update these settings later from channel details.
            </div>
            <div className="flex items-center gap-2">
              <Button
                type="button"
                variant="ghost"
                onClick={() => onOpenChange(false)}
                disabled={createChannel.isPending}
              >
                Cancel
              </Button>
              <Button type="submit" disabled={createChannel.isPending}>
                {createChannel.isPending ? "Creating..." : "Create channel"}
              </Button>
            </div>
          </DialogFooter>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}
