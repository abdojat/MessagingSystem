"use client";

import { formatDistanceToNow } from "date-fns";
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

const emptyStats: DeliveryStatsResponse = {
  pending: 0,
  publishing: 0,
  published: 0,
  retry_scheduled: 0,
  failed: 0,
  dead_lettered: 0,
};

function formatRelativeTime(value?: string | null) {
  if (!value) return "Not scheduled";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return "Not scheduled";
  return formatDistanceToNow(parsed, { addSuffix: true });
}

function getErrorMessage(error: unknown, fallback: string) {
  if (error instanceof Error && error.message) return error.message;
  return fallback;
}

function StatusBadge({ status }: { status: string }) {
  if (status === "dead_lettered") return <Badge variant="destructive">dead-lettered</Badge>;
  if (status === "retry_scheduled") return <Badge variant="secondary">retry scheduled</Badge>;
  if (status === "failed") return <Badge variant="destructive">failed</Badge>;
  if (status === "published") return <Badge>published</Badge>;
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
                <TableHead>Channel</TableHead>
                <TableHead>Type</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Attempts</TableHead>
                <TableHead>Next retry</TableHead>
                <TableHead>Last error</TableHead>
                <TableHead className="text-right">Action</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {items.map((item) => (
                <TableRow key={item.id}>
                  <TableCell className="min-w-40 font-medium">
                    {item.channel_slug ? `#${item.channel_slug}` : item.channel_id}
                  </TableCell>
                  <TableCell className="min-w-36 text-muted-foreground">
                    {item.event_type || item.payload_type || "message"}
                  </TableCell>
                  <TableCell>
                    <StatusBadge status={item.status} />
                  </TableCell>
                  <TableCell>
                    {item.attempt_count}/{item.max_attempts}
                  </TableCell>
                  <TableCell className="min-w-32 text-muted-foreground">
                    {formatRelativeTime(item.next_attempt_at)}
                  </TableCell>
                  <TableCell className="max-w-80">
                    <span className="line-clamp-2 text-sm text-muted-foreground">
                      {item.last_error || "No error recorded"}
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
                      {retryingId === item.id ? "Retrying" : "Retry"}
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
          title: result.retried_count ? "Delivery queued for retry" : "Delivery already active",
          description: result.retried_count ? "The worker will pick it up on the next poll." : "No status change was needed.",
        });
      },
      onError: (retryError) => {
        toast({
          title: "Retry failed",
          description: getErrorMessage(retryError, "Please try again."),
          variant: "destructive",
        });
      },
    });
  }

  function handleRetryAll() {
    retryAllDeliveries.mutate(undefined, {
      onSuccess: (result) => {
        toast({
          title: "Retry request saved",
          description: `${result.retried_count} delivery record${result.retried_count === 1 ? "" : "s"} queued.`,
        });
      },
      onError: (retryError) => {
        toast({
          title: "Retry all failed",
          description: getErrorMessage(retryError, "Please try again."),
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
            <h1 className="text-3xl font-bold tracking-tight">Delivery Monitor</h1>
            <p className="mt-1 text-sm text-muted-foreground">Outbox reliability status for channels you manage.</p>
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
              Refresh
            </Button>
            <Button
              onClick={handleRetryAll}
              disabled={retryableCount === 0 || retryAllDeliveries.isPending}
            >
              <RotateCcw className="mr-2 h-4 w-4" />
              {retryAllDeliveries.isPending ? "Retrying" : "Retry all"}
            </Button>
          </div>
        </div>

        {isError ? (
          <Card className="rounded-lg border-destructive/50 p-5">
            <div className="flex items-start gap-3 text-destructive">
              <AlertTriangle className="mt-0.5 h-5 w-5" />
              <div>
                <h2 className="font-semibold">Could not load delivery data</h2>
                <p className="mt-1 text-sm text-muted-foreground">
                  {getErrorMessage(error, "Delivery monitor is available to channel owners and admins.")}
                </p>
              </div>
            </div>
          </Card>
        ) : null}

        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-6">
          <StatCard label="Pending" value={stats.pending} icon={Clock3} />
          <StatCard label="Publishing" value={stats.publishing} icon={Send} />
          <StatCard label="Published" value={stats.published} icon={CheckCircle2} />
          <StatCard label="Retrying" value={stats.retry_scheduled} icon={RefreshCw} />
          <StatCard label="Failed" value={stats.failed} icon={XCircle} />
          <StatCard label="Dead" value={stats.dead_lettered} icon={AlertTriangle} />
        </div>

        <div className="grid gap-6 xl:grid-cols-2">
          <DeliveryTable
            title="Failed / Retry Scheduled"
            items={failedItems}
            isLoading={failedQuery.isLoading}
            emptyMessage="No failed or retry-scheduled deliveries."
            onRetry={handleRetry}
            retryingId={retryingId}
          />
          <DeliveryTable
            title="Dead-Lettered"
            items={deadLetteredItems}
            isLoading={deadLetteredQuery.isLoading}
            emptyMessage="No dead-lettered deliveries."
            onRetry={handleRetry}
            retryingId={retryingId}
          />
        </div>
      </div>
    </div>
  );
}
