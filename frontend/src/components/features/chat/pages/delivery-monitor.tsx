"use client";

import { useLocale, useTranslations } from "next-intl";
import type { ComponentType } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  Clock3,
  RefreshCw,
  RotateCcw,
  Send,
  XCircle,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  useDeadLetteredDeliveries,
  useDeliveryStats,
  useFailedDeliveries,
  useRetryAllDeliveries,
  useRetryDelivery,
} from "@/hooks/use-delivery";
import { toast } from "@/hooks/use-toast";
import type { DeliveryItemResponse, DeliveryStatsResponse } from "@/types/api";
import { formatRelativeTimeLocalized } from "@/lib/i18n-format";

const emptyStats: DeliveryStatsResponse = {
  pending: 0,
  publishing: 0,
  published: 0,
  retry_scheduled: 0,
  failed: 0,
  dead_lettered: 0,
};

function getErrorMessage(error: unknown, fallback: string) {
  if (error instanceof Error && error.message) return error.message;
  return fallback;
}

function StatusBadge({ status }: { status: string }) {
  const t = useTranslations("delivery.status");
  if (status === "dead_lettered") return <Badge variant="destructive">{t("deadLettered")}</Badge>;
  if (status === "retry_scheduled") return <Badge variant="secondary">{t("retryScheduled")}</Badge>;
  if (status === "failed") return <Badge variant="destructive">{t("failed")}</Badge>;
  if (status === "published") return <Badge>{t("published")}</Badge>;
  if (status === "pending") return <Badge variant="outline">{t("pending")}</Badge>;
  if (status === "publishing") return <Badge variant="outline">{t("publishing")}</Badge>;
  return <Badge variant="outline">{status.replace("_", " ")}</Badge>;
}

function StatCard({
  label,
  value,
  icon: Icon,
}: {
  label: string;
  value: number;
  icon: ComponentType<{ className?: string }>;
}) {
  return (
    <Card className="rounded-lg border-border/60 p-4">
      <div className="flex items-center justify-between gap-3">
        <div>
          <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">{label}</p>
          <p className="mt-2 text-2xl font-semibold">{value}</p>
        </div>
        <div className="flex h-10 w-10 items-center justify-center rounded-md bg-muted text-muted-foreground">
          <Icon className="h-5 w-5" />
        </div>
      </div>
    </Card>
  );
}

function DeliveryTable({
  title,
  items,
  isLoading,
  emptyMessage,
  onRetry,
  retryingId,
}: {
  title: string;
  items: DeliveryItemResponse[];
  isLoading: boolean;
  emptyMessage: string;
  onRetry: (outboxId: string) => void;
  retryingId: string | null;
}) {
  const locale = useLocale();
  const t = useTranslations("delivery.table");
  const commonT = useTranslations("common");

  return (
    <Card className="rounded-lg border-border/60">
      <div className="flex items-center justify-between border-b border-border/60 px-4 py-3">
        <h2 className="text-base font-semibold">{title}</h2>
        <Badge variant="outline">{items.length}</Badge>
      </div>
      {isLoading ? (
        <div className="space-y-3 p-4">
          <Skeleton className="h-10 w-full" />
          <Skeleton className="h-10 w-full" />
          <Skeleton className="h-10 w-full" />
        </div>
      ) : items.length === 0 ? (
        <div className="px-4 py-8 text-sm text-muted-foreground">{emptyMessage}</div>
      ) : (
        <div className="overflow-x-auto">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{t("channel")}</TableHead>
                <TableHead>{t("type")}</TableHead>
                <TableHead>{t("status")}</TableHead>
                <TableHead>{t("attempts")}</TableHead>
                <TableHead>{t("nextRetry")}</TableHead>
                <TableHead>{t("lastError")}</TableHead>
                <TableHead className="text-right">{t("action")}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {items.map((item) => (
                <TableRow key={item.id}>
                  <TableCell className="min-w-40 font-medium">
                    {item.channel_slug ? `#${item.channel_slug}` : item.channel_id}
                  </TableCell>
                  <TableCell className="min-w-36 text-muted-foreground">
                    {item.event_type || item.payload_type || t("message")}
                  </TableCell>
                  <TableCell>
                    <StatusBadge status={item.status} />
                  </TableCell>
                  <TableCell>
                    {item.attempt_count}/{item.max_attempts}
                  </TableCell>
                  <TableCell className="min-w-32 text-muted-foreground">
                    {formatRelativeTimeLocalized(item.next_attempt_at, locale, t("notScheduled"))}
                  </TableCell>
                  <TableCell className="max-w-80">
                    <span className="line-clamp-2 text-sm text-muted-foreground">
                      {item.last_error || t("noError")}
                    </span>
                  </TableCell>
                  <TableCell className="text-right">
                    <Button
                      size="sm"
                      variant="outline"
                      disabled={retryingId === item.id}
                      onClick={() => onRetry(item.id)}
                    >
                      <RotateCcw className="mr-1 h-4 w-4" />
                      {retryingId === item.id ? commonT("actions.retrying") : commonT("actions.retry")}
                    </Button>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}
    </Card>
  );
}

export default function DeliveryMonitorPage() {
  const t = useTranslations("delivery");
  const commonT = useTranslations("common");
  const statsQuery = useDeliveryStats();
  const failedQuery = useFailedDeliveries();
  const deadLetteredQuery = useDeadLetteredDeliveries();
  const retryDelivery = useRetryDelivery();
  const retryAllDeliveries = useRetryAllDeliveries();
  const stats = statsQuery.data ?? emptyStats;
  const failedItems = failedQuery.data?.items ?? [];
  const deadLetteredItems = deadLetteredQuery.data?.items ?? [];
  const retryingId = typeof retryDelivery.variables === "string" && retryDelivery.isPending ? retryDelivery.variables : null;
  const isError = statsQuery.isError || failedQuery.isError || deadLetteredQuery.isError;
  const error = statsQuery.error || failedQuery.error || deadLetteredQuery.error;
  const retryableCount = failedItems.length + deadLetteredItems.length;

  function handleRetry(outboxId: string) {
    retryDelivery.mutate(outboxId, {
      onSuccess: (result) => {
        toast({
          title: result.retried_count ? t("toasts.retryQueuedTitle") : t("toasts.alreadyActiveTitle"),
          description: result.retried_count ? t("toasts.retryQueuedDescription") : t("toasts.alreadyActiveDescription"),
        });
      },
      onError: (retryError) => {
        toast({
          title: t("toasts.retryFailedTitle"),
          description: getErrorMessage(retryError, commonT("tryAgain")),
          variant: "destructive",
        });
      },
    });
  }

  function handleRetryAll() {
    retryAllDeliveries.mutate(undefined, {
      onSuccess: (result) => {
        toast({
          title: t("toasts.retryAllSavedTitle"),
          description: t("toasts.retryAllSavedDescription", { count: result.retried_count }),
        });
      },
      onError: (retryError) => {
        toast({
          title: t("toasts.retryAllFailedTitle"),
          description: getErrorMessage(retryError, commonT("tryAgain")),
          variant: "destructive",
        });
      },
    });
  }

  return (
    <div className="h-full min-h-0 overflow-y-auto bg-background p-6 text-foreground sm:p-8">
      <div className="mx-auto max-w-6xl space-y-6">
        <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <h1 className="text-3xl font-bold tracking-tight">{t("title")}</h1>
            <p className="mt-1 text-sm text-muted-foreground">{t("description")}</p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Button
              variant="outline"
              onClick={() => {
                statsQuery.refetch();
                failedQuery.refetch();
                deadLetteredQuery.refetch();
              }}
            >
              <RefreshCw className="mr-2 h-4 w-4" />
              {commonT("actions.refresh")}
            </Button>
            <Button
              onClick={handleRetryAll}
              disabled={retryableCount === 0 || retryAllDeliveries.isPending}
            >
              <RotateCcw className="mr-2 h-4 w-4" />
              {retryAllDeliveries.isPending ? commonT("actions.retrying") : t("actions.retryAll")}
            </Button>
          </div>
        </div>

        {isError ? (
          <Card className="rounded-lg border-destructive/50 p-5">
            <div className="flex items-start gap-3 text-destructive">
              <AlertTriangle className="mt-0.5 h-5 w-5" />
              <div>
                <h2 className="font-semibold">{t("errors.loadTitle")}</h2>
                <p className="mt-1 text-sm text-muted-foreground">
                  {getErrorMessage(error, t("errors.loadDescription"))}
                </p>
              </div>
            </div>
          </Card>
        ) : null}

        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-6">
          <StatCard label={t("stats.pending")} value={stats.pending} icon={Clock3} />
          <StatCard label={t("stats.publishing")} value={stats.publishing} icon={Send} />
          <StatCard label={t("stats.published")} value={stats.published} icon={CheckCircle2} />
          <StatCard label={t("stats.retrying")} value={stats.retry_scheduled} icon={RefreshCw} />
          <StatCard label={t("stats.failed")} value={stats.failed} icon={XCircle} />
          <StatCard label={t("stats.dead")} value={stats.dead_lettered} icon={AlertTriangle} />
        </div>

        <div className="grid gap-6 xl:grid-cols-2">
          <DeliveryTable
            title={t("tables.failedTitle")}
            items={failedItems}
            isLoading={failedQuery.isLoading}
            emptyMessage={t("tables.failedEmpty")}
            onRetry={handleRetry}
            retryingId={retryingId}
          />
          <DeliveryTable
            title={t("tables.deadLetteredTitle")}
            items={deadLetteredItems}
            isLoading={deadLetteredQuery.isLoading}
            emptyMessage={t("tables.deadLetteredEmpty")}
            onRetry={handleRetry}
            retryingId={retryingId}
          />
        </div>
      </div>
    </div>
  );
}
