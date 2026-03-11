import { X } from "lucide-react";
import { cn } from "@/lib/utils";

export function AppDialog({ open, onOpenChange, title, children }: { open: boolean; onOpenChange: (open: boolean) => void; title: string; children: React.ReactNode }) {
  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <button className="absolute inset-0 bg-black/40" onClick={() => onOpenChange(false)} aria-label="Close modal" />
      <div className="relative z-10 max-h-[90vh] w-[95vw] max-w-lg overflow-auto rounded-xl border border-slate-200 bg-white p-4 shadow-xl sm:p-5 dark:border-slate-800 dark:bg-slate-950">
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-lg font-semibold">{title}</h2>
          <button className={cn("rounded p-1 hover:bg-slate-100 dark:hover:bg-slate-800")} onClick={() => onOpenChange(false)}>
            <X className="size-4" />
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}
