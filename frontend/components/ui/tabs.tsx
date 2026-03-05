"use client";

import * as Tabs from "@radix-ui/react-tabs";
import { cn } from "@/lib/utils";

export const AppTabs = Tabs.Root;

export function AppTabsList({ className, ...props }: Tabs.TabsListProps) {
  return <Tabs.List className={cn("inline-flex rounded-md bg-slate-100 p-1 dark:bg-slate-800", className)} {...props} />;
}

export function AppTabsTrigger({ className, ...props }: Tabs.TabsTriggerProps) {
  return (
    <Tabs.Trigger
      className={cn(
        "rounded px-3 py-1.5 text-sm data-[state=active]:bg-white data-[state=active]:shadow data-[state=active]:dark:bg-slate-900",
        className,
      )}
      {...props}
    />
  );
}

export const AppTabsContent = Tabs.Content;

