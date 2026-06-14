"use client";

import { type FormEvent, useEffect, useState } from "react";
import { Globe, Lock, ShieldCheck, Sparkles, Users } from "lucide-react";
import { useTranslations } from "next-intl";
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

const presetConfigs: Array<{
  id: "community" | "screened" | "private";
  visibility: Visibility;
  joinMode: JoinMode;
  icon: typeof Globe;
}> = [
  {
    id: "community",
    visibility: "public",
    joinMode: "open",
    icon: Globe,
  },
  {
    id: "screened",
    visibility: "public",
    joinMode: "approval_required",
    icon: ShieldCheck,
  },
  {
    id: "private",
    visibility: "private",
    joinMode: "invite_only",
    icon: Lock,
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
  const t = useTranslations("createChannel");
  const commonT = useTranslations("common");
  const createChannel = useCreateChannel();
  const [form, setForm] = useState(initialForm);

  useEffect(() => {
    if (!open) {
      setForm(initialForm);
    }
  }, [open]);

  const visibilityOptions = [
    {
      value: "public" as const,
      label: commonT("visibility.public"),
      description: t("visibility.publicDescription"),
    },
    {
      value: "private" as const,
      label: commonT("visibility.private"),
      description: t("visibility.privateDescription"),
    },
  ];

  const joinModeOptions = [
    {
      value: "open" as const,
      label: commonT("joinMode.open"),
      description: t("joinMode.openDescription"),
    },
    {
      value: "approval_required" as const,
      label: commonT("joinMode.approvalRequired"),
      description: t("joinMode.approvalDescription"),
    },
    {
      value: "invite_only" as const,
      label: commonT("joinMode.inviteOnly"),
      description: t("joinMode.inviteDescription"),
    },
  ];

  const presets = presetConfigs.map((preset) => ({
    ...preset,
    title: t(`presets.${preset.id}.title`),
    description: t(`presets.${preset.id}.description`),
  }));

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
        title: t("toasts.nameRequiredTitle"),
        description: t("toasts.nameRequiredDescription"),
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
            title: t("toasts.createdTitle"),
            description: t("toasts.createdDescription", { name: channel.name }),
          });
        },
        onError: () => {
          toast({
            title: t("toasts.createFailedTitle"),
            description: commonT("tryAgainLater"),
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
                {t("eyebrow")}
              </div>
              <div className="space-y-1">
                <DialogTitle className="text-2xl font-semibold tracking-tight">
                  {t("title")}
                </DialogTitle>
                <DialogDescription className="max-w-xl text-sm leading-6">
                  {t("description")}
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
              <Label htmlFor="channel-name">{t("fields.name")}</Label>
              <Input
                id="channel-name"
                value={form.name}
                onChange={(event) =>
                  setForm((current) => ({ ...current, name: event.target.value }))
                }
                placeholder={t("fields.namePlaceholder")}
                maxLength={80}
                autoFocus
              />
              <p className="text-xs text-muted-foreground">
                {t("fields.nameHint")}
              </p>
            </div>

            <div className="grid gap-2">
              <Label htmlFor="channel-description">{t("fields.description")}</Label>
              <Textarea
                id="channel-description"
                value={form.description}
                onChange={(event) =>
                  setForm((current) => ({ ...current, description: event.target.value }))
                }
                placeholder={t("fields.descriptionPlaceholder")}
                className="min-h-28 resize-none"
                maxLength={240}
              />
            </div>

            <div className="grid gap-4 sm:grid-cols-2">
              <div className="grid gap-2">
                <Label>{t("fields.visibility")}</Label>
                <Select
                  value={form.visibility}
                  onValueChange={(value: Visibility) =>
                    setForm((current) => ({ ...current, visibility: value }))
                  }
                >
                  <SelectTrigger>
                    <SelectValue placeholder={t("fields.visibilityPlaceholder")} />
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
                <Label>{t("fields.joinAccess")}</Label>
                <Select
                  value={form.joinMode}
                  onValueChange={(value: JoinMode) =>
                    setForm((current) => ({ ...current, joinMode: value }))
                  }
                >
                  <SelectTrigger>
                    <SelectValue placeholder={t("fields.joinModePlaceholder")} />
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
                  {form.visibility === "public" ? t("summary.publicTitle") : t("summary.privateTitle")}
                </div>
                <div className="text-sm leading-6 text-muted-foreground">
                  {form.visibility === "public"
                    ? t("summary.publicDescription")
                    : t("summary.privateDescription")}{" "}
                  {form.joinMode === "open" && t("summary.open")}
                  {form.joinMode === "approval_required" &&
                    t("summary.approvalRequired")}
                  {form.joinMode === "invite_only" &&
                    t("summary.inviteOnly")}
                </div>
              </div>
            </div>
          </div>

          <DialogFooter className="gap-2 sm:justify-between">
            <div className="text-xs text-muted-foreground">
              {t("footerHint")}
            </div>
            <div className="flex items-center gap-2">
              <Button
                type="button"
                variant="ghost"
                onClick={() => onOpenChange(false)}
                disabled={createChannel.isPending}
              >
                {commonT("actions.cancel")}
              </Button>
              <Button type="submit" disabled={createChannel.isPending}>
                {createChannel.isPending ? t("actions.creating") : t("actions.create")}
              </Button>
            </div>
          </DialogFooter>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}
