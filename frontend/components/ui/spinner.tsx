import { cn } from "@/lib/utils";

export function Spinner({ className }: { className?: string }) {
  return <div className={cn("size-5 animate-spin rounded-full border-2 border-slate-300 border-t-slate-700 dark:border-slate-700 dark:border-t-slate-100", className)} />;
}

